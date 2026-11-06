"""企微自动化后台「创建 AI 视频」任务板的 HTTP 客户端（11-05 批 H 接线）。

这个模块是素材库**唯一允许出网连板**的地方，只做三件事：建任务、按天回读、下载成片。
业务判断（闸门、状态迁移、attempts、计数、审计）全在 `app/api/assets.py` 的投递口里，
这里不碰数据库、不碰状态机——板子是一条外部系统，把"我们到底知道它什么"集中写在一处，
将来它改接口时只需要动这一个文件。

口径来源（逐条对着权威件核过，**不是猜的**）：
  skill `relax-video-pipeline/scripts/av_dispatch_cards.py` + `monitor_and_fetch.py`
  ＋ NAS《每日解压视频-操作手册-20261022.md》。要点：

1. **两个前缀不一样**：建任务走 `/api-g/aivideo/create`，回读走 `/api/task/aivideo/info`。
   写成同一个会 404，而 404 会被误读成"这批一条都没投上"（11-04 实测过这条路的坑）。
2. **Authorization 是 `Basic base64("user:pass")`**：把 `user:pass` 原文塞进 header 会 401
   （10-25 实测）。凭据只从环境变量 `AIVIDEO_AUTH` 读，**任何日志与异常文本都不许带出它**。
3. payload **只有七个键**、键序 `tag/reqID/total/date/prompt/name/picDatas`：多一个键板侧不认，
   **没有时长与分辨率参数**，成片恒 10.08s / 720×1280。请求体按 `ensure_ascii=False` 发
   （与页面/权威脚本一致，中文原样发出、不做 Unicode 转义，排查时能直接对上板面看到的字）。
4. `date` 必须是**完整时间戳**：只写日期接口照样回 succ，但 `info?date=` 按任何日期都查不到，
   额度白烧、成片永久取不回（1021 那次 120 条）。生成口径见 `asset_service.board_timestamp`。
5. **回读要双日并集**（批次日＋板面今天）：跨午夜只查一天会把整批误判成"全失败"。
6. `status` 只有 `succ` / `fail` 算终态。`waiting` **不是失败**——11-04 把它当失败去重投，
   同一条烧了两遍号池。查不到／查得抖一下，都不许当成失败（见 `readback` 的容错口径）。
7. 成片下载是 `GET /data<outUrl>`：`outUrl` 是**相对路径**，直接当绝对地址用会连不上。
8. 号池是**单日上限、且与每日解压线共用**（1023 叠两份量 → 115/120 成批 fail）。解压线在
   我们的库里没有台账，所以 `assets.py` 算的当日余量**只含素材库自己投的**，天然偏乐观——
   这也是"只提示不硬拦"的另一条理由（用户 11-04 拍板：产能不限）。
"""
import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── 板面状态词（大小写按板接口原样，别自己发明）──
STATE_SUCC = "succ"
STATE_FAIL = "fail"
# 只有这两个算"结束了"。其它（waiting/running/空）一律算还在跑：判死＝重复烧号
TERMINAL_STATES: Tuple[str, ...] = (STATE_SUCC, STATE_FAIL)


class BoardError(RuntimeError):
    """板侧拒绝、连不上、或响应看不懂。

    `detail` 是给一线看的白话（会原样进 HTTPException 与任务台账），所以：
    只说"哪一步没成、接下来做什么"，**绝不带凭据、不带完整 URL 的 query**。
    """


def base_url() -> str:
    return str(settings.ASSET_BOARD_BASE_URL or "").strip().rstrip("/")


def is_configured() -> bool:
    """能不能自动投板：地址＋凭据齐了才算齐。

    故意**不再加一个 `ASSET_BOARD_DISPATCH_ENABLED` 之类的开关**——11-04 第二轮审核（D-3）
    刚清掉两个"改了没读者"的假旋钮。凭据在不在就是唯一事实：没填凭据，投板必然失败，
    多一个旋钮只会多一种"旋钮说能投、凭据说投不了"的矛盾状态。
    """
    return bool(base_url()) and bool(str(settings.AIVIDEO_AUTH or "").strip())


def _auth_header() -> str:
    cred = str(settings.AIVIDEO_AUTH or "").strip()
    if not cred:
        raise BoardError(
            "后台板凭据没配（环境变量 AIVIDEO_AUTH 为空）：自动投板没启用，"
            "这一批请用导出 payload 人工投板，投完走投递状态回写口记账"
        )
    # 板要的是 Basic base64(user:pass)。这里兼容"运维已经把 base64 填进 env"的写法：
    # 解得开且形如 user:pass 就直接用原文，解不开当作原文再编一次——两条路都不会
    # 把凭据回显到任何地方。
    try:
        decoded = base64.b64decode(cred + "=" * (-len(cred) % 4)).decode()
        if ":" in decoded and " " not in decoded:
            return "Basic " + base64.b64encode(decoded.encode()).decode()
    except Exception:  # noqa: BLE001 — 解不开就当原文，不是错误
        pass
    return "Basic " + base64.b64encode(cred.encode()).decode()


def _headers() -> Dict[str, str]:
    if not base_url():
        raise BoardError("后台板地址没配（ASSET_BOARD_BASE_URL 为空），连不上板")
    return {"Authorization": _auth_header(), "Content-Type": "application/json"}


def board_day(dt: Optional[datetime]) -> str:
    """板面日期串（YYYY-MM-DD）：`board_date` 已经是板面本地时间的 naive 值，直接取。"""
    return (dt or datetime.utcnow()).strftime("%Y-%m-%d")


def days_to_query(dates: Iterable[Optional[datetime]]) -> List[str]:
    """要并集查的日期：本批每张单的批次日 ＋ 板面今天。

    为什么不能只查批次日：号池排队时板子可能把活落到跨午夜之后；
    为什么不能只查今天：昨天投的那批今天来回读就会"查不到"→被误判失败。
    """
    today = datetime.utcnow() + timedelta(hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0))
    days = {board_day(today)}
    for d in dates:
        if d is not None:
            days.add(board_day(d))
    return sorted(days)


async def create_task(payload: Dict[str, Any]) -> str:
    """POST `/api-g/aivideo/create` 建一条板任务，成功返回响应文本片段。

    成功判据照权威脚本：HTTP 200 **且**响应体含 `succ`。只看 200 不够——板子会带着
    200 回一段错误说明。
    """
    url = f"{base_url()}/api-g/aivideo/create"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        async with httpx.AsyncClient(timeout=float(settings.ASSET_BOARD_CREATE_TIMEOUT)) as client:
            resp = await client.post(url, content=body, headers=_headers())
    except httpx.RequestError as e:
        # 只记异常类型：URL 里不带凭据，但为了避免任何意外泄漏，这里连 URL 都不写进 detail
        logger.error("板子建任务连接失败：%s", e)
        raise BoardError(f"连不上后台任务板（{type(e).__name__}），本条没投出去，稍后重试或改人工投板") from e
    text = (resp.text or "")[:300]
    if resp.status_code != 200 or STATE_SUCC not in text:
        logger.error("板子建任务失败 HTTP %s：%s", resp.status_code, text[:200])
        raise BoardError(f"后台板拒绝建任务（HTTP {resp.status_code}）：{text[:180]}")
    return text


async def list_tasks(day: str, tag: str) -> List[Dict[str, Any]]:
    """GET `/api/task/aivideo/info?date=<YYYY-MM-DD>T00:00:00&tag=<拥有者>` 的单日行。

    响应两种形状都收：`{"data": [...]}` 或裸数组（权威脚本 `rows.get("data", rows)` 同款）。
    少了 `tag` 会连别人的任务一起读回来，tid 对账就会串到不相关的单上，所以 tag 必传。
    """
    if not tag:
        raise BoardError("回读缺 tag：板上 tag＝拥有者标记，空 tag 查出来是全校所有人的任务，对不上账")
    # 参数交给 httpx 编码（tag 里出现中文或空格时，手拼字符串会拼出一个查不到任何东西的日期）
    params = {"date": f"{day}T00:00:00", "tag": tag}
    url = f"{base_url()}/api/task/aivideo/info"
    try:
        async with httpx.AsyncClient(timeout=float(settings.ASSET_BOARD_READ_TIMEOUT)) as client:
            resp = await client.get(url, params=params, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise BoardError(f"回读 {day} 的任务列表失败（HTTP {e.response.status_code}）") from e
    except (httpx.RequestError, ValueError) as e:
        raise BoardError(f"回读 {day} 的任务列表失败（{type(e).__name__}）") from e
    rows = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise BoardError(f"回读 {day} 的响应形状看不懂（不是列表），先去看板面而不是猜状态")
    return [r for r in rows if isinstance(r, dict)]


async def readback(days: Iterable[str], tag: str) -> Dict[str, Dict[str, Any]]:
    """多日并集回读，返回 `tid → 行`。

    容错口径（照 11-04 反推轮询那次修的「查询抖动＝判死」教训）：
    **某几天查不到就先用查到的这几天**，只有**所有**日期都失败才抛错。
    轮询方拿"暂时查不到"当成失败就会去重投，那就是同一条烧两遍号池。
    """
    wanted = sorted({str(d) for d in days if d})
    if not wanted:
        raise BoardError("回读没给日期，不知道该查哪一天")
    found: Dict[str, Dict[str, Any]] = {}
    last_error: Optional[BoardError] = None
    ok = 0
    for day in wanted:
        try:
            rows = await list_tasks(day, tag)
        except BoardError as e:
            last_error = e
            logger.warning("板子回读 %s 失败（先按其它日期继续）：%s", day, e)
            continue
        ok += 1
        for row in rows:
            tid = str(row.get("tid") or "").strip()
            if tid:
                found[tid] = row
    if ok == 0:
        raise last_error or BoardError("板子回读全部失败")
    return found


async def download_output(out_url: str) -> bytes:
    """GET `/data<outUrl>` 把成片拉回内存（调用方负责落桶，本模块不碰存储）。"""
    if not out_url:
        raise BoardError("板上这行没有 outUrl，成片还取不到")
    path = str(out_url) if str(out_url).startswith("/") else f"/{out_url}"
    url = f"{base_url()}/data{path}"
    try:
        async with httpx.AsyncClient(timeout=float(settings.ASSET_BOARD_DOWNLOAD_TIMEOUT)) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            raw = resp.content
    except httpx.HTTPStatusError as e:
        raise BoardError(f"成片下载失败（HTTP {e.response.status_code}），文件可能在板上已被清掉") from e
    except httpx.RequestError as e:
        raise BoardError(f"成片下载失败（{type(e).__name__}），稍后重试") from e
    # 空体／几十个字节的"错误页"都长这样。判小不判大：判大要猜规格，猜错会把好片子当失败。
    if not raw or len(raw) < 1024:
        raise BoardError(f"下载到的内容不像一支视频（{len(raw or b'')} 字节），这条按失败处理")
    return raw


def state_after_board(board_status: Optional[str]) -> str:
    """板面状态 → 我们台账的迁移目标（`queued`/`running`/`success`/`failed` 之一）。

    非终态（waiting 以及任何看不懂的词）**一律算 running**：在板子上还没结束的单，
    我们判它失败就会去重投，判它成功就会拿不到产物——只有 running 是无害的。
    """
    s = str(board_status or "").strip().lower()
    if s == STATE_SUCC:
        return "success"
    if s == STATE_FAIL:
        return "failed"
    return "running"


def is_terminal(board_status: Optional[str]) -> bool:
    return str(board_status or "").strip().lower() in TERMINAL_STATES
