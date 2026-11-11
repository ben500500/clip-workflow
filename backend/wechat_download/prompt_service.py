"""视频反推提示词业务编排（智令 doc/120 提交 + doc/119 轮询）。

职责边界：
- 只读写本包独立表 `wechat_dl_prompt_tasks`，不碰主系统表；
- 外部调用 fail-soft：提交被拒一律写库 `failed` + `error`，由 API 层返回任务本体
  （不抛 500），保证「一次外部抖动不产生 5xx」；**轮询链路抖动不判失败**，
  保持 processing 继续问，超过容忍时长才收口（见 refresh_prompt_task）。

竞态教训（沿用 create_import_task 的既有注释约定）：提交前先 commit 落行，
再调外部接口，避免持有事务跨网络 IO 导致连接池被长时间占用。

11-09 现网排查后加的两层（都是「钱」的口径，改动前先看这段）：
- 终态失败自动补投一次（`WECHAT_DL_PROMPT_AUTO_RETRY`）：上游 FAIL 的 errMsg 常见
  「视频理解服务返回空结果」，同一条链接换个时刻再投就成功——那是它读流抖动，不是
  链接坏了。补投**每条只一次**，名额用 `UPDATE ... WHERE retry_count = 0` 原子认领，
  认领事务先提交再跨网络 IO，所以并发轮询／多次刷新都不会双扣。
- 补投前先按 doc/107 把分享链接解析成直链（`WECHAT_DL_PROMPT_RETRY_VIA_DIRECT`）：
  反推只吃「上游能直接拉流的地址」，花约 0.01 元换掉一次 0.16 元的空跑。
"""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import User, user_can_access_all_materials
from wechat_download.models import (
    PST_UPLOAD,
    PST_URL,
    PT_FAILED,
    PT_PROCESSING,
    PT_SUCCESS,
    WechatDlPromptTask,
)
from wechat_download.prompt_client import FAIL_DEFAULT_REASON, PromptClient, PromptError
from wechat_download.services_client import ZhilingServiceClient
from wechat_download.services_service import is_direct_video_url
from wechat_download.upload_client import UploadClient, UploadError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 失败原因 → 人话处置建议
# ─────────────────────────────────────────────────────────────

# 上游 errMsg 原文是给机器看的（「视频理解服务返回空结果」），一线要知道的是「下一步干什么、
# 要不要再花钱」。error 存原文，本表只出建议，两边都不丢信息。
RETRYABLE_FAILURE_MARKERS = (
    "空结果", "返回空", "超时", "timeout", "timed out", "繁忙", "稍后",
    "try again", "unavailable", "无法下载", "下载失败", "读取失败",
)
# 明确不该自动补投的原因（先判黑名单，命中就不花钱）：钱不够／配置缺失／链接本身非法
NON_RETRYABLE_FAILURE_MARKERS = (
    "额度", "余额", "点数", "未配置", "为空", "不支持", "无效", "无权限", "权限", "欠费",
)


def _norm_err(error: Optional[str]) -> str:
    return (error or "").strip().lower()


# 失败时附带的原始响应长度上限：够看清 code/msg/errMsg 三件套，又不至于把 error 列灌满
_RAW_BRIEF_LIMIT = 220
# 原始响应里绝不能跟着报错入库的字段名（子串匹配，防上游把密钥回显）
_SENSITIVE_KEYS = ("key", "token", "secret", "password", "authorization", "cookie")


def _raw_brief(raw) -> str:
    """把一次轮询的原始响应压成一行可入库文本（先脱敏，再截断）。

    11-09 现网三条死链的 FAIL 响应里 `errMsg` 是空的，库里就只剩「任务处理失败」一句
    废话：既命中不了 RETRYABLE／NON_RETRYABLE 任何一套标记（不知道该不该补投），一线
    也看不出所以然。把原文截一段附上，至少这条错误事后可查。
    """
    if raw is None:
        return ""
    data = raw
    if isinstance(data, dict):
        data = {
            k: ("***" if any(s in str(k).lower() for s in _SENSITIVE_KEYS) else v)
            for k, v in data.items()
        }
    try:
        text = json.dumps(data, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        text = str(data)
    return text[:_RAW_BRIEF_LIMIT]


def _failed_reason_text(st) -> str:
    """终态失败时该落库的原因文本：上游给了人话就用原文，没给就把原始响应补上。

    认 `FAIL_DEFAULT_REASON` 而不是判空：`_fail_reason` 在什么键都没捞到时返回的就是这句
    兜底文案，它既不含信息也命中不了任何处置标记，等于「原因丢了」。
    """
    reason = (st.error or "").strip()
    if reason and reason != FAIL_DEFAULT_REASON:
        return reason
    brief = _raw_brief(getattr(st, "raw", None))
    base = reason or FAIL_DEFAULT_REASON
    return f"{base}（上游未给原因，原始响应：{brief}）" if brief else base


# 「自动补投未成功（X）；原始失败：Y」这种我们自己拼出来的句子，X 才是当下要看的原因
_AUTO_RETRY_INNER = re.compile(r"^自动补投未成功（(?P<inner>[^）]*)）")


def _is_retryable_failure(error: Optional[str]) -> bool:
    """这条失败值不值得系统自己再投一次（会再扣一次钱，所以默认保守）。"""
    text = _norm_err(error)
    if not text:
        return False
    if any(marker in text for marker in NON_RETRYABLE_FAILURE_MARKERS):
        return False
    return any(marker in text for marker in RETRYABLE_FAILURE_MARKERS)


def explain_prompt_error(error: Optional[str], retry_count: int = 0) -> Optional[str]:
    """把上游失败原文翻成「现在该怎么办」，供界面直接展示（原文仍留在 error 里）。

    retry_count 参与判断：同样一句「返回空结果」，第一次失败时该说「系统会补投一次」，
    补投过之后再说同样的话就是骗人——那时唯一出路是人工重投或换链接。
    """
    text = _norm_err(error)
    if not text:
        return None
    retried = int(retry_count or 0) > 0
    if text.startswith("自动补投未成功"):
        inner = _AUTO_RETRY_INNER.search(error or "")
        return (
            "系统已经自己补投过一次，这一次连投出去都没成"
            + (f"（{inner.group('inner')}）" if inner else "")
            + "；再投就是人工决定的事了——点列表里的「重试」，或换一条能在浏览器直接播的链接。"
        )
    if "空结果" in text or "返回空" in text:
        if retried:
            return (
                "上游还是没读到视频内容，而系统已经为这条链接自动补投过一次（只补一次，不再自己烧钱）。"
                "现在人工点「重试」或换一条能直接播的链接。"
            )
        return (
            "上游这一次没读到视频内容，多数是它拉流的瞬时抖动——系统会自动补投一次，稍等即可；"
            "列表里出现「已补投」就说明补投在跑了。"
        )
    if any(marker in text for marker in ("额度", "余额", "点数", "欠费")):
        return "智令账号额度不够，这一条做不了也省不下钱；先充值或换账号再重投，多点几次只是白等。"
    if "未配置" in text or "wechat_dl_zhiling_key" in text:
        return "服务端没配好智令密钥（WECHAT_DL_ZHILING_KEY），这条没扣费；找管理员补配后重新发起。"
    if any(marker in text for marker in ("无效", "不支持", "无法下载", "下载失败")):
        return (
            "这条链接上游取不到视频（可能已失效、需要登录、或本来不是视频页）。"
            + ("系统已试过换成解析出的直链，仍然不行——换一条能直接播的链接吧。" if retried
               else "系统会自动换成解析出的直链再试一次；还不行就换一条能在浏览器里直接播的链接。")
        )
    if any(marker in text for marker in ("超时", "timeout", "timed out", "繁忙", "稍后", "unavailable")):
        return "上游处理超时／正忙，重投一次通常就能出。"
    if "查询" in text and "不通" in text:
        return (
            "是上游查询链路一直不通，任务本身很可能已经做完了。别急着重投——重投会再扣一次钱，"
            "先隔几分钟刷新看看，确实没有再重投。"
        )
    if "没有拿到上游任务号" in text:
        return "提交那一步没走完（这条没扣费），在列表里点「重试」或重新发起一次就行。"
    return "重投一次试试；连着两次都失败，基本就是这条视频本身的问题，换链接或人工看片写提示词。"


def _retry_count_of(task: WechatDlPromptTask) -> int:
    """读补投次数；读不出整数一律按「已经补投过」处理——判不准时宁可少花一次钱。"""
    try:
        return int(getattr(task, "retry_count", 0) or 0)
    except (TypeError, ValueError):
        return 1


def _retry_count_for_api(task: WechatDlPromptTask) -> int:
    """给界面的补投次数：非整数（老替身/脏数据）显示 0，不在前端玩魔术。"""
    value = getattr(task, "retry_count", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def serialize_prompt_task(t: WechatDlPromptTask) -> dict:
    retry_count = _retry_count_for_api(t)
    return {
        "id": str(t.id),
        "created_by": str(t.created_by) if t.created_by else None,
        "source_type": t.source_type or PST_URL,
        "source_url": t.source_url,
        "file_name": t.file_name,
        "provider_task_id": t.provider_task_id,
        "status": t.status,
        "content": t.content,
        "error": t.error,
        # error 是上游原文（errMsg），error_hint 是给一线看的处置建议，两个都给，别二选一
        # 建议要按「补投过没有」说不同的话，所以把 retry_count 一起传给 explain
        "error_hint": explain_prompt_error(t.error, retry_count),
        # 1=系统已经自己补投过一次（前端据此打「已自动补投」徽标，避免误以为没动过）
        "retry_count": retry_count,
        "max_duration": t.max_duration,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def can_access_prompt_task(task: WechatDlPromptTask, current_user: Optional[User]) -> bool:
    """可见口径与 wechat-dl 下载任务列表保持一致。

    - scope=all（admin/material/publisher）：可见全部
    - operator：仅见自己发起的；**发起人为空（历史/系统任务）视为公共**，
      与 ISSUE #361 任务 C「无主即公共」的口径一致。
    """
    if current_user is None:
        return False
    if user_can_access_all_materials(current_user):
        return True
    if task.created_by is None:
        return True
    return task.created_by == current_user.id


async def prompt_task_scope_stmt(current_user: Optional[User], limit: int = 50):
    """按可见口径构造列表查询（供 API 复用，避免口径漂移）。"""
    stmt = select(WechatDlPromptTask).order_by(WechatDlPromptTask.created_at.desc()).limit(limit)
    if current_user is not None and not user_can_access_all_materials(current_user):
        stmt = stmt.where(
            WechatDlPromptTask.created_by.is_(None)
            | (WechatDlPromptTask.created_by == current_user.id)
        )
    return stmt


async def create_prompt_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    source_url: str,
    max_duration: Optional[int] = None,
    source_type: str = PST_URL,
    file_name: Optional[str] = None,
) -> WechatDlPromptTask:
    """建行 + 提交智令。返回落库后的任务（失败时 status=failed，带 error）。

    source_type=upload 时 source_url 是 doc/125 上传后拿到的 fileUrl，
    file_name 保留用户原始文件名（仅作展示/追溯）。
    """
    task = WechatDlPromptTask(
        created_by=created_by,
        source_url=(source_url or "").strip()[:1000],
        source_type=source_type or PST_URL,
        file_name=(file_name or None) and str(file_name)[:255],
        max_duration=max_duration,
        status=PT_PROCESSING,
    )
    db.add(task)
    # 先提交：外部请求可能耗时数秒，且失败时要保证用户能在列表里看到这条失败的记录
    await db.commit()
    await db.refresh(task)

    client = PromptClient()
    try:
        provider_task_id = await client.submit(task.source_url, max_duration)
    except PromptError as e:
        task.status = PT_FAILED
        task.error = str(e)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("反推提示词任务提交失败 task=%s: %s", task.id, e)
        return task
    finally:
        await client.close()

    task.provider_task_id = provider_task_id
    task.status = PT_PROCESSING
    task.error = None
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    return task


async def get_prompt_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[WechatDlPromptTask]:
    result = await db.execute(select(WechatDlPromptTask).where(WechatDlPromptTask.id == task_id))
    return result.scalar_one_or_none()


def _poll_giveup_seconds() -> int:
    """轮询不通的容忍时长（秒），每次现读 settings 便于测试/运维改 env 即时生效。"""
    return max(60, int(settings.WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS or 3600))


def _poll_giveup_exceeded(task: WechatDlPromptTask, now: Optional[datetime] = None) -> bool:
    """任务从**提交**起算是否已超过容忍时长。

    基准只能用 created_at 不能用 updated_at：抖动那一轮也会刷 updated_at，
    按 updated_at 算的话「一直在问、一直问不通」会永远不满阈值。
    """
    ref = task.created_at
    if ref is None:
        return False
    if ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    return ((now or datetime.utcnow()) - ref).total_seconds() > _poll_giveup_seconds()


async def _claim_retry_slot(db: AsyncSession, task: WechatDlPromptTask) -> bool:
    """原子认领「本条只自动补投一次」的名额。

    为什么不能用「先读 retry_count 再写」：轮询是前端 4s 一次、可能多标签页同时刷，
    读-改-写中间谁都能插进来，两次都读到 0 就会投两次、同一链接多扣一次钱。
    UPDATE 的 WHERE 由数据库串行执行，rowcount 才是「我抢到了」的唯一凭据。
    """
    res = await db.execute(
        update(WechatDlPromptTask)
        .where(
            WechatDlPromptTask.id == task.id,
            WechatDlPromptTask.retry_count == 0,
        )
        .values(retry_count=1, updated_at=datetime.utcnow())
    )
    try:
        claimed = int(getattr(res, "rowcount", 0) or 0) > 0
    except (TypeError, ValueError):
        # 拿不到确切的行数（驱动返回形状不对／替身没配好）就当作没抢到：判不准时不花钱
        claimed = False
    if claimed:
        task.retry_count = 1
    return claimed


async def _resolve_retry_url(task: WechatDlPromptTask) -> Optional[str]:
    """补投前把分享链接换成 doc/107 解析出的直链（约 0.01 元）；拿不到就返回 None 用原链接。

    反推只吃「上游能直接拉流的地址」。现网失败的基本都是分享链接——上游要自己解析再拉流，
    失败率明显高。花一分钱换掉一次 0.16 元的空跑是划算的。
    两种情况不解析：上传件（source_url 本来就是智令 temp 桶直链）、以及已经是直链的输入。
    """
    if not bool(getattr(settings, "WECHAT_DL_PROMPT_RETRY_VIA_DIRECT", True)):
        return None
    url = (task.source_url or "").strip()
    if not url or (task.source_type or PST_URL) == PST_UPLOAD or is_direct_video_url(url):
        return None
    svc = ZhilingServiceClient()
    try:
        direct = await svc.resolve_direct_url(url)
    except Exception as e:  # noqa: BLE001 - 解析不通不代表不能补投，退回原链接继续
        logger.warning("反推补投直链解析失败 task=%s（退回原链接）: %s", task.id, e)
        return None
    finally:
        await svc.close()
    return (direct or "").strip() or None


async def _auto_retry_prompt_task(db: AsyncSession, task: WechatDlPromptTask, reason: Optional[str]) -> bool:
    """可重试的终态失败 → 系统自己补投一次。返回是否真的补投了。

    闸门口径照素材库 `_converge_analyze` 的「快速失败自动重试一次」：一次为限、
    原子认领、只补可重试的原因、开关可关（`WECHAT_DL_PROMPT_AUTO_RETRY=false`）。
    补投仍失败就停在 failed，error 里留的是上游原文，界面另给一句该怎么办的建议。
    """
    if not bool(getattr(settings, "WECHAT_DL_PROMPT_AUTO_RETRY", True)):
        return False
    if _retry_count_of(task) != 0 or not _is_retryable_failure(reason):
        return False
    if not await _claim_retry_slot(db, task):
        return False
    # 名额先落库再跨网络 IO：中途进程被切，这条也已经是「补投过」的状态，
    # 重启后不会再来一次——宁可少投一次，也不双扣。
    await db.commit()

    url = await _resolve_retry_url(task) or task.source_url
    client = PromptClient()
    try:
        provider_task_id = await client.submit(url, task.max_duration)
    except PromptError as e:
        task.status = PT_FAILED
        task.error = f"自动补投未成功（{str(e)[:200]}）；原始失败：{reason or '未知原因'}"[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        logger.warning("反推任务 %s 自动补投提交失败：%s", task.id, e)
        return True
    finally:
        await client.close()

    task.provider_task_id = provider_task_id
    task.status = PT_PROCESSING
    # error 不清空：留着说清「上一次为什么失败」，这轮成功后 SUCCESS 分支自然会清掉
    task.error = f"上次失败：{reason or '未知原因'}；系统已自动补投一次，正在处理中"[:500]
    task.content = None
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    logger.warning(
        "反推任务 %s 终态失败「%s」→ 已自动补投一次（provider_task_id=%s，直链=%s）",
        task.id, reason, provider_task_id, "是" if url != task.source_url else "否",
    )
    return True


async def refresh_prompt_task(db: AsyncSession, task: WechatDlPromptTask) -> WechatDlPromptTask:
    """仍在 processing 时向智令查询一次并按 schedule 更新状态/内容。

    只在 `processing` 且已有 provider_task_id 时才发起外部查询，终态任务不重复扣费/请求。

    「查询不通」的处理口径（11-03 在 163 现网实测后改的）：智令网关自己转发超时
    （code=500 转发请求失败）时**保持 processing** 继续轮，不当终态失败——旧写法会
    把已扣费的反推判死，一线只能 retry_failed 重跑、同一条再扣一次钱。为避免永远
    挂在处理中，连续不通满 `WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS`（默认 1 小时）
    才收口判 failed，并把最后一次不通的原因写进 error。

    没有 provider_task_id 的 processing 行是僵尸行（建行后提交那一步没跑完，比如进程
    被切），旧写法直接 return 让它永远「生成中」骗人刷新；现在同样按容忍时长收口，
    并在 error 里说清这条没扣费、重投不花钱。
    """
    if task.status != PT_PROCESSING:
        return task

    if not task.provider_task_id:
        if not _poll_giveup_exceeded(task):
            return task
        giveup_min = int(_poll_giveup_seconds() // 60)
        task.status = PT_FAILED
        task.error = (
            f"任务提交后 {giveup_min} 分钟以上没有拿到上游任务号，已判失败"
            "（这一步没有扣费，重新发起一次即可，不用带 retry_failed）"
        )[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        logger.warning("反推任务 %s 僵尸 processing 行收口 failed：%s", task.id, task.error)
        return task

    client = PromptClient()
    try:
        st = await client.query(task.provider_task_id)
    finally:
        await client.close()

    if st.status == PT_SUCCESS:
        task.status = PT_SUCCESS
        task.content = st.content
        task.error = None
    elif st.status == PT_FAILED:
        task.status = PT_FAILED
        # 上游给了人话就用原文；只拿到兜底文案时把原始响应截一段附上（11-10），
        # 否则库里那句「任务处理失败」既看不出所以然、也命中不了下面的处置标记
        reason_text = _failed_reason_text(st)[:500]
        task.error = reason_text
    elif st.transient and _poll_giveup_exceeded(task):
        # 抖动持续超过容忍时长：收口，别让它无限「处理中」骗一线一直点刷新
        giveup_min = int(_poll_giveup_seconds() // 60)
        task.status = PT_FAILED
        task.error = (
            f"反推查询连续 {giveup_min} 分钟以上不通，已判失败（最后一次：{st.error}）；"
            "任务本身可能已完成，先刷新看看，重跑会再扣一次钱"
        )[:500]
        logger.warning("反推任务 %s 轮询超时收口 failed：%s", task.id, task.error)
    else:
        # 处理中（含链路抖动）：仅刷新 updated_at，保持轮询可继续
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        return task

    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)

    # 终态失败才考虑补投：此时 failed 已经落库，补投成功会把它改回 processing，
    # 补投失败则停在 failed（error 里同时留下两次原因），不会出现「既没成功也没记录」。
    # 判断依据用刚落库的 task.error：上游只回兜底文案时它带著原始响应，标记才有机会命中
    if st.status == PT_FAILED:
        await _auto_retry_prompt_task(db, task, task.error)
    return task


# ─────────────────────────────────────────────────────────────
# 全表僵尸收口（11-10）
# ─────────────────────────────────────────────────────────────

async def sweep_zombie_prompt_tasks(db: AsyncSession) -> int:
    """把「永远开跑不了」的僵尸 processing 行收成 failed，返回收口条数。

    判据跟 `refresh_prompt_task` 里那条**一模一样**：`processing` ＋ 没有
    `provider_task_id` ＋ 自提交起超过容忍时长（`WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS`）。
    这里补的从来不是判据，是**触发**：那个函数全仓只有 4 个「按单条刷」的入口会调
    （wechat-dl 详情口 ＋ assets.py 三处按素材刷新），没有全表扫；而 upload 型又没有
    别的入口会去刷它（一键重试口对 upload 直接 400），于是现网攒出 6 条永远「生成中」
    的行，最后只能人工进库里判（见 docs 8-11/8-12）。

    0 元：没有上游任务号的行本来就查无可查，这条 UPDATE 不发任何外部请求。

    **有意只管无 pid 的行**。有 pid 的 processing 留给原轮询口——全表口要是去刷它们，
    就会连带走 `_auto_retry_prompt_task`，等于在进程启动／别人打开列表时无人值守地
    偷偷补投花钱。这个口子不开。
    """
    giveup_seconds = _poll_giveup_seconds()
    cutoff = datetime.utcnow() - timedelta(seconds=giveup_seconds)
    giveup_min = int(giveup_seconds // 60)
    res = await db.execute(
        update(WechatDlPromptTask)
        .where(
            WechatDlPromptTask.status == PT_PROCESSING,
            WechatDlPromptTask.provider_task_id.is_(None),
            WechatDlPromptTask.created_at < cutoff,
        )
        .values(
            status=PT_FAILED,
            error=(
                f"任务提交后 {giveup_min} 分钟以上没有拿到上游任务号，已判失败"
                "（这一步没有扣费，重新发起一次即可，不用带 retry_failed）"
            )[:500],
            updated_at=datetime.utcnow(),
        )
    )
    changed = int(getattr(res, "rowcount", 0) or 0)
    if changed:
        await db.commit()
        logger.warning(
            "反推僵尸 processing 行全表收口 %s 条（无上游任务号且超 %s 分钟，0 元）",
            changed, giveup_min,
        )
    return changed


# 允许上传的视频扩展名（前端 accept 与后端校验共用一份，避免两边漂移）
UPLOAD_ALLOWED_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v")

# 扩展名 → content type：doc/125 签名要按 contentType 签，S3 侧写入同值
EXT_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


def upload_max_bytes() -> int:
    """上传大小上限（字节）。每次现读 settings，便于测试/运维改 env 后即时生效。"""
    return int(settings.WECHAT_DL_PROMPT_UPLOAD_MAX_MB) * 1024 * 1024


def validate_upload_ext(file_name: Optional[str]) -> Optional[str]:
    """校验扩展名白名单。返回错误原因（None 表示通过）。

    与大小分开两个函数：API 层要在**落盘之前**先拒非法扩展名，
    此时还不知道真实大小，硬塞一个假 size 进来只会让校验语义变浑浊。
    """
    name = (file_name or "").strip()
    if not name:
        return "缺少文件名"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in UPLOAD_ALLOWED_EXTS:
        return f"不支持的文件类型 {ext or '(无扩展名)'}，仅支持 {' '.join(UPLOAD_ALLOWED_EXTS)}"
    return None


def validate_upload_size(size_bytes: int) -> Optional[str]:
    """校验文件大小。返回错误原因（None 表示通过）。超限由 API 层转 413。"""
    if size_bytes <= 0:
        return "上传文件为空"
    limit = upload_max_bytes()
    if size_bytes > limit:
        return f"文件过大（{size_bytes / 1024 / 1024:.1f}MB），上限 {limit // 1024 // 1024}MB"
    return None


def validate_upload_file(file_name: Optional[str], size_bytes: int) -> Optional[str]:
    """扩展名 + 大小一起校验（组合便捷入口），返回错误原因或 None。"""
    return validate_upload_ext(file_name) or validate_upload_size(size_bytes)


def content_type_for(file_name: Optional[str]) -> str:
    name = (file_name or "").lower()
    ext = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""
    return EXT_CONTENT_TYPES.get(ext, "video/mp4")


async def create_upload_prompt_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    file_obj,
    file_name: str,
    size_bytes: int,
    max_duration: Optional[int] = None,
) -> WechatDlPromptTask:
    """本地视频上传 → 反推：建行（先 commit）→ doc/125 签名 → S3 POST → doc/120 提交。

    与 create_prompt_task 同样 fail-soft：签名/S3 失败只把任务写 failed + error，
    绝不向上抛（API 层仍返回 201 任务本体），保证一次外部抖动不产生 5xx。
    文件对象由调用方（API 层）负责生命周期：这里只读不关，临时文件在 API 层 finally 删。
    """
    task = WechatDlPromptTask(
        created_by=created_by,
        # doc/125 上传完成前还不知道 fileUrl，先占位，成功后回填
        source_url="",
        source_type=PST_UPLOAD,
        file_name=(file_name or "")[:255] or None,
        max_duration=max_duration,
        status=PT_PROCESSING,
    )
    db.add(task)
    # 先提交：上传大文件可能耗时数分钟，必须先让用户在列表里看到这条在跑的任务
    await db.commit()
    await db.refresh(task)

    ctype = content_type_for(file_name)
    up = UploadClient()
    try:
        ticket = await up.sign(file_name=file_name, content_type=ctype)
        await up.post_file(
            ticket, file_obj, file_name=file_name, size_bytes=size_bytes, content_type=ctype,
        )
    except UploadError as e:
        task.status = PT_FAILED
        task.error = str(e)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("反推提示词上传失败 task=%s: %s", task.id, e)
        return task
    finally:
        await up.close()

    task.source_url = (ticket.file_url or "")[:1000]
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)

    # 拿到 fileUrl 后走既有提交链路（doc/120），复用同一套 fail-soft 与计费口径
    client = PromptClient()
    try:
        provider_task_id = await client.submit(task.source_url, max_duration)
    except PromptError as e:
        task.status = PT_FAILED
        task.error = str(e)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("反推提示词任务提交失败 task=%s: %s", task.id, e)
        return task
    finally:
        await client.close()

    task.provider_task_id = provider_task_id
    task.status = PT_PROCESSING
    task.error = None
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    return task
