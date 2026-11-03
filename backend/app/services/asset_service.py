"""素材库纯逻辑层：链接归一化去重、成本预估与熔断、阶段派生、审核状态机、
高风险词扫描、文案一致性校验。

设计原则：
- 这一层**不碰数据库、不碰网络**（除本模块外的 DB 操作留在 api 层），全部是
  可单测的纯函数——批量导入最容易出事的正是这些判定口径。
- `normalize_source_url` 只用于**去重命中提示**，绝不用于实际取视频：真正提交给
  智令的永远是 `asset_items.source_url` 原始链接。归一化宁可"漏合"（同一素材两个
  写法没认出来）也不能"误合"（把两条不同素材认成一条，会静默丢素材）。
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# ─────────────────────────  智令单价（元）  ─────────────────────────
# 单价的**真源**是 `wechat_download/prompt_client.py` 头注（doc/120=0.00054 元/秒）与
# 前端 `ResourceDownload.tsx` 的计费速查表；仓库里**没有** docs/资源下载模块使用手册.md
# （D-5：注释原引该路径属误记）。改价要同步这里与上述两处。
PRICE_PROMPT_PER_SECOND = 0.00054   # doc/120 反推提示词，按**计时上限**计费
PRICE_PARSE_PER_CALL = 0.01         # doc/107 视频解析
PRICE_COPY_EXTRACT_PER_CALL = 0.1   # doc/102 文案提取
PRICE_UPLOAD_PER_CALL = 0.001       # doc/125 本地上传（6 小时自删，只做中转）
PRICE_AI_ERASER_PER_SECOND = 0.005  # doc/114 AI 消除
PRICE_HD_RESTORE_PER_MINUTE = 0.3   # doc/123 画质修复

# 反推计时上限档位（与前端下拉、智令 doc/120 一致）
PROMPT_MAX_DURATION_TIERS = (60, 180, 300, 600)
# 默认档位：**不允许默认 600**（100 条误选 600 档一次烧 32.4 元，采集席位硬性反对过）
DEFAULT_PROMPT_MAX_DURATION = 180

# 豆包产能口径（2026-10-27 实测，见 short-drama-hook-writer SKILL.md:44）：
# 单号 2~4 条/日，排产按每号约 3 条规划。瓶颈是**额度不是工时**。
DOUBAO_PER_ACCOUNT_PER_DAY = 3


# ─────────────────────────  链接归一化（跨批次去重键）  ─────────────────────────

# 明确只影响分享来源/埋点的参数前缀与精确键：命中即从去重键里剔除。
_NOISE_PARAM_PREFIXES = (
    "utm_", "share_", "traffic_", "track_", "msclkid", "spm", "scm",
    "from_", "refer", "callback", "req_id", "reason", "app_", "discovery_",
)
_NOISE_PARAM_KEYS = {
    "from", "source", "scene", "scenario", "timestamp", "verifyfp", "fp",
    "tt_b", "tt_channel", "ch", "channel_id", "is_copy_url", "is_short_video",
    "secuid", "s", "k", "u", "v", "cid", "mid", "relation_id", "enter_method",
    "cover_ratio", "status", "share_url", "wechat_share_id", "xsec_token",
    "xsec_source", "xhsshare", "appuid", "app_token", "sversion", "platform_id",
    "note_copyright", "page_ver", "share_id", "share_from", "app", "openapp",
}
# 承载"身份"的参数键：这类键**必须保留**（有些平台视频 ID 在 query 里）。
_IDENTITY_PARAM_KEYS = {
    "id", "vid", "video_id", "itemid", "item_id", "note_id", "objective_id",
    "photo_id", "aweme_id", "moment_id", "mid_id", "bv", "aid",
}

# (host 正则, path 正则, 规范前缀) —— 命中即收敛成 "平台:ID" 形式，跨写法去重最稳。
_ID_PATTERNS: Tuple[Tuple[str, str, str], ...] = (
    (r"(?:^|\.)douyin\.com$", r"^/(?:video|note)/(\d+)", "douyin"),
    (r"(?:^|\.)iesdouyin\.com$", r"^/share/video/(\d+)", "douyin"),
    (r"(?:^|\.)kuaishou\.com$", r"^/short-video/([\w-]+)", "kuaishou"),
    (r"(?:^|\.)kuaishou\.com$", r"^/f/([\w-]+)", "kuaishou"),
    (r"(?:^|\.)xiaohongshu\.com$", r"^/(?:discovery/item|explore)/([0-9a-f]+)", "xiaohongshu"),
    (r"(?:^|\.)weixin\.qq\.com$", r"^/sph/([\w-]+)", "channels"),
    (r"(?:^|\.)bilibili\.com$", r"^/video/(bv[\w]+|av\d+)", "bilibili"),
    (r"(?:^|\.)weibo\.cn$", r"^/status/(\d+)", "weibo"),
    (r"(?:^|\.)bilibili\.com$", r"^/opus/(\d+)", "bilibili-opus"),
    (r"(?:^|\.)ixigua\.com$", r"^/(\d+)", "ixigua"),
    (r"(?:^|\.)toutiao\.com$", r"^/(?:video|a)/(\d+)", "toutiao"),
    (r"(?:^|\.)haokan\.baidu\.com$", r"^/v/\?vid=(\d+)", "haokan"),
    (r"(?:^|\.)video\.qq\.com$", r"^/cover/([\w-]+)", "qqvideo"),
    (r"(?:^|\.)youtube\.com$", r"^/shorts/([\w-]+)", "youtube"),
)

# host → 平台标签（仅用于列表展示与筛选，不参与去重）
_PLATFORM_BY_HOST: Tuple[Tuple[str, str], ...] = (
    ("douyin", "抖音"), ("iesdouyin", "抖音"),
    ("kuaishou", "快手"),
    ("xiaohongshu", "小红书"), ("xhslink", "小红书"),
    ("weixin", "微信视频号"), ("channels.", "微信视频号"),
    ("bilibili", "B站"), ("b23.tv", "B站"),
    ("weibo", "微博"),
    ("ixigua", "西瓜视频"),
    ("toutiao", "头条"),
    ("haokan", "好看视频"),
    ("video.qq", "腾讯视频"),
    ("jimeng", "即梦"), ("doubao", "豆包"),
    ("youtube", "YouTube"),
)

_SHORT_LINK_HOSTS = {
    "v.douyin.com", "v.kuaishou.com", "xhslink.com", "b23.tv",
    "weixin.qq.com", "url.cn", "t.cn", "s.id",
}


def normalize_source_url(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """把分享链接归一化成去重键，并识别平台标签。

    返回 (norm, platform)。norm 为 None 表示无法解析（原样不比对，交由调用方放行）。

    收敛顺序：scheme 统一 https → host 小写去 www → 路径正则命中则收成 "平台:ID"
    → 未命中则 host+path（去尾斜杠）+ 仅保留身份类 query 键（键值排序）。
    """
    url = (raw or "").strip()
    if not url:
        return None, None
    # 分享文案里常夹中文说明，取第一个 http(s) token
    m = re.search(r"https?://\S+", url)
    if m:
        url = m.group(0)
    if not url.lower().startswith(("http://", "https://")):
        return None, None

    try:
        parts = urlsplit(url)
    except ValueError:
        return None, None
    host = (parts.hostname or "").lower()
    if not host:
        return None, None
    host = host[4:] if host.startswith("www.") else host
    path = re.sub(r"/{2,}", "/", (parts.path or "")).rstrip("/") or "/"

    platform = guess_platform(host)

    for host_pat, path_pat, prefix in _ID_PATTERNS:
        if re.search(host_pat, host) and re.match(path_pat, parts.path or ""):
            mm = re.match(path_pat, parts.path or "")
            if mm:
                vid = mm.group(1)
                # BV 号大小写敏感，其余 ID 统一小写
                vid = vid if prefix == "bilibili" and vid.startswith("BV") else vid.lower()
                return f"{prefix}:{vid}", platform

    # 兜底：保留身份类 query 参数（其它一律视为埋点噪声）
    keep: List[Tuple[str, str]] = []
    for key, value in _iter_query(parts.query):
        if key.lower() in _IDENTITY_PARAM_KEYS and value:
            keep.append((key.lower(), value))
    keep.sort()
    query = "&".join(f"{k}={v}" for k, v in keep)
    # 短链（v.douyin.com/xxxx/ 这类）path 即身份，必须留在去重键里
    return urlunsplit(("https", host, path, query, "")), platform


def _iter_query(query: str) -> Iterable[Tuple[str, str]]:
    if not query:
        return
    for chunk in query.split("&"):
        if not chunk:
            continue
        k, _, v = chunk.partition("=")
        yield k, v


def guess_platform(host: str) -> Optional[str]:
    for needle, label in _PLATFORM_BY_HOST:
        if needle in host:
            return label
    return None


def is_noise_param(key: str) -> bool:
    """判断某 query 参数是否属于可丢弃的分享埋点（供前端提示/后续扩展用）。"""
    k = (key or "").lower()
    return k in _NOISE_PARAM_KEYS or any(k.startswith(p) for p in _NOISE_PARAM_PREFIXES)


def looks_like_direct_url(raw: Optional[str]) -> bool:
    """是否视频直链（AI 消除/画质修复吃直链最省，分享链接要多花 0.01 元解析）。"""
    url = (raw or "").strip().lower()
    if not url:
        return False
    path = urlsplit(url).path.lower()
    return path.endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".flv", ".ts"))


# ─────────────────────────  成本预估与熔断  ─────────────────────────

def estimate_unit_cost(
    max_duration: int = DEFAULT_PROMPT_MAX_DURATION,
    need_parse: bool = False,
    need_copy_extract: bool = False,
    need_upload: bool = False,
) -> float:
    """单条素材入库成本（元）。

    反推按 **计时上限** 而非实际时长扣费——这是整条链路最大的成本杠杆。
    """
    cost = PRICE_PROMPT_PER_SECOND * max(0, int(max_duration or 0))
    if need_parse:
        cost += PRICE_PARSE_PER_CALL
    if need_copy_extract:
        cost += PRICE_COPY_EXTRACT_PER_CALL
    if need_upload:
        cost += PRICE_UPLOAD_PER_CALL
    return round(cost, 4)


def estimate_batch_cost(
    count: int,
    max_duration: int = DEFAULT_PROMPT_MAX_DURATION,
    need_parse: bool = False,
    need_copy_extract: bool = False,
    need_upload: bool = False,
) -> Dict[str, Any]:
    """整批预估（含逐档明细），供导入确认单展示"预估费 + 当前余额"。"""
    unit = estimate_unit_cost(max_duration, need_parse, need_copy_extract, need_upload)
    total = round(unit * max(0, int(count)), 4)
    return {
        "count": int(count),
        "prompt_max_duration": int(max_duration),
        "unit_cost": unit,
        "total_cost": total,
        "breakdown": {
            "prompt": round(PRICE_PROMPT_PER_SECOND * max_duration * count, 4),
            "parse": round(PRICE_PARSE_PER_CALL * count, 4) if need_parse else 0.0,
            "copy_extract": round(PRICE_COPY_EXTRACT_PER_CALL * count, 4) if need_copy_extract else 0.0,
            "upload": round(PRICE_UPLOAD_PER_CALL * count, 4) if need_upload else 0.0,
        },
        "tiers": {
            str(t): round(estimate_unit_cost(t, need_parse, need_copy_extract, need_upload) * count, 4)
            for t in PROMPT_MAX_DURATION_TIERS
        },
    }


def budget_gate(
    estimate: float,
    balance: Optional[float],
    batch_cap: Optional[float] = None,
    safety_ratio: float = 1.2,
) -> Dict[str, Any]:
    """批量动作前的熔断判定（审核席位硬要求：没有闸门就别开批量按钮）。

    - 余额 < 预估×safety_ratio → blocked（余额不足，跑一半会整批卡死在半空）
    - 预估 > batch_cap → need_approval（超单批预算，拆批或等 admin 放批）

    balance 传 None 表示余额查询失败：**按放行处理但带 note**，因为余额查询本身
    是实时接口、有波动（手册明确写了"有波动属正常"），不能因为它抖动就挡死业务。
    """
    if balance is not None and balance < estimate * safety_ratio:
        return {
            "allowed": False, "level": "blocked",
            "reason": f"智令余额 {balance:.2f} 元 < 预估 {estimate:.2f} 元 ×{safety_ratio}，本批已挡",
            "estimate": estimate, "balance": balance,
        }
    if batch_cap is not None and estimate > batch_cap:
        return {
            "allowed": False, "level": "need_approval",
            "reason": f"本批预估 {estimate:.2f} 元超单批上限 {batch_cap:.2f} 元，需拆批或管理员放批",
            "estimate": estimate, "balance": balance,
        }
    note = None if balance is not None else "余额查询未成功，本批按预估放行，请事后对账"
    return {"allowed": True, "level": "ok", "reason": None, "note": note,
            "estimate": estimate, "balance": balance}


def estimate_production_days(
    count: int, account_count: int, per_account_per_day: Optional[int] = None
) -> Dict[str, Any]:
    """按号池把"生产数量 N"折成天数（瓶颈是额度不是工时）。

    `per_account_per_day` 由调用方传 `settings.ASSET_DOUBAO_PER_ACCOUNT_PER_DAY`
    （B 组：那格配置原先无人读，改配置不生效；本层保持不 import config，纯函数好测）。
    """
    per_day_unit = max(1, int(per_account_per_day or DOUBAO_PER_ACCOUNT_PER_DAY))
    accounts = max(1, int(account_count or 1))
    per_day = max(1, accounts * per_day_unit)
    n = max(0, int(count))
    return {
        "count": n,
        "account_count": accounts,
        "per_account_per_day": per_day_unit,
        "capacity_per_day": per_day,
        "days": -(-n // per_day),  # 向上取整
    }


# ─────────────────────────  阶段派生  ─────────────────────────

def derive_status(stages: Dict[str, str], has_approved_copy: bool = False) -> str:
    """由 5 个阶段态算素材派生态（**任一 failed 优先**，其余按"当前所处环节"取最先命中）。

    规则表（自上而下 first-match）：
      任一 failed                     → failed
      compose success / (produce success + compose skipped) → ready
      compose running                 → composing
      produce running                 → producing
      produce success|skipped         → composing（产物已具备合成条件）
      summary running                 → summarizing
      summary success 且无过审文案     → awaiting_review
      summary success 且有过审文案     → ready_to_produce
      prompt running                  → analyzing
      prompt success                  → summarizing
      import running                  → importing
      import success                  → waiting_prompt（**待反推**，任务还没提交）
      其余                            → draft

    A4-6：`analyzing` 与 `waiting_prompt` 必须分开。旧口径把「导入完成待反推」和
    「智令正在跑」都算成 analyzing，200 条的队列里一线看不出哪些是**没人提交**、
    哪些是**提交了在等**，两种情况的处置动作完全相反（一个要点提交、一个要等收敛）。
    """
    s = {k: (stages.get(k) or "pending") for k in ("import", "prompt", "summary", "produce", "compose")}
    if "failed" in s.values():
        return "failed"
    if s["compose"] == "success" or (s["produce"] == "success" and s["compose"] == "skipped"):
        return "ready"
    if s["compose"] == "running":
        return "composing"
    if s["produce"] == "running":
        return "producing"
    if s["produce"] in ("success", "skipped") and s["compose"] == "pending":
        return "composing"
    if s["summary"] == "running":
        return "summarizing"
    if s["summary"] == "success":
        return "ready_to_produce" if has_approved_copy else "awaiting_review"
    if s["prompt"] == "running":
        return "analyzing"
    if s["prompt"] == "success":
        return "summarizing"
    if s["import"] == "running":
        return "importing"
    if s["import"] in ("success", "skipped"):
        return "waiting_prompt"
    return "draft"


def stage_of(asset: Any) -> Dict[str, str]:
    """从 ORM 行取 5 个阶段态（列名 stage_<阶段>）。"""
    return {k: getattr(asset, f"stage_{k}") or "pending" for k in ("import", "prompt", "summary", "produce", "compose")}


def apply_stage(asset: Any, stage: str, state: str, *, has_approved_copy: Optional[bool] = None) -> str:
    """写阶段态并重算派生态，返回新 status（不 commit，交由调用方控事务）。"""
    if stage not in ("import", "prompt", "summary", "produce", "compose"):
        raise ValueError(f"未知阶段：{stage}")
    if state not in ("pending", "running", "success", "failed", "skipped"):
        raise ValueError(f"未知阶段态：{state}")
    setattr(asset, f"stage_{stage}", state)
    stages = stage_of(asset)
    approved = asset.has_approved_copy if has_approved_copy is None else has_approved_copy
    asset.status = derive_status(stages, has_approved_copy=bool(approved))
    return asset.status


# ─────────────────────────  审核状态机  ─────────────────────────

# 允许的审核迁移（未列出的一律拒，防"改完再改"绕过留痕）
_REVIEW_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "pending": ("approved", "rejected", "need_rewrite", "passed_edited"),
    "approved": ("pending", "rejected"),              # 撤销 / 回炉
    "passed_edited": ("pending", "rejected"),
    "rejected": ("pending", "approved", "passed_edited"),
    "need_rewrite": ("pending", "approved", "passed_edited", "rejected"),
}


def assert_review_transition(frm: str, to: str) -> None:
    if to == frm:
        return
    if to not in _REVIEW_TRANSITIONS.get(frm, ()):
        raise ValueError(f"审核态不允许从 {frm} 直接到 {to}")


def count_copy_chars(text: Optional[str]) -> int:
    """字数口径：含标点、**不含任何空白**（与 video-copy-rewriter 一致）。"""
    return len(re.findall(r"\S", text or ""))


def check_copy_shape(text: str, *, max_chars: int = 80, max_first_clause: int = 25) -> Dict[str, Any]:
    """钩子文案形态校验（设计方案 §2 的口径落成功程）。"""
    t = (text or "").strip()
    chars = count_copy_chars(t)
    first = re.split(r"[。！？!?；;，,]", t, maxsplit=1)[0]
    problems: List[str] = []
    if not t:
        problems.append("空文案")
    if chars > max_chars:
        problems.append(f"超字数 {chars}>{max_chars}")
    if count_copy_chars(first) > max_first_clause:
        problems.append(f"首句钩子超 {max_first_clause} 字")
    if len(t) > 0 and t.endswith(("，", ",", "、")):
        problems.append("结尾悬空（以逗号/顿号结尾）")
    return {"ok": not problems, "chars": chars, "first_clause": first, "problems": problems}


# ─────────────  高风险词：**分级 + 豁免正则 + 可热更词表**（A2-3）  ─────────────
# 为什么分级而不是一锅端：这里是**子串**匹配，绝对化用语误杀率极高
# （"她第一次心动"命中"第一"、"全网第一"才是真违规）。把它们和"砍死"同等硬拒，
# 一线学会的是"绕道改词"而不是真删风险，审核栏位会被训练成集体无视。
#   block = 命中即不许过审、不许投产（血腥/色情/违法/歧视/医疗绝对化）
#   warn  = 只留痕预警，人看一眼决定改不改（绝对化用语、夸大承诺）
# 词表不再是"改一个词要发版"：`system_config.key='asset_risk_lexicon'` 可整体覆盖，
# API 层现读带 TTL（见 assets.py `_risk_lexicon`）。
RISK_LEVEL_BLOCK = "block"
RISK_LEVEL_WARN = "warn"
RISK_LEVELS = (RISK_LEVEL_BLOCK, RISK_LEVEL_WARN)

DEFAULT_RISK_LEXICON: Dict[str, Tuple[str, ...]] = {
    RISK_LEVEL_BLOCK: (
        # 血腥暴力
        "砍死", "捅死", "打死", "血流成河", "分尸", "自杀", "跳楼", "吞药",
        # 色情低俗
        "上床", "脱衣", "裸", "强奸", "猥亵", "迷奸", "约炮",
        # 违法诱导
        "赌博", "开盘", "放贷", "高利贷", "网贷", "洗钱", "毒品", "冰毒",
        # 歧视侮辱
        "婊子", "贱人", "废物", "傻子", "残废", "乡下人",
        # 医疗绝对化
        "根治", "包治", "神药", "特效药", "绝不复发",
    ),
    RISK_LEVEL_WARN: (
        # 绝对化用语（广告法口径）：真该改，但子串误杀高，交给 warn 让人判断
        "第一", "最强", "国家级", "百分百", "全网最低", "史上",
    ),
}

# 豁免正则：命中点若被这些匹配整个包住，就不算命中。默认只给误杀大户配。
# system_config 里同格式追加，例如 {"第一": "第一次|第一时间|第一眼"}
DEFAULT_RISK_EXEMPTIONS: Dict[str, str] = {
    "第一": r"第一(次|时间|眼|天|声|反应|位|回|场|晚|步|句|个|条|张|口|滴)",
    "史上": r"史上(来|今)",
}

RISK_LEXICON_CONFIG_KEY = "asset_risk_lexicon"


def normalize_risk_lexicon(
    lexicon: Optional[Dict[str, Any]],
    exemptions: Optional[Dict[str, str]],
) -> Tuple[Dict[str, List[str]], Dict[str, "re.Pattern"]]:
    """把（可能来自 system_config 的）词表规整成 {level: [词]} + {词: 已编译正则}。

    未知级别一律并到 block（宁可多拦不可漏），空词表回退默认表——
    配置写错不能把闸门写成"全放行"。
    """
    src = lexicon if lexicon else DEFAULT_RISK_LEXICON
    out: Dict[str, List[str]] = {level: [] for level in RISK_LEVELS}
    for level, words in (src or {}).items():
        bucket = level if level in out else RISK_LEVEL_BLOCK
        for w in (words or []):
            word = str(w or "").strip()
            if word and word not in out[bucket]:
                out[bucket].append(word)
    if not any(out.values()):
        out = {level: list(words) for level, words in DEFAULT_RISK_LEXICON.items()}

    ex_src = exemptions if exemptions is not None else DEFAULT_RISK_EXEMPTIONS
    compiled: Dict[str, "re.Pattern"] = {}
    for word, pattern in (ex_src or {}).items():
        if pattern is None or pattern == "":
            continue
        if isinstance(pattern, re.Pattern):  # 允许把已规整过的表再传进来（幂等）
            compiled[str(word)] = pattern
            continue
        try:
            compiled[str(word)] = re.compile(str(pattern))
        except re.error:
            logger.warning("风险词豁免正则无效，已忽略：%s -> %s", word, pattern)
    return out, compiled


def scan_risk(
    text: Optional[str],
    *,
    lexicon: Optional[Dict[str, Any]] = None,
    exemptions: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """扫描风险词，返回 [{"word","level"}]（去重、按 block→warn、词表原序保序）。

    `lexicon` / `exemptions` 传 system_config 里的覆盖表；不传用默认表。
    调用方拿到的是**带级别**的结果：block 拦人，warn 只留痕。
    """
    t = text or ""
    if not t:
        return []
    book, ex = normalize_risk_lexicon(lexicon, exemptions)
    spans = [
        (m.start(), m.end())
        for rx in ex.values()
        for m in rx.finditer(t)
        if m.end() > m.start()
    ]
    hits: List[Dict[str, str]] = []
    for level in RISK_LEVELS:
        for word in book.get(level, []):
            start = t.find(word)
            while start != -1:
                end = start + len(word)
                if not any(s <= start and end <= e for s, e in spans):
                    hits.append({"word": word, "level": level})
                    break
                start = t.find(word, end)
    return hits


def risk_block_hits(hits: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [h for h in (hits or []) if (h or {}).get("level") == RISK_LEVEL_BLOCK]


def format_risk_hits(hits: Optional[List[Dict[str, str]]]) -> Optional[str]:
    """落库形态：`砍死|block,第一|warn`（NULL=干净）。单列存级别，前端才能分开渲染。"""
    if not hits:
        return None
    return ",".join(f"{h['word']}|{h.get('level') or RISK_LEVEL_BLOCK}" for h in hits)[:500]


def parse_risk_hits(raw: Optional[str]) -> List[Dict[str, str]]:
    """读回 `risk_hit` 列。旧数据（没有 `|级别` 的裸词）一律按 block 处理——往严的方向靠。"""
    if not raw:
        return []
    out: List[Dict[str, str]] = []
    for chunk in str(raw).split(","):
        piece = chunk.strip()
        if not piece:
            continue
        word, _, level = piece.partition("|")
        out.append({"word": word, "level": level if level in RISK_LEVELS else RISK_LEVEL_BLOCK})
    return out


# 十行骨架里**必须出现**的关键词（11-02 版权威）；判"有没有"，不判"写得好不好"。
PROMPT_SKELETON_KEYS: Tuple[str, ...] = (
    "剧情", "画面变化", "人物", "时长", "音频", "字幕", "画质", "负面",
)


def check_prompt_skeleton(prompt: Optional[str]) -> Dict[str, Any]:
    """提示词骨架齐全判据（A2-1 的第④道：投产前必须齐）。

    走接口投豆包前缺哪一行都会出事：缺「负面约束」会出怪片，缺「音频与字幕」会被
    加字幕，缺「执行要求」豆包弹二次确认卡住整批。
    """
    text = prompt or ""
    missing = [k for k in PROMPT_SKELETON_KEYS if k not in text]
    return {"ok": not missing, "missing": missing}


def recheck_copy(
    text: Optional[str],
    script: Optional[str] = None,
    *,
    lexicon: Optional[Dict[str, Any]] = None,
    exemptions: Optional[Dict[str, str]] = None,
    check_consistency_too: bool = True,
    max_chars: int = 80,
    max_first_clause: int = 25,
) -> Dict[str, Any]:
    """过审前 / 投产前的同一套复核（A2-1）：形态、风险词、一致性。

    返回 {"ok", "problems": [{"code","message"}], "chars", "risk", "consistency"}。
    problems 只收 **block 级**风险词——warn 级进 risk 供人看，但不拦（分级口径见上）。
    """
    problems: List[Dict[str, str]] = []
    shape = check_copy_shape(text, max_chars=max_chars, max_first_clause=max_first_clause)
    for p in shape["problems"]:
        problems.append({"code": "shape", "message": p})
    risk = scan_risk(text, lexicon=lexicon, exemptions=exemptions)
    for h in risk_block_hits(risk):
        problems.append({"code": "risk", "message": f"含高风险词「{h['word']}」"})
    consist: Optional[Dict[str, Any]] = None
    if check_consistency_too:
        consist = check_consistency(text or "", script)
        if not consist["ok"]:
            if consist.get("missing"):
                problems.append({
                    "code": "consistency",
                    "message": "与反推详规对不上：" + "、".join(consist["missing"]),
                })
            else:
                problems.append({"code": "consistency", "message": consist.get("note") or "无反推脚本可比对"})
    return {
        "ok": not problems,
        "problems": problems,
        "chars": shape["chars"],
        "risk": risk,
        "consistency": consist,
    }


# ── 专名识别（人物称呼 / 机构）：一致性校验用，只当**预警**，绝不当硬闸 ──
# 为什么用姓氏白名单而不是「任意 1~4 字 + 称呼」的正则：
# 中文没有词边界，`([\u4e00-\u9fa5]{1,4})(?:总|姐)` 会在「张总当着李姐的面」里
# 把「当着李」当姓、「着李姐」当称呼，抽出来的实体全是垃圾，审核员被假警报训练成无视这一栏。
# 白名单漏了罕见姓只会**减弱**校验（漏报），不会制造假警报——这个方向是安全的。
_SURNAMES = (
    "王李张刘陈杨黄赵周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
)
_COMPOUND_SURNAMES = ("欧阳", "司马", "上官", "诸葛", "东方", "夏侯", "皇甫", "尉迟", "公孙", "令狐")
_TITLES = ("总", "经理", "医生", "律师", "老师", "主任", "队长", "董事长", "姐", "哥", "妈", "爸", "嫂", "婶", "爷", "奶")
_ORG_SUFFIXES = ("公司", "医院", "集团", "学校", "小区", "酒店", "会所", "派出所", "法院", "银行", "工厂", "饭店")
# 常见虚词/动词：抽机构名时按它们切段，取最后一段当名字（见 extract_entities 内注释）。
# ⚠️ 别把「和/中/间/上/下」放进来——它们既是虚词也是店名用字
# （仁和医院、中山医院、天和会所），当切分符用会把「仁和」切成「仁」，抽出「仁医院」这种鬼东西。
_HEAD_STOP_CHARS = set("把在去到从跟与的了是吧是看进出回让被给向往对着又还就才先后拿做因为所以然后但只")
# 人名**可以**跟在的字后（中文没有词边界，用「助词/代词/动词」当轻量边界）：
# 「当着李姐的面」里李姐是人名，「提高总产量」里的高总不是——一个边界集合就能分开这两种。
_NAME_BOUNDARY_CHARS = set(
    "的着了在和跟让被向对把从到又也就还才正很太这那我你他她它咱您们叫是有要给为而但可都已被会能说问看听等于以时候前里外上下"
    "，。！？；：、,.!?;: “”\"'（）()【】《》 \t\n"
)


def extract_entities(text: Optional[str]) -> List[str]:
    """从文案里抽实体（人物称呼 / 机构），供「文案实体必须能在反推脚本里命中」校验。

    只认白名单姓 + 称呼、后缀式机构名；认不出来就是没有实体（校验直接放行），
    宁可漏报也不给出假实体——假实体会把一致性校验变成没人看的噪音栏。
    """
    t = text or ""
    out: List[str] = []

    # 人物称呼：复姓优先（「欧阳总」不能被拆成「阳总」）
    for cs in _COMPOUND_SURNAMES:
        for title in _TITLES:
            if cs + title in t:
                out.append(cs + title)

    surname_class = "".join(dict.fromkeys(_SURNAMES))
    for title in _TITLES:
        for m in re.finditer(f"([{surname_class}]){title}", t):
            start = m.start()
            prev = t[start - 1] if start else ""
            if prev and prev not in _NAME_BOUNDARY_CHARS:
                continue  # 非边界（如「提高总」）不当人名
            out.append(m.group(0))

    # 机构名：后缀前的连续字词里，取**最后一个虚词/动词之后**的那一段做名字。
    # 「欧阳总去了仁和医院」的 head 是「欧阳总去了仁和」，从左削只会削掉「去」，
    # 剩下「了仁和医院」还是错的；按虚词切段取尾段才拿到「仁和」。
    for suffix in _ORG_SUFFIXES:
        for m in re.finditer(rf"([\u4e00-\u9fa5A-Za-z0-9]{{1,8}}){suffix}", t):
            head = m.group(1)
            pieces = [p for p in re.split(f"[{''.join(sorted(_HEAD_STOP_CHARS))}]", head) if p]
            if pieces:
                out.append(pieces[-1] + suffix)

    dedup: List[str] = []
    for e in out:
        if e and e not in dedup:
            dedup.append(e)
    return dedup


def check_consistency(copy: str, script: Optional[str], *, min_overlap: float = 0.5) -> Dict[str, Any]:
    """一致性校验：文案里的实体必须能在反推脚本中命中。

    防的是"反推其实失败了，但文案编得像模像样"——审核员看不出，投了豆包才炸。
    无实体时（纯情绪型钩子）判 ok 但带 note，不硬拦。
    """
    ents = extract_entities(copy)
    if not ents:
        return {"ok": True, "entities": [], "missing": [], "note": "文案无专名实体，跳过一致性比对"}
    src = script or ""
    missing = [e for e in ents if e not in src]
    overlap = (len(ents) - len(missing)) / len(ents)
    return {
        "ok": overlap >= min_overlap,
        "entities": ents,
        "missing": missing,
        "overlap": round(overlap, 2),
        "note": None if src else "无反推脚本可比对",
    }


# ─────────────────────────  生产单差异化（N 的语义）  ─────────────────────────

# N 条之间的差异来源，按序取用；超出后循环并附加序号，保证 variant_basis 不重复。
_VARIANT_BASES: Tuple[str, ...] = (
    "首句句式轮换（倒装陈述↔疑问起手）",
    "情绪支点换轴（痛点↔爽点侧重互换）",
    "开场形态换式（高潮倒叙 / 危机前置 / 时间限制起手）",
    "人设口吻换装（毒舌 / 佛系 / 话痨）",
    "镜头顺序重排（节拍不变，画面先后换序）",
    "角色卡替换（同人物不同时期定妆照）",
)


def variant_basis(seq: int, total: int) -> str:
    """第 seq 条（1 起）相对同批其它条的差异来源。"""
    base = _VARIANT_BASES[(max(1, seq) - 1) % len(_VARIANT_BASES)]
    if seq > len(_VARIANT_BASES):
        return f"{base}（第 {seq}/{total} 轮）"
    return base


# ─────────────────────────  展开结果漂移判定（A3-3）  ─────────────────────────
# 旧判据是「去掉空格后子串包含」，实测三种改写全都能过：前面加半句、把原句塞进括号、
# 整句复制两遍。审的和产的不是同一条的时候，豆包出来的片就跟审核台看到的完全无关。

_WS_RE = re.compile(r"\s+")

# 原句**前面**允许出现的字符：句读/开括号/省略。集合按审核席位的口径给窄不给宽——
# **故意不含逗号、顿号、分号**：「镜头推进，〈原句〉」正是"前面被拼了半句"的典型形态，
# 放进白名单等于把这条判据废掉（旧实现就是这个漏洞）。冒号/引号留着，那是模板
# 正常引出钩子的写法（旁白：〈原句〉），不算改写。
_COPY_HEAD_OK = set("。．：:！!？?“”\"「」『』（()【】[]—…")
# 原句**后面**紧跟这些＝原句被括号包住了（模板里常见于把钩子塞进「（画面：…）」）。
# 只收括号、不收引号：字幕/台词行写 `字幕："〈原句〉"` 是**合法引用**不是改写，
# 把引号也算进来会天天误报，而 drift 提示一多一线就不看了（这套闸门的命门在可信度）。
_COPY_TAIL_BAD = set("）)】]")


def _norm_copy(text: Optional[str]) -> str:
    return _WS_RE.sub("", text or "")


def judge_drift(copy: Optional[str], prompt: Optional[str]) -> Dict[str, Any]:
    """过审钩子在展开提示词里是否**原样、唯一、独立**地存活（A3-3）。

    返回 {"drift": bool, "reasons": [...], "occurrences": int}。
    注意：这里**不判十行骨架齐不齐**——缺行是"模板没写全"，不是"审的和产的不是同一条"，
    混进 drift 会把这个字段失去含义（骨架缺行由 `check_prompt_skeleton` 单独出警示）。
    """
    needle = _norm_copy(copy)
    haystack = _norm_copy(prompt)
    if not needle:
        return {"drift": True, "reasons": ["无过审文案可比对"], "occurrences": 0}
    if not haystack:
        return {"drift": True, "reasons": ["展开结果为空，无从比对"], "occurrences": 0}

    occurrences = haystack.count(needle)
    reasons: List[str] = []
    if occurrences == 0:
        reasons.append("过审原句没出现在提示词里（模型重写了文案）")
    elif occurrences > 1:
        reasons.append(f"过审原句出现了 {occurrences} 遍（整句复制两遍＝N 条差异失效）")
    else:
        pos = haystack.find(needle)
        before = haystack[pos - 1] if pos > 0 else None
        after_at = pos + len(needle)
        after = haystack[after_at] if after_at < len(haystack) else None
        if before is not None and before not in _COPY_HEAD_OK:
            reasons.append(f"原句前面被拼了字（「…{before}{needle[:8]}」）")
        if after is not None and after in _COPY_TAIL_BAD:
            reasons.append(f"原句被括号包住（「{needle[:8]}…{after}」）")
    return {"drift": bool(reasons), "reasons": reasons, "occurrences": occurrences}


# ─────────────────────────  企微后台 AI 视频任务板（通道 wework_aivideo）  ─────────────────────────
# 权威口径：NAS《每日解压视频-操作手册-20261022.md》+ Drama/共享配置/skill/relax-video-pipeline。
# 建任务 POST /api-g/aivideo/create，payload **只有七个键** tag/reqID/total/date/prompt/name/picDatas；
# 这条通道不扣现金、**没有时长与分辨率参数**（成片恒 10.08s / 720×1280）。

# 板上 name 即交付文件名，非法字符口径与权威文档「推荐标题禁止包含文件名非法字符」一致。
BOARD_NAME_ILLEGAL = '\\/:*?"<>|'
# ≤60 码点：与网页 RPA 线取「项目标题」的截断口径对齐，超长会在小V猫标题栏尾部被裁
BOARD_NAME_MAX_CODEPOINTS = 60
# 五位钩子编号 = 日期2位base36 + 剧码2位 + 当日序号1位（《剧码登记.json》format 字段）。
# ⚠️ 取号统一用 hook_id.py，**后端绝不自己编号**（多人在共享盘取号，手编必撞码）。
HOOK_CODE_RE = re.compile(r"^[0-9A-Z]{5}$")


def is_valid_hook_code(raw: Any) -> bool:
    return bool(raw) and bool(HOOK_CODE_RE.match(str(raw).strip().upper()))


def sanitize_board_name(title: Optional[str], *, max_codepoints: int = BOARD_NAME_MAX_CODEPOINTS) -> Optional[str]:
    """推荐视频标题第 1 条 → 板上 `name`（也是回收改名依据）。

    11-02 版权威：「1020 起项目标题行已取消」，豆包导出文件按推荐视频标题第 1 条改名，
    所以 name 的唯一来源是 `video_titles[0]`，不再是提示词里的「项目标题：」。
    处理：剥文件名非法字符、控制字符、首尾空白与结尾句点（Windows 会吞），压缩连续空白，
    按**码点**截断（中文一个字算 1，不用 len 之外的字节口径）。
    """
    if not title:
        return None
    text = str(title)
    cleaned = "".join(
        " " if ch in BOARD_NAME_ILLEGAL else ch
        for ch in text
        if ch == " " or (ch >= "\x20" and ch != "\x7f")
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".。 ")
    if not cleaned:
        return None
    return cleaned[:max_codepoints]


# 投放要求行的识别（B-9）：这些行本来是**给人看的操作指令**，走接口后没有执行对象，
# 还会被模型当画面描述——历史上"画面顶部标题条"就是这么被生成出来的。
_DISPATCH_LINE_RE = re.compile(r"^\s*[【\[]?\s*(执行要求|投放要求|操作要求|注意事项|备注)\s*[:：]")


def split_dispatch_note(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """把「提示词正文」与「投放指令」拆开，返回 (正文, 投放要求)。

    只做**整行搬移**，一个字都不改词（改词等于把「审的」变成「产的」）。
    模板侧的正确做法是让模型直接输出分字段 JSON；这里是兜底：模板还没改到位时，
    执行要求行也不该整段丢进豆包对话。
    """
    if not text:
        return None, None
    lines = str(text).splitlines()
    cut = None
    for idx, line in enumerate(lines):
        if _DISPATCH_LINE_RE.match(line):
            cut = idx
            break
    if cut is None:
        return (str(text).strip() or None), None
    # 权威模板里「执行要求」是**最后一段**，所以命中即把该行及其后全部归入投放要求；
    # 不做逐行猜测（猜错会把画面描述当成指令删掉，那就是改词）。
    body = "\n".join(lines[:cut]).strip()
    note = "\n".join(lines[cut:]).strip()
    return (body or None), (note or None)


def board_timestamp(now: Optional[datetime] = None, tz_offset_hours: int = 8) -> datetime:
    """板上 `date`：后端生成的**完整时间戳**（YYYY-MM-DD HH:MM:SS）。

    两条实测教训都落在这里：
    1. 只写日期（或让前端传）→ 接口照样返回 succ，但 `info?date=` 按任何日期都查不到，
       额度白烧、成片永久取不回（1021 那次 120 条）。
    2. 板面按 NAS 本地时区（CST）切日，后端存 UTC —— 16:00~24:00 投放会错一天。
    所以时间由后端生成、按偏移折算成板面本地时间（naive，与板接口一致），落库为准。
    """
    base = (now or datetime.utcnow()) + timedelta(hours=int(tz_offset_hours or 0))
    return base.replace(microsecond=0)


# ────────────────  导出形态：可投文本块 + 板面七键 payload（A3-1）  ────────────────
# 权威口径：pipeline.py:240-262 —— POST /api-g/aivideo/create 的 payload **只有这七个键**，
# 键序按它抄；多给一个键板侧不认（历史上加过 duration/resolution 直接被忽略，白跑）。
BOARD_PAYLOAD_KEYS: Tuple[str, ...] = ("tag", "reqID", "total", "date", "prompt", "name", "picDatas")
# 板上 date 的字符串口径：必须完整时间戳（只写日期 → succ 但永久查不到）
BOARD_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def board_date_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime(BOARD_DATE_FMT) if dt else None


def board_req_id(production_id: Any) -> str:
    """板上 `reqID` = 生产单 id（不是随机 uuid4）。

    pipeline.py 里是 `str(uuid.uuid4())`——那是一次性脚本，没有可对账的主键。
    我们每行单本来就有稳定主键，用它当 reqID 换来两件事：
    重复导出/重复点投放不换号（板侧按 reqID 幂等）、回收时 reqID 直接回指生产单。
    """
    return str(production_id)


def build_board_payload(
    *,
    production_id: Any,
    board_tag: Optional[str],
    board_total: Optional[int],
    board_date: Optional[datetime],
    prompt_text: Optional[str],
    board_name: Optional[str],
    card_b64_items: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """后台任务板 `create` 的七键 payload（缺正文/缺 name 时照结构给空值，不猜）。"""
    return {
        "tag": board_tag or "",
        "reqID": board_req_id(production_id),
        "total": max(1, min(int(board_total or 1), 20)),
        "date": board_date_str(board_date),
        "prompt": prompt_text or "",
        "name": board_name or "",
        "picDatas": list(card_b64_items or []),
    }


def card_b64_from_bytes(raw: bytes) -> str:
    """角色卡字节 → 板上 `picDatas` 的一项（纯 base64，**不带 `data:` 前缀**）。

    权威口径（pipeline.py:77-89 `_card_b64`）还要求长边 ≤1024、转 JPEG q80。后端没有
    Pillow（且「未经同意不得本机安装」），所以这里**只做编码、不做缩放**，超限由
    调用方按 `card_advisory` 提示处理：卡是在上传侧压好的就没问题，原图直接传上来的
    要先压一遍——板侧收到超大 picData 会静默建任务失败，排查成本极高。
    """
    import base64

    return base64.b64encode(raw).decode()


def _hook_code_tail(code: Optional[str]) -> str:
    return f"（{code}）" if is_valid_hook_code(code) else ""


def format_titles_with_code(video_titles: Optional[List[str]], hook_code: Optional[str]) -> List[str]:
    """推荐标题逐条补五位编号尾巴（11-02：编号在推荐标题里出现，是第二处必带）。

    只在**没带**时补，绝不改标题本身一个字（改词＝把「审的」变成「产的」）。
    """
    tail = _hook_code_tail(hook_code)
    out: List[str] = []
    for idx, raw in enumerate(video_titles or [], start=1):
        title = str(raw or "").strip()
        if not title:
            continue
        if tail and tail not in title and (hook_code or "").upper() not in title.upper():
            title = f"{title}{tail}"
        out.append(f"{idx}. {title}")
    return out


# 推荐视频标题正文字数预算（P1 #19，与 hook_expand.txt 第 17 条钉死同一口径）：
# 展开导出的标题数组**不带【账号】前缀**，发布侧补 4 字前缀后小V猫报表/板面标题列
# 只显示前 22 字 → 正文上限 = 22 − 4 = **18 字**。
# 「精简钩子上限＝11－剧缩字数」是同一预算的**内部配额**（正文＝剧缩＋「·」＋5 位编号
# ＋「·」＋精简钩子，18 − 1 − 5 − 1 = 11），标题拼得规范时正文 ≤18 已覆盖它，
# 拆段重判反而会被「缺剧缩/缺编号」的降级标题误伤——判据统一落在正文上。
TITLE_BODY_BUDGET_CHARS = 18


def check_video_title_budget(
    video_titles: Optional[List[str]], *, limit: int = TITLE_BODY_BUDGET_CHARS
) -> List[Dict[str, Any]]:
    """推荐标题正文逐条软校验：只报超预算的，**不拦、不改状态**（P1 #19）。

    字数口径必须复用 `count_copy_chars`（含标点、不含空白）——前端/报表/本判据
    三处数是同一把尺，才不会「这边报超、那边看着没超」。
    空标题/None/纯空白＝0 字，不报（缺标题另有 missing_names 警告，别在这里双报）。
    """
    problems: List[Dict[str, Any]] = []
    for raw in video_titles or []:
        title = str(raw or "").strip()
        chars = count_copy_chars(title)
        if chars > limit:
            problems.append({"title": title, "chars": chars, "limit": limit})
    return problems


def format_export_block(
    *,
    hook_code: Optional[str],
    prompt_text: Optional[str],
    video_titles: Optional[List[str]],
    dispatch_note: Optional[str] = None,
) -> str:
    """一条生产单 → 一整块可投文本：段头（带编号）+ 正文 + 推荐标题（11-02 三处编号）。

    段头只写编号与产出序号——正文第一行本就是模板给的段头，重复写会生成两份标题条。
    `dispatch_note` 附在块尾并明确标「不进 payload」：那是给人看的投放要求（B-9）。
    """
    lines: List[str] = []
    head = (hook_code or "缺编号").strip() or "缺编号"
    lines.append(f"=== {head} ===")
    lines.append((prompt_text or "").strip() or "【无正文：expand=false 的裸单，投放前先展开】")
    titled = format_titles_with_code(video_titles, hook_code)
    if titled:
        lines.append("推荐视频标题：")
        lines.extend(titled)
    else:
        lines.append("推荐视频标题：（无——板上 name 无从生成，不许投）")
    if dispatch_note:
        lines.append("─── 以下投放要求只给人看，不要贴进豆包对话 ───")
        lines.append(dispatch_note.strip())
    return "\n".join(lines)


def format_output_manifest(rows: List[Dict[str, Any]]) -> str:
    """批次级「产出清单」（11-02 的第三处必带编号）：一行一张单，给投放人打勾用。"""
    if not rows:
        return ""
    lines = ["产出清单（编号｜板上 name｜素材｜序号）"]
    for r in rows:
        lines.append(
            f"{r.get('hook_code') or '缺编号'}｜{r.get('board_name') or '缺name'}"
            f"｜{r.get('asset_code') or r.get('asset_id') or '未知'}｜第{r.get('seq')}条"
        )
    return "\n".join(lines)


def board_capacity_hint(
    planned: int,
    already_today: int,
    soft_cap: int,
) -> Dict[str, Any]:
    """当日投放量的软提示（B-8）：**不硬限**（用户口径「产能不限」），只把实测说清楚。

    号池实测 ≈120 条/日：1023 一天叠两份量（240），其中一批 10 分钟内 115/120 全 fail；
    1028 投 230 只到手 162（70%），90 分钟后不再增加 —— 超出 120 的那部分基本是白投。
    正确排法是"今天 120 + 明天 120"，所以提示给的是**分日建议**，不是拒绝。
    soft_cap<=0 视为关闭提示。
    """
    planned = max(0, int(planned))
    already = max(0, int(already_today))
    cap = int(soft_cap or 0)
    total = already + planned
    over = max(0, total - cap) if cap > 0 else 0
    hint: Dict[str, Any] = {
        "planned": planned,
        "already_today": already,
        "total_today": total,
        "soft_cap": cap,
        "over_cap": over,
        "advisory": None,
    }
    if over > 0:
        hint["advisory"] = (
            f"今日板上已投 {already} 条，本批再加 {planned} 条 = {total} 条，"
            f"超出号池实测 ≈{cap} 条/日约 {over} 条：超出部分预计到手率明显下降"
            "（1028 实测 230 条只到手 162 条）。建议分日投（今天 {a} + 明天 {b}），"
            "产能不限、可继续，只是别指望全出片。".format(
                a=min(total, cap) - already, b=max(0, total - cap)
            )
        )
    return hint


def normalize_source_list(raw: Any) -> Tuple[List[str], List[str]]:
    """批量导入入参清洗：去空、去**同批内**重复（不再按单批上限报错，见 `chunk_by_limit`）。

    返回 (可用链接, 跳过原因)。跨批次去重要查库（source_url_norm 命中），
    由 api 层负责并回「谁在什么时候导入的」。
    """
    items = raw if isinstance(raw, list) else [raw]
    kept: List[str] = []
    skipped: List[str] = []
    seen = set()
    for u in items:
        url = (u or "").strip()
        if not url:
            skipped.append("存在空链接，已跳过")
            continue
        if url in seen:
            skipped.append(f"同批内重复链接已跳过: {url[:40]}")
            continue
        seen.add(url)
        kept.append(url)
    return kept, skipped


def chunk_by_limit(items: List[Any], limit: int) -> List[List[Any]]:
    """超单批上限 → **自动拆批**（方案 §四），不是 400 打回（A4-1）。

    一线的真实动作是「今天收了 300 条链接，一把粘进来」。让他自己数到 100 分三次提交，
    等于把系统约束变成人工劳动，还会拆出三个来路不明的批次名。这里按 limit 切片、
    每片各建一个批次并各自记成本，回 `split_into` 让调用方知道**到底建了几批**。
    limit<=0 视为不拆（整批一批）。
    """
    if not items:
        return []
    size = int(limit or 0)
    if size <= 0 or len(items) <= size:
        return [list(items)]
    return [list(items[i:i + size]) for i in range(0, len(items), size)]
