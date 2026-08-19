"""多视频号素材去重：变体矩阵看板与运营控制 API（圆桌定稿 Phase 2 可观测）。

提供：
- 变体矩阵列表（按变体组聚合，展示各变体状态 / 指纹距离 / 撞车标记 / 账号绑定）
- 变体详情（含指纹与配方）
- 手动触发变体生成（对已有切片输出）
- 发布前指纹复核
- 撞车阈值运营可调（system_config.variant_thresholds）
- 变体 ↔ 账号绑定分配（一账号一变体硬约束）

设计：variant_count=1 或未生成变体时，接口零侵入返回空/单基准，不影响既有流程。
"""
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.auth import get_current_user
from app.config import settings
from app.database import async_session_factory, get_db
from app.models.models import (
    SliceOutput,
    SliceTask,
    Episode,
    ClipVariant,
    VideoFingerprint,
    SystemConfig,
    User,
    Project,
    user_can_access_all_materials,
)
from app.models.drama import Drama
from app.services.minio_service import get_presigned_url

router = APIRouter()

# 撞车阈值默认（可经 system_config.variant_thresholds 覆盖）
DEFAULT_THRESHOLDS = {
    "phash": 0.20,
    "audio": 0.15,
    "seg": 0.30,
    "combined": 0.15,
}


class VariantGenerateRequest(BaseModel):
    output_id: str
    count: int = 3
    dedupe_config: Optional[dict] = None
    thresholds: Optional[dict] = None


class VariantBindRequest(BaseModel):
    variant_id: str
    account_id: Optional[str] = None


async def _get_thresholds() -> dict:
    async with async_session_factory() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "variant_thresholds")
        )
        cfg = result.scalar_one_or_none()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 cfg 被 expire，会话外访问 cfg.value 抛 DetachedInstanceError（#230）。
    if cfg and isinstance(cfg.value, dict):
        merged = dict(DEFAULT_THRESHOLDS)
        merged.update(cfg.value)
        return merged
    return dict(DEFAULT_THRESHOLDS)


async def _list_variant_groups() -> list[dict]:
    async with async_session_factory() as session:
        outputs = (await session.execute(
            select(SliceOutput)
            .where(SliceOutput.variant_group_id.isnot(None))
            .order_by(SliceOutput.created_at.desc())
            .limit(100)
        )).scalars().all()
        groups = {}
        for out in outputs:
            vg = str(out.variant_group_id)
            variants = (await session.execute(
                select(ClipVariant).where(ClipVariant.variant_group_id == out.variant_group_id)
            )).scalars().all()
            groups[vg] = {
                "variant_group_id": vg,
                "base_output_id": str(out.id),
                "base_file_name": out.file_name,
                "created_at": out.created_at.isoformat() if out.created_at else "",
                "variants": [{
                    "id": str(v.id),
                    "variant_index": v.variant_index,
                    "status": v.status,
                    "file_name": v.file_name,
                    "file_key": v.file_key,
                    "phash_distance": v.phash_distance,
                    "audio_distance": v.audio_distance,
                    "seg_distance": v.seg_distance,
                    "structural_diff": v.structural_diff,
                    "collision": v.collision,
                    "collision_reason": v.collision_reason,
                    "account_id": str(v.account_id) if v.account_id else None,
                    "created_at": v.created_at.isoformat() if v.created_at else "",
                } for v in variants],
            }
        # 事务内只读：显式结束事务
        await session.rollback()
    return list(groups.values())


@router.get("/variant-matrix")
async def variant_matrix(
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """变体矩阵看板：按变体组聚合展示各变体状态 / 指纹距离 / 撞车标记 / 账号绑定。"""
    groups = await _list_variant_groups()
    thresholds = await _get_thresholds()
    return {"variant_groups": groups, "thresholds": thresholds}


@router.get("/variants/{variant_id}")
async def variant_detail(
    variant_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """变体详情：基本信息 + 配方 + 指纹。"""
    from sqlalchemy import select as _sel
    async with async_session_factory() as session:
        v = (await session.execute(
            _sel(ClipVariant).where(ClipVariant.id == uuid_of(variant_id))
        )).scalar_one_or_none()
        if v is None:
            raise HTTPException(status_code=404, detail="variant not found")
        fps = (await session.execute(
            _sel(VideoFingerprint).where(VideoFingerprint.variant_id == v.id)
        )).scalars().all()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 v/fps 被 expire，会话外访问 v.id/v.status 等属性抛 DetachedInstanceError（#230）。
    return {
        "id": str(v.id),
        "variant_group_id": str(v.variant_group_id) if v.variant_group_id else None,
        "variant_index": v.variant_index,
        "status": v.status,
        "file_name": v.file_name,
        "file_key": v.file_key,
        "dedupe_config": v.dedupe_config,
        "structural_diff": v.structural_diff,
        "phash_distance": v.phash_distance,
        "audio_distance": v.audio_distance,
        "seg_distance": v.seg_distance,
        "collision": v.collision,
        "collision_reason": v.collision_reason,
        "account_id": str(v.account_id) if v.account_id else None,
        "fingerprints": [{
            "algorithm": f.algorithm,
            "hash_value": f.hash_value,
            "duration": f.duration,
        } for f in fps],
    }


@router.post("/variants/generate")
async def generate_variants(
    data: VariantGenerateRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """手动触发变体生成（对已有切片输出）。count=1 时零侵入。"""
    from app.celery.variant_tasks import generate_variants_task
    from sqlalchemy import select as _sel
    async with async_session_factory() as session:
        out = (await session.execute(
            _sel(SliceOutput).where(SliceOutput.id == uuid_of(data.output_id))
        )).scalar_one_or_none()
        if out is None:
            raise HTTPException(status_code=404, detail="output not found")
        # 事务内只读：显式结束事务
        await session.rollback()
    task = generate_variants_task.delay(
        data.output_id, count=data.count,
        base_dedupe=data.dedupe_config, thresholds=data.thresholds,
    )
    return {"task_id": task.id, "output_id": data.output_id, "count": data.count}


@router.post("/variants/{variant_id}/verify")
async def verify_variant(
    variant_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """发布前复核变体指纹：确认与同组其它变体拉开距离（撞车则拒绝直接发布）。"""
    from app.celery.variant_tasks import verify_variant_fingerprint_task
    thresholds = await _get_thresholds()
    result = verify_variant_fingerprint_task.apply_async(
        args=[variant_id], kwargs={"thresholds": thresholds}
    )
    # 同步等待结果（复核为轻量查询，短超时）
    try:
        res = result.get(timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"verify failed: {e}")
    return res


@router.post("/variants/{variant_id}/bind")
async def bind_variant_account(
    variant_id: str,
    data: VariantBindRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """变体 ↔ 账号绑定分配。一账号一变体硬约束（防同素材原样发多号）。"""
    from sqlalchemy import select as _sel, update
    async with async_session_factory() as session:
        v = (await session.execute(
            _sel(ClipVariant).where(ClipVariant.id == uuid_of(variant_id))
        )).scalar_one_or_none()
        if v is None:
            raise HTTPException(status_code=404, detail="variant not found")
        if data.account_id:
            # 校验账号未被其它变体占用
            occupied = (await session.execute(
                _sel(ClipVariant).where(ClipVariant.account_id == uuid_of(data.account_id))
            )).scalar_one_or_none()
            if occupied and occupied.id != v.id:
                raise HTTPException(status_code=409, detail="该账号已被其它变体绑定")
        v.account_id = uuid_of(data.account_id) if data.account_id else None
        await session.commit()
    return {"variant_id": variant_id, "account_id": data.account_id}


@router.put("/variant-thresholds")
async def update_thresholds(
    data: dict,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新撞车判定阈值（运营可调，system_config.variant_thresholds）。"""
    merged = dict(DEFAULT_THRESHOLDS)
    for k in ("phash", "audio", "seg", "combined"):
        if data.get(k) is not None:
            merged[k] = float(data[k])
    async with async_session_factory() as session:
        cfg = (await session.execute(
            select(SystemConfig).where(SystemConfig.key == "variant_thresholds")
        )).scalar_one_or_none()
        if cfg:
            cfg.value = merged
        else:
            session.add(SystemConfig(key="variant_thresholds", value=merged,
                                     description="变体撞车判定阈值（0~1）"))
        await session.commit()
    return {"thresholds": merged}


def uuid_of(v: str):
    import uuid
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid UUID format")

class VariantGenerateBatchRequest(BaseModel):
    output_ids: List[str]
    count: int = 3
    dedupe_config: Optional[dict] = None
    thresholds: Optional[dict] = None


class SliceOutputListRequest(BaseModel):
    page: int = 1
    page_size: int = 50
    keyword: Optional[str] = None


@router.post("/variants/generate-batch")
async def generate_variants_batch(
    data: VariantGenerateBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """批量变体生成（去重处理入口）：对多个切片输出各生成 N 套变体。

    比前端逐个循环 /variants/generate 更稳：单次请求投递全部任务、
    统一去重配置与变体数量，避免前端循环因网络抖动/超时部分漏发。
    count=1 时对单个输出零侵入。
    """
    if not data.output_ids:
        raise HTTPException(status_code=400, detail="output_ids 不能为空")
    if len(data.output_ids) > 200:
        raise HTTPException(status_code=400, detail="单次最多处理 200 个切片输出")
    count = max(1, min(int(data.count or 1), 20))  # 硬上限 MAX_VARIANTS=20

    from app.celery.variant_tasks import generate_variants_task
    from sqlalchemy import select as _sel
    tasks = []
    async with async_session_factory() as session:
        for raw_id in data.output_ids:
            try:
                out_id = uuid_of(raw_id)
            except HTTPException:
                continue  # 非法 UUID 直接跳过，不阻断整批
            out = (await session.execute(
                _sel(SliceOutput).where(SliceOutput.id == out_id)
            )).scalar_one_or_none()
            if out is None:
                continue  # 不存在的输出跳过，不阻断整批
            # 数据隔离：校验当前用户对输出所属项目的访问权限；
            # 无权限的输出直接跳过（不抛 404 中断整批，也不泄露存在性）
            try:
                await _check_output_access(session, out, current_user)
            except HTTPException:
                continue
            task = generate_variants_task.delay(
                str(out.id), count=count,
                base_dedupe=data.dedupe_config, thresholds=data.thresholds,
            )
            tasks.append({"output_id": str(out.id), "task_id": task.id})
        # 事务内只读：显式结束事务
        await session.rollback()

    if not tasks:
        raise HTTPException(status_code=404, detail="没有找到任何可处理的切片输出")
    return {"tasks": tasks, "count": count, "total": len(tasks)}


async def _check_output_access(session, out: SliceOutput, current_user: User):
    """数据隔离：校验当前用户对某个切片输出所属剧集/项目的访问权限。

    与 preview 等接口一致：all 范围用户放行；否则校验 project.created_by。
    """
    if current_user is None or user_can_access_all_materials(current_user):
        return
    task = (await session.execute(
        select(SliceTask).where(SliceTask.id == out.task_id)
    )).scalar_one_or_none()
    if not task:
        return
    episode = (await session.execute(
        select(Episode).where(Episode.id == task.episode_id)
    )).scalar_one_or_none()
    if not episode:
        return
    await check_project_access_by_episode(session, episode, current_user)


@router.get("/dedupe/slice-outputs")
async def list_slice_outputs(
    page: int = 1,
    page_size: int = 50,
    keyword: Optional[str] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """列出全部已切片输出（去重处理入口：从已切片任务多选 SliceOutput）。

    数据隔离：all 范围用户见全部；运营专员仅见自己项目下的输出。
    返回带 presigned_url，供前端直接预览/下载。
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 200))

    async with async_session_factory() as session:
        # ── 数据隔离：非 all 用户先收集可访问的 project → episode 集合 ──
        allowed_episode_ids = None
        if current_user is not None and not user_can_access_all_materials(current_user):
            projects = (await session.execute(
                select(Project).where(Project.created_by == current_user.id)
            )).scalars().all()
            allowed_project_ids = [p.id for p in projects]
            episodes = (await session.execute(
                select(Episode).where(Episode.project_id.in_(allowed_project_ids))
            )).scalars().all() if allowed_project_ids else []
            allowed_episode_ids = [e.id for e in episodes]

        # ── 关键词搜索：匹配 project_name / episode_title / file_name（模糊）──
        conds = []
        if keyword:
            # 命中项目名 → 该项目的 episode_id 集合
            kw_projects = (await session.execute(
                select(Project.id).where(Project.name.ilike(f"%{keyword}%"))
            )).scalars().all()
            kw_episode_ids = set()
            if kw_projects:
                kw_episode_ids.update((await session.execute(
                    select(Episode.id).where(Episode.project_id.in_(kw_projects))
                )).scalars().all())
            # 命中剧集名 → 对应 episode_id
            kw_episode_ids.update((await session.execute(
                select(Episode.id).where(Episode.title.ilike(f"%{keyword}%"))
            )).scalars().all())
            kw_task_ids = set()
            if kw_episode_ids:
                kw_task_ids.update((await session.execute(
                    select(SliceTask.id).where(SliceTask.episode_id.in_(kw_episode_ids))
                )).scalars().all())
            conds.append(or_(
                SliceOutput.file_name.ilike(f"%{keyword}%"),
                SliceOutput.task_id.in_(kw_task_ids) if kw_task_ids else False,
            ))

        # ── 数据隔离：限制到可访问剧集下的切片任务 ──
        if allowed_episode_ids is not None:
            tasks = (await session.execute(
                select(SliceTask).where(SliceTask.episode_id.in_(allowed_episode_ids))
            )).scalars().all()
            task_ids = [t.id for t in tasks]
            conds.append(SliceOutput.task_id.in_(task_ids))

        if conds:
            total = (await session.execute(
                select(SliceOutput.id).where(*conds)
            )).scalars().all()
            total_count = len(total)
        else:
            total_count = (await session.execute(
                select(SliceOutput.id)
            )).scalars().all().__len__()

        if conds:
            outputs = (await session.execute(
                select(SliceOutput)
                .where(*conds)
                .order_by(SliceOutput.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )).scalars().all()
        else:
            outputs = (await session.execute(
                select(SliceOutput)
                .order_by(SliceOutput.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )).scalars().all()

        # ── 逐条补齐 task → episode → project → drama 元数据 ──
        tasks = (await session.execute(
            select(SliceTask).where(SliceTask.id.in_([o.task_id for o in outputs]))
        )).scalars().all() if outputs else []
        task_map = {t.id: t for t in tasks}
        episode_ids = [t.episode_id for t in tasks if t.episode_id]
        episodes = (await session.execute(
            select(Episode).where(Episode.id.in_(episode_ids))
        )).scalars().all() if episode_ids else []
        episode_map = {e.id: e for e in episodes}
        project_ids = [e.project_id for e in episodes if e.project_id]
        projects = (await session.execute(
            select(Project).where(Project.id.in_(project_ids))
        )).scalars().all() if project_ids else []
        project_map = {p.id: p for p in projects}
        drama_ids = [e.drama_id for e in episodes if e.drama_id]
        dramas = (await session.execute(
            select(Drama).where(Drama.id.in_(drama_ids))
        )).scalars().all() if drama_ids else []
        drama_map = {d.id: d for d in dramas}

        # ── 组装分组结构：project → episodes → outputs ──
        groups = []
        project_index = {}  # project_id -> groups idx
        episode_index = {}  # (project_id, episode_id) -> episodes idx
        for out in outputs:
            url = None
            if out.file_key:
                url = await get_presigned_url(
                    settings.MINIO_BUCKET_SLICED, out.file_key, expires_seconds=3600
                )
            item = {
                "id": str(out.id),
                "task_id": str(out.task_id),
                "file_name": out.file_name,
                "file_key": out.file_key,
                "duration": out.duration,
                "file_size": out.file_size,
                "resolution": out.resolution,
                "variant_group_id": str(out.variant_group_id) if out.variant_group_id else None,
                "created_at": out.created_at.isoformat() if out.created_at else "",
                "presigned_url": url,
            }
            task = task_map.get(out.task_id)
            episode = episode_map.get(task.episode_id) if task and task.episode_id else None
            project = project_map.get(episode.project_id) if episode and episode.project_id else None
            drama = drama_map.get(episode.drama_id) if episode and episode.drama_id else None

            pid = str(project.id) if project else ""
            if pid not in project_index:
                project_index[pid] = len(groups)
                groups.append({
                    "project_id": pid or None,
                    "project_name": project.name if project else "未分类",
                    "episodes": [],
                })
            g_idx = project_index[pid]
            eid = str(episode.id) if episode else ""
            ekey = (pid, eid)
            if ekey not in episode_index:
                episode_index[ekey] = len(groups[g_idx]["episodes"])
                groups[g_idx]["episodes"].append({
                    "episode_id": eid or None,
                    "episode_title": (episode.title if episode and episode.title else "未分类"),
                    "drama_name": drama.name if drama else None,
                    "outputs": [],
                })
            groups[g_idx]["episodes"][episode_index[ekey]]["outputs"].append(item)

        # 事务内只读：显式结束事务
        await session.rollback()

    return {"groups": groups, "total": total_count, "page": page, "page_size": page_size}


