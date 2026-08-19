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
from sqlalchemy import select

from app.auth import get_current_user
from app.database import async_session_factory, get_db
from app.models.models import (
    SliceOutput,
    ClipVariant,
    VideoFingerprint,
    SystemConfig,
    User,
)

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
