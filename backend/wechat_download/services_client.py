"""智令「其他服务」客户端：文案提取 / AI消除 / 画质修复 / TTS / 音色训练。

一份 key 走五条链路（域名 https://api.17zhiling.com，key 作为 query/表单参数）：

| 能力 | 提交 | 查询 |
|---|---|---|
| 文案提取 doc/102 | POST /api/asr/parse-video-url | GET /api/asr/task-status |
| AI消除·计时 doc/114 | POST /api/ai-eraser/submit-task-time | GET /api/ai-eraser/task-status |
| 画质修复 doc/123 | POST /api/ai-eraser/submit-task-hd-time | 同上（doc/105） |
| 文字转语音 doc/108 | POST /api/voiceclone/tts/async | GET /api/voiceclone/tts/status |
| 音色训练 doc/128 | POST /api/voiceclone/my-models/create（multipart） | 同步返回 |

两处状态口径完全不同，必须分别归一化，别指望一个 field 通吃：
- asr / ai-eraser 用 `data.schedule`：asr 是字符串（SUCCESS/WAIT_HANDLE/ING/FAIL），
  ai-eraser 是整数（2 成功 / 0 待处理 / 1 处理中 / 3 失败）；
- tts 用 `data.status`：processing / completed / failed。

密钥复用 WECHAT_DL_ZHILING_KEY（与 doc/107、doc/120 同一账号），不落仓库、不新增配置项。
失败一律 fail-soft：抛 ZhilingServiceError 由上层写库 failed，不在 API 层抬 500。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import settings
from wechat_download.url_gate import direct_url_reject_reason, url_shape_text

logger = logging.getLogger(__name__)

# 归一化状态（与 models.ZS_* 对齐）
STATUS_PROCESSING = "processing"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

# 服务类型（与 models.ZS_TASK_TYPES 对齐）
T_COPY_EXTRACT = "copy_extract"
T_AI_ERASER = "ai_eraser"
T_HD_RESTORE = "hd_restore"
T_TTS = "tts"
T_VOICE_CLONE = "voice_clone"

# TTS 单次文本上限（官方限制）
TTS_MAX_TEXT = 5000
# TTS 音频产物有效期（官方 24 小时），落库/展示口径一致
TTS_AUDIO_TTL_HOURS = 24


class ZhilingServiceError(Exception):
    """智令其他服务调用失败（参数/网络/业务异常），供上层记 failed。"""


@dataclass
class ZhilingStatus:
    """一次轮询的归一化结果。"""

    status: str
    progress: Optional[float] = None
    result_url: Optional[str] = None
    result_text: Optional[str] = None
    srt_text: Optional[str] = None
    voice_model_id: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[dict] = field(default=None)


def _truncate(text: Optional[str], limit: int = 500) -> Optional[str]:
    if not text:
        return None
    text = str(text).strip()
    return text[:limit] if len(text) > limit else text


def _dig(data, path: str):
    """按点分路径取嵌套字段，任意一层缺失返回 None。"""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


# 上游响应里值得进报错的字段：只有这几个机器可读的状态位
_HINT_KEYS = ("code", "msg", "message", "errMsg", "error")


def _resp_hint(data) -> str:
    """把上游响应的 code/msg 拼成报错后缀（**不带 key、不带整包 body**）。

    旧写法是 `str(data)[:200]` 整包塞进报错：一来上游若在响应里回显敏感字段会跟着
    入库存，二来一线看见一坨 JSON 也不知道下一步干什么。这里只挑状态码和原因文本，
    外层和 `data` 内层各取一次（智令两种形状都见过）。
    """
    if not isinstance(data, dict):
        return f"；上游响应不是对象（{_truncate(str(data), 120) or '空'}）"
    bits = []
    for source in (data, data.get("data") if isinstance(data.get("data"), dict) else None):
        if source is None:
            continue
        for key in _HINT_KEYS:
            value = source.get(key)
            if value is None or str(value).strip() == "" or f"{key}={value}" in bits:
                continue
            bits.append(f"{key}={_truncate(str(value).strip(), 80)}")
    return f"；上游响应 {' '.join(bits)}" if bits else ""


class ZhilingServiceClient:
    """智令其他服务客户端（提交 + 轮询 + 视频直链解析）。"""

    def __init__(self) -> None:
        self.base = (settings.WECHAT_DL_ZHILING_PROMPT_BASE or "").rstrip("/")
        # 与 doc/107/120/125 复用同一个 env，走 os.getenv 保证多条链路读同一份
        self.key = (
            os.getenv("WECHAT_DL_ZHILING_KEY", "")
            or getattr(settings, "WECHAT_DL_ZHILING_KEY", "")
            or ""
        ).strip()
        self.timeout = settings.WECHAT_DL_PROMPT_TIMEOUT
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(float(self.timeout)),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (clip-workflow/wechat-dl)"},
        )

    # ── 基础设施 ──
    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    def _require_key(self) -> None:
        if not self.key:
            raise ZhilingServiceError("未配置 WECHAT_DL_ZHILING_KEY，无法调用智令服务接口")

    async def _post_form(self, path: str, payload: dict) -> dict:
        """form-urlencoded 提交，返回 `data`；业务异常（code != 200）抛错。"""
        self._require_key()
        payload = {k: v for k, v in payload.items() if v is not None}
        payload["key"] = self.key
        return await self._request("POST", path, data=payload)

    async def _post_multipart(self, path: str, fields: dict) -> dict:
        """multipart/form-data 提交（音色训练建模型用），files 只放文本字段。"""
        self._require_key()
        fields = {k: str(v) for k, v in fields.items() if v is not None}
        files = {k: (None, v) for k, v in fields.items()}
        try:
            resp = await self._client.post(
                self._url(path), params={"key": self.key}, files=files,
            )
        except httpx.HTTPError as e:
            raise ZhilingServiceError(f"请求失败: {e}") from e
        return self._unwrap(resp, path)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = await self._client.request(method, self._url(path), **kwargs)
        except httpx.HTTPError as e:
            raise ZhilingServiceError(f"请求 {path} 失败: {e}") from e
        return self._unwrap(resp, path)

    def _unwrap(self, resp: httpx.Response, path: str) -> dict:
        """统一解包 `{code:200, msg, data}`；code != 200（含 -1）取 msg 抛错。"""
        if resp.status_code != 200:
            raise ZhilingServiceError(f"请求 {path} http {resp.status_code}: {_truncate(resp.text, 200)}")
        try:
            body = resp.json()
        except Exception:
            raise ZhilingServiceError(
                f"请求 {path} 响应非 JSON（可能被 WAF 拦截），body 前 120 字节: {resp.text[:120]}"
            )
        if not isinstance(body, dict):
            raise ZhilingServiceError(f"请求 {path} 响应结构异常: {_truncate(str(body), 200)}")
        code = body.get("code")
        if code != 200:
            raise ZhilingServiceError(
                f"请求 {path} 失败（code={code}）: {body.get('msg') or '未知原因'}"
            )
        return body.get("data")

    async def _get_status(self, path: str, params: dict) -> dict:
        """查询接口：只带 key + 业务参数，返回 data（dict）。"""
        self._require_key()
        q = {"key": self.key}
        q.update({k: v for k, v in params.items() if v is not None})
        data = await self._request("GET", path, params=q)
        if not isinstance(data, dict):
            raise ZhilingServiceError(f"查询 {path} 响应缺少 data")
        return data

    @staticmethod
    def _task_id(data) -> str:
        """提交返回的 data 即 taskId（字符串）。"""
        if isinstance(data, str) and data.strip():
            return data.strip()
        if isinstance(data, dict):
            for k in ("taskId", "task_id", "id", "recordId"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        raise ZhilingServiceError(f"提交未返回 taskId: {_truncate(str(data), 200)}")

    # ── ① 文案提取 doc/102 ──
    async def submit_copy_extract(self, video_url: str, need_srt: bool = True) -> str:
        data = await self._post_form(
            "/api/asr/parse-video-url",
            {"videoUrl": video_url, "needSrt": "true" if need_srt else "false"},
        )
        return self._task_id(data)

    async def query_asr(self, task_id: str) -> ZhilingStatus:
        data = await self._get_status("/api/asr/task-status", {"taskId": task_id})
        schedule = str(data.get("schedule") or "").upper()
        if schedule == "SUCCESS":
            return ZhilingStatus(
                status=STATUS_SUCCESS,
                result_text=data.get("content"),
                srt_text=data.get("srtContent"),
                raw=data,
            )
        if schedule == "FAIL":
            return ZhilingStatus(
                status=STATUS_FAILED,
                error=_truncate(data.get("msg") or data.get("error") or "文案提取失败"),
                raw=data,
            )
        # WAIT_HANDLE / ING / 未知：一律处理中（不误判终态）
        return ZhilingStatus(status=STATUS_PROCESSING, raw=data)

    # ── ② AI消除 doc/114 + ③ 画质修复 doc/123（共用查询 doc/105）──
    async def submit_eraser(self, file_url: str, hd: bool = False) -> str:
        path = "/api/ai-eraser/submit-task-hd-time" if hd else "/api/ai-eraser/submit-task-time"
        data = await self._post_form(path, {"fileUrl": file_url})
        return self._task_id(data)

    async def query_eraser(self, task_id: str) -> ZhilingStatus:
        data = await self._get_status("/api/ai-eraser/task-status", {"taskId": task_id})
        raw_schedule = data.get("schedule")
        # schedule 是整数（2 成功 / 0 待处理 / 1 处理中 / 3 失败），但也兼容字符串 "2"
        try:
            code = int(str(raw_schedule).strip())
        except (TypeError, ValueError):
            return ZhilingStatus(status=STATUS_PROCESSING, raw=data)
        progress = data.get("progress")
        try:
            progress = float(progress) if progress is not None else None
        except (TypeError, ValueError):
            progress = None
        if code == 2:
            result = data.get("resultUrl") or data.get("result_url")
            if not result:
                return ZhilingStatus(
                    status=STATUS_FAILED, progress=progress,
                    error="任务已完成但未返回结果地址", raw=data,
                )
            return ZhilingStatus(status=STATUS_SUCCESS, progress=1.0, result_url=result, raw=data)
        if code == 3:
            return ZhilingStatus(
                status=STATUS_FAILED, progress=progress,
                error=_truncate(data.get("msg") or data.get("error") or "处理失败"),
                raw=data,
            )
        return ZhilingStatus(status=STATUS_PROCESSING, progress=progress, raw=data)

    # ── ④ 文字转语音 doc/108 ──
    async def submit_tts(
        self,
        *,
        text: str,
        voice_type: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        audio_format: str = "mp3",
    ) -> str:
        data = await self._post_form(
            "/api/voiceclone/tts/async",
            {
                "text": text,
                "voiceType": voice_type,
                "voiceId": voice_id,
                "modelId": model_id,
                "format": audio_format,
            },
        )
        return self._task_id(data)

    async def query_tts(self, task_id: str) -> ZhilingStatus:
        # 注意参数名是 recordId（不是 taskId），照抄官方文档，写错必 400
        data = await self._get_status("/api/voiceclone/tts/status", {"recordId": task_id})
        status = str(data.get("status") or "").lower()
        if status == "completed":
            url = data.get("url") or _dig(data, "data.url")
            if not url:
                return ZhilingStatus(status=STATUS_FAILED, error="合成完成但未返回音频地址", raw=data)
            return ZhilingStatus(status=STATUS_SUCCESS, result_url=url, raw=data)
        if status == "failed":
            return ZhilingStatus(
                status=STATUS_FAILED,
                error=_truncate(data.get("msg") or data.get("error") or "语音合成失败"),
                raw=data,
            )
        return ZhilingStatus(status=STATUS_PROCESSING, raw=data)

    # ── ⑤ 音色训练 doc/128（同步返回，无轮询）──
    async def create_voice_model(
        self, *, name: str, audio_url: str, description: Optional[str] = None,
    ) -> dict:
        data = await self._post_multipart(
            "/api/voiceclone/my-models/create",
            {"name": name, "audioUrl": audio_url, "description": description},
        )
        if not isinstance(data, dict):
            raise ZhilingServiceError(f"音色训练返回结构异常: {_truncate(str(data), 200)}")
        model_id = data.get("modelId") or data.get("model_id")
        if not model_id:
            raise ZhilingServiceError(f"音色训练未返回 modelId: {_truncate(str(data), 200)}")
        return {"model_id": str(model_id), "model_name": data.get("modelName") or name, "raw": data}

    # ── 视频直链解析（复用 doc/107 解析链路）──
    async def resolve_direct_url(self, share_url: str) -> str:
        """分享链接 → 视频直链（智令 doc/107，约 0.01 元/次）。

        AI消除 / 画质修复只吃直链，分享链接必须先过这一层。

        **收单要过形状闸门**（11-10 加，见 `url_gate` 模块注释）：短剧导流页那类链接，
        智令会「解析成功」地回一个站点根（实测 `https://vnd2.17zhilian.cn/`）。旧写法
        只看「是不是以 http 开头」就收，于是下游把首页当视频用——下载原片存成 10KB 的
        HTML、反推必然「未检测到视频」、补投再解析一次再拿回同一个根路径。现在这种
        地址在**花钱解析的这一层**就白话拒收，报错里带上「解析到什么形状 + 上游
        code/msg」，一线看得懂下一步干什么。
        """
        self._require_key()
        data = await self._request(
            "GET", "/api/video/parse-video-url", params={"key": self.key, "url": share_url},
        )
        candidates = [
            "play_url", "url", "video_url", "mp4", "videoUrl",
            "data.play_url", "data.url", "data.video_url",
        ]
        gate_on = bool(getattr(settings, "WECHAT_DL_DIRECT_URL_SHAPE_GATE", True))
        rejected: Optional[str] = None
        for c in candidates:
            v = _dig(data, c) if "." in c else (data.get(c) if isinstance(data, dict) else None)
            if not (isinstance(v, str) and v.startswith("http")):
                continue
            reason = direct_url_reject_reason(v) if gate_on else None
            if reason is None:
                return v
            # 记第一条被拒的形状继续找下一个候选：智令有时同一层里给多个地址
            rejected = rejected or f"{reason}（解析到 {url_shape_text(v)}）"
        if rejected:
            raise ZhilingServiceError(f"视频直链不可用：{rejected}{_resp_hint(data)}")
        raise ZhilingServiceError(f"视频直链解析失败：响应里没有 http 地址{_resp_hint(data)}")
