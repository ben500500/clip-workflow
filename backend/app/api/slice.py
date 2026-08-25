"""切片任务 API。

支持三种引擎分发方式：
- worker：通过 Redis Stream 将切片任务分发到分布式 Worker 节点（默认）
- local：单机同步执行（SLICE_ENGINE=local，不走队列，直接 await 引擎）
- celery：回退到 Celery 队列（兼容旧版，迁移期可回退）

Worker 完成/失败/进度均通过回调接口上报，回调与上传 URL 申请接口使用
每次任务生成的临时 Token 鉴权，防止伪造回调。

Phase 1 上帝类拆分：原「上帝类」slice.py（~2170 行）中的 Pydantic 模型、
引擎封装辅助函数、序列化器与 Worker/Celery 分发逻辑已拆入 `slice_helpers.py`，
本文件保留业务路由（router）与 Worker 回调路由（worker_router），职责更聚焦于路由。
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db, async_session_factory
from app.models.models import (
    Episode,
    SliceTask,
    SliceOutput,
    ClipCandidate,
    DetectedInterval,
    AutoClipProject,
    User,
    UserPreference,
)
from app.services.data_scope import check_project_access_by_episode
from app.utils.helpers import utc_iso, generate_cutlist, build_clip_name, generate_intervals_file, format_time
from app.services.minio_service import (
    get_presigned_url,
    get_presigned_upload_url,
    ensure_bucket,
    list_files,
    delete_file,
    upload_file_from_path,
)
from app.services.redis_stream import (
    get_task_redis_status,
    mark_task_cancelled,
    remove_slice_task_from_streams,
    get_redis,
)
from app.api.slice_helpers import (
    BadgeItem,
    TextOverlayItem,
    SliceRunRequest,
    SliceRunResponse,
    SliceTaskResponse,
    SliceOutputResponse,
    SliceTaskCallback,
    UserSliceConfigRequest,
    _serialize_task,
    _serialize_output,
    _resolve_engine,
    _ffprobe_duration,
    _build_watermark_config,
    _build_vert2horiz_config,
    _build_badges_config,
    _build_text_overlays_config,
    _build_subtitle_mask_config,
    _build_watermark_mask_config,
    _read_uploaded_subtitle,
    _resolve_source_subtitle_srt,
    _generate_subtitle_config,
    _not_detect_task,
    _acquire_concurrency_slot,
    _output_prefix,
    _refresh_episode_status,
    refine_clip_boundaries,
    _publish_to_worker,
    _dispatch_celery,
    _dispatch_local,
    _verify_worker_token,
)
# 后端兜底：无候选片段时复用 autoclip 的选点触发流程（仅 auto_autoclip_if_empty 分支导入使用，
# 无循环依赖：autoclip 模块不反向导入 slice）
from app.api.autoclip import AutoClipRunRequest, run_autoclip

logger = logging.getLogger(__name__)

router = APIRouter()

# 供 Go slice-worker 回调使用的开放 router（走 X-Worker-Token 鉴权，而非用户 JWT），
# 在 main.py 中单独挂载、不套用户鉴权依赖。
worker_router = APIRouter()


# ──────────────────────────────────────────────
# API 端点
# ──────────────────────────────────────────────


@router.post("/slice/badge-upload")
async def upload_badge_image(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """上传角标图片（png/jpg/jpeg/webp/gif/bmp），存入 MinIO（raw-footage 桶 badge/ 前缀）。

    返回 file_key，前端将其纳入切片请求的 badges 列表。
    """
    # 注意：角标是图片，不能复用 validate_file_name（它按 ALLOWED_VIDEO_EXTENSIONS
    # 视频白名单校验，png/jpg 会被拒为 unsupported file type）。这里只做安全清洗
    # （取 basename、去路径穿越），扩展名白名单单独校验。
    import posixpath

    raw_name = file.filename or ""
    safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="empty file name")

    # 仅允许图片类型
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        raise HTTPException(status_code=400, detail="角标仅支持图片文件（png/jpg/jpeg/webp/gif/bmp）")

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/badge_upload/{upload_id}_{safe_name}"
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

    # 角标图片存入 raw-footage 桶 badge/ 前缀
    file_key = f"badge/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW,
        file_key,
        local_path,
        content_type=file.content_type or "image/png",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="角标图片上传存储失败")

    return {
        "file_name": safe_name,
        "file_key": file_key,
        "file_size": size,
        "upload_id": upload_id,
    }


@router.post("/slice/hook-upload")
async def upload_hook_video(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """上传钩子视频（mp4/avi/mov/mkv/webm），存入 MinIO（raw-footage 桶 hook/ 前缀）。

    返回 file_key，前端将其作为 hook_video_key 传入切片请求；
    切片引擎把钩子视频作为片头拼接在封面首帧与本体之间（[封面][钩子][本体]）。
    """
    # 钩子视频按视频白名单校验（与 validate_file_name 一致），并做安全清洗。
    import posixpath

    raw_name = file.filename or ""
    safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="empty file name")

    ext = os.path.splitext(safe_name)[1].lower()
    allowed_video = {e.strip().lower() for e in settings.ALLOWED_VIDEO_EXTENSIONS.split(",")}
    if ext not in allowed_video:
        raise HTTPException(status_code=400, detail=f"钩子仅支持视频文件（{settings.ALLOWED_VIDEO_EXTENSIONS}）")

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/hook_upload/{upload_id}_{safe_name}"
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

    # 钩子视频存入 raw-footage 桶 hook/ 前缀
    file_key = f"hook/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW,
        file_key,
        local_path,
        content_type=file.content_type or "video/mp4",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="钩子视频上传存储失败")

    return {
        "file_name": safe_name,
        "file_key": file_key,
        "file_size": size,
        "upload_id": upload_id,
    }


@router.post("/slice/hook-folder-upload")
async def upload_hook_folder(
    files: List[UploadFile] = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """上传整个钩子视频文件夹（多个视频），存入 MinIO（raw-footage 桶 hook/ 前缀）。

    需求：钩子视频选择改成选择文件夹，文件夹中含多个钩子视频，切片时随机组合。
    把所有文件统一存到同一个文件夹前缀 hook/<folder_id>/ 下，返回每个文件的
    file_key；前端将其作为 hook_video_keys 列表传入切片请求，引擎在每个成品
    切片时随机取一个钩子作为片头。
    """
    import posixpath

    folder_id = str(uuid.uuid4())
    allowed_video = {e.strip().lower() for e in settings.ALLOWED_VIDEO_EXTENSIONS.split(",")}
    uploaded: list = []
    errors: list = []

    for file in files:
        raw_name = file.filename or ""
        safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
        if not safe_name:
            continue
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in allowed_video:
            errors.append(f"{safe_name}: 仅支持视频文件（{settings.ALLOWED_VIDEO_EXTENSIONS}）")
            continue

        local_path = f"/tmp/hook_upload/{folder_id}_{safe_name}"
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        size = 0
        try:
            with open(local_path, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > settings.UPLOAD_MAX_SIZE:
                        out.close()
                        os.unlink(local_path)
                        raise HTTPException(status_code=413, detail=f"文件超过大小上限: {safe_name}")
                    out.write(chunk)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append(f"{safe_name}: 读取失败 {e}")
            if os.path.exists(local_path):
                os.unlink(local_path)
            continue

        if size == 0:
            if os.path.exists(local_path):
                os.unlink(local_path)
            errors.append(f"{safe_name}: 文件为空")
            continue

        # 整个文件夹统一存到同一前缀 hook/<folder_id>/ 下
        file_key = f"hook/{folder_id}/{safe_name}"
        ok = await upload_file_from_path(
            settings.MINIO_BUCKET_RAW,
            file_key,
            local_path,
            content_type=file.content_type or "video/mp4",
        )
        if os.path.exists(local_path):
            os.unlink(local_path)
        if not ok:
            errors.append(f"{safe_name}: 上传存储失败")
            continue
        uploaded.append({
            "file_name": safe_name,
            "file_key": file_key,
            "file_size": size,
        })

    if not uploaded:
        raise HTTPException(
            status_code=400,
            detail="钩子文件夹中没有可用的视频文件" + (f"（{'；'.join(errors)}）" if errors else ""),
        )

    return {
        "folder_id": folder_id,
        "items": uploaded,
        "errors": errors,
    }


async def upload_subtitle_file(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """上传字幕文件（srt/vtt），存入 MinIO（raw-footage 桶 subtitle/ 前缀）。

    返回 file_key，前端将其作为 subtitle_file_key 传入切片请求；
    提供字幕文件后，后端直接使用该字幕烧录，跳过 ASR 识别。
    """
    import posixpath

    raw_name = file.filename or ""
    safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="empty file name")

    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".srt", ".vtt"):
        raise HTTPException(status_code=400, detail="字幕仅支持 srt/vtt 文件")

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/subtitle_upload/{upload_id}_{safe_name}"
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

    file_key = f"subtitle/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW,
        file_key,
        local_path,
        content_type=file.content_type or "application/x-subrip",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="字幕文件上传存储失败")

    return {
        "file_name": safe_name,
        "file_key": file_key,
        "file_size": size,
        "upload_id": upload_id,
    }


@router.get("/slice/preferences")
async def get_slice_preferences(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的切片个人配置（保存到个人账号，跨设备/浏览器持久化）。"""
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    return {"slice_config": pref.slice_config if pref else None}


@router.put("/slice/preferences")
async def save_slice_preferences(
    data: UserSliceConfigRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """保存当前用户的切片个人配置到个人账号。"""
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if pref:
        pref.slice_config = data.slice_config
    else:
        pref = UserPreference(user_id=current_user.id, slice_config=data.slice_config)
        db.add(pref)
    await db.commit()
    return {"ok": True, "slice_config": data.slice_config}


async def _resolve_slice_inputs(
    db: AsyncSession,
    eid: uuid.UUID,
    episode: Episode,
    data: SliceRunRequest,
    source_file_key: Optional[str],
    source_bucket: str,
    episode_id: str,
    current_user: Optional[User] = None,
) -> tuple:
    """解析源视频来源并生成 cutlist / intervals。

    返回 (source_file_key, source_bucket, cutlist, intervals_content, fallback_whole_video)。
    run_slice 三阶段之「输入解析」。
    """
    # 免审核一键切片：选点未产出候选片段时是否回退为整片切片（仅 auto_accept_all 分支会置 True）
    fallback_whole_video = False

    if data.video_path and not os.path.isfile(data.video_path):
        raise HTTPException(
            status_code=400,
            detail=f"video_path 指向的文件不存在: {data.video_path}",
        )
    if not data.video_path and not source_file_key:
        raise HTTPException(
            status_code=400,
            detail="Episode has no source file. Upload a video first or provide video_path.",
        )

    # ── 快速转换：跳过 AI 选点/区间检测，直接整片应用下方配置转换输出 ──
    if data.no_cut:
        # 无需候选片段/区间，整段源视频作为单个片段处理。
        # 时长优先取剧集已探测的 duration；缺失时下载源视频用 ffprobe 探测，
        # 保证「快速转换」在尚未做过选点（episode.duration 为空）时也能直接出片。
        duration = episode.duration
        if not duration:
            if data.video_path and os.path.isfile(data.video_path):
                duration = _ffprobe_duration(data.video_path)
            elif source_file_key:
                from app.services.minio_service import download_to_file
                local_path = (
                    f"/tmp/nocut_{uuid.uuid4().hex}"
                    f"{os.path.splitext(source_file_key)[1] or '.mp4'}"
                )
                try:
                    if await download_to_file(source_bucket, source_file_key, local_path):
                        duration = _ffprobe_duration(local_path)
                finally:
                    if os.path.isfile(local_path):
                        try:
                            os.unlink(local_path)
                        except OSError:
                            pass
        if not duration or float(duration) <= 0:
            raise HTTPException(
                status_code=400,
                detail="该剧集未记录视频时长，且探测源视频时长失败，无法快速转换。请重新上传视频。",
            )
        cutlist = f"{format_time(0.0)} {format_time(float(duration))} {build_clip_name(episode.title if episode else None, 1)}"
        intervals_content = ""

    # ── 成品重新剪辑：以某个切片输出（成品）为源，重新裁剪出一个新片段 ──
    elif data.output_id:
        if data.video_path:
            raise HTTPException(
                status_code=400,
                detail="指定 output_id 重新剪辑时不能同时传 video_path",
            )
        try:
            out_id = uuid.UUID(data.output_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="output_id 格式不合法")

        out_res = await db.execute(select(SliceOutput).where(SliceOutput.id == out_id))
        output = out_res.scalar_one_or_none()
        if not output:
            raise HTTPException(status_code=404, detail="输出文件不存在")

        # 校验输出属于当前剧集
        out_task_res = await db.execute(select(SliceTask).where(SliceTask.id == output.task_id))
        out_task = out_task_res.scalar_one_or_none()
        if not out_task or str(out_task.episode_id) != str(eid):
            raise HTTPException(status_code=400, detail="输出文件不属于当前剧集")
        if not output.file_key:
            raise HTTPException(status_code=400, detail="输出文件缺少存储对象，无法重新剪辑")

        src_duration = output.duration or episode.duration or 0.0
        start = data.cut_start if data.cut_start is not None else 0.0
        end = data.cut_end if data.cut_end is not None else src_duration
        if start < 0 or end <= start:
            raise HTTPException(
                status_code=400,
                detail="剪辑区间不合法：需要 0 <= 开始时间 < 结束时间",
            )

        source_file_key = output.file_key
        source_bucket = settings.MINIO_BUCKET_SLICED
        cutlist = f"{format_time(start)} {format_time(end)} {build_clip_name(episode.title if episode else None, 1)}"
        intervals_content = ""
    else:
        # Generate cutlist from accepted clips
        clips_result = await db.execute(
            select(ClipCandidate).where(
                ClipCandidate.episode_id == eid,
                ClipCandidate.status == "accepted",
            )
        )
        accepted_clips = clips_result.scalars().all()

        if data.auto_accept_all:
            # 免审核一键切片：不要求审核通过，直接把所有候选片段纳入切片
            all_clips_result = await db.execute(
                select(ClipCandidate)
                .where(ClipCandidate.episode_id == eid)
                .order_by(ClipCandidate.clip_index.asc().nullslast())
            )
            all_clips = all_clips_result.scalars().all()
            if not all_clips:
                # 竞态防护：autoclip 服务标 completed 先于候选写入本库（celery 回调
                # _save_autoclip_results 滞后约 1-2s），一键切片在选点刚完成时可能查到
                # 空候选 → 静默回退整片（表现为「选点 N 个高光、切片只出 1 个整片」）。
                # 短轮询等待候选落库（最多 ~20s），消除竞态窗口。
                for _ in range(10):
                    await asyncio.sleep(2)
                    retry_result = await db.execute(
                        select(ClipCandidate)
                        .where(ClipCandidate.episode_id == eid)
                        .order_by(ClipCandidate.clip_index.asc().nullslast())
                    )
                    retry_clips = retry_result.scalars().all()
                    if retry_clips:
                        logger.info(
                            "Episode %s 选点候选已落库（等待 %d 轮），纳入 %d 个候选",
                            eid, _, len(retry_clips),
                        )
                        all_clips = retry_clips
                        break
            if not all_clips and data.auto_autoclip_if_empty:
                # 后端兜底：无候选片段时自动补一轮 AI 选点（复用 autoclip run 流程），
                # 等待选点完成后重新取候选再切片——前端提交即走、关窗口安全。
                #
                # 事务安全（P0，Issue #236）：本分支复用接口主事务 db 调用 run_autoclip
                # 后再长轮询，若复用同一 db 事务，run_autoclip 末尾 flush 开启的新事务会
                # 持 autoclip_runs 的 RowExclusiveLock 跨最长 10 分钟轮询悬挂，挡死
                # worker-selection 的 UPDATE（statement_timeout）→ 任务死在 pending。
                # 因此：调用前先提交主事务，轮询改用独立 session（每轮 rollback），
                # 任何路径（成功/异常/超时）都不把事务带锁悬挂。
                logger.info(
                    "Episode %s 无候选片段，自动补一轮 AI 选点（后端兜底）", eid
                )
                # 先提交接口主事务，避免与 run_autoclip 的写操作混在同一事务里
                #（共享事务会让 autoclip_runs 锁延续到后续长轮询）
                await db.commit()
                try:
                    await run_autoclip(
                        episode_id,
                        AutoClipRunRequest(config=data.autoclip_config),
                        current_user,
                        db,
                    )
                except HTTPException as e:
                    # 选点触发失败（如 autoclip 服务不可达）不阻断，继续走整片回退/报错分支；
                    # 回滚 run_autoclip 中途可能留下的未提交事务，确保不悬挂锁
                    await db.rollback()
                    logger.warning(
                        "Episode %s 自动补选点触发失败: %s", eid, e.detail
                    )
                else:
                    # run_autoclip 末尾 flush 会开启新事务并持有 autoclip_runs 锁，
                    # 先提交把锁释放，再开始轮询（轮询改独立 session，不再复用主事务）
                    await db.commit()
                    # 轮询等待选点完成（最长 ~10 分钟，每 5s 查一次 DB 状态）
                    # 用独立 session，每轮结束 rollback 归还事务，避免主事务跨轮询悬挂
                    async with async_session_factory() as poll:
                        for _ in range(120):
                            await asyncio.sleep(5)
                            st_result = await poll.execute(
                                select(AutoClipProject.pipeline_status).where(
                                    AutoClipProject.episode_id == eid
                                )
                            )
                            st = st_result.scalar_one_or_none()
                            # 每轮结束 rollback，不留空事务跨轮悬挂（读多轮无需保留状态）
                            await poll.rollback()
                            if st in ("completed", "failed"):
                                break
                    # 重新取候选（含竞态：选点标 completed 后候选落库约滞后 1-2s）
                    for _ in range(10):
                        retry_result = await db.execute(
                            select(ClipCandidate)
                            .where(ClipCandidate.episode_id == eid)
                            .order_by(ClipCandidate.clip_index.asc().nullslast())
                        )
                        all_clips = retry_result.scalars().all()
                        if all_clips:
                            break
                        await asyncio.sleep(2)
                    if all_clips:
                        logger.info(
                            "Episode %s 自动补选点完成，纳入 %d 个候选",
                            eid, len(all_clips),
                        )
                    else:
                        logger.warning(
                            "Episode %s 自动补选点后仍无候选片段", eid
                        )
            if not all_clips:
                if not data.allow_fallback_whole_video:
                    # 显式关闭整片回退：选点未产出候选片段时明确报错，
                    # 供自动化脚本识别并单独处理，而不是静默整片切片。
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "AI 选点未产出任何候选片段，且 allow_fallback_whole_video=false "
                            "已关闭整片回退。请先检查选点结果或重新触发选点，再发起切片。"
                        ),
                    )
                # 一键切片全自动兜底：选点未产出候选片段时不再报错，
                # 直接回退为「整片切片」，保证自动化流程一定出片。
                logger.warning(
                    "Episode %s 无候选片段，一键切片回退为整片切片", eid
                )
                fallback_whole_video = True
            else:
                fallback_whole_video = False
                # 自动通过所有待审核片段，方便后续在切片任务/成品预览中看到关联关系。
                # 一键切片=候选自动全部通过审核：不仅 pending，之前被手动拒绝(rejected)的
                # 候选也一并恢复为 accepted，确保一次一键切片后所有候选都处于「已通过」状态。
                for clip in all_clips:
                    if clip.status in ("pending", "rejected"):
                        clip.status = "accepted"
                await db.flush()
                accepted_clips = all_clips
        else:
            fallback_whole_video = False

        if not fallback_whole_video and not accepted_clips:
            raise HTTPException(
                status_code=400,
                detail="没有已通过的候选片段，无法生成切片。请先在片段审核中通过至少一个片段，或重新触发选点。",
            )

        if fallback_whole_video:
            # 空 cutlist：切片引擎收到后自动按整片时长切片（见 engines/slice.py 兜底逻辑）
            cutlist = ""
            intervals_content = ""
        else:
            # 选点结尾优化：boundary_refine="silence" 时，生成 cutlist 前把每个片段
            # 的 start/end 吸附到最近的自然停顿（静音）处，解决“突然中断”和“高光后拖尾”。
            # 需要本地源视频：优先用 data.video_path；否则下载 MinIO 源到临时文件检测。
            refine_mode = (data.boundary_refine or "off").strip().lower()
            if refine_mode == "silence" and accepted_clips:
                local_video = data.video_path if data.video_path and os.path.isfile(data.video_path) else None
                _tmp_local = None
                try:
                    if not local_video and source_file_key:
                        from app.services.minio_service import download_to_file
                        _tmp_local = (
                            f"/tmp/refine_{uuid.uuid4().hex}"
                            f"{os.path.splitext(source_file_key)[1] or '.mp4'}"
                        )
                        if await download_to_file(source_bucket, source_file_key, _tmp_local):
                            local_video = _tmp_local
                    if local_video:
                        refined_n = refine_clip_boundaries(
                            accepted_clips, local_video, mode="silence"
                        )
                        if refined_n:
                            await db.flush()
                            logger.info("选点结尾优化：%d 个片段已做静音边界吸附", refined_n)
                except Exception as e:  # 边界精修失败不影响主流程，仅记录
                    logger.warning("静音边界吸附失败（回退原边界）: %s", e)
                finally:
                    if _tmp_local and os.path.isfile(_tmp_local):
                        try:
                            os.unlink(_tmp_local)
                        except OSError:
                            pass

            cutlist = generate_cutlist(
                accepted_clips,
                episode_title=episode.title if episode else None,
                highlight_mix=bool(data.highlight_mix_enabled),
                max_duration=data.highlight_mix_max_duration,
                max_clip_duration=data.highlight_mix_max_clip_duration,
                order=data.highlight_mix_order or "time",
            )

            # Generate intervals from enabled intervals
            intervals_result = await db.execute(
                select(DetectedInterval).where(
                    DetectedInterval.episode_id == eid,
                    DetectedInterval.enabled == True,
                )
            )
            enabled_intervals = intervals_result.scalars().all()
            intervals_content = generate_intervals_file(enabled_intervals)

    return source_file_key, source_bucket, cutlist, intervals_content, fallback_whole_video


async def _create_slice_task_record(
    db: AsyncSession,
    eid: uuid.UUID,
    episode: Episode,
    data: SliceRunRequest,
    cutlist: str,
    intervals_content: str,
    source_file_key: Optional[str],
    source_bucket: str,
) -> tuple:
    """获取并发闸门、创建 SliceTask 记录并构造全部转换配置。

    run_slice 三阶段之「任务记录构建」。返回 (slice_task, configs)。
    configs 为分派阶段所需的全部 *_config 字典。
    """
    # 多人同时切片的全局并发闸门：超过 max_concurrent_tasks 上限直接拒绝。
    # 在创建任务记录前检查，running_count 为当前在飞任务数（不含本任务），
    # 保证“同时处理的切片任务数不超过 max_concurrent_tasks”。
    await _acquire_concurrency_slot(db)

    # Create slice task record
    slice_task = SliceTask(
        episode_id=eid,
        mode=data.mode,
        cutlist=cutlist,
        intervals=intervals_content,
        dedupe_config=data.dedupe_config,
        variant_count=data.variant_count,
        source_bucket=source_bucket,
        source_file_key=source_file_key,
        subtitle_align_mask=data.subtitle_align_mask,
        status="pending",
        progress=0.0,
    )
    db.add(slice_task)
    await db.flush()
    await db.refresh(slice_task)

    # 构造水印配置（开启后随任务下发给引擎）
    watermark_config = _build_watermark_config(data, episode)
    # 构造竖屏转横屏预处理配置（开启后随任务下发给引擎）
    vert2horiz_config = _build_vert2horiz_config(data)
    # 构造图片角标配置（开启后随任务下发给引擎）
    badges_config = _build_badges_config(data)
    # 解析源视频字幕 SRT（时间轴），供 ASR 字幕烧录与源字幕打码共用。
    # 打码与字幕烧录是相互独立的开关：任意一个开启都解析 SRT，
    # 但只有字幕烧录开启才会真正烧录，只有打码开启才会打码。
    # 优先使用用户上传的字幕文件（跳过 ASR 识别 / 选点字幕复用）。
    source_subtitle_srt = None
    if data.subtitle_file_key:
        uploaded = await _read_uploaded_subtitle(data.subtitle_file_key)
        if uploaded is not None and uploaded.get("srt"):
            source_subtitle_srt = uploaded["srt"]
    if source_subtitle_srt is None and (data.subtitle_enabled or data.subtitle_mask_enabled) and source_file_key:
        source_subtitle_srt = await _resolve_source_subtitle_srt(
            data, source_file_key, source_bucket, episode, db
        )
    # 构造字幕烧录配置（开启时把源 SRT 随任务下发给引擎烧录）
    subtitle_config = _generate_subtitle_config(data, source_subtitle_srt)
    # 构造固定文字角标配置（文字版角标，无需上传图片）
    text_overlays_config = _build_text_overlays_config(data)
    # 构造源视频字幕打码配置（去片源自带字幕，独立开关，携带打码时间轴 SRT）
    subtitle_mask_config = _build_subtitle_mask_config(data, source_subtitle_srt)
    # 构造恒定水印/角标打码配置（打掉片源固定水印，独立开关）
    watermark_mask_config = _build_watermark_mask_config(data)
    # 持久化竖屏转横屏/角标/字幕/打码/固定文字配置，重试时保留
    slice_task.vert2horiz_config = vert2horiz_config
    slice_task.watermark_config = watermark_config
    slice_task.badges_config = badges_config
    slice_task.badge_default_width = data.badge_default_width or 0
    slice_task.subtitle_config = subtitle_config
    slice_task.subtitle_mask_config = subtitle_mask_config
    slice_task.text_overlays_config = text_overlays_config
    slice_task.watermark_mask_config = watermark_mask_config
    # 视频封面：选择图片作为视频首帧（重试时保留）。
    # 优先请求中的封面；未显式指定时回退到该集独立封面（按剧集存储），
    # 仍为空则引擎使用源视频首帧。
    cover_key = data.cover_image_key or (getattr(episode, "cover_image_key", None) if episode else None)
    slice_task.cover_image_key = cover_key or None
    # 钩子视频：作为片头拼接（[封面][钩子][本体]）。钩子是临时素材，不按剧集持久化，
    # 仅随本次切片请求透传（重试时保留）。
    # 文件夹方式优先：勾选了文件夹（多个钩子）时保存 hook_video_keys 列表；
    # 否则回退到单钩子 hook_video_key。
    slice_task.hook_video_key = data.hook_video_key or None
    slice_task.hook_video_keys = data.hook_video_keys or None
    # 输出档位：高分辨率/高 fps 素材降档提速（重试时保留）
    slice_task.output_tier = data.output_tier or "auto"

    configs = {
        "watermark": watermark_config,
        "vert2horiz": vert2horiz_config,
        "badges": badges_config,
        "subtitle": subtitle_config,
        "text_overlays": text_overlays_config,
        "subtitle_mask": subtitle_mask_config,
        "watermark_mask": watermark_mask_config,
    }
    return slice_task, configs


async def _dispatch_slice_task(
    db: AsyncSession,
    engine: str,
    episode: Episode,
    slice_task: SliceTask,
    data: SliceRunRequest,
    source_file_key: Optional[str],
    source_bucket: str,
    cutlist: str,
    intervals_content: str,
    configs: dict,
    fallback_whole_video: bool,
) -> SliceRunResponse:
    """按引擎（worker/celery）分发切片任务并推进状态。

    run_slice 三阶段之「分发与收尾」。返回 SliceRunResponse。
    """
    watermark_config = configs["watermark"]
    vert2horiz_config = configs["vert2horiz"]
    badges_config = configs["badges"]
    subtitle_config = configs["subtitle"]
    text_overlays_config = configs["text_overlays"]
    subtitle_mask_config = configs["subtitle_mask"]
    watermark_mask_config = configs["watermark_mask"]

    if engine == "worker":
        # 确保输出桶存在（全新部署时 sliced 桶可能未初始化）
        await ensure_bucket(settings.MINIO_BUCKET_SLICED)

        published = await _publish_to_worker(
            slice_task,
            episode,
            cutlist,
            intervals_content,
            source_file_key,
            data.dedupe_config,
            watermark_config,
            data.encoder,
            vert2horiz_config,
            badges_config,
            data.badge_default_width,
            source_bucket,
            subtitle_config,
            text_overlays_config,
            subtitle_mask_config,
            watermark_mask_config,
            data.subtitle_align_mask,
            data.cover_image_key,
            data.output_tier,
            data.hook_video_key,
            data.hook_video_keys,
        )

        if not published:
            # 如果发布失败，标记任务为失败
            slice_task.status = "failed"
            slice_task.error_message = "发布到 Worker 队列失败，请检查 Redis 连接"
            await db.flush()
            raise HTTPException(
                status_code=500,
                detail="发布切片任务到 Worker 队列失败，请检查 Redis 连接",
            )
    elif engine == "local":
        # 单机同步执行：直接 await 引擎（复用 run_slice_fast/scrub），不走队列。
        # 成功时 _dispatch_local 内部已复用现有收尾（上传 MinIO + 更新 DB，任务落为 completed）；
        # 失败时内部已回写 failed + error_message 并抛出 HTTPException。
        # 先 commit 任务记录，确保 _save_slice_outputs 的独立会话能读到刚创建的 slice_task。
        await db.commit()
        try:
            await _dispatch_local(
                slice_task,
                episode,
                cutlist,
                intervals_content,
                source_file_key,
                data.dedupe_config,
                data.video_path,
                source_bucket,
                watermark_config,
                data.encoder,
                vert2horiz_config,
                badges_config,
                data.badge_default_width,
                subtitle_config,
                text_overlays_config,
                subtitle_mask_config,
                watermark_mask_config,
                data.subtitle_align_mask,
                data.cover_image_key,
                data.output_tier,
                data.hook_video_key,
                data.hook_video_keys,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Local 切片任务执行失败: %s", e)
            raise HTTPException(status_code=500, detail=f"本地同步切片失败: {e}")
    else:
        try:
            dispatched = await _dispatch_celery(
                slice_task,
                episode,
                cutlist,
                intervals_content,
                source_file_key,
                data.dedupe_config,
                data.video_path,
                watermark_config,
                data.encoder,
                vert2horiz_config,
                badges_config,
                data.badge_default_width,
                source_bucket,
                subtitle_config,
                text_overlays_config,
                subtitle_mask_config,
                watermark_mask_config,
                data.subtitle_align_mask,
                data.cover_image_key,
                data.output_tier,
                data.hook_video_key,
                data.hook_video_keys,
            )
        except Exception as e:
            logger.error("Celery 分发切片任务失败: %s", e)
            slice_task.status = "failed"
            slice_task.error_message = f"Celery 分发失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"Celery 分发切片任务失败: {e}")
        if not dispatched:
            slice_task.status = "failed"
            slice_task.error_message = "Celery 分发失败"
            await db.flush()
            raise HTTPException(status_code=500, detail="Celery 分发切片任务失败")

    # 切片启动时推进剧集状态，使工作流步骤条正确展示到“切片执行”
    # （local 同步模式在 _dispatch_local 内已把任务/剧集推进到 completed，跳过）
    if engine != "local":
        if episode.status not in ("slicing", "completed"):
            episode.status = "slicing"
        await db.flush()

        slice_task.status = "running"
        slice_task.started_at = datetime.utcnow()
        await db.flush()

        return SliceRunResponse(
            task_id=str(slice_task.id),
            engine=engine,
            fallback_whole_video=fallback_whole_video,
            message=(
                "切片任务已发布到 %s 队列（模式: %s），正在处理中…"
                % (engine, data.mode)
            )
            + ("（已整片回退：AI 选点未产出候选片段）" if fallback_whole_video else ""),
        )

    # local 同步模式：任务已同步完成
    return SliceRunResponse(
        task_id=str(slice_task.id),
        engine=engine,
        fallback_whole_video=fallback_whole_video,
        message=(
            "切片任务已同步完成（模式: %s）" % data.mode
        )
        + ("（已整片回退：AI 选点未产出候选片段）" if fallback_whole_video else ""),
    )


@router.post("/episodes/{episode_id}/slice/run", response_model=SliceRunResponse)
async def run_slice(
    episode_id: str,
    data: SliceRunRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger video slicing for an episode via Worker node or Celery（数据隔离）.

    三阶段编排：① 解析源视频并生成 cutlist → ② 创建任务记录与配置 → ③ 按引擎分发。
    """
    engine = _resolve_engine(data.engine)

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

    source_file_key = episode.source_file_key
    source_bucket = settings.MINIO_BUCKET_RAW

    source_file_key, source_bucket, cutlist, intervals_content, fallback_whole_video = (
        await _resolve_slice_inputs(
            db, eid, episode, data, source_file_key, source_bucket, episode_id, current_user
        )
    )
    slice_task, configs = await _create_slice_task_record(
        db, eid, episode, data, cutlist, intervals_content, source_file_key, source_bucket
    )
    return await _dispatch_slice_task(
        db, engine, episode, slice_task, data, source_file_key, source_bucket,
        cutlist, intervals_content, configs, fallback_whole_video,
    )


@router.get("/episodes/{episode_id}/slice/tasks", response_model=List[SliceTaskResponse])
async def list_slice_tasks(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all slice tasks for an episode（数据隔离）. """
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

    # 排除 detect_* 内部进度跟踪记录（区间检测复用了 slice_tasks 表）。
    result = await db.execute(
        select(SliceTask)
        .where(SliceTask.episode_id == eid)
        .where(_not_detect_task())
        .order_by(SliceTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_serialize_task(t) for t in tasks]


@router.get("/slice-tasks/{task_id}", response_model=SliceTaskResponse)
async def get_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a slice task's details and progress（数据隔离）. 

    同时从 Redis 获取 Worker 上报的实时进度，同步到数据库。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    # 从 Redis 获取 Worker 上报的实时状态
    try:
        redis_status = await get_task_redis_status(task_id)
        if redis_status:
            rs = redis_status
            if rs.get("status") == "completed" and task.status != "completed":
                task.status = "completed"
                task.progress = 100.0
                task.completed_at = datetime.utcnow()
            elif rs.get("status") == "failed" and task.status != "failed":
                task.status = "failed"
                task.error_message = rs.get("error", "Worker 报告错误")
                task.completed_at = datetime.utcnow()
            elif rs.get("status") == "cancelled" and task.status != "cancelled":
                task.status = "cancelled"
                task.error_message = rs.get("error", "任务已取消")
                task.completed_at = datetime.utcnow()
            elif rs.get("progress") is not None:
                task.progress = max(task.progress or 0, rs["progress"])
    except Exception as e:
        logger.warning("Failed to get Redis status for task %s: %s", task_id, e)

    await db.flush()
    return _serialize_task(task)


@router.get("/slice-tasks/{task_id}/outputs", response_model=List[SliceOutputResponse])
async def get_slice_outputs(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all outputs for a slice task（数据隔离）. """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # Verify task exists
    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    # Get outputs
    outputs_result = await db.execute(
        select(SliceOutput)
        .where(SliceOutput.task_id == tid)
        .order_by(SliceOutput.created_at.asc())
    )
    outputs = outputs_result.scalars().all()

    # Generate presigned URLs for each output
    result_list = []
    for output in outputs:
        url = None
        if output.file_key:
            url = await get_presigned_url("sliced", output.file_key, expires_seconds=3600)
        result_list.append(_serialize_output(output, url))

    return result_list


@router.get("/slice-outputs/{output_id}", response_model=SliceOutputResponse)
async def get_slice_output(
    output_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """按 output_id 单查切片输出（方案A：本机发布执行器据此拿 file_key/下载地址）。"""
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Slice output not found")

    # 数据隔离（复用现有权限校验）
    task = (
        await db.execute(select(SliceTask).where(SliceTask.id == output.task_id))
    ).scalar_one_or_none()
    if task:
        episode = (
            await db.execute(select(Episode).where(Episode.id == task.episode_id))
        ).scalar_one_or_none()
        if episode:
            await check_project_access_by_episode(db, episode, current_user)

    url = None
    if output.file_key:
        url = await get_presigned_url("sliced", output.file_key, expires_seconds=3600)
    return _serialize_output(output, url)


@worker_router.get("/slice-tasks/{task_id}/upload-url")
async def get_slice_upload_url(
    task_id: str,
    file_name: str,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 上传每个输出文件前，逐一申请精确绑定 object key 的 presigned PUT URL。

    修复"单 URL 拼文件名导致 MinIO 签名失效（403 SignatureDoesNotMatch）"问题。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    if not file_name or file_name != os.path.basename(file_name):
        raise HTTPException(status_code=400, detail="file_name 不合法")

    # 精确生成该文件的上传 URL（避免路径拼接导致签名失效）
    file_key = f"{_output_prefix(task)}{file_name}"
    upload_url = await get_presigned_upload_url(
        "sliced",
        file_key,
        expires_seconds=7200,
    )
    if not upload_url:
        raise HTTPException(status_code=500, detail="生成上传 URL 失败")

    return {"upload_url": upload_url, "file_key": file_key}


@worker_router.post("/slice-tasks/{task_id}/callback")
async def slice_task_callback(
    task_id: str,
    data: SliceTaskCallback,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 完成任务后的回调。

    Worker 在处理完切片任务后，调用此接口通知后端结果。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权：防止伪造任务完成/失败回调
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    now = datetime.utcnow()

    # 本次新建的切片输出（variant_count>1 时用于投递变体生成；非 completed 分支保持空列表）
    created_outputs: list = []

    if data.status == "completed":
        # ── 幂等保护 ──
        # 任务可能因 PEL 重新认领 / 回调重发被重复上报 completed。
        # 若任务已处于终态且输出已落库，直接返回，避免切片输出重复添加。
        if task.status == "completed":
            return {"ok": True, "duplicate": True}
        if task.status in ("failed", "cancelled") and task.output_count and task.output_count > 0:
            return {"ok": True, "duplicate": True}

        # 记录执行该任务的节点（用于切片任务列表展示"由哪个节点完成"）
        if data.node_id:
            task.node_id = data.node_id

        # 按接受的候选片段顺序映射 clip_id（文件名 clip_XX.mp4 对应片段顺序）
        clip_result = await db.execute(
            select(ClipCandidate)
            .where(
                ClipCandidate.episode_id == task.episode_id,
                ClipCandidate.status == "accepted",
            )
            .order_by(ClipCandidate.clip_index.asc())
        )
        accepted_clips = clip_result.scalars().all()

        # 按文件名中的序号或输出顺序关联 clip_id
        clip_index = 0
        for out in data.outputs:
            fname = out.get("file_name", "")
            file_key = out.get("file_key", "")
            clip_id = None
            matched = False
            # 尝试从文件名 clip_{index}.mp4 解析
            base = os.path.splitext(os.path.basename(fname))[0]
            if base.startswith("clip_"):
                try:
                    idx = int(base.split("_")[1])
                    if 1 <= idx <= len(accepted_clips):
                        clip_id = accepted_clips[idx - 1].id
                        matched = True
                except (ValueError, IndexError):
                    pass
            if not matched:
                # 兜底：按输出顺序关联
                if clip_index < len(accepted_clips):
                    clip_id = accepted_clips[clip_index].id
                clip_index += 1

            # 同一 file_key 已存在则跳过，避免重复回调/重跑时输出记录叠加
            if file_key:
                existing_out = await db.execute(
                    select(SliceOutput).where(
                        SliceOutput.task_id == tid,
                        SliceOutput.file_key == file_key,
                    )
                )
                if existing_out.scalar_one_or_none():
                    continue

            db_output = SliceOutput(
                task_id=tid,
                clip_id=clip_id,
                file_key=file_key,
                file_name=fname,
                duration=out.get("duration"),
                file_size=out.get("file_size"),
                created_at=now,
            )
            db.add(db_output)
            created_outputs.append(db_output)

        task.status = "completed"
        task.progress = 100.0
        task.output_count = data.output_count or len(data.outputs)
        task.completed_at = now
        task.error_message = None
        logger.info("Slice task %s completed with %d outputs", task_id, task.output_count)

        # 完成时清理 Redis hash 里的 error 字段：任务成功但 error 残留会误导
        # 查状态（"completed 但 error 还在"）。失败路径由 worker 写 error，成功路径在此清掉。
        try:
            _redis = await get_redis()
            await _redis.hdel(f"slice:task:{task_id}", "error")
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            logger.warning("清理任务 %s 的 Redis error 字段失败", task_id)

        # 推进剧集状态：所有切片任务完成后置为 completed（而非仅依赖最近一条）
        await _refresh_episode_status(db, task.episode_id)

    elif data.status == "progress":
        # 进度更新（真实 ffmpeg 进度）
        if data.progress is not None:
            task.progress = max(task.progress or 0, data.progress)

    else:  # failed
        task.status = "failed"
        if data.node_id:
            task.node_id = data.node_id
        task.error_message = (data.error or "Worker 报告错误")[:2000]
        task.completed_at = now
        logger.warning("Slice task %s failed: %s", task_id, task.error_message)

        # 任务失败也刷新剧集状态（保证不是"最近一条未完成就永远切片中"）
        await _refresh_episode_status(db, task.episode_id)

    await db.flush()

    # 多视频号素材去重：variant_count>1 时对本次新建的每个切片输出触发变体生成（异步，不阻塞主链路）
    # 对齐 celery slice_task（backend/app/celery/tasks.py 1214-1227）逻辑：零侵入，variant_count<=1 直接跳过。
    variant_count = int(task.variant_count or 1) if task.variant_count else 1
    if variant_count > 1 and created_outputs:
        try:
            from app.celery.variant_tasks import generate_variants_task
            for out in created_outputs:
                generate_variants_task.delay(
                    str(out.id),
                    count=variant_count,
                    base_dedupe=task.dedupe_config,
                    created_by=None,
                )
            logger.info(
                "已投递变体生成任务: task=%s outputs=%s variant_count=%s",
                task_id, len(created_outputs), variant_count,
            )
        except Exception as e:  # noqa: BLE001 - 投递失败不阻塞回调主流程
            logger.exception("投递变体生成任务失败 task=%s: %s", task_id, e)

    return {"ok": True}


@worker_router.post("/slice-tasks/{task_id}/progress")
async def update_slice_progress(
    task_id: str,
    data: dict,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 实时进度上报端点。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    progress = data.get("progress")
    if progress is not None:
        task.progress = max(task.progress or 0, float(progress))

    await db.flush()
    return {"ok": True}


@router.post("/slice-tasks/{task_id}/retry", response_model=SliceRunResponse)
async def retry_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed or cancelled slice task by re-dispatching it to Worker（数据隔离）. """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    if task.status not in ("failed", "cancelled", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry task with status '{task.status}'",
        )

    episode = await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ep = episode.scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")

    source_file_key = task.source_file_key or ep.source_file_key
    source_bucket = task.source_bucket or settings.MINIO_BUCKET_RAW
    if not source_file_key:
        raise HTTPException(status_code=400, detail="Episode has no source file")

    engine = _resolve_engine(None)  # 沿用默认引擎

    new_task = SliceTask(
        episode_id=task.episode_id,
        mode=task.mode,
        cutlist=task.cutlist,
        intervals=task.intervals,
        dedupe_config=task.dedupe_config,
        variant_count=getattr(task, "variant_count", None),
        # 重试时保留原任务的源与水印/角标配置
        source_bucket=source_bucket,
        source_file_key=source_file_key,
        watermark_config=task.watermark_config,
        badges_config=task.badges_config,
        vert2horiz_config=task.vert2horiz_config,
        subtitle_config=task.subtitle_config,
        subtitle_align_mask=getattr(task, "subtitle_align_mask", True),
        subtitle_mask_config=task.subtitle_mask_config,
        text_overlays_config=task.text_overlays_config,
        watermark_mask_config=task.watermark_mask_config,
        cover_image_key=task.cover_image_key,
        hook_video_key=getattr(task, "hook_video_key", None),
        hook_video_keys=getattr(task, "hook_video_keys", None),
        output_tier=getattr(task, "output_tier", None) or "auto",
        status="pending",
        progress=0.0,
    )

    # 全局并发闸门：重试同样受 max_concurrent_tasks 限制，避免堆积
    await _acquire_concurrency_slot(db)

    db.add(new_task)
    await db.flush()
    await db.refresh(new_task)

    if engine == "worker":
        await ensure_bucket(settings.MINIO_BUCKET_SLICED)
        published = await _publish_to_worker(
            new_task,
            ep,
            task.cutlist or "",
            task.intervals or "",
            source_file_key,
            task.dedupe_config,
            task.watermark_config,
            None,
            task.vert2horiz_config,
            task.badges_config,
            task.badge_default_width or 0,
            source_bucket,
            task.subtitle_config,
            task.text_overlays_config,
            task.subtitle_mask_config,
            task.watermark_mask_config,
            getattr(task, "subtitle_align_mask", True),
            task.cover_image_key,
            getattr(task, "output_tier", None) or "auto",
            getattr(task, "hook_video_key", None),
            getattr(task, "hook_video_keys", None),
        )

        if not published:
            new_task.status = "failed"
            new_task.error_message = "发布到 Worker 队列失败"
            await db.flush()
            raise HTTPException(
                status_code=500,
                detail="发布切片任务到 Worker 队列失败",
            )
    elif engine == "local":
        # 单机同步执行：直接 await 引擎（复用 run_slice_fast/scrub），不走队列。
        # 先 commit 任务记录，确保 _save_slice_outputs 的独立会话能读到刚创建的 slice_task。
        await db.commit()
        try:
            await _dispatch_local(
                new_task,
                ep,
                task.cutlist or "",
                task.intervals or "",
                source_file_key,
                task.dedupe_config,
                None,
                source_bucket,
                task.watermark_config,
                None,
                task.vert2horiz_config,
                task.badges_config,
                task.badge_default_width or 0,
                task.subtitle_config,
                task.text_overlays_config,
                task.subtitle_mask_config,
                task.watermark_mask_config,
                getattr(task, "subtitle_align_mask", True),
                task.cover_image_key,
                getattr(task, "output_tier", None) or "auto",
                getattr(task, "hook_video_key", None),
                getattr(task, "hook_video_keys", None),
            )
        except HTTPException:
            raise
        except Exception as e:
            new_task.status = "failed"
            new_task.error_message = f"本地同步切片失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"本地同步切片任务失败: {e}")
    else:
        try:
            await _dispatch_celery(
                new_task,
                ep,
                task.cutlist or "",
                task.intervals or "",
                source_file_key,
                task.dedupe_config,
                None,
                task.watermark_config,
                None,
                task.vert2horiz_config,
                task.badges_config,
                task.badge_default_width or 0,
                source_bucket,
                task.subtitle_config,
                task.text_overlays_config,
                task.subtitle_mask_config,
                task.watermark_mask_config,
                getattr(task, "subtitle_align_mask", True),
                task.cover_image_key,
                getattr(task, "output_tier", None) or "auto",
                getattr(task, "hook_video_key", None),
                getattr(task, "hook_video_keys", None),
            )
        except Exception as e:
            new_task.status = "failed"
            new_task.error_message = f"Celery 分发失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"Celery 分发切片任务失败: {e}")

    if engine != "local":
        new_task.status = "running"
        new_task.started_at = datetime.utcnow()
        if ep.status not in ("slicing", "completed"):
            ep.status = "slicing"
        await db.flush()

        return SliceRunResponse(
            task_id=str(new_task.id),
            engine=engine,
            message="切片任务已重新发布到 Worker 队列",
        )

    # local 同步模式：重试已同步完成
    return SliceRunResponse(
        task_id=str(new_task.id),
        engine=engine,
        message="切片任务已同步完成",
    )


@router.post("/slice-tasks/{task_id}/cancel", response_model=dict)
async def cancel_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running slice task（数据隔离）. 

    Worker 模式下，取消操作会同时更新数据库状态并写入 Redis 任务 Hash，
    Worker 端通过轮询任务 Hash 感知取消并强杀 ffmpeg 进程。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status '{task.status}'",
        )

    task.status = "cancelled"
    await db.flush()

    # 写入 Redis，通知 Worker 端强杀任务
    await mark_task_cancelled(task_id)

    # 本地引擎（SLICE_ENGINE=local）同步路径：引擎子进程由后端进程内运行，
    # 这里直接查杀（连带 ffmpeg 子进程），避免「前端停任务后 ffmpeg 白跑」。
    # Worker/Celery 路径无本地进程登记，kill 返回 False 由 Worker 端 Redis 轮询处理。
    from app.services.slice_service import kill_slice_proc
    killed = await kill_slice_proc(task_id)
    if killed:
        logger.info("Local slice 引擎子进程已终止 task=%s", task_id)

    return {"message": "任务已取消（Worker 端将收到取消信号并终止 ffmpeg）", "task_id": task_id}


@router.delete("/slice-tasks/{task_id}", status_code=200)
async def delete_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """删除切片任务，同时删除其输出文件（MinIO 临时资源，数据隔离）。

    - 若任务正在运行/排队，先取消（写入 Redis 取消标记，Worker 端会强杀 ffmpeg）
    - 删除该任务在 MinIO sliced 桶中的全部输出对象
    - 级联删除数据库中的 SliceOutput / Publication 等关联记录
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    # 正在运行/排队中的任务先取消，避免 Worker 还在写入
    if task.status in ("pending", "running"):
        task.status = "cancelled"
        await mark_task_cancelled(task_id)
        # 本地引擎同步路径：直接查杀引擎子进程（连带 ffmpeg），避免删任务后白跑
        from app.services.slice_service import kill_slice_proc
        if await kill_slice_proc(task_id):
            logger.info("Local slice 引擎子进程已终止（删除任务） task=%s", task_id)
        await db.flush()

    # 清理该任务在 Redis Stream（含消费者组 PEL）中的残留消息，
    # 避免 Worker 读到已删除任务的 task_id 反复重试而卡死队列
    await remove_slice_task_from_streams(task_id)

    # 删除该任务在 MinIO 中的输出文件（slices/{episode}/{task}/ 前缀）
    prefix = _output_prefix(task)
    try:
        objs = await list_files(settings.MINIO_BUCKET_SLICED, prefix=prefix)
        for obj in objs:
            await delete_file(settings.MINIO_BUCKET_SLICED, obj["key"])
        if objs:
            logger.info("Deleted %d output files for slice task %s from MinIO", len(objs), task_id)
    except Exception as e:
        logger.warning("Failed to delete MinIO outputs for task %s: %s", task_id, e)

    # 删除数据库记录（级联删除 SliceOutput / Publication / PublishTask）
    episode_id_for_refresh = task.episode_id
    await db.delete(task)
    await db.flush()

    # 删除后刷新剧集状态（避免删除了任务仍停留在 slicing）
    await _refresh_episode_status(db, episode_id_for_refresh)
    await db.flush()

    return {"message": "任务已删除，相关输出文件已清理", "task_id": task_id}
