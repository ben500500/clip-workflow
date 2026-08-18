"""剧目管理 API（ISSUE #130「视频号自动发布」→ 剧目管理，P0）。

按《剧目管理设计方案-20260818.md》落地：
- 剧目 CRUD + RBAC data_scope 过滤（operator 仅见自己创建/归属的剧目）+ 审计可溯源；
- 剧目导入 `/dramas/import/preview|confirm`：复用 smart_import 三段式骨架，
  以 `name` 为去重键，preview 返回 new/update/unchanged 三组（update 带旧值vs新值 diff），
  confirm 仅对用户勾选项写入/更新，未勾选不落库；记录导入历史支持回滚；
- 剧照（drama_stills，MinIO key）增删排序；
- 剧目↔视频号关联（drama_accounts，一剧多号）；
- 剧目↔发布素材关联（drama_materials）：发布弹窗一键生成素材后挂关联。

唯一 ID 生成规则：`DR-<8位大写HEX>`（如 DR-0A3F9C2E），入库前做唯一性冲突重抽。
"""
import os
import posixpath
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.drama import Drama, DramaStill, DramaAccount, DramaMaterial, gen_drama_code
from app.models.models import (
    User,
    ImportHistory,
    Episode,
    AutoClipRun,
    SliceTask,
    user_can_access_all_materials,
)
from app.api.slice_helpers import _not_detect_task
from app.services.minio_service import get_presigned_url, upload_file_from_path
from app.utils.helpers import utc_iso

router = APIRouter()


# ─────────────────────────────── Schema ───────────────────────────────

class DramaCreate(BaseModel):
    name: str
    frequency: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    rating: Optional[str] = None
    synopsis: Optional[str] = None
    cover_file_key: Optional[str] = None
    listing_status: str = "已上架"
    updated_date: Optional[str] = None
    listed_at: Optional[str] = None
    material_link: Optional[str] = None
    material_link_pwd: Optional[str] = None
    operator_id: Optional[str] = None
    # 关联视频号（可空，创建时一并关联）
    account_ids: Optional[List[str]] = None


class DramaUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    rating: Optional[str] = None
    synopsis: Optional[str] = None
    cover_file_key: Optional[str] = None
    listing_status: Optional[str] = None
    updated_date: Optional[str] = None
    listed_at: Optional[str] = None
    material_link: Optional[str] = None
    material_link_pwd: Optional[str] = None
    operator_id: Optional[str] = None


class DramaStillPayload(BaseModel):
    drama_id: str
    file_key: str
    sort_order: Optional[int] = 0


class DramaLinkAccounts(BaseModel):
    account_ids: List[str]


# ─────────────────────────────── Serialize ───────────────────────────────

async def _resolve_image_url(file_key: Optional[str]) -> Optional[str]:
    """将 MinIO file_key 解析为临时可访问的 presigned URL（用于封面/剧照展示）。"""
    if not file_key:
        return None
    try:
        return await get_presigned_url(settings.MINIO_BUCKET_RAW, file_key, expires_seconds=3600)
    except Exception:
        return None


async def _serialize_drama(d: Drama) -> dict:
    return {
        "id": str(d.id),
        "code": d.code,
        "name": d.name,
        "frequency": d.frequency,
        "type": d.type,
        "tags": list(d.tags) if d.tags else None,
        "rating": d.rating,
        "synopsis": d.synopsis,
        "cover_file_key": d.cover_file_key,
        "cover_url": await _resolve_image_url(d.cover_file_key),
        "listing_status": d.listing_status,
        "updated_date": d.updated_date.isoformat() if d.updated_date else None,
        "listed_at": utc_iso(d.listed_at) if d.listed_at else None,
        "material_link": d.material_link,
        # 网盘提取码不回传明文（密文），前端不可见
        "material_link_pwd_masked": bool(d.material_link_pwd),
        "created_by": str(d.created_by) if d.created_by else None,
        "operator_id": str(d.operator_id) if d.operator_id else None,
        "created_at": utc_iso(d.created_at) if d.created_at else "",
        "updated_at": utc_iso(d.updated_at) if d.updated_at else "",
    }


async def _serialize_drama_detail(d: Drama) -> dict:
    data = await _serialize_drama(d)
    stills = []
    for s in d.stills:
        stills.append({
            "id": str(s.id),
            "file_key": s.file_key,
            "sort_order": s.sort_order,
            "presigned_url": await _resolve_image_url(s.file_key),
        })
    data["stills"] = stills
    data["account_ids"] = [str(a.account_id) for a in d.accounts]
    # 剧集维度打通切片产线：归属剧集的 id（供剧目下展示该剧已切片/待切片）
    data["episode_ids"] = [str(e.id) for e in d.episodes]
    data["episode_count"] = len(d.episodes)
    return data


# ─────────────────────────────── Helpers ───────────────────────────────

async def _resolve_drama(db: AsyncSession, drama_id: str) -> Drama:
    try:
        did = uuid.UUID(drama_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid drama ID format")
    result = await db.execute(
        select(Drama)
        .where(Drama.id == did)
        .options(
            selectinload(Drama.stills),
            selectinload(Drama.accounts),
            selectinload(Drama.episodes),
        )
    )
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Drama not found")
    return d


def _can_manage(d: Drama, current_user: User) -> bool:
    """operator 仅可管理自己创建/归属的剧目；admin/material/publisher 全量。"""
    if current_user and not user_can_access_all_materials(current_user):
        if d.operator_id not in (current_user.id, None) and d.created_by != current_user.id:
            return False
    return True


def _apply_rbac_filter(current_user: User):
    if current_user and not user_can_access_all_materials(current_user):
        return (Drama.operator_id == current_user.id) | (Drama.created_by == current_user.id)
    return None


async def _associate_accounts(db: AsyncSession, drama_id: uuid.UUID, account_ids: List[str]):
    """将 video_accounts 关联到剧目（一剧多号），幂等：已关联跳过。"""
    if not account_ids:
        return
    existing = await db.execute(select(DramaAccount.account_id).where(DramaAccount.drama_id == drama_id))
    existing_ids = set(existing.scalars().all())
    for raw in account_ids:
        try:
            aid = uuid.UUID(raw)
        except ValueError:
            continue
        if aid in existing_ids:
            continue
        db.add(DramaAccount(drama_id=drama_id, account_id=aid))


# ─────────────────────────────── CRUD ───────────────────────────────

@router.get("/dramas", response_model=List[dict])
async def list_dramas(
    q: Optional[str] = Query(None, description="按名称/编码模糊搜索"),
    frequency: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    listing_status: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None, description="反查：该视频号关联的剧目"),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """剧目库列表（支持搜索/筛选；account_id 反查某号关联剧目；RBAC 过滤）。"""
    filters = []
    if q:
        filters.append(Drama.name.ilike(f"%{q}%") | Drama.code.ilike(f"%{q}%"))
    if frequency:
        filters.append(Drama.frequency == frequency)
    if rating:
        filters.append(Drama.rating == rating)
    if listing_status:
        filters.append(Drama.listing_status == listing_status)

    rbac = _apply_rbac_filter(current_user)
    if rbac is not None:
        filters.append(rbac)

    query = select(Drama)
    if account_id:
        try:
            aid = uuid.UUID(account_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid account_id")
        query = query.join(DramaAccount, DramaAccount.drama_id == Drama.id).where(
            DramaAccount.account_id == aid
        )
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(Drama.updated_at.desc())
    result = await db.execute(query)
    dramas = result.unique().scalars().all()
    return [await _serialize_drama(d) for d in dramas]


@router.post("/dramas", response_model=dict, status_code=201)
async def create_drama(
    data: DramaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增剧目（手动录入）。name 唯一；code 自动生成 DR-<8位HEX> 并做冲突重抽。"""
    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="剧目名称不能为空")

    existing = await db.execute(select(Drama).where(Drama.name == data.name.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"同名剧目已存在：{data.name}")

    # code 冲突重抽（最多 5 次）
    code = gen_drama_code()
    for _ in range(5):
        dup = await db.execute(select(Drama).where(Drama.code == code))
        if not dup.scalar_one_or_none():
            break
        code = gen_drama_code()

    d = Drama(
        code=code,
        name=data.name.strip(),
        frequency=data.frequency,
        type=data.type,
        tags=data.tags,
        rating=data.rating,
        synopsis=data.synopsis,
        cover_file_key=data.cover_file_key,
        listing_status=data.listing_status,
        material_link=data.material_link,
        material_link_pwd=data.material_link_pwd,
        created_by=current_user.id if current_user else None,
        operator_id=uuid.UUID(data.operator_id) if data.operator_id else (current_user.id if current_user else None),
    )
    if data.updated_date:
        d.updated_date = _parse_date(data.updated_date)
    if data.listed_at:
        d.listed_at = _parse_dt(data.listed_at)
    db.add(d)
    await db.flush()
    await _associate_accounts(db, d.id, data.account_ids or [])
    # 重新预加载关系后序列化（async 会话同步访问 lazy 关系会触发 MissingGreenlet）
    result = await db.execute(
        select(Drama)
        .where(Drama.id == d.id)
        .options(
            selectinload(Drama.stills),
            selectinload(Drama.accounts),
            selectinload(Drama.episodes),
        )
    )
    d = result.scalar_one()
    return await _serialize_drama_detail(d)


@router.get("/dramas/{drama_id}", response_model=dict)
async def get_drama(
    drama_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """剧目详情（含剧照、关联视频号）。"""
    d = await _resolve_drama(db, drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission to view this drama")
    return await _serialize_drama_detail(d)


@router.put("/dramas/{drama_id}", response_model=dict)
async def update_drama(
    drama_id: str,
    data: DramaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新剧目信息（含剧情简介/封面人工录入）。"""
    d = await _resolve_drama(db, drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission to update this drama")

    payload = data.model_dump(exclude_unset=True)
    # name 冲突校验（改名）
    new_name = payload.get("name")
    if new_name and new_name.strip() != d.name:
        existing = await db.execute(
            select(Drama).where(Drama.name == new_name.strip(), Drama.id != d.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"同名剧目已存在：{new_name}")

    for field, value in payload.items():
        if field == "operator_id":
            setattr(d, field, uuid.UUID(value) if value else None)
        elif field == "updated_date":
            d.updated_date = _parse_date(value) if value else None
        elif field == "listed_at":
            d.listed_at = _parse_dt(value) if value else None
        elif field == "name":
            d.name = value.strip()
        else:
            setattr(d, field, value)

    await db.flush()
    await db.refresh(d)
    return await _serialize_drama_detail(d)


@router.delete("/dramas/{drama_id}", status_code=204)
async def delete_drama(
    drama_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除剧目（级联删除剧照/关联）。"""
    d = await _resolve_drama(db, drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission to delete this drama")
    await db.delete(d)
    await db.flush()
    return None


# ─────────────────────────────── 剧照（MinIO key）───────────────────────────────

@router.post("/dramas/stills", response_model=dict, status_code=201)
async def add_drama_still(
    data: DramaStillPayload,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """为剧目添加一张剧照（封面/剧照由人工上传 MinIO 后传 key）。"""
    d = await _resolve_drama(db, data.drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission")
    s = DramaStill(
        drama_id=d.id,
        file_key=data.file_key,
        sort_order=data.sort_order or 0,
    )
    db.add(s)
    await db.flush()
    return {"id": str(s.id), "file_key": s.file_key, "sort_order": s.sort_order}


@router.delete("/dramas/stills/{still_id}", status_code=204)
async def delete_drama_still(
    still_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除一张剧照。"""
    try:
        sid = uuid.UUID(still_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid still ID")
    result = await db.execute(select(DramaStill).where(DramaStill.id == sid))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Still not found")
    d = await _resolve_drama(db, str(s.drama_id))
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission")
    await db.delete(s)
    await db.flush()
    return None


@router.post("/dramas/image-upload", response_model=dict)
async def upload_drama_image(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """上传剧目封面/剧照图片，存入 MinIO（raw-footage 桶 drama/ 前缀）。

    返回 file_key，前端将其分别作为 `cover_file_key` / 剧照 file_key 提交。
    """
    raw_name = file.filename or ""
    safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="empty file name")

    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        raise HTTPException(status_code=400, detail="剧目图片仅支持图片文件（png/jpg/jpeg/webp/gif/bmp）")

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/drama_upload/{upload_id}_{safe_name}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    size = 0
    with open(local_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.UPLOAD_MAX_SIZE:
                out.close()
                os.unlink(local_path)
                raise HTTPException(status_code=413, detail="文件超过大小上限")
            out.write(chunk)

    if size == 0:
        os.unlink(local_path)
        raise HTTPException(status_code=400, detail="文件为空")

    # 剧目图片存 raw-footage 桶 drama/ 前缀
    file_key = f"drama/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW,
        file_key,
        local_path,
        content_type=file.content_type or "image/png",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="剧目图片上传存储失败")

    return {
        "file_name": safe_name,
        "file_key": file_key,
        "file_size": size,
        "upload_id": upload_id,
    }


# ─────────────────────────────── 剧目↔视频号关联 ───────────────────────────────

@router.post("/dramas/{drama_id}/accounts", response_model=dict)
async def link_drama_accounts(
    drama_id: str,
    data: DramaLinkAccounts,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """为剧目批量关联视频号（一剧多号）。"""
    d = await _resolve_drama(db, drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission")
    await _associate_accounts(db, d.id, data.account_ids)
    await db.flush()
    result = await db.execute(select(DramaAccount.account_id).where(DramaAccount.drama_id == d.id))
    return {"account_ids": [str(x) for x in result.scalars().all()]}


# ─────────────────────────────── 剧目导入（diff 预览 + 询问确认）───────────────────────────────

class DramaImportRow(BaseModel):
    """单条导入数据（由前端解析 Excel 后逐行映射为结构化数组）。

    与表格字段一一对应：name 为去重键；synopsis/封面/剧照由人工在导入后补录。
    """
    name: str
    frequency: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    rating: Optional[str] = None
    listing_status: str = "已上架"
    updated_date: Optional[str] = None
    listed_at: Optional[str] = None
    material_link: Optional[str] = None
    material_link_pwd: Optional[str] = None
    account_name: Optional[str] = None  # 上架账号名（映射到 VideoAccount）


class DramaImportRequest(BaseModel):
    rows: List[DramaImportRow]
    file_name: Optional[str] = None


class DramaImportConfirmItem(BaseModel):
    """confirm 时的一条确定项：携带 id（update 时=drama 主键，new 时为空）+ 完整字段。

    由前端把 import_preview 里用户勾选的 new/update 行携带到这里，保证 confirm 自包含，
    后端据此执行真实的写入/更新（新字段值来自本 payload，而非预览时的内存状态）。
    """
    id: Optional[str] = None  # update 时必填 = preview update[].id
    name: str
    frequency: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    rating: Optional[str] = None
    synopsis: Optional[str] = None
    listing_status: str = "已上架"
    updated_date: Optional[str] = None
    listed_at: Optional[str] = None
    material_link: Optional[str] = None
    material_link_pwd: Optional[str] = None
    account_name: Optional[str] = None


class DramaImportConfirm(BaseModel):
    accept_new: List[DramaImportConfirmItem] = []
    accept_update: List[DramaImportConfirmItem] = []
    file_name: Optional[str] = None


def _row_key(row: DramaImportRow) -> str:
    """行去重键：name 唯一（本表 name 全唯一，主键用 name）。"""
    return row.name.strip()


def _diff_fields(old: Drama, row: DramaImportRow) -> dict:
    """对比旧值与新值，返回差异字段的旧值vs新值。"""
    diffs = {}
    mapping = [
        ("frequency", "frequency"),
        ("type", "type"),
        ("rating", "rating"),
        ("synopsis", "synopsis"),
        ("listing_status", "listing_status"),
        ("material_link", "material_link"),
    ]
    for attr, field in mapping:
        new_val = getattr(row, field)
        old_val = getattr(old, field)
        if new_val is not None and new_val != old_val:
            diffs[field] = {"old": old_val, "new": new_val}
    if row.tags is not None and list(row.tags) != (list(old.tags) if old.tags else []):
        diffs["tags"] = {"old": list(old.tags) if old.tags else [], "new": list(row.tags)}
    return diffs


@router.post("/dramas/import/preview", response_model=dict)
async def drama_import_preview(
    data: DramaImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """导入预览：以 name 为去重键，返回 new / update / unchanged 三组。

    - new[]：待新增（名称不在库中）
    - update[]：待更新（名称命中，逐条给出 旧值vs新值 diff）
    - unchanged[]：名称命中且各字段一致（默认跳过，前端可勾选强制覆盖）
    """
    if not data.rows:
        raise HTTPException(status_code=400, detail="导入数据为空")

    new = []
    update = []
    unchanged = []
    existing_names = {}
    result = await db.execute(select(Drama).where(Drama.name.in_([_row_key(r) for r in data.rows])))
    for d in result.scalars().all():
        existing_names[d.name] = d

    for row in data.rows:
        key = _row_key(row)
        old = existing_names.get(key)
        if old is None:
            new.append({
                "name": key,
                "fields": {
                    "frequency": row.frequency,
                    "type": row.type,
                    "tags": row.tags,
                    "rating": row.rating,
                    "listing_status": row.listing_status,
                    "updated_date": row.updated_date,
                    "listed_at": row.listed_at,
                    "material_link": row.material_link,
                    "account_name": row.account_name,
                },
            })
        else:
            diffs = _diff_fields(old, row)
            if diffs:
                update.append({
                    "id": str(old.id),
                    "code": old.code,
                    "name": key,
                    "diff": diffs,
                })
            else:
                unchanged.append({"id": str(old.id), "code": old.code, "name": key})

    return {
        "new": new,
        "update": update,
        "unchanged": unchanged,
        "summary": {
            "new_count": len(new),
            "update_count": len(update),
            "unchanged_count": len(unchanged),
        },
        # 前端展示提示
        "message": "请核对新增/更新项后确认；未勾选的项不落库。",
    }


@router.post("/dramas/import/parse", response_model=dict)
async def drama_import_parse(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """上传剧目 Excel 文件并解析为结构化行（供前端调用 /dramas/import/preview）。

    列名对齐《剧目管理设计方案》数据底座表（漫剧名称/更新日期/男/女频/题材/漫剧类型/
    上架状态/上架日期/评级/素材链接/上架账号）。题材列按 /、, 分隔拆成标签数组。
    返回 DramaImportRow 数组，前端原样传给 preview。
    """
    import io as _io

    try:
        import pandas as pd  # 与 smart_import_service 一致
    except Exception:
        raise HTTPException(status_code=500, detail="服务端缺少 pandas，无法解析 Excel")

    raw_name = file.filename or ""
    safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls / .csv")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        df = pd.read_excel(_io.BytesIO(file_bytes), engine="openpyxl").fillna("")
    except Exception:
        try:
            df = pd.read_csv(_io.BytesIO(file_bytes)).fillna("")
        except Exception:
            raise HTTPException(status_code=400, detail="Excel 解析失败，请检查文件格式")

    # 列名 → 目标字段映射（模糊匹配表头）
    def _norm(v: str) -> str:
        return str(v).strip().replace("\u00a0", " ").replace("\ufeff", "")

    cols = {_norm(c): str(c) for c in df.columns}

    def _find(*keys: str):
        for k in keys:
            for norm, orig in cols.items():
                if k in norm:
                    return orig
        return None

    col_name = _find("漫剧名称") or _find("名称") or _find("剧名")
    col_update = _find("更新日期")
    col_freq = _find("男/女频") or _find("男女频") or _find("频")
    col_type = _find("漫剧类型") or _find("剧类型")
    col_tags = _find("题材")
    col_status = _find("上架状态")
    col_listed = _find("上架日期")
    col_rating = _find("评级")
    col_link = _find("素材链接")
    col_account = _find("上架账号")

    rows = []
    for _, row in df.iterrows():
        name = _norm(row.get(col_name, "")) if col_name else ""
        if not name:
            continue  # 跳过空行
        tags_raw = _norm(row.get(col_tags, "")) if col_tags else ""
        tags = [t for t in [x.strip() for x in tags_raw.replace(";", "/").replace("，", "/").split("/")] if t] if tags_raw else None
        rows.append({
            "name": name,
            "frequency": _norm(row.get(col_freq, "")) if col_freq else None,
            "type": _norm(row.get(col_type, "")) if col_type else None,
            "tags": tags,
            "rating": _norm(row.get(col_rating, "")) if col_rating else None,
            "listing_status": _norm(row.get(col_status, "")) if col_status else "已上架",
            "updated_date": _norm(row.get(col_update, "")) if col_update else None,
            "listed_at": _norm(row.get(col_listed, "")) if col_listed else None,
            "material_link": _norm(row.get(col_link, "")) if col_link else None,
            "account_name": _norm(row.get(col_account, "")) if col_account else None,
        })

    if not rows:
        raise HTTPException(status_code=400, detail="未识别到有效数据行（缺少「漫剧名称」列或全为空行）")

    return {"rows": rows, "total": len(rows), "file_name": safe_name, "message": f"解析到 {len(rows)} 条剧目"}


@router.post("/dramas/import/confirm", response_model=dict)
async def drama_import_confirm(
    data: DramaImportConfirm,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """导入确认：仅对用户勾选项执行真实的写入/更新；未勾选跳过；记录导入历史支持回滚。

    accept_new / accept_update 均由前端把 import_preview 里用户勾选的行携带到这里
    （含完整字段值），后端据此执行新增或更新。以 `name` 为去重键：
    - accept_new 项按 name 新增（同名已存在则跳过）并自动生成 DR-<8位HEX> code；
    - accept_update 项按 id 定位既有剧目，将 payload 新值覆盖旧值（diff 已在 preview 展示）。
    """
    imported = 0
    updated = 0
    skipped = 0
    errors = []

    created_by = current_user.id if current_user else None
    operator_id = current_user.id if current_user else None

    # 1) 处理新增
    for item in data.accept_new:
        name = (item.name or "").strip()
        if not name:
            skipped += 1
            continue
        existing = await db.execute(select(Drama).where(Drama.name == name))
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        code = gen_drama_code()
        for _ in range(5):
            dup = await db.execute(select(Drama).where(Drama.code == code))
            if not dup.scalar_one_or_none():
                break
            code = gen_drama_code()
        d = Drama(
            code=code,
            name=name,
            frequency=item.frequency,
            type=item.type,
            tags=item.tags,
            rating=item.rating,
            synopsis=item.synopsis,
            listing_status=item.listing_status,
            material_link=item.material_link,
            material_link_pwd=item.material_link_pwd,
            created_by=created_by,
            operator_id=operator_id,
        )
        if item.updated_date:
            d.updated_date = _parse_date(item.updated_date)
        if item.listed_at:
            d.listed_at = _parse_dt(item.listed_at)
        db.add(d)
        imported += 1

    # 2) 处理更新（按 id 定位，应用新值）
    for item in data.accept_update:
        raw_id = item.id
        if not raw_id:
            errors.append({"name": item.name, "error": "missing id for update"})
            continue
        try:
            did = uuid.UUID(raw_id)
        except ValueError:
            errors.append({"id": raw_id, "error": "invalid id"})
            continue
        result = await db.execute(select(Drama).where(Drama.id == did))
        d = result.scalar_one_or_none()
        if not d:
            errors.append({"id": raw_id, "error": "not found"})
            continue
        if not _can_manage(d, current_user):
            errors.append({"id": raw_id, "error": "no permission"})
            continue
        # 应用新值（name 冲突保护）
        new_name = (item.name or "").strip()
        if new_name and new_name != d.name:
            name_dup = await db.execute(
                select(Drama).where(Drama.name == new_name, Drama.id != d.id)
            )
            if name_dup.scalar_one_or_none():
                errors.append({"id": raw_id, "error": f"name conflict: {new_name}"})
                continue
            d.name = new_name
        d.frequency = item.frequency
        d.type = item.type
        d.tags = item.tags
        d.rating = item.rating
        d.synopsis = item.synopsis
        d.listing_status = item.listing_status
        d.material_link = item.material_link
        d.material_link_pwd = item.material_link_pwd
        if item.updated_date:
            d.updated_date = _parse_date(item.updated_date)
        if item.listed_at:
            d.listed_at = _parse_dt(item.listed_at)
        updated += 1

    await db.flush()

    # 3) 记录导入历史（支持回滚追踪）
    history = ImportHistory(
        file_name=data.file_name or "剧目导入",
        platform="drama",
        import_mode="confirm",
        target_table="dramas",
        imported_count=imported,
        updated_count=updated,
        error_count=len(errors),
        errors=errors or None,
        operator=created_by,
    )
    db.add(history)

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "import_history_id": str(history.id) if history.id else None,
    }


# ─────────────────────────────── 发布联动（选剧目→带剧情简介→挂素材）───────────────────────────────

@router.get("/dramas/{drama_id}/publish-context", response_model=dict)
async def get_drama_publish_context(
    drama_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """发布弹窗取剧目发布上下文：剧情简介 story + 题材 tags（用于一键生成发布素材）。"""
    d = await _resolve_drama(db, drama_id)
    return {
        "drama_id": str(d.id),
        "code": d.code,
        "name": d.name,
        "story": d.synopsis or "",
        "tags": list(d.tags) if d.tags else [],
        "has_synopsis": bool(d.synopsis and d.synopsis.strip()),
    }


class DramaMaterialLink(BaseModel):
    drama_id: str
    material_id: str
    account_id: Optional[str] = None


@router.post("/dramas/materials/link", response_model=dict, status_code=201)
async def link_drama_material(
    data: DramaMaterialLink,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """发布弹窗生成发布素材后，建立 剧目↔发布素材 关联（drama_materials）。

    由前端在调用 `/shortdrama/publish-material/generate`（save=true）拿到 record_id 后调用。
    """
    d = await _resolve_drama(db, data.drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission")
    try:
        mid = uuid.UUID(data.material_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid material_id")
    account_uuid = uuid.UUID(data.account_id) if data.account_id else None
    dm = DramaMaterial(
        drama_id=d.id,
        material_id=mid,
        account_id=account_uuid,
    )
    db.add(dm)
    await db.flush()
    return {"id": str(dm.id), "drama_id": str(d.id), "material_id": str(mid)}


# ─────────────────────────────── 剧集维度打通切片产线 ───────────────────────────────

class DramaLinkEpisodes(BaseModel):
    """将剧集关联到剧目（set 语义：传入全集即替换）。"""
    episode_ids: List[str]


@router.post("/dramas/{drama_id}/episodes", response_model=dict)
async def link_drama_episodes(
    drama_id: str,
    data: DramaLinkEpisodes,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """剧集维度打通切片产线：将指定剧集关联到剧目（一剧多集）。

    set 语义：传入的 episode_ids 全集替换该剧目下已关联的剧集（传入空列表即清空关联）。
    数据隔离：剧集须为当前用户可访问（数据范围校验），operator 仅可关联自己创建的剧集。
    """
    d = await _resolve_drama(db, drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission to manage this drama")

    # 解析并校验剧集存在（且当前用户可访问）
    ep_ids = []
    seen = set()
    for raw in data.episode_ids:
        try:
            eid = uuid.UUID(raw)
        except ValueError:
            continue
        if eid in seen:
            continue
        seen.add(eid)
        ep = (await db.execute(select(Episode).where(Episode.id == eid))).scalar_one_or_none()
        if not ep:
            raise HTTPException(status_code=404, detail=f"Episode not found: {raw}")
        if current_user and not user_can_access_all_materials(current_user):
            # 剧集通过项目归属做数据隔离
            from app.services.data_scope import check_project_access_by_episode
            if not check_project_access_by_episode(ep.project_id, current_user):
                raise HTTPException(status_code=403, detail=f"No permission to link episode: {raw}")
        ep_ids.append(eid)

    # set 语义：先把该剧目下已关联的剧集解绑，再绑定新全集
    from sqlalchemy import update
    await db.execute(
        update(Episode)
        .where(Episode.drama_id == d.id)
        .values(drama_id=None)
        .execution_options(synchronize_session=False)
    )
    if ep_ids:
        await db.execute(
            update(Episode)
            .where(Episode.id.in_(ep_ids))
            .values(drama_id=d.id)
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    # commit 后实例过期，重新预加载关系再序列化（避免 async 会话同步访问 lazy 关系触发 MissingGreenlet）
    result = await db.execute(
        select(Drama)
        .where(Drama.id == d.id)
        .options(
            selectinload(Drama.stills),
            selectinload(Drama.accounts),
            selectinload(Drama.episodes),
        )
    )
    d = result.scalar_one()
    return await _serialize_drama_detail(d)


@router.get("/dramas/{drama_id}/slice-status", response_model=dict)
async def get_drama_slice_status(
    drama_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """剧集维度打通切片产线：剧目级切片产线状态聚合。

    汇总该剧目下所有关联剧集在「选点 autoclip / 区间检测 detect / 切片 slice」
    三个阶段的实时状态，输出每集明细 + 整体进度，供剧目详情展示「该剧已切片/待切片」。
    """
    d = await _resolve_drama(db, drama_id)
    if not _can_manage(d, current_user):
        raise HTTPException(status_code=403, detail="No permission to view this drama")

    episodes = (
        await db.execute(
            select(Episode)
            .where(Episode.drama_id == d.id)
            .order_by(Episode.episode_no, Episode.created_at)
        )
    ).scalars().all()
    ep_ids = [e.id for e in episodes]

    autoclip_runs = []
    slice_tasks = []
    detect_counts = {}
    if ep_ids:
        autoclip_runs = (
            await db.execute(
                select(AutoClipRun)
                .where(AutoClipRun.episode_id.in_(ep_ids))
                .order_by(AutoClipRun.created_at)
            )
        ).scalars().all()
        slice_tasks = (
            await db.execute(
                select(SliceTask)
                .where(SliceTask.episode_id.in_(ep_ids))
                .where(_not_detect_task())
                .order_by(SliceTask.created_at)
            )
        ).scalars().all()
        detect_rows = (
            await db.execute(
                select(SliceTask.episode_id, func.count())
                .where(SliceTask.episode_id.in_(ep_ids))
                .where(SliceTask.mode.like("detect_%"))
                .group_by(SliceTask.episode_id)
            )
        ).all()
        detect_counts = {str(r[0]): r[1] for r in detect_rows}

    def _stage_status(status):
        s = (status or "pending").lower()
        if s in ("completed", "success"):
            return "completed"
        if s in ("failed", "cancelled"):
            return "failed"
        if s in ("running", "processing", "uploading"):
            return "running"
        if s in ("pending", "parsing", "downloading", "queued"):
            return "pending"
        return "unknown"

    episodes_payload = []
    slice_done = 0
    for ep in episodes:
        eid = ep.id
        run = next((r for r in autoclip_runs if r.episode_id == eid), None)
        task = next((t for t in slice_tasks if t.episode_id == eid), None)
        detect_count = detect_counts.get(str(eid), 0)
        detect_status = "completed" if detect_count > 0 else "pending"
        slice_status = _stage_status(task.status if task else None)
        if slice_status == "completed":
            slice_done += 1

        episodes_payload.append({
            "episode_id": str(eid),
            "title": ep.title,
            "episode_no": ep.episode_no,
            "source_file_key": ep.source_file_key,
            "status": ep.status,
            "stages": {
                "autoclip": {
                    "status": _stage_status(run.status if run else None),
                    "progress": (run.progress or 0) if run else 0,
                    "run_count": sum(1 for r in autoclip_runs if r.episode_id == eid),
                },
                "detect": {
                    "status": detect_status,
                    "progress": 100.0 if detect_status == "completed" else 0,
                    "interval_count": detect_count,
                },
                "slice": {
                    "status": slice_status,
                    "progress": (task.progress or 0) if task else 0,
                    "task_count": sum(1 for t in slice_tasks if t.episode_id == eid),
                    "output_count": task.output_count if task else 0,
                },
            },
            # 该集是否已切片（切片任务完成且产出非空）
            "sliced": slice_status == "completed" and bool(task and task.output_count > 0),
            "pending": slice_status in ("pending", "unknown", "running") or task is None,
        })

    total = len(episodes)
    return {
        "drama_id": str(d.id),
        "code": d.code,
        "name": d.name,
        "total_episodes": total,
        "sliced_count": slice_done,
        "pending_count": total - slice_done,
        "progress_percent": round((slice_done / total * 100), 1) if total else 0,
        "episodes": episodes_payload,
    }


# ─────────────────────────────── 工具 ───────────────────────────────

def _parse_date(s: str):
    from datetime import date
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _parse_dt(s: str):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None
