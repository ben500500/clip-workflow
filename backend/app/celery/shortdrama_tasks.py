"""短片制作 Celery 任务（Phase 1 上帝类拆分）。

从原「上帝类」celery/tasks.py 拆出的「短片制作」任务域：
- 一键豆包生成（RPA）：doubao_generate_task
- Seedance 官方 API 直连出片（火山方舟）：seedance_generate_task

依赖主模块 `app.celery.tasks` 中的 `celery_app` 与 `run_async`。
为避免循环导入，tasks.py 在所有任务定义完成后才 import 本模块并 re-export。
"""
import asyncio
import os
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory

# 从主模块复用 celery_app 与 run_async（tasks.py 定义完成后才 import 本模块，
# 故此处可安全导入）
from app.celery.tasks import celery_app, run_async
from app.celery.tasks import logger


# ══════════════════════════════════════════════════════════════════
# 共用辅助
# ══════════════════════════════════════════════════════════════════

async def _load_shortdrama_prompt(prompt_id: str):
    """读取提示词记录(含豆包任务字段)。"""
    from app.models.models import ShortdramaPrompt

    async with async_session_factory() as session:
        try:
            pid = uuid.UUID(str(prompt_id))
        except ValueError:
            return None
        result = await session.execute(
            select(ShortdramaPrompt).where(ShortdramaPrompt.id == pid)
        )
        rec = result.scalar_one_or_none()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 rec 被 expire，调用方在会话外访问 record.xxx 属性时抛 DetachedInstanceError（#230）。
        return rec


def _now_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


# ══════════════════════════════════════════════════════════════════
# 一键豆包生成（RPA）
# ══════════════════════════════════════════════════════════════════

async def _update_doubao_prompt(
    prompt_id: str,
    *,
    status: Optional[str] = None,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    qrcode: Optional[str] = None,
    screenshot: Optional[str] = None,
    task_id: Optional[str] = None,
    approved_prompt: Optional[str] = None,
    rewrite_history: Optional[list] = None,
    confirm_token: Optional[str] = None,
    progress: Optional[int] = None,
    account: Optional[str] = None,
) -> bool:
    """更新提示词记录的豆包任务字段(供 Celery 任务在同步上下文调用)。"""
    from app.models.models import ShortdramaPrompt

    async with async_session_factory() as session:
        try:
            pid = uuid.UUID(str(prompt_id))
        except ValueError:
            return False
        result = await session.execute(
            select(ShortdramaPrompt).where(ShortdramaPrompt.id == pid)
        )
        record = result.scalar_one_or_none()
        if not record:
            # 事务内已执行 SELECT：显式结束事务
            await session.rollback()
            return False
        if status is not None:
            record.doubao_status = status
        if message is not None:
            record.doubao_message = message
        if error_message is not None:
            record.doubao_error_message = error_message
        if qrcode is not None:
            record.doubao_qrcode = qrcode
        if screenshot is not None:
            record.doubao_screenshot = screenshot
        if task_id is not None:
            record.doubao_task_id = task_id
        if approved_prompt is not None:
            record.doubao_approved_prompt = approved_prompt
        if rewrite_history is not None:
            record.doubao_rewrite_history = rewrite_history
        if confirm_token is not None:
            record.doubao_confirm_token = confirm_token
        if progress is not None:
            record.doubao_progress = int(progress)
        if account is not None:
            record.doubao_account = account
        await session.commit()
        return True


async def _sync_doubao_video(
    prompt_id: str,
    *,
    download_url: str,
    file_name: str,
) -> dict:
    """从豆包下载成片视频并上传 MinIO,回填提示词记录(返回 {'ok': bool, 'error': str})。"""
    from app.models.models import ShortdramaPrompt
    from app.services.minio_service import upload_file_from_path

    tmp_path = f"/tmp/doubao_videos/{uuid.uuid4().hex}.mp4"
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    try:
        import httpx

        # 豆包成片直链为 douyin CDN,带上 Referer/UA 提升直链可下载成功率
        _headers = {
            "Referer": "https://www.doubao.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True, headers=_headers) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)

        if not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {"ok": False, "error": "下载豆包成片失败(空文件)"}

        async with async_session_factory() as session:
            try:
                pid = uuid.UUID(str(prompt_id))
            except ValueError:
                return {"ok": False, "error": "提示词记录不存在"}
            result = await session.execute(
                select(ShortdramaPrompt).where(ShortdramaPrompt.id == pid)
            )
            record = result.scalar_one_or_none()
            if not record:
                # 事务内已执行 SELECT：显式结束事务
                await session.rollback()
                return {"ok": False, "error": "提示词记录不存在"}

            safe_name = file_name or f"doubao_{_now_str()}.mp4"
            file_key = f"shortdrama/{str(record.id)}/doubao_{_now_str()}_{safe_name}"
            uploaded = await upload_file_from_path(
                settings.MINIO_BUCKET_WATERMARK_RAW,
                file_key,
                tmp_path,
                content_type="video/mp4",
            )
            if not uploaded:
                await session.rollback()
                return {"ok": False, "error": "上传豆包成片到 MinIO 失败"}

            # 清理旧成片
            if record.video_file_key and record.video_bucket:
                try:
                    from app.services.minio_service import delete_file
                    await delete_file(record.video_bucket, record.video_file_key)
                except Exception:
                    pass

            record.video_file_name = safe_name
            record.video_file_key = file_key
            record.video_bucket = settings.MINIO_BUCKET_WATERMARK_RAW
            record.video_file_size = os.path.getsize(tmp_path)
            record.video_status = "completed"
            record.video_error_message = None
            record.video_uploaded_at = datetime.utcnow()
            # 成片来源通道:豆包 RPA(与 Seedance 官方 API 直连 / 手动上传区分)
            record.gen_channel = "doubao_rpa"

            await session.commit()
            return {"ok": True, "file_name": safe_name, "file_size": os.path.getsize(tmp_path)}
    except Exception as e:
        logger.error("sync doubao video failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


async def _load_doubao_config() -> dict:
    """读取豆包配置(system_config.shortdrama_doubao_config),无则返回空。"""
    from app.models.models import SystemConfig

    async with async_session_factory() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "shortdrama_doubao_config")
        )
        cfg = result.scalar_one_or_none()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 cfg 被 expire，访问 cfg.value 抛 DetachedInstanceError（#230）。
        return (cfg.value or {}) if cfg and isinstance(cfg.value, dict) else {}


async def _check_doubao_cancelled(prompt_id: str) -> bool:
    """检查豆包任务是否已取消(用户取消时置 doubao_status=cancelled)。"""
    record = await _load_shortdrama_prompt(prompt_id)
    if record is None:
        return True
    return record.doubao_status == "cancelled"


@celery_app.task(bind=True, name="app.celery.tasks.doubao_generate_task", max_retries=0)
def doubao_generate_task(
    self,
    prompt_id: str,
    *,
    account_type: str = "free",
    duration: Optional[int] = None,
    lock_token: Optional[str] = None,
):
    """一键豆包生成:RPA 自动打开豆包 → 检测登录(弹二维码)→ 设置参数 →
    贴提示词发送 → 等待生成 → 被拒改写确认 → 下载成片上传 MinIO 回填记录。

    状态机(shortdrama_prompts.doubao_status):
      pending → running → need_login(可选) → awaiting_rewrite(可选)
              → completed / failed / cancelled
    """
    self.update_state(state="STARTED", meta={"progress": 5, "message": "豆包生成任务启动..."})

    try:
        record = run_async(_load_shortdrama_prompt(prompt_id))
        if not record:
            logger.error("Doubao prompt record %s not found", prompt_id)
            return {"success": False, "status": "failed", "message": "提示词记录不存在"}

        # 任务已取消则不执行
        if record.doubao_status == "cancelled":
            logger.info("Doubao task %s already cancelled, skip", prompt_id)
            return {"success": False, "status": "cancelled", "message": "任务已取消"}

        # 读取豆包配置(账户时长上限等)
        config = run_async(_load_doubao_config())
        from app.services.doubao_service import get_account_limits

        limits = get_account_limits(config)

        run_async(_update_doubao_prompt(
            prompt_id,
            status="running",
            message="豆包生成任务启动,正在连接浏览器...",
            error_message=None,
            progress=5,
        ))

        async def _progress_cb(msg: str, p: float):
            self.update_state(state="PROGRESS", meta={"progress": p, "message": msg})
            await _update_doubao_prompt(
                prompt_id,
                message=msg,
                progress=p,
            )

        # 二维码回调:写入数据库供前端轮询展示
        async def _qrcode_cb(qr_data_url: str):
            await _update_doubao_prompt(
                prompt_id,
                status="need_login",
                message="请使用豆包 App 扫码登录",
                qrcode=qr_data_url,
            )

        # 扫码成功回调:把状态从 need_login 拉回 running 并清空二维码,
        # 否则前端以 status != need_login 作为弹窗关闭条件,弹窗永不消失
        async def _on_login_success():
            await _update_doubao_prompt(
                prompt_id,
                status="running",
                message="扫码登录成功,正在进入视频生成...",
                qrcode="",
            )

        # 截图回调:写入数据库供前端展示豆包对话窗口制作过程
        async def _screenshot_cb(shot_data_url: str):
            await _update_doubao_prompt(
                prompt_id,
                screenshot=shot_data_url,
            )

        # 账户回调:提取到当前登录的豆包账户昵称后写入数据库,供前端展示
        async def _account_cb(account: Optional[str]):
            if not account:
                return
            await _update_doubao_prompt(
                prompt_id,
                account=account,
            )

        # 改写确认回调:写入 awaiting_rewrite 状态并挂起等待用户确认
        async def _rewrite_cb(payload: dict) -> str:
            import secrets

            token = secrets.token_hex(16)
            # 重新加载最新改写历史(多次改写时每次都要基于最新值追加)
            latest = await _load_shortdrama_prompt(prompt_id)
            history = (latest.doubao_rewrite_history or []) if latest else []
            history = history + [{
                "round": payload.get("round"),
                "attempt": payload.get("attempt"),
                "original": payload.get("original"),
                "rewritten": payload.get("rewritten"),
                "reason": payload.get("reason"),
                "created_at": datetime.utcnow().isoformat(),
            }]
            await _update_doubao_prompt(
                prompt_id,
                status="awaiting_rewrite",
                message="豆包已返回改写稿,等待用户确认",
                rewrite_history=history,
                confirm_token=token,
            )
            # 挂起等待用户在前端确认(轮询数据库状态)。
            # 注:为释放唯一 worker 槽位,等待上限由配置控制(默认 30s,原 600s 会长期占住槽位)。
            # 若超时未确认,返回 rejected 由前端重新发起改写流程即可。
            deadline = time.time() + settings.DOUBAO_REWRITE_WAIT_SECONDS
            while time.time() < deadline:
                await asyncio.sleep(3)
                cur = await _load_shortdrama_prompt(prompt_id)
                if cur is None:
                    return "cancelled"
                if cur.doubao_confirm_token != token:
                    # token 被使用(用户已确认)→ 判断决策结果
                    if cur.doubao_status == "running":
                        return "approved"
                    if cur.doubao_status == "cancelled":
                        return "cancelled"
                    # 用户点了「再让豆包改写」:状态保持 awaiting_rewrite,返回 rejected
                    return "rejected"
            return "rejected"

        from app.services.doubao_service import DoubaoGenerator

        gen = DoubaoGenerator(
            chrome_port=settings.CHROME_DEBUG_PORT,
            chrome_host=settings.CHROME_DEBUG_HOST,
        )
        result = run_async(gen.generate(
            prompt=record.prompt_text,
            account_type=account_type,
            duration=duration or record.duration,
            limits=limits,
            progress_cb=_progress_cb,
            qrcode_cb=_qrcode_cb,
            screenshot_cb=_screenshot_cb,
            on_rewrite_available=_rewrite_cb,
            on_login_success=_on_login_success,
            on_account_cb=_account_cb,
            cancel_check=lambda: _check_doubao_cancelled(prompt_id),
        ))

        if not result.get("success"):
            status = result.get("status", "failed")
            run_async(_update_doubao_prompt(
                prompt_id,
                status=status,
                message=result.get("message", "豆包生成失败"),
                error_message=result.get("message", "豆包生成失败"),
            ))
            # 注意:不能在此 update_state(state="FAILURE") 后再 return dict--
            # Celery 后端 mark_as_done 时会读旧 FAILURE meta 并把 result 当异常解析,
            # 抛 ValueError('Exception information must include the exception type')。
            # 前端状态展示依赖 DB 轮询(doubao_status),无需手动标记 celery FAILURE。
            return result

        # 生成成功:下载成片并上传 MinIO
        run_async(_update_doubao_prompt(
            prompt_id,
            status="running",
            message="视频生成完成,正在下载并上传成片...",
            progress=95,
        ))
        download_url = result.get("download_url") or ""
        if not download_url:
            run_async(_update_doubao_prompt(
                prompt_id,
                status="failed",
                message="豆包返回成功但未获取到下载地址",
                error_message="豆包返回成功但未获取到下载地址",
            ))
            return {"success": False, "status": "failed", "message": "未获取到下载地址"}

        sync = run_async(_sync_doubao_video(
            prompt_id,
            download_url=download_url,
            file_name=f"doubao_{_now_str()}.mp4",
        ))
        if not sync.get("ok"):
            run_async(_update_doubao_prompt(
                prompt_id,
                status="failed",
                message=sync.get("error", "成片同步失败"),
                error_message=sync.get("error", "成片同步失败"),
            ))
            return {"success": False, "status": "failed", "message": sync.get("error", "成片同步失败")}

        # 回填最终通过豆包审核的提示词
        run_async(_update_doubao_prompt(
            prompt_id,
            status="completed",
            message="豆包成片已生成并保存到历史",
            approved_prompt=result.get("approved_prompt"),
            confirm_token=None,
            progress=100,
        ))
        self.update_state(state="SUCCESS", meta={"progress": 100, "message": "豆包成片已生成"})
        return {
            "success": True,
            "status": "completed",
            "message": "豆包成片已生成并保存到历史",
            "file_name": sync.get("file_name"),
            "file_size": sync.get("file_size"),
        }

    except Exception as e:
        logger.exception("Doubao generate task failed: %s", e)
        run_async(_update_doubao_prompt(
            prompt_id,
            status="failed",
            message=f"豆包生成任务异常: {e}",
            error_message=str(e),
        ))
        # 与失败分支同理:不 update_state(FAILURE)+return dict,避免 Celery 后端解析异常
        return {"success": False, "status": "failed", "message": str(e)}
    finally:
        # 释放入口互斥锁（token 不匹配时 Lua 不会误删他人的锁）
        if lock_token:
            try:
                from app.services.distributed_lock import release_lock
                run_async(release_lock(f"shortdrama:lock:doubao:{prompt_id}", lock_token))
            except Exception:
                logger.warning("释放豆包互斥锁失败 prompt=%s", prompt_id)


# ══════════════════════════════════════════════════════════════════
# Seedance 官方 API 直连出片(火山方舟)-- 与豆包 RPA 完全独立的第二通道
# ══════════════════════════════════════════════════════════════════

async def _update_seedance_prompt(
    prompt_id: str,
    *,
    status: Optional[str] = None,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    task_id: Optional[str] = None,
    resolution: Optional[str] = None,
    gen_channel: Optional[str] = None,
) -> bool:
    """更新提示词记录的 Seedance 直连任务字段(供 Celery 任务在同步上下文调用)。"""
    from app.models.models import ShortdramaPrompt

    async with async_session_factory() as session:
        try:
            pid = uuid.UUID(str(prompt_id))
        except ValueError:
            return False
        result = await session.execute(
            select(ShortdramaPrompt).where(ShortdramaPrompt.id == pid)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        if status is not None:
            record.seedance_status = status
        if message is not None:
            record.seedance_message = message
        if error_message is not None:
            record.seedance_error_message = error_message
        if task_id is not None:
            record.seedance_task_id = task_id
        if resolution is not None:
            record.seedance_resolution = resolution
        if gen_channel is not None:
            record.gen_channel = gen_channel
        await session.commit()
        return True


async def _load_seedance_db_config() -> dict:
    """读取 Seedance 直连配置(system_config.shortdrama_seedance_config),无则返回空。"""
    from app.models.models import SystemConfig

    async with async_session_factory() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "shortdrama_seedance_config")
        )
        cfg = result.scalar_one_or_none()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 cfg 被 expire，访问 cfg.value 抛 DetachedInstanceError（#230）。
        return (cfg.value or {}) if cfg and isinstance(cfg.value, dict) else {}


async def _check_seedance_cancelled(prompt_id: str) -> bool:
    """检查 Seedance 直连任务是否已取消(用户取消时置 seedance_status=cancelled)。"""
    record = await _load_shortdrama_prompt(prompt_id)
    if record is None:
        return True
    return record.seedance_status == "cancelled"


async def _sync_generated_video(
    prompt_id: str,
    *,
    download_url: str,
    file_name: str,
    channel: str = "seedance_api",
) -> dict:
    """下载成片视频并上传 MinIO,回填提示词记录(豆包 RPA / Seedance API 共用)。

    Returns: {'ok': bool, 'file_name': str, 'file_size': int, 'error': str}
    """
    from app.models.models import ShortdramaPrompt
    from app.services.minio_service import upload_file_from_path

    tmp_path = f"/tmp/generated_videos/{uuid.uuid4().hex}.mp4"
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    try:
        import httpx

        # 豆包成片直链为 douyin CDN,带上 Referer/UA 提升直链可下载成功率
        _headers = {
            "Referer": "https://www.doubao.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True, headers=_headers) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)

        if not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {"ok": False, "error": "下载成片失败(空文件)"}

        async with async_session_factory() as session:
            try:
                pid = uuid.UUID(str(prompt_id))
            except ValueError:
                return {"ok": False, "error": "提示词记录不存在"}
            result = await session.execute(
                select(ShortdramaPrompt).where(ShortdramaPrompt.id == pid)
            )
            record = result.scalar_one_or_none()
            if not record:
                # 事务内已执行 SELECT：显式结束事务
                await session.rollback()
                return {"ok": False, "error": "提示词记录不存在"}

            safe_name = file_name or f"{channel}_{_now_str()}.mp4"
            file_key = f"shortdrama/{str(record.id)}/{channel}_{_now_str()}_{safe_name}"
            uploaded = await upload_file_from_path(
                settings.MINIO_BUCKET_WATERMARK_RAW,
                file_key,
                tmp_path,
                content_type="video/mp4",
            )
            if not uploaded:
                await session.rollback()
                return {"ok": False, "error": f"上传成片到 MinIO 失败({channel})"}

            # 清理旧成片
            if record.video_file_key and record.video_bucket:
                try:
                    from app.services.minio_service import delete_file
                    await delete_file(record.video_bucket, record.video_file_key)
                except Exception:
                    pass

            record.video_file_name = safe_name
            record.video_file_key = file_key
            record.video_bucket = settings.MINIO_BUCKET_WATERMARK_RAW
            record.video_file_size = os.path.getsize(tmp_path)
            record.video_status = "completed"
            record.video_error_message = None
            record.video_uploaded_at = datetime.utcnow()
            record.gen_channel = channel
            await session.commit()
            return {"ok": True, "file_name": safe_name, "file_size": os.path.getsize(tmp_path)}
    except Exception as e:
        logger.error("sync generated video failed (%s): %s", channel, e)
        return {"ok": False, "error": str(e)}
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


@celery_app.task(bind=True, name="app.celery.tasks.seedance_generate_task", max_retries=0)
def seedance_generate_task(
    self,
    prompt_id: str,
    *,
    duration: Optional[int] = None,
    resolution: Optional[str] = None,
    lock_token: Optional[str] = None,
):
    """Seedance 官方 API 直连出片:HTTP 调用火山方舟(无浏览器 / 无扫码)。

    状态机(shortdrama_prompts.seedance_status):
      pending → running → completed / failed / cancelled

    与豆包 RPA(doubao_generate_task)完全独立:
    - 状态字段 seedance_* 与 doubao_* 互不读写;
    - 成片统一写回 video_* 字段(下游去水印/发布零感知),
      并以 gen_channel=seedance_api 标记来源通道。
    """
    self.update_state(state="STARTED", meta={"progress": 5, "message": "Seedance 直连任务启动..."})

    try:
        record = run_async(_load_shortdrama_prompt(prompt_id))
        if not record:
            logger.error("Seedance prompt record %s not found", prompt_id)
            return {"success": False, "status": "failed", "message": "提示词记录不存在"}

        # 任务已取消则不执行
        if record.seedance_status == "cancelled":
            logger.info("Seedance task %s already cancelled, skip", prompt_id)
            return {"success": False, "status": "cancelled", "message": "任务已取消"}

        # 读取 Seedance 直连配置(环境变量 + system_config 合并),校验开关与 Key
        from app.services.ark_client import (
            load_seedance_config,
            SeedanceClient,
            resolve_duration_policy,
            poll_task,
        )

        db_config = run_async(_load_seedance_db_config())
        cfg = load_seedance_config(db_config=db_config)
        if not cfg.enabled:
            run_async(_update_seedance_prompt(
                prompt_id,
                status="failed",
                message="Seedance 官方 API 直连未启用(开关默认关闭),请先开启",
                error_message="SEEDANCE_ENABLED=false",
            ))
            return {"success": False, "status": "failed", "message": "Seedance 官方 API 直连未启用"}

        missing = cfg.validate()
        if missing:
            run_async(_update_seedance_prompt(
                prompt_id,
                status="failed",
                message=missing,
                error_message=missing,
            ))
            return {"success": False, "status": "failed", "message": missing}

        run_async(_update_seedance_prompt(
            prompt_id,
            status="running",
            message="Seedance 直连任务启动,正在创建火山方舟任务...",
            error_message=None,
        ))

        async def _progress_cb(msg: str, p: float):
            self.update_state(state="PROGRESS", meta={"progress": p, "message": msg})
            await _update_seedance_prompt(
                prompt_id,
                status="running",
                message=msg,
            )

        # 时长策略:>10s 按 truncate 截断 / block 拒绝
        want_duration = int(duration or record.duration or 10)
        actual_duration, tip = run_async(resolve_duration_policy(cfg, want_duration))
        if actual_duration == 0:
            run_async(_update_seedance_prompt(
                prompt_id,
                status="failed",
                message=tip,
                error_message=tip,
            ))
            return {"success": False, "status": "failed", "message": tip}
        if tip:
            run_async(_update_seedance_prompt(
                prompt_id,
                status="running",
                message=tip,
            ))

        client = SeedanceClient(cfg)
        # 创建方舟任务前再确认一次未被取消(缩小竞态窗口,避免已取消任务仍发起方舟调用)
        if run_async(_check_seedance_cancelled(prompt_id)):
            run_async(_update_seedance_prompt(
                prompt_id,
                status="cancelled",
                message="任务已取消",
                error_message="用户取消",
            ))
            return {"success": False, "status": "cancelled", "message": "任务已取消"}

        run_async(_update_seedance_prompt(
            prompt_id,
            status="running",
            message=f"正在创建火山方舟任务({actual_duration}s / {cfg.resolution})...",
        ))
        created = run_async(client.create_task(
            record.prompt_text,
            duration=actual_duration,
            resolution=resolution or cfg.resolution,
        ))
        task_id = created["task_id"]
        run_async(_update_seedance_prompt(
            prompt_id,
            status="running",
            message=f"火山方舟任务已创建({task_id}),等待生成...",
            task_id=task_id,
            resolution=cfg.resolution,
        ))

        # 轮询任务直到完成 / 失败 / 取消 / 超时
        outcome = run_async(poll_task(
            client,
            task_id,
            progress_cb=_progress_cb,
            cancel_check=lambda: _check_seedance_cancelled(prompt_id),
        ))

        if outcome["status"] == "cancelled":
            # 尝试取消方舟侧任务
            run_async(client.cancel_task(task_id))
            run_async(_update_seedance_prompt(
                prompt_id,
                status="cancelled",
                message="任务已取消",
                error_message="用户取消",
            ))
            return {"success": False, "status": "cancelled", "message": "任务已取消"}

        if outcome["status"] != "completed":
            run_async(_update_seedance_prompt(
                prompt_id,
                status="failed",
                message=outcome["message"],
                error_message=outcome["message"],
            ))
            return {"success": False, "status": "failed", "message": outcome["message"]}

        # 生成成功:下载成片并上传 MinIO 回填
        run_async(_update_seedance_prompt(
            prompt_id,
            status="running",
            message="视频生成完成,正在下载并上传成片...",
        ))
        download_url = outcome.get("video_url") or ""
        if not download_url:
            run_async(_update_seedance_prompt(
                prompt_id,
                status="failed",
                message="Seedance 返回成功但未获取到视频地址",
                error_message="Seedance 返回成功但未获取到视频地址",
            ))
            return {"success": False, "status": "failed", "message": "未获取到视频地址"}

        sync = run_async(_sync_generated_video(
            prompt_id,
            download_url=download_url,
            file_name=f"seedance_{_now_str()}.mp4",
            channel="seedance_api",
        ))
        if not sync.get("ok"):
            run_async(_update_seedance_prompt(
                prompt_id,
                status="failed",
                message=sync.get("error", "成片同步失败"),
                error_message=sync.get("error", "成片同步失败"),
            ))
            return {"success": False, "status": "failed", "message": sync.get("error", "成片同步失败")}

        run_async(_update_seedance_prompt(
            prompt_id,
            status="completed",
            message="Seedance 成片已生成并保存到历史",
        ))
        self.update_state(state="SUCCESS", meta={"progress": 100, "message": "Seedance 成片已生成"})
        return {
            "success": True,
            "status": "completed",
            "message": "Seedance 成片已生成并保存到历史",
            "file_name": sync.get("file_name"),
            "file_size": sync.get("file_size"),
            "task_id": task_id,
        }

    except Exception as e:
        logger.exception("Seedance generate task failed: %s", e)
        run_async(_update_seedance_prompt(
            prompt_id,
            status="failed",
            message=f"Seedance 直连生成任务异常: {e}",
            error_message=str(e),
        ))
        # 与 L432 已修复模式对齐：不 update_state(state="FAILURE") 后再 return dict,
        # 否则 Celery 后端 mark_as_done 读旧 FAILURE meta 会把 result 当异常解析,
        # 抛 ValueError('Exception information must include the exception type')。
        # 前端状态展示依赖 DB 轮询(_update_seedance_prompt 已置 failed)。
        return {"success": False, "status": "failed", "message": str(e)}
    finally:
        # 释放入口互斥锁（token 不匹配时 Lua 不会误删他人的锁）
        if lock_token:
            try:
                from app.services.distributed_lock import release_lock
                run_async(release_lock(f"shortdrama:lock:seedance:{prompt_id}", lock_token))
            except Exception:
                logger.warning("释放 Seedance 互斥锁失败 prompt=%s", prompt_id)
