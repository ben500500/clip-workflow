"""智令「其他服务」业务编排（文案提取 / AI消除 / 画质修复 / TTS / 音色训练）。

职责边界与 prompt_service 一致：
- 只读写本包独立表 `zhiling_service_tasks`，不碰主系统表；
- 外部调用 fail-soft：参数/网络/业务异常一律写库 `failed` + `error`，由 API 层
  返回任务本体（不抛 500），保证「一次外部抖动不产生 5xx」；
- 先 commit 落行再调外部接口，避免事务跨网络 IO 占住连接池。

AI消除 / 画质修复只吃**视频直链**：用户黏的是分享链接时，先走 doc/107 解析
（+0.01 元/次），直链写回 `params.direct_url` 便于追溯与重试。
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User, user_can_access_all_materials
from wechat_download.models import (
    ZS_DIRECT_URL_TYPES,
    ZS_FAILED,
    ZS_PROCESSING,
    ZS_SUCCESS,
    ZS_TASK_TYPES,
    ZT_COPY_EXTRACT,
    ZT_HD_RESTORE,
    ZT_TTS,
    ZT_VOICE_CLONE,
    ZhilingServiceTask,
)
from wechat_download.services_client import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    TTS_MAX_TEXT,
    ZhilingServiceClient,
    ZhilingServiceError,
)

logger = logging.getLogger(__name__)

# 视频直链识别用的扩展名（与 prompt_service.UPLOAD_ALLOWED_EXTS 同口径）
DIRECT_URL_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v")
TTS_FORMATS = ("mp3", "wav", "pcm")
VOICE_TYPES = ("builtin", "cloned")


def serialize_service_task(t: ZhilingServiceTask) -> dict:
    return {
        "id": str(t.id),
        "created_by": str(t.created_by) if t.created_by else None,
        "task_type": t.task_type,
        "input_url": t.input_url,
        "input_text": t.input_text,
        "params": t.params or {},
        "provider_task_id": t.provider_task_id,
        "status": t.status,
        "progress": t.progress,
        "result_url": t.result_url,
        "result_text": t.result_text,
        "srt_text": t.srt_text,
        "voice_model_id": t.voice_model_id,
        "error": t.error,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def can_access_service_task(task: ZhilingServiceTask, current_user: Optional[User]) -> bool:
    """可见口径照抄 can_access_prompt_task：管理员全见，operater 只见自己的，无主即公共。"""
    if current_user is None:
        return False
    if user_can_access_all_materials(current_user):
        return True
    if task.created_by is None:
        return True
    return task.created_by == current_user.id


async def service_task_scope_stmt(current_user: Optional[User], limit: int = 50):
    stmt = (
        select(ZhilingServiceTask)
        .order_by(ZhilingServiceTask.created_at.desc())
        .limit(limit)
    )
    if current_user is not None and not user_can_access_all_materials(current_user):
        stmt = stmt.where(
            ZhilingServiceTask.created_by.is_(None)
            | (ZhilingServiceTask.created_by == current_user.id)
        )
    return stmt


def is_direct_video_url(url: str) -> bool:
    """http(s) 且以视频扩展名结尾 → 视为直链。

    查询串无所谓（CDN 直链普遍带 ?sign=...），取 path 部分判扩展名。
    """
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return False
    path = u.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(DIRECT_URL_EXTS)


def validate_submit(
    *, task_type: str, source_url: Optional[str], text: Optional[str], options: dict,
) -> Optional[str]:
    """提交前参数校验，返回错误文案（None 表示通过）。

    放在服务层而非 pydantic：口径要同时被 create 和 retry 复用，
    且 TTS 的上限/必填随 voice_type 变化，塞进 schema 只会让两个入口各写一遍。
    """
    if task_type not in ZS_TASK_TYPES:
        return f"不支持的任务类型 {task_type}"
    url = (source_url or "").strip()

    if task_type in (ZT_COPY_EXTRACT,) + ZS_DIRECT_URL_TYPES and not url:
        return "请填写视频链接"

    if task_type == ZT_TTS:
        body = (text or "").strip()
        if not body:
            return "请填写要合成的文本"
        if len(body) > TTS_MAX_TEXT:
            return f"文本过长（{len(body)} 字），单次上限 {TTS_MAX_TEXT} 字"
        voice_type = (options.get("voice_type") or "builtin").strip()
        if voice_type not in VOICE_TYPES:
            return f"音色类型非法：{voice_type}"
        if voice_type == "builtin" and not (options.get("voice_id") or "").strip():
            return "内置音色需选择音色（voiceId）"
        if voice_type == "cloned" and not (options.get("model_id") or "").strip():
            return "自定义音色需填写 modelId"
        fmt = (options.get("format") or "mp3").strip().lower()
        if fmt not in TTS_FORMATS:
            return f"音频格式非法：{fmt}"

    if task_type == ZT_VOICE_CLONE:
        if not (options.get("model_name") or "").strip():
            return "请填写音色模型名称"
        if not url:
            return "请填写音频 URL（mp3/wav）"

    return None


def _apply_status(task: ZhilingServiceTask, st) -> None:
    """把归一化上游状态写回任务行（五条链路的映射差异全部收在这里）。"""
    if st.status == STATUS_SUCCESS:
        task.status = ZS_SUCCESS
        task.error = None
        if st.result_url:
            task.result_url = st.result_url
        if st.result_text:
            task.result_text = st.result_text
        if st.srt_text:
            task.srt_text = st.srt_text
        if st.voice_model_id:
            task.voice_model_id = st.voice_model_id
        # AI消除 / 画质修复完成即 100%，避免前端进度条停在 99%
        if getattr(task, "progress", None) is not None:
            task.progress = 1.0
    elif st.status == STATUS_FAILED:
        task.status = ZS_FAILED
        task.error = (st.error or "任务处理失败")[:500]
    else:
        task.status = ZS_PROCESSING
        if st.progress is not None:
            task.progress = max(0.0, min(1.0, float(st.progress)))
    task.updated_at = datetime.utcnow()


async def create_service_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    task_type: str,
    source_url: Optional[str] = None,
    text: Optional[str] = None,
    options: Optional[dict] = None,
) -> ZhilingServiceTask:
    """建行 + 提交智令。返回落库后的任务（失败时 status=failed，带 error）。

    校验失败不建行（API 层已先挡一次，这里兜住 retry 等其它入口）；
    外部失败则建行写 failed，让用户能在列表里看到失败原因并一键重试。
    """
    options = dict(options or {})
    url = (source_url or "").strip()

    task = ZhilingServiceTask(
        created_by=created_by,
        task_type=task_type,
        input_url=url[:1000] or None,
        input_text=(text or None),
        params=options,
        status=ZS_PROCESSING,
    )
    db.add(task)
    # 先提交：外部请求可能耗时数秒，失败时用户也要能在列表看到这条记录
    await db.commit()
    await db.refresh(task)

    direct_resolve = False
    client = ZhilingServiceClient()
    try:
        if task_type in ZS_DIRECT_URL_TYPES:
            direct = url
            if not is_direct_video_url(url):
                # 分享链接 → 直链（doc/107，+0.01 元/次）；失败直接落 failed
                direct_resolve = True
                direct = await client.resolve_direct_url(url)
                options["direct_url"] = direct
                task.params = options
            task.params = options
            provider_id = await client.submit_eraser(direct, hd=(task_type == ZT_HD_RESTORE))
        elif task_type == ZT_COPY_EXTRACT:
            need_srt = bool(options.get("need_srt", True))
            options["need_srt"] = need_srt
            task.params = options
            provider_id = await client.submit_copy_extract(url, need_srt=need_srt)
        elif task_type == ZT_TTS:
            body = (text or "").strip()
            voice_type = (options.get("voice_type") or "builtin").strip()
            fmt = (options.get("format") or "mp3").strip().lower()
            options["format"] = fmt
            task.params = options
            provider_id = await client.submit_tts(
                text=body,
                voice_type=voice_type,
                voice_id=(options.get("voice_id") or "").strip() or None,
                model_id=(options.get("model_id") or "").strip() or None,
                audio_format=fmt,
            )
        elif task_type == ZT_VOICE_CLONE:
            # 同步接口：创建即成功，落 voice_model_id 供 TTS 自定义音色使用
            created = await client.create_voice_model(
                name=(options.get("model_name") or "").strip(),
                audio_url=url,
                description=(options.get("description") or "").strip() or None,
            )
            task.status = ZS_SUCCESS
            task.voice_model_id = created.get("model_id")
            task.params = {**options, "model_name": created.get("model_name")}
            task.error = None
            task.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(task)
            return task
        else:  # pragma: no cover - validate_submit 已挡住
            raise ZhilingServiceError(f"不支持的任务类型 {task_type}")
    except ZhilingServiceError as e:
        task.status = ZS_FAILED
        task.error = _resolve_error(str(e), direct_resolve=direct_resolve)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("智令服务任务提交失败 task=%s type=%s: %s", task.id, task_type, e)
        return task
    finally:
        await client.close()

    task.provider_task_id = provider_id
    task.status = ZS_PROCESSING
    task.error = None
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    return task


def _resolve_error(msg: str, *, direct_resolve: bool = False) -> str:
    """直链解析失败的文案要能直接指路（用户看到的唯一线索）。"""
    if direct_resolve:
        return f"视频直链解析失败（AI消除/画质修复仅支持视频直链，分享链接解析未成功）：{msg}"
    return msg


async def get_service_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[ZhilingServiceTask]:
    result = await db.execute(
        select(ZhilingServiceTask).where(ZhilingServiceTask.id == task_id)
    )
    return result.scalar_one_or_none()


async def refresh_service_task(
    db: AsyncSession, task: ZhilingServiceTask,
) -> ZhilingServiceTask:
    """仍在 processing 时向上游查询一次并更新（懒同步，同反推模式）。

    终态任务不重复请求：查询虽免费，但无意义地打上游只会放大失败面。
    """
    if task.status != ZS_PROCESSING or not task.provider_task_id:
        return task

    client = ZhilingServiceClient()
    try:
        if task.task_type == ZT_COPY_EXTRACT:
            st = await client.query_asr(task.provider_task_id)
        elif task.task_type in ZS_DIRECT_URL_TYPES:
            st = await client.query_eraser(task.provider_task_id)
        elif task.task_type == ZT_TTS:
            st = await client.query_tts(task.provider_task_id)
        else:
            # 音色训练无轮询：走到这里说明是历史脏数据，直接收口为成功
            return task
    except ZhilingServiceError as e:
        # 查询抖动不写 failed：下一次轮询大概率就能拿到结果，写死反而误伤
        logger.warning("智令服务任务查询失败 task=%s: %s", task.id, e)
        return task
    finally:
        await client.close()

    _apply_status(task, st)
    await db.commit()
    await db.refresh(task)
    return task
