import os
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from app.database import async_session_factory
from app.config import settings
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.slice_helpers import _refresh_episode_status
from app.auth import get_current_user
from app.database import get_db
from app.models.models import (
    Episode,
    AutoClipProject,
    ClipCandidate,
    AutoClipRun,
    DetectedInterval,
    SliceOutput,
    User,
    SystemConfig,
)
from app.services.data_scope import check_project_access_by_episode
from app.services.autoclip_service import (
    create_autoclip_project,
    upload_video,
    get_pipeline_progress,
    get_clips,
    check_autoclip_health,
    delete_autoclip_project,
)
from app.celery.tasks import autoclip_task as celery_autoclip_task
from app.utils.helpers import utc_iso

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


async def _merge_default_autoclip_config(db, config: Optional[dict]) -> dict:
    """合并系统设置 default_autoclip_config 到本次选点 config。

    - 系统设置（default_autoclip_config.llm_model / llm_provider / min_score_threshold 等）
      作为默认值打底；
    - 请求体传入的 config 字段（前端/批量任务覆盖）优先生效。
    这样在“系统设置”里修改模型名/评分阈值能真正作用于选点引擎。
    """
    base: dict = {}
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "default_autoclip_config")
        )
        cfg = result.scalar_one_or_none()
        if cfg and isinstance(cfg.value, dict):
            base = dict(cfg.value)
    except Exception as e:
        logger.warning("读取系统设置 default_autoclip_config 失败，使用请求参数: %s", e)

    # 并入在线 LLM 网关配置（llm_config）：把 llm_api_base / llm_model / llm_api_key
    # 平铺进选点 config，供 trigger_pipeline 透传给 AutoClip 覆盖环境变量。
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "llm_config")
        )
        llm_cfg = result.scalar_one_or_none()
        if llm_cfg and isinstance(llm_cfg.value, dict):
            for k, v in llm_cfg.value.items():
                if v not in (None, ""):
                    base[k] = v  # 覆盖语义：系统 llm_config（网关/模型/key）优先于 default_autoclip_config
    except Exception as e:
        logger.warning("读取系统设置 llm_config 失败，使用请求参数: %s", e)

    # 并入画面理解配置（frame_analysis_config）：把 provider/model/vision_base/vision_api_key
    # 平铺进选点 config，供 trigger_pipeline 透传给 AutoClip。
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "frame_analysis_config")
        )
        fa_cfg = result.scalar_one_or_none()
        if fa_cfg and isinstance(fa_cfg.value, dict):
            fa_val = dict(fa_cfg.value)
            # provider -> frame_analysis_provider（与现有前端字段对齐）
            if fa_val.get("provider"):
                base.setdefault("frame_analysis_provider", fa_val["provider"])
            if fa_val.get("model"):
                base.setdefault("frame_analysis_model", fa_val["model"])
            if fa_val.get("vision_base"):
                base.setdefault("vision_base", fa_val["vision_base"])
            if fa_val.get("vision_api_key"):
                base.setdefault("vision_api_key", fa_val["vision_api_key"])
    except Exception as e:
        logger.warning("读取系统设置 frame_analysis_config 失败，使用请求参数: %s", e)

    if not isinstance(config, dict):
        config = {}
    merged = dict(base)
    merged.update(config)
    return merged



@router.get("/autoclip/llm-models")
async def list_llm_models(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """返回系统设置 llm_config.models 模型仓库（不含密钥），供选点界面下拉。"""
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == "llm_config"))
    cfg = result.scalar_one_or_none()
    entries = (
        cfg.value.get("models") if cfg and isinstance(cfg.value, dict) else None
    ) or []
    return [
        {"name": e.get("name"), "model": e.get("model"), "api_base": e.get("api_base")}
        for e in entries
        if isinstance(e, dict) and e.get("name") and e.get("model")
    ]


@router.post("/autoclip/llm-models")
async def save_llm_model(
    payload: dict,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """新增/更新一个命名模型进仓库（llm_config.models）。同名=覆盖。"""
    name = (payload.get("name") or "").strip()
    model = (payload.get("model") or "").strip()
    if not name or not model:
        raise HTTPException(status_code=400, detail="名称与模型名必填")
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == "llm_config"))
    cfg = result.scalar_one_or_none()
    base = dict(cfg.value) if cfg and isinstance(cfg.value, dict) else {}
    models = [m for m in (base.get("models") or []) if isinstance(m, dict)]
    old_key = next((m.get("api_key") for m in models if m.get("name") == name), "")
    entry = {
        "name": name,
        "model": model,
        "api_base": (payload.get("api_base") or "").strip(),
        "api_key": (payload.get("api_key") or "").strip() or (old_key or ""),
    }
    models = [m for m in models if m.get("name") != name]
    models.append(entry)
    base["models"] = models
    if cfg:
        cfg.value = base
    else:
        db.add(SystemConfig(key="llm_config", value=base,
                            description="在线 LLM 网关配置（含模型仓库 models）"))
    await db.commit()
    return {"ok": True, "count": len(models)}


@router.post("/autoclip/llm-test")
async def llm_test(payload: dict, db: AsyncSession = Depends(get_db)):
    """LLM 连通性测试代理：转发 AutoClip 服务发起一次最小补全（45s 上限）。

    密钥语义与选点一致：显式传入优先；不传则解析仓库同名条目密钥；
    仍无则沿用服务 env（LLM_API_KEY / DASHSCOPE_API_KEY）。
    """
    name = (payload.get("name") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    if name and not api_key:
        try:
            row = (await db.execute(
                select(SystemConfig).where(SystemConfig.key == "llm_config")
            )).scalar_one_or_none()
            models = (row.value.get("models") if row and isinstance(row.value, dict) else None) or []
            m = next((x for x in models if x.get("name") == name), None)
            if m:
                api_key = m.get("api_key") or ""
                payload.setdefault("model", m.get("model") or "")
                payload.setdefault("api_base", m.get("api_base") or "")
        except Exception:
            pass
    # 修复（2026-11-23）：解析出的仓库密钥必须注入转发 payload，否则服务端
    # 回退 env 密钥导致按名称测试恒 401（局部变量 api_key 此前未写回 payload）
    if api_key:
        payload["api_key"] = api_key
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(f"{settings.AUTOCLIP_URL}/llm-test", json=payload)
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"AutoClip 服务不可达: {e}")


class AutoClipRunRequest(BaseModel):
    config: Optional[dict] = None
    video_path: Optional[str] = None


class AutoClipRunResponse(BaseModel):
    celery_task_id: str
    autoclip_project_id: Optional[str] = None
    message: str


class AutoClipProgressResponse(BaseModel):
    status: str
    progress: float
    message: str
    error_message: Optional[str] = None


class AutoClipRunResponseItem(BaseModel):
    id: str
    episode_id: str
    autoclip_project_id: Optional[str] = None
    celery_task_id: Optional[str] = None
    status: str
    progress: float
    message: Optional[str] = None
    error_message: Optional[str] = None
    config: Optional[dict] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class ClipUpdateRequest(BaseModel):
    status: Optional[str] = None
    adjusted_start: Optional[float] = None
    adjusted_end: Optional[float] = None


class ClipResponse(BaseModel):
    id: str
    episode_id: str
    clip_index: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    title: Optional[str] = None
    content: Optional[str] = None
    outline: Optional[str] = None
    score: Optional[float] = None
    recommend_reason: Optional[str] = None
    # 出片形态：suspense_cut / full_highlight / highlight（高光识别模式的短高光段）
    clip_type: Optional[str] = None
    status: str
    adjusted_start: Optional[float] = None
    adjusted_end: Optional[float] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_clip(clip: ClipCandidate) -> dict:
    return {
        "id": str(clip.id),
        "episode_id": str(clip.episode_id),
        "clip_index": clip.clip_index,
        "start_time": clip.start_time,
        "end_time": clip.end_time,
        "duration": clip.duration,
        "title": clip.title,
        "content": clip.content,
        "outline": clip.outline,
        "score": clip.score,
        "recommend_reason": clip.recommend_reason,
        "clip_type": clip.clip_type,
        "status": clip.status,
        "adjusted_start": clip.adjusted_start,
        "adjusted_end": clip.adjusted_end,
        "created_at": utc_iso(clip.created_at) if clip.created_at else "",
    }


def _serialize_autoclip_run(run: AutoClipRun) -> dict:
    return {
        "id": str(run.id),
        "episode_id": str(run.episode_id),
        "autoclip_project_id": run.autoclip_project_id,
        "celery_task_id": run.celery_task_id,
        "status": run.status or "pending",
        "progress": run.progress or 0.0,
        "message": run.message,
        "error_message": run.error_message,
        "config": run.config or {},
        "started_at": utc_iso(run.started_at) if run.started_at else None,
        "completed_at": utc_iso(run.completed_at) if run.completed_at else None,
        "created_at": utc_iso(run.created_at) if run.created_at else "",
    }


@router.post("/episodes/{episode_id}/autoclip/run", response_model=AutoClipRunResponse)
async def run_autoclip(
    episode_id: str,
    data: AutoClipRunRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger the AutoClip 6-step pipeline for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # Get episode
    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 数据隔离
    await check_project_access_by_episode(db, episode, current_user)

    if data.video_path and not os.path.isfile(data.video_path):
        raise HTTPException(
            status_code=400,
            detail=f"video_path 指向的文件不存在: {data.video_path}",
        )
    if not episode.source_file_key and not data.video_path:
        raise HTTPException(
            status_code=400,
            detail="Episode has no source file. Upload a video first or provide video_path.",
        )

    # Check if AutoClip is reachable
    healthy = await check_autoclip_health()
    if not healthy:
        raise HTTPException(status_code=503, detail="AutoClip service is not reachable")

    # 并发互斥锁：同一剧集同时只允许一个选点任务。
    # 背景：并发触发时两个 Celery 任务都会「清空全剧集候选再写入自己的结果」，
    # 后收尾者会覆盖/清空先收尾者的数据（2026-09-02 事故）。
    # 锁 TTL 1800s 覆盖上传视频 + 10 分钟轮询 + 收尾；崩溃未释放时自动过期兜底。
    from app.services.distributed_lock import acquire_lock, release_lock

    lock_key = f"autoclip:lock:{eid}"
    lock_token = await acquire_lock(lock_key, ttl=1800)
    if not lock_token:
        raise HTTPException(
            status_code=409,
            detail="该剧集已有选点任务在运行中，请等待完成或失败后再触发",
        )

    # Create AutoClip project
    # 合并系统设置 default_autoclip_config（模型名/评分阈值等），使系统设置生效
    config = await _merge_default_autoclip_config(db, data.config)

    # 模型仓库解析（2026-11-23 用户需求「保存多个模型可供选择」）：前端只传
    # llm_model_name（仓库条目名），密钥等敏感字段由服务端从 llm_config.models
    # 解析注入，不下发前端。找不到名称时安全降级为跟随系统默认。
    model_name = (data.config or {}).get("llm_model_name")
    repo_entries = []
    selected_repo_name = None
    if model_name:
        try:
            llm_cfg_row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "llm_config")
            )
            llm_cfg = llm_cfg_row.scalar_one_or_none()
            entries = (
                llm_cfg.value.get("models") if llm_cfg and isinstance(llm_cfg.value, dict) else None
            ) or []
            repo_entries = [e for e in entries if isinstance(e, dict)]
            entry = next(
                (e for e in entries if isinstance(e, dict) and e.get("name") == model_name),
                None,
            )
            if entry:
                selected_repo_name = model_name
                for cfg_key, entry_key in (
                    ("llm_model", "model"),
                    ("llm_api_base", "api_base"),
                    ("llm_api_key", "api_key"),
                ):
                    val = entry.get(entry_key)
                    if val:
                        config[cfg_key] = val
                config.pop("llm_model_name", None)
                logger.info("选点使用仓库模型 %s（%s @ %s）", model_name, entry.get("model"), entry.get("api_base"))
            else:
                config.pop("llm_model_name", None)
                logger.warning("仓库中不存在模型 %s，降级为跟随系统默认", model_name)
        except Exception as e:  # noqa: BLE001 - 仓库解析失败不阻塞选点
            logger.warning("模型仓库解析失败: %s", e)
            config.pop("llm_model_name", None)

    # 失败切换链（2026-11-23 用户需求：当前模型长时间无响应自动切换下一个）：
    # 主模型在前、仓库其余模型依次兜底；密钥一并下发服务侧内存（不出后端边界）。
    # 无仓库条目时不组链=行为与旧版一致。
    if config.get("llm_model") and repo_entries:
        chain = [{
            "model": config.get("llm_model"),
            "api_base": config.get("llm_api_base") or "",
            "api_key": config.get("llm_api_key") or "",
            "provider": config.get("llm_provider") or "",
        }]
        for e in repo_entries:
            if selected_repo_name and e.get("name") == selected_repo_name:
                continue
            if e.get("model"):
                chain.append({
                    "model": e["model"],
                    "api_base": e.get("api_base") or "",
                    "api_key": e.get("api_key") or "",
                    "provider": config.get("llm_provider") or "",
                })
        if len(chain) > 1:
            config["llm_failovers"] = chain[1:]
            logger.info(
                "选点失败切换链已组装：主=%s，备用=%s",
                config.get("llm_model"),
                [c["model"] for c in chain[1:]],
            )
    autoclip_project_id = await create_autoclip_project(
        name=f"episode_{episode_id}",
        config=config,
    )
    if not autoclip_project_id:
        raise HTTPException(status_code=500, detail="Failed to create AutoClip project")

    # Save or update AutoClip project association
    try:
        existing = await db.execute(
            select(AutoClipProject).where(AutoClipProject.episode_id == eid)
        )
        autoclip_project = existing.scalar_one_or_none()
        if autoclip_project:
            autoclip_project.autoclip_project_id = autoclip_project_id
            autoclip_project.config = config
            autoclip_project.pipeline_status = "pending"
        else:
            autoclip_project = AutoClipProject(
                episode_id=eid,
                autoclip_project_id=autoclip_project_id,
                config=config,
                pipeline_status="pending",
            )
            db.add(autoclip_project)
        await db.flush()
    except Exception:
        # Rollback: clean up remote project if local DB save fails
        await delete_autoclip_project(autoclip_project_id)
        raise

    # 每次选点都落库一条执行历史记录（供工作台历史展示）
    autoclip_run = AutoClipRun(
        episode_id=eid,
        autoclip_project_id=autoclip_project_id,
        status="pending",
        progress=0.0,
        message="选点任务排队中，等待处理…",
        config=config,
    )
    db.add(autoclip_run)
    # 先提交历史记录，避免 Celery 任务抢先查询时找不到记录而重复建一条
    await db.commit()
    await db.refresh(autoclip_run)

    # Determine video path
    source_file_key = episode.source_file_key
    video_path = data.video_path or f"/data/videos/{source_file_key}"

    # Dispatch Celery task
    try:
        task = celery_autoclip_task.delay(
            episode_id=str(eid),
            autoclip_project_id=autoclip_project_id,
            video_path=video_path,
            config=config,
            source_file_key=source_file_key,
            lock_token=lock_token,
        )
    except Exception as e:
        # Celery dispatch failed: mark DB status as failed
        autoclip_project.pipeline_status = "failed"
        autoclip_project.error_message = f"选点任务调度失败: {e}"
        autoclip_run.status = "failed"
        autoclip_run.error_message = f"选点任务调度失败: {e}"
        autoclip_run.completed_at = datetime.utcnow()
        # 任务未跑起来，无人释放互斥锁，这里释放避免死锁 30 分钟
        await release_lock(lock_key, lock_token)
        # 历史记录已提前提交，这里单独提交失败状态
        await db.commit()
        raise

    # Update celery task ID
    autoclip_project.celery_task_id = task.id
    autoclip_run.celery_task_id = task.id
    await db.flush()

    return AutoClipRunResponse(
        celery_task_id=task.id,
        autoclip_project_id=autoclip_project_id,
        message="AI 智能选点任务已启动，正在分析中…",
    )


@router.get("/episodes/{episode_id}/autoclip/history", response_model=List[AutoClipRunResponseItem])
async def get_autoclip_history(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询该剧集所有 AI 选点执行历史（按创建时间倒序，数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    result = await db.execute(
        select(AutoClipRun)
        .where(AutoClipRun.episode_id == eid)
        .order_by(AutoClipRun.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [_serialize_autoclip_run(r) for r in runs]


@router.get("/episodes/{episode_id}/autoclip/progress", response_model=AutoClipProgressResponse)
async def get_autoclip_progress(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get the AutoClip pipeline progress for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    # Get autoclip project
    result = await db.execute(
        select(AutoClipProject).where(AutoClipProject.episode_id == eid)
    )
    autoclip_project = result.scalar_one_or_none()
    if not autoclip_project:
        raise HTTPException(status_code=404, detail="No AutoClip project found for this episode")

    # 选点执行历史已全部删除时不再返回「已完成」等残留进度，
    # 返回 404 让前端隐藏选点进度条（与删除历史后的状态一致）。
    runs_res = await db.execute(
        select(func.count()).select_from(AutoClipRun).where(AutoClipRun.episode_id == eid)
    )
    if (runs_res.scalar() or 0) == 0:
        raise HTTPException(status_code=404, detail="No AutoClip history for this episode")

    # Try to get progress from AutoClip service
    if autoclip_project.autoclip_project_id:
        progress = await get_pipeline_progress(autoclip_project.autoclip_project_id)
        if progress:
            return AutoClipProgressResponse(
                status=progress.get("status", "unknown"),
                progress=progress.get("progress", 0),
                message=progress.get("message", ""),
                error_message=autoclip_project.error_message,
            )

    # Fall back to local database status
    status_map = {
        "pending": "running",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
    }
    message_map = {
        "pending": "选点任务排队中，等待处理…",
        "running": "选点任务运行中，正在分析视频…",
        "completed": "选点任务已完成",
        "failed": "选点任务执行失败",
    }
    status = autoclip_project.pipeline_status or "pending"
    progress_value = 100.0 if status == "completed" else 0.0
    return AutoClipProgressResponse(
        status=status_map.get(status, "unknown"),
        progress=progress_value,
        message=message_map.get(status, status),
        error_message=autoclip_project.error_message,
    )


@router.get("/episodes/{episode_id}/autoclip/clips", response_model=List[ClipResponse])
async def get_autoclip_clips(
    episode_id: str,
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get the clip candidates for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    query = select(ClipCandidate).where(ClipCandidate.episode_id == eid)
    if min_score > 0:
        query = query.where(ClipCandidate.score >= min_score)
    query = query.order_by(ClipCandidate.clip_index.asc().nullslast())

    result = await db.execute(query)
    clips = result.scalars().all()
    return [_serialize_clip(c) for c in clips]


@router.put("/clips/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: str,
    data: ClipUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Update a clip candidate's status or adjusted times（数据隔离）. """
    try:
        cid = uuid.UUID(clip_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid clip ID format")

    result = await db.execute(select(ClipCandidate).where(ClipCandidate.id == cid))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == clip.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    if data.status is not None:
        if data.status not in ("pending", "accepted", "rejected", "adjusted"):
            raise HTTPException(
                status_code=400,
                detail="Status must be one of: pending, accepted, rejected, adjusted",
            )
        clip.status = data.status
    if data.adjusted_start is not None:
        clip.adjusted_start = data.adjusted_start
    if data.adjusted_end is not None:
        clip.adjusted_end = data.adjusted_end

    await db.flush()
    await db.refresh(clip)
    return _serialize_clip(clip)


@router.post("/episodes/{episode_id}/autoclip/regenerate", response_model=AutoClipRunResponse)
async def regenerate_autoclip(
    episode_id: str,
    data: AutoClipRunRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate AutoClip clips with updated parameters（数据隔离）. 

    Creates the new AutoClip project first; only after it is successfully
    created are the old clips deleted, so a failure does not lose existing data.
    """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离：先校验当前用户对剧集所属项目的访问权限
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    # First, run autoclip to create new project and dispatch task
    response = await run_autoclip(episode_id, data, current_user, db)

    # Only after successful creation, delete old clips
    result = await db.execute(
        select(ClipCandidate).where(ClipCandidate.episode_id == eid)
    )
    existing_clips = result.scalars().all()
    for clip in existing_clips:
        # Keep clips that belong to the new run (just created by _save_autoclip_results
        # would not have happened yet since the Celery task is async). Delete all
        # pending clips from previous runs.
        if clip.status == "pending":
            await db.delete(clip)
    await db.flush()

    return response

@router.delete("/episodes/{episode_id}/autoclip/history/{run_id}", status_code=200)
async def delete_autoclip_history(
    episode_id: str,
    run_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """删除一条 AI 选点执行历史记录（数据隔离）。

    删除 AutoClipRun 历史记录本身；若删除后该集已无任何选点历史，
    则视为「清空选点结果」：片段候选（clip_candidates）与区间检测
    （detected_intervals）一并删除，剧集回滚到未选点状态——否则残留
    候选会让一键切片误判「已有选点结果」而跳过重新选点，直接拿旧
    候选切片（表现为「没有选点直接进入切片流程」）。
    """
    try:
        eid = uuid.UUID(episode_id)
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    # 数据隔离：先校验当前用户对剧集所属项目的访问权限
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    result = await db.execute(
        select(AutoClipRun).where(
            AutoClipRun.id == rid,
            AutoClipRun.episode_id == eid,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="选点执行记录不存在")

    cleared_results = False
    result_message = "选点执行记录已删除"
    await db.delete(run)
    await db.flush()
    # 选点历史删光后联动重置：清掉残留的「已完成/失败」选点项目状态并
    # 回滚剧集状态，避免进度条与剧集状态停留在删除前的旧结果上。
    remain_res = await db.execute(
        select(func.count()).select_from(AutoClipRun).where(AutoClipRun.episode_id == eid)
    )
    if (remain_res.scalar() or 0) == 0:
        proj_res = await db.execute(
            select(AutoClipProject).where(AutoClipProject.episode_id == eid)
        )
        proj = proj_res.scalar_one_or_none()
        if proj and proj.pipeline_status in ("completed", "failed"):
            proj.pipeline_status = None
            proj.error_message = None
        # 选点产物一并清空（语义：删光历史 = 清空选点结果），让下一次
        # 一键切片正确触发重新选点，而不是复用旧候选直接切片。
        # 例外：候选已被切片成品（slice_outputs.clip_id）引用时不能硬删
        # （外键 RESTRICT 且会误删成品数据）；删除切片任务会级联清理成品
        # 记录，此时保留选点结果并在 message 中引导用户先删切片任务。
        cand_ids = (
            await db.execute(
                select(ClipCandidate.id).where(ClipCandidate.episode_id == eid)
            )
        ).scalars().all()
        if cand_ids:
            ref_count = (
                await db.execute(
                    select(func.count())
                    .select_from(SliceOutput)
                    .where(SliceOutput.clip_id.in_(cand_ids))
                )
            ).scalar() or 0
            if ref_count == 0:
                await db.execute(
                    delete(ClipCandidate).where(ClipCandidate.episode_id == eid)
                )
                await db.execute(
                    delete(DetectedInterval).where(DetectedInterval.episode_id == eid)
                )
                cleared_results = True
                result_message = (
                    "选点执行记录已删除，该集选点结果（片段候选/区间检测）已一并清空"
                )
            else:
                result_message = (
                    f"选点执行记录已删除；该集切片成品仍引用片段候选（{ref_count} 条成品），"
                    "选点结果未清空。如需重新选点：请先删除相关切片任务"
                    "（会一并清理切片成品），再删除选点历史"
                )
        else:
            # 已无候选：区间检测若无引用残留也一并清掉，保持状态自洽
            await db.execute(
                delete(DetectedInterval).where(DetectedInterval.episode_id == eid)
            )
            cleared_results = True
            result_message = (
                "选点执行记录已删除，该集选点结果（片段候选/区间检测）已一并清空"
            )
    await _refresh_episode_status(db, eid)
    await db.commit()
    return {
        "message": result_message,
        "run_id": run_id,
        "cleared_results": cleared_results,
    }
