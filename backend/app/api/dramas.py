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
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import (
    Drama,
    DramaStill,
    DramaAccount,
    DramaMaterial,
    User,
    ImportHistory,
    user_can_access_all_materials,
    gen_drama_code,
)
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

def _serialize_drama(d: Drama) -> dict:
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


def _serialize_drama_detail(d: Drama) -> dict:
    data = _serialize_drama(d)
    data["stills"] = [
        {"id": str(s.id), "file_key": s.file_key, "sort_order": s.sort_order}
        for s in d.stills
    ]
    data["account_ids"] = [str(a.account_id) for a in d.accounts]
    return data


# ─────────────────────────────── Helpers ───────────────────────────────

async def _resolve_drama(db: AsyncSession, drama_id: str) -> Drama:
    try:
        did = uuid.UUID(drama_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid drama ID format")
    result = await db.execute(select(Drama).where(Drama.id == did))
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
    return [_serialize_drama(d) for d in dramas]


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
    await db.refresh(d)
    return _serialize_drama_detail(d)


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
    return _serialize_drama_detail(d)


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
    return _serialize_drama_detail(d)


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
