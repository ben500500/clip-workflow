"""Seedance 官方 API 直连客户端（火山方舟 Volcano Ark）。

与「豆包 RPA」出片通道完全独立、互不影响的第二条出片通道：
- 豆包 RPA：Playwright 浏览器自动化（doubao_service.DoubaoGenerator）
- Seedance 官方 API：HTTP 直连火山方舟（本模块）

本模块仅封装「创建任务 / 查询状态 / 取消任务」三个官方接口与配置读取，
不包含任何豆包 RPA 逻辑，保证两套方案逻辑隔离、开关切换时不会弄混。

官方接口（ARK_BASE = https://ark.cn-beijing.volces.com/api/v3）：
  POST {ARK_BASE}/contents/generations/tasks          → 创建生成任务，返回 task_id
  GET  {ARK_BASE}/contents/generations/tasks/{task_id} → 查询任务状态
  POST {ARK_BASE}/contents/generations/tasks/{task_id}/cancel → 取消任务

鉴权：Authorization: Bearer ${SEEDANCE_API_KEY}

开关控制（seedance 直连默认关闭）：
  - 开关存在 system_config 的 shortdrama_seedance_config.enabled（默认 false），
    同时受环境变量 SEEDANCE_ENABLED 兜底（默认 false）。
  - 开关未打开时，后端启动/取消/状态查询接口一律返回 403，前端不展示该通道。
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 火山方舟 API 基础地址
ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
# 创建生成任务
ARK_TASK_CREATE = f"{ARK_BASE}/contents/generations/tasks"
# 查询任务状态 / 取消任务（%s 为 task_id）
ARK_TASK_GET = f"{ARK_BASE}/contents/generations/tasks/{{task_id}}"
ARK_TASK_CANCEL = f"{ARK_BASE}/contents/generations/tasks/{{task_id}}/cancel"

# Seedance 1.0 官方仅支持 5s / 10s
SEEDANCE_SUPPORTED_DURATIONS = (5, 10)
# 超长时长策略
LONG_DURATION_POLICY_TRUNCATE = "truncate"   # 截断为 10s 生成
LONG_DURATION_POLICY_BLOCK = "block"         # 拒绝并提示

# 任务状态机（官方返回 status 字段）
ARK_STATUS_QUEUED = "queued"
ARK_STATUS_RUNNING = "running"
ARK_STATUS_SUCCEEDED = "succeeded"
ARK_STATUS_FAILED = "failed"
ARK_STATUS_CANCELLED = "cancelled"
# 未结束（仍需轮询）的状态
ARK_PENDING_STATUSES = {ARK_STATUS_QUEUED, ARK_STATUS_RUNNING}


def _normalize_bool(value) -> bool:
    """宽松的布尔解析：true/1/yes/on → True，其余 → False。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on", "y")
    return False


class SeedanceConfig:
    """Seedance 直连配置（环境变量 + system_config 覆盖）。

    system_config key = shortdrama_seedance_config（JSON）：
      {
        "enabled": false,            # 总开关（默认关闭）
        "api_key": "",               # 火山方舟 API Key（可留空，优先取环境变量）
        "model": "seedance-1-0-pro-250528",
        "resolution": "1080p",
        "watermark": true,
        "long_duration_policy": "truncate",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "timeout": 600,
        "daily_quota": 50,           # 日配额（0=不限）
      }

    优先级：system_config 中显式配置 > 环境变量 > 内置默认。
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        api_key: str = "",
        model: str = "seedance-1-0-pro-250528",
        resolution: str = "1080p",
        watermark: bool = True,
        long_duration_policy: str = LONG_DURATION_POLICY_TRUNCATE,
        api_base: str = ARK_BASE,
        timeout: int = 600,
        daily_quota: int = 0,
    ):
        self.enabled = enabled
        self.api_key = api_key
        self.model = model
        self.resolution = resolution
        self.watermark = watermark
        self.long_duration_policy = long_duration_policy
        self.api_base = api_base
        self.timeout = timeout
        self.daily_quota = daily_quota

    def to_public_dict(self) -> dict:
        """对外暴露的只读配置（绝不包含 api_key）。"""
        return {
            "enabled": self.enabled,
            "model": self.model,
            "resolution": self.resolution,
            "watermark": self.watermark,
            "long_duration_policy": self.long_duration_policy,
            "supported_durations": list(SEEDANCE_SUPPORTED_DURATIONS),
            "timeout": self.timeout,
            "daily_quota": self.daily_quota,
            "has_api_key": bool(self.api_key),
        }

    def validate(self) -> Optional[str]:
        """返回配置缺失说明；None 表示可正常使用。"""
        if not self.api_key:
            return "未配置 SEEDANCE_API_KEY（火山方舟 API Key）"
        return None


def load_seedance_config(env: Optional[dict] = None, db_config: Optional[dict] = None) -> SeedanceConfig:
    """从环境变量 + system_config 合并构建 Seedance 直连配置。

    Args:
        env: 环境变量字典（默认取 os.environ，测试可注入）
        db_config: system_config.shortdrama_seedance_config 的 JSON 值（可空）

    优先级：db_config 显式字段 > 环境变量 > 内置默认。
    """
    import os as _os

    env = env if env is not None else dict(_os.environ)

    # 环境变量兜底
    env_enabled = _normalize_bool(env.get("SEEDANCE_ENABLED", ""))
    env_key = (env.get("SEEDANCE_API_KEY") or "").strip()
    env_model = (env.get("SEEDANCE_MODEL") or "").strip() or "seedance-1-0-pro-250528"
    env_resolution = (env.get("SEEDANCE_RESOLUTION") or "").strip() or "1080p"
    env_watermark = _normalize_bool(env.get("SEEDANCE_WATERMARK", "true"))
    env_policy = (env.get("SEEDANCE_LONG_DURATION_POLICY") or "").strip() or LONG_DURATION_POLICY_TRUNCATE
    env_base = (env.get("SEEDANCE_API_BASE") or "").strip() or ARK_BASE
    try:
        env_timeout = int(env.get("SEEDANCE_TIMEOUT", "600"))
    except (TypeError, ValueError):
        env_timeout = 600
    try:
        env_quota = int(env.get("SEEDANCE_DAILY_QUOTA", "0"))
    except (TypeError, ValueError):
        env_quota = 0

    db = db_config or {}

    enabled = db.get("enabled") if "enabled" in db else env_enabled
    api_key = str(db.get("api_key") or env_key or "").strip()
    model = str(db.get("model") or env_model or "seedance-1-0-pro-250528").strip()
    resolution = str(db.get("resolution") or env_resolution or "1080p").strip()
    watermark = db.get("watermark") if "watermark" in db else env_watermark
    policy = str(db.get("long_duration_policy") or env_policy or LONG_DURATION_POLICY_TRUNCATE).strip()
    api_base = str(db.get("api_base") or env_base or ARK_BASE).strip().rstrip("/")
    timeout = db.get("timeout") if "timeout" in db else env_timeout
    quota = db.get("daily_quota") if "daily_quota" in db else env_quota

    return SeedanceConfig(
        enabled=_normalize_bool(enabled),
        api_key=api_key,
        model=model,
        resolution=resolution,
        watermark=_normalize_bool(watermark),
        long_duration_policy=policy if policy in (LONG_DURATION_POLICY_TRUNCATE, LONG_DURATION_POLICY_BLOCK) else LONG_DURATION_POLICY_TRUNCATE,
        api_base=api_base,
        timeout=int(timeout) if str(timeout).isdigit() else 600,
        daily_quota=int(quota) if str(quota).isdigit() else 0,
    )


class SeedanceClient:
    """火山方舟 Seedance 官方 API 客户端（HTTP 直连，无浏览器）。"""

    def __init__(self, config: SeedanceConfig):
        self.config = config

    def _base(self) -> str:
        return self.config.api_base or ARK_BASE

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _task_url(self, task_id: str) -> str:
        return f"{self._base()}/contents/generations/tasks/{task_id}"

    def _cancel_url(self, task_id: str) -> str:
        return f"{self._base()}/contents/generations/tasks/{task_id}/cancel"

    # ──────────────────────────────────────────────
    # 创建生成任务
    # ──────────────────────────────────────────────

    async def create_task(
        self,
        prompt: str,
        *,
        duration: int = 10,
        resolution: Optional[str] = None,
        watermark: Optional[bool] = None,
        seed: int = 0,
        fps: int = 24,
    ) -> dict:
        """创建 Seedance 生成任务。

        Returns:
            {"task_id": str, "raw": dict}
        Raises:
            httpx.HTTPStatusError / httpx.RequestError
        """
        # 时长归一化：Seedance 1.0 仅支持 5s/10s，>10s 由上层按策略处理
        duration = int(duration)
        if duration not in SEEDANCE_SUPPORTED_DURATIONS:
            duration = 10 if duration > 10 else 5

        payload = {
            "model": self.config.model,
            "content": [{"type": "text", "text": prompt}],
            "resolution": resolution or self.config.resolution,
            "duration": f"{duration}s",
            "watermark": self.config.watermark if watermark is None else watermark,
            "fps": fps,
            "seed": seed,
        }
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(
                f"{self._base()}/contents/generations/tasks",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        task_id = (data or {}).get("id") or (data or {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"创建 Seedance 任务未返回 task_id：{data}")
        return {"task_id": str(task_id), "raw": data}

    # ──────────────────────────────────────────────
    # 查询任务状态
    # ──────────────────────────────────────────────

    async def get_task(self, task_id: str) -> dict:
        """查询任务状态。

        Returns:
            {"status": str, "video_url": Optional[str], "message": str, "raw": dict}
        """
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.get(self._task_url(task_id), headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

        status = (data or {}).get("status") or "unknown"
        video_url = None
        # 不同版本字段差异：content.video.url / video_url / output.url
        content = (data or {}).get("content") or {}
        if isinstance(content, dict):
            video_url = content.get("video", {}).get("url") if isinstance(content.get("video"), dict) else None
            video_url = video_url or content.get("url")
        video_url = video_url or (data or {}).get("video_url") or (data or {}).get("output", {}).get("url")
        error = (data or {}).get("error") or {}
        message = ""
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or ""
        elif error:
            message = str(error)
        return {"status": status, "video_url": video_url, "message": message, "raw": data}

    # ──────────────────────────────────────────────
    # 取消任务
    # ──────────────────────────────────────────────

    async def cancel_task(self, task_id: str) -> dict:
        """取消任务（尽力而为，失败不抛错）。"""
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(self._cancel_url(task_id), headers=self._headers())
                resp.raise_for_status()
                return {"ok": True, "raw": resp.json()}
        except Exception as e:  # noqa: BLE001
            logger.warning("取消 Seedance 任务 %s 失败（忽略）: %s", task_id, e)
            return {"ok": False, "error": str(e)}


async def resolve_duration_policy(config: SeedanceConfig, duration: int) -> tuple[int, Optional[str]]:
    """按超长策略解析实际生成时长。

    Returns:
        (实际时长, 提示消息或 None)
    """
    duration = int(duration or 10)
    if duration in SEEDANCE_SUPPORTED_DURATIONS:
        return duration, None
    if duration > max(SEEDANCE_SUPPORTED_DURATIONS):
        if config.long_duration_policy == LONG_DURATION_POLICY_BLOCK:
            return 0, f"Seedance 官方 API 当前仅支持 {SEEDANCE_SUPPORTED_DURATIONS[0]}s / {SEEDANCE_SUPPORTED_DURATIONS[1]}s，请选择 10s 或改用豆包 RPA 出片"
        # truncate：截断为 10s 生成
        return max(SEEDANCE_SUPPORTED_DURATIONS), f"提示词时长为 {duration}s，Seedance 官方 API 当前仅支持 10s，已按 10s 生成"
    # 小于 5s：按 5s
    return min(SEEDANCE_SUPPORTED_DURATIONS), None


async def poll_task(
    client: SeedanceClient,
    task_id: str,
    *,
    progress_cb=None,
    cancel_check=None,
    poll_interval: float = 5.0,
    timeout: Optional[int] = None,
) -> dict:
    """轮询 Seedance 生成任务直到结束。

    Args:
        progress_cb: async def cb(status: str, message: str, progress: float)
        cancel_check: callable -> bool（返回 True 表示任务已取消）
        timeout: 轮询总超时（秒），默认取配置 timeout

    Returns:
        {"status": "completed"/"failed"/"cancelled"/"timeout",
         "video_url": Optional[str], "message": str}
    """
    timeout = timeout or client.config.timeout
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_check is not None:
            try:
                res = cancel_check()
                if asyncio.iscoroutine(res):
                    res = await res
                if res:
                    return {"status": "cancelled", "video_url": None, "message": "任务已取消"}
            except Exception:
                pass

        try:
            state = await client.get_task(task_id)
        except httpx.RequestError as e:
            logger.warning("查询 Seedance 任务 %s 失败（重试）: %s", task_id, e)
            await asyncio.sleep(poll_interval)
            continue
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "video_url": None, "message": f"查询 Seedance 任务失败: {e}"}

        status = state.get("status") or "unknown"
        if progress_cb is not None:
            await progress_cb(status, state.get("message") or "", 0.0)

        if status == ARK_STATUS_SUCCEEDED:
            video_url = state.get("video_url")
            if not video_url:
                return {"status": "failed", "video_url": None, "message": "Seedance 任务成功但未返回视频地址"}
            return {"status": "completed", "video_url": video_url, "message": "Seedance 视频生成完成"}
        if status == ARK_STATUS_FAILED:
            return {"status": "failed", "video_url": None, "message": state.get("message") or "Seedance 生成失败"}
        if status == ARK_STATUS_CANCELLED:
            return {"status": "cancelled", "video_url": None, "message": "Seedance 任务已取消"}
        if status not in ARK_PENDING_STATUSES:
            logger.warning("Seedance 任务未知状态 %s，继续轮询", status)

        await asyncio.sleep(poll_interval)

    return {"status": "timeout", "video_url": None, "message": f"等待 Seedance 生成超时（{timeout}s）"}
