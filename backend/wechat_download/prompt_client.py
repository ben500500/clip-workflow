"""智令「视频反推提示词」客户端（doc/120 提交 + doc/119 轮询）。

链路（官方文档 https://api.17zhiling.com/doc/120）：
1. 提交 `POST /api/video-inference/parse-video-url-time`
   - form-urlencoded：key / videoUrl / maxDuration（可选，秒，最大 600；
     本系统默认取 `WECHAT_DL_PROMPT_MAX_DURATION`，11-09 起为 180——**按这个上限
     计费，失败也扣钱**，所以默认值就是单价，别随手留空按 600 投）
   - 返回 `{code:200, data:"<taskId>", msg, exec_time}`，`data` 即任务 id
2. 轮询 `GET /api/video-inference/task-status?key=&taskId=`（官方免费，建议 3~5s 一次）
   - `data.schedule`：WAIT_HANDLE / PROCESSING / SUCCESS / FAIL
   - SUCCESS 时 `data.content` 为提示词正文（markdown）
   - **FAIL 时原因在 `data.errMsg`**（外层 `msg` 此时仍是 "success"，不能当原因用），
     现网实测常见值「视频理解服务返回空结果」——换时刻重投通常就好了，见 _fail_reason
   - `code=-1` 为业务异常（含额度耗尽），原因看 `msg`
   - 计费 0.00054 元/秒（点数 0.54 点/秒，不足 1 点按 1 点），注册赠 30 次

密钥复用 WECHAT_DL_ZHILING_KEY（与 doc/107 解析同一账号），不落仓库。
失败一律 fail-soft：抛 PromptError 由上层写库，不在 API 层抬成 500。
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 官方 schedule → 本系统状态
SCHEDULE_WAIT = "WAIT_HANDLE"
SCHEDULE_PROCESSING = "PROCESSING"
SCHEDULE_SUCCESS = "SUCCESS"
SCHEDULE_FAIL = "FAIL"

# 归一化后的本系统状态（与 models.PT_* 对齐）
STATUS_PROCESSING = "processing"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


class PromptError(Exception):
    """反推提示词外部调用失败（网络/业务异常），供上层记 failed 而不抬 500。"""


# 「查询没查到，但不代表任务死了」的信号（11-03 接 163 现网实测踩到的坑）：
# 智令自己的网关转发上游超时时会回 code=500 + msg="转发请求失败: CURL请求失败:
# Operation timed out after 10001 milliseconds with 0 bytes received"。
# 这是**它的查询链路**抖动，任务侧大概率还在跑——旧逻辑把它当终态失败，
# 结果：钱已经扣了（提交时按 maxDuration 计费），素材却判死，一线只能带
# retry_failed=true 重跑，同一条视频再扣一次 0.097 元。所以这类一律归为
# 「仍在处理中」，让下一轮轮询去收；真正的终态失败只认 schedule=FAIL
# 和明确的业务 code（如 -1 额度耗尽）。
TRANSIENT_MSG_MARKERS = (
    "转发请求失败",
    "curl请求失败",
    "operation timed out",
    "timed out",
    "timeout",
    "connection refused",
    "connection reset",
    "temporarily unavailable",
    "try again later",
    "upstream",
    "bad gateway",
    "gateway timeout",
    "service unavailable",
)
# 这些 HTTP 状态是网关/服务端抖动，不是「任务失败」
TRANSIENT_HTTP_CODES = (408, 429, 500, 502, 503, 504)


def _looks_transient(code: object, msg: Optional[str]) -> bool:
    """判断一次 code!=200 的查询是「链路抖动」还是「业务终态失败」。"""
    try:
        code_int = int(code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        code_int = None
    if code_int in TRANSIENT_HTTP_CODES:
        return True
    text = (msg or "").strip().lower()
    return any(marker in text for marker in TRANSIENT_MSG_MARKERS)


@dataclass
class PromptStatus:
    """一次轮询的归一化结果。"""

    status: str  # processing / success / failed
    content: Optional[str] = None
    error: Optional[str] = None
    schedule: Optional[str] = None
    # True＝这一轮查询链路不通（不是任务失败），status 会保持 processing；
    # 上层据此决定「继续等」还是「等够了再收口」，见 prompt_service.refresh_prompt_task
    transient: bool = False
    raw: Optional[dict] = None


def _truncate(text: Optional[str], limit: int = 500) -> Optional[str]:
    if not text:
        return None
    text = str(text).strip()
    return text[:limit] if len(text) > limit else text


# 终态失败的原因字段：官方 doc/119 在 schedule=FAIL 时把原因放在 **errMsg**，
# 不是 msg（外层 msg 这时候是 "success"，拿它当原因等于把真因丢了）。
# 11-09 现网成批 failed 就卡在这：库里只写「任务处理失败」，一线看不见是
# 「视频理解服务返回空结果」还是「额度耗尽」，两种处置完全不一样。
# 多个候选键按官方新旧响应形状依次取，第一个非空即用；msg 放最后兜底
# （个别版本确实把原因写在 msg 里）。
FAIL_REASON_KEYS = ("errMsg", "error_msg", "errorMsg", "error", "msg")

# 一个原因都没捞出来时的兜底文案。上层（prompt_service）靠**认这句**判断「原文里没人话」，
# 从而把原始响应体补进 error——所以它必须是个常量，不能让两边各写一遍字面量。
FAIL_DEFAULT_REASON = "任务处理失败"


def _fail_reason(data: dict, default: str = FAIL_DEFAULT_REASON) -> str:
    """从 FAIL 响应的 data 里捞出人话失败原因（errMsg 优先）。"""
    for key in FAIL_REASON_KEYS:
        value = data.get(key)
        if value and str(value).strip().lower() not in ("success", "ok", "null", "none"):
            return _truncate(str(value).strip()) or default
    return default


class PromptClient:
    """智令视频反推提示词客户端（提交 + 轮询）。"""

    def __init__(self) -> None:
        self.base = (settings.WECHAT_DL_ZHILING_PROMPT_BASE or "").rstrip("/")
        # 密钥与 doc/107 解析复用同一个 env（HttpApiAdapter 亦按 WECHAT_DL_<NAME>_KEY 读取），
        # 走 os.getenv 保证两条链路读的是同一个变量、不会各读一份而漂移。
        self.key = (
            os.getenv("WECHAT_DL_ZHILING_KEY", "")
            or getattr(settings, "WECHAT_DL_ZHILING_KEY", "")
            or ""
        ).strip()
        self.submit_path = settings.WECHAT_DL_ZHILING_PROMPT_SUBMIT_PATH
        self.status_path = settings.WECHAT_DL_ZHILING_PROMPT_STATUS_PATH
        self.timeout = settings.WECHAT_DL_PROMPT_TIMEOUT
        self.default_max_duration = settings.WECHAT_DL_PROMPT_MAX_DURATION
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(float(self.timeout)),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (clip-workflow/wechat-dl)"},
        )

    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    async def submit(self, video_url: str, max_duration: Optional[int] = None) -> str:
        """提交反推任务，返回智令侧 taskId。

        业务异常（code != 200，含 -1 额度耗尽）抛 PromptError（原因取 msg）。
        """
        if not self.key:
            raise PromptError("未配置 WECHAT_DL_ZHILING_KEY，无法调用反推提示词接口")
        video_url = (video_url or "").strip()
        if not video_url:
            raise PromptError("视频链接为空")
        # 注意必须判 None：max_duration=0 是「显式传入」而非缺省，用 `or` 会被吞成默认值。
        duration = self.default_max_duration if max_duration is None else max_duration
        # 官方上限 600s，超界直接夹紧，避免被服务端拒绝
        duration = max(1, min(int(duration), 600))

        payload = {"key": self.key, "videoUrl": video_url, "maxDuration": str(duration)}
        try:
            resp = await self._client.post(self._url(self.submit_path), data=payload)
        except httpx.HTTPError as e:
            raise PromptError(f"提交反推任务请求失败: {e}") from e

        if resp.status_code != 200:
            raise PromptError(f"提交反推任务 http {resp.status_code}: {_truncate(resp.text, 200)}")
        try:
            body = resp.json()
        except Exception:
            raise PromptError(
                f"提交反推任务响应非 JSON（可能被 WAF 拦截），body 前 120 字节: {resp.text[:120]}"
            )

        code = body.get("code")
        if code != 200:
            raise PromptError(f"提交反推任务失败（code={code}）: {body.get('msg') or '未知原因'}")
        task_id = body.get("data")
        if not task_id or not isinstance(task_id, str):
            raise PromptError(f"提交反推任务未返回 taskId: {_truncate(str(body), 200)}")
        return task_id

    async def query(self, task_id: str) -> PromptStatus:
        """查询一次任务状态（doc/119）。

        免费接口。**链路抖动不等于任务失败**：本地超时／非 JSON／智令网关自己转发失败
        （code=500「转发请求失败」）一律归为 processing + `transient=True`，由上层
        按容忍时长决定何时收口；只有 schedule=FAIL 与明确业务异常（如 -1 额度耗尽）
        才判 failed。不抛错给 API 层。
        """
        if not self.key:
            return PromptStatus(status=STATUS_FAILED, error="未配置 WECHAT_DL_ZHILING_KEY")
        if not task_id:
            return PromptStatus(status=STATUS_FAILED, error="缺失 provider task id")

        params = {"key": self.key, "taskId": task_id}
        try:
            resp = await self._client.get(self._url(self.status_path), params=params)
            if resp.status_code != 200:
                if resp.status_code in TRANSIENT_HTTP_CODES:
                    return PromptStatus(
                        status=STATUS_PROCESSING,
                        error=(
                            f"查询反推状态 http {resp.status_code}（链路抖动，保持处理中）: "
                            f"{_truncate(resp.text, 200)}"
                        ),
                        transient=True,
                    )
                return PromptStatus(
                    status=STATUS_FAILED,
                    error=f"查询反推状态 http {resp.status_code}: {_truncate(resp.text, 200)}",
                )
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            # 本地网络超时／被网关截成错误页：问不通 ≠ 做不出来，保持处理中
            return PromptStatus(
                status=STATUS_PROCESSING,
                error=f"查询反推状态失败: {e}",
                transient=True,
            )

        code = body.get("code")
        if code != 200:
            # code=-1 为业务异常（含额度耗尽），msg 给出原因
            if _looks_transient(code, body.get("msg")):
                return PromptStatus(
                    status=STATUS_PROCESSING,
                    error=f"查询反推状态不通（code={code}）: {body.get('msg') or '未知原因'}",
                    transient=True,
                    raw=body,
                )
            return PromptStatus(
                status=STATUS_FAILED,
                error=f"查询反推状态异常（code={code}）: {body.get('msg') or '未知原因'}",
                raw=body,
            )

        data = body.get("data") or {}
        if not isinstance(data, dict):
            return PromptStatus(status=STATUS_FAILED, error="查询反推状态响应缺少 data", raw=body)

        schedule = (data.get("schedule") or "").upper()
        if schedule == SCHEDULE_SUCCESS:
            content = data.get("content")
            if not content:
                return PromptStatus(
                    status=STATUS_FAILED,
                    error="任务已完成但未返回提示词内容",
                    schedule=schedule, raw=body,
                )
            return PromptStatus(status=STATUS_SUCCESS, content=str(content), schedule=schedule, raw=body)
        if schedule == SCHEDULE_FAIL:
            return PromptStatus(
                status=STATUS_FAILED,
                error=_fail_reason(data),
                schedule=schedule, raw=body,
            )
        # WAIT_HANDLE / PROCESSING / 未知 schedule：一律按处理中（不误判终态）
        return PromptStatus(status=STATUS_PROCESSING, schedule=schedule or None, raw=body)

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass
