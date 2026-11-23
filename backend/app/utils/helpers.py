import os
import json
import re
import logging
from datetime import datetime, timedelta, timezone
import tempfile
from typing import List, Optional

from app.models.models import ClipCandidate, DetectedInterval

logger = logging.getLogger(__name__)


def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def parse_time(time_str: str) -> float:
    """Parse HH:MM:SS.mmm or HH:MM:SS format back to seconds."""
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """清洗文件名：保留中文/字母/数字/._-，其余替换为 _，去首尾分隔符。

    防剧集名含 / \\ : * ? " < > | 等路径/文件名非法字符破坏输出路径。
    """
    if not name:
        return "clip"
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", name, flags=re.UNICODE)
    cleaned = cleaned.strip("._- ") or "clip"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("._- ") or "clip"
    return cleaned


def build_clip_name(episode_title: Optional[str], index: int) -> str:
    """切片成品文件名：剧集名 + 当前日期(MMdd, 北京时间, 无年份) + 3位自增序号。

    例：剧集「扫地出门三胎宝妈是千金」→ 扫地出门三胎宝妈是千金_0818_001.mp4
    剧集名缺失/清洗后为空时回退 clip_{index:02d}（与历史命名兼容）。
    """
    mmdd = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%m%d")
    title = sanitize_filename(episode_title or "")
    if title == "clip":
        return f"clip_{index:02d}"
    return f"{title}_{mmdd}_{index:03d}"


def generate_cutlist(clips: List[ClipCandidate], episode_title: Optional[str] = None,
                    highlight_mix: bool = False,
                    max_duration: Optional[float] = None,
                    max_clip_duration: Optional[float] = None,
                    order: str = "time",
                    trim_over_duration: Optional[float] = None,
                    drop_under_duration: Optional[float] = None,
                    mix_output_count: Optional[int] = None,
                    dual_mix: bool = False,
                    dual_highlight_count: int = 2,
                    dual_main_count: int = 1,
                    dual_highlight_position: str = "head",
                    dual_output_count: Optional[int] = None) -> str:
    """Generate cutlist content from accepted clip candidates.

    Format per line:
        start_time end_time clip_name

    highlight_mix=True 时，把所有入选高光段共用同一输出文件名（同 name）生成 cutlist：
    引擎 groups 按 name 分组后天然顺序 concat 成单个混剪视频。可选配置：
    - max_duration: 每个输出文件的时长上限（秒），该文件累计段长不超过该值，
      塞入会超额时 time/score 顺序丢弃该段、random 顺序跳过后继续尝试更短的段；
    - max_clip_duration: 单段最大时长（秒），超长段裁剪到该上限后纳入（只裁不丢，段数不变），
      避免全部候选超长被过滤后静默返回空 cutlist -> 引擎兜底整片切片；
    - order: "time"（按源时间升序，默认）/ "score"（按评分从高到低）/ "random"（随机抽取：
      打乱候选贪心累计凑近 max_duration，单段超额则跳过继续尝试更短的段）；
    - mix_output_count: 输出文件个数（默认 1）。>1 时把入选段按顺序分组填充，产出
      N 个混剪文件（剧名_MMDD_001..N）：max_duration 为**每个文件**的时长上限，
      段耗尽或组满即止；未设 max_duration 时按段数均分到 N 个文件。
    不开启混剪时行为不变：每段独立命名（独立输出文件）。

    非混剪路径的时长硬规整（duration_hard_limit=true 时由 api/slice.py 传入）：
    - trim_over_duration: 单段超过该时长（秒）→ 裁剪 end=start+上限。只裁不丢，段数不变，
      避免「硬过滤砍成 0 候选」问题（P1 #228 的安全替代）；
    - drop_under_duration: 短于该时长（秒）的段丢弃；若全部段都过短则保留最长一段，
      保证 cutlist 非空（不出 0 候选）。
    """
    lines = []
    accepted = [c for c in clips if c.status == "accepted"]
    if not accepted:
        return ""
    if dual_mix:
        # 双批混拼（2026-11-23 用户需求）：高光批(clip_type=highlight)×N + 正片批×M
        # 组成每条成品，同名分组 -> 引擎顺序 concat；高光在前(head)或在后(tail)。
        seg_hl: list = []
        seg_mn: list = []
        for c in accepted:
            start = c.adjusted_start if c.adjusted_start is not None else c.start_time
            end = c.adjusted_end if c.adjusted_end is not None else c.end_time
            if start is None or end is None or end <= start:
                continue
            item = (start, end, end - start, c)
            (seg_hl if (c.clip_type == "highlight") else seg_mn).append(item)
        seg_hl.sort(key=lambda s: (s[3].score if s[3].score is not None else 0.0), reverse=True)
        seg_mn.sort(key=lambda s: (s[3].score if s[3].score is not None else 0.0), reverse=True)
        if not seg_mn and not seg_hl:
            logger.warning("双批混拼无有效段（候选时间轴均无效），cutlist 将为空")
            return ""
        n = max(0, int(dual_highlight_count))
        m = max(1, int(dual_main_count))
        pos = dual_highlight_position if dual_highlight_position in ("head", "tail") else "head"
        default_k = max(1, -(-len(seg_mn) // m)) if seg_mn else 1
        k = max(1, int(dual_output_count)) if dual_output_count else default_k
        lines = []
        out_idx = 0
        used_sigs = set()
        for g in range(k):
            take_hl = [seg_hl[(g * n + i) % len(seg_hl)] for i in range(min(n, len(seg_hl)))] if (seg_hl and n) else []
            take_mn = [seg_mn[(g * m + i) % len(seg_mn)] for i in range(min(m, len(seg_mn)))] if seg_mn else []
            group = (take_hl + take_mn) if pos == "head" else (take_mn + take_hl)
            if not group:
                continue
            sig = tuple((s[0], s[1]) for s in group)
            if sig in used_sigs and (len(seg_mn) > m or len(seg_hl) > n):
                continue
            used_sigs.add(sig)
            out_idx += 1
            g_name = build_clip_name(episode_title, out_idx)
            for start, end, _dur, _c in group:
                lines.append(f"{format_time(start)} {format_time(end)} {g_name}")
        if not lines:
            logger.warning("双批混拼分组后无有效行，回退首段保底")
            pool = seg_hl + seg_mn
            start, end, _d, _c = pool[0]
            lines.append(f"{format_time(start)} {format_time(end)} {build_clip_name(episode_title, 1)}")
        logger.info(
            "双批混剪 cutlist：高光 %d 段×%d + 正片 %d 段×%d（高光%s），输出 %d 条共 %d 段",
            len(seg_hl), n, len(seg_mn), m, pos, out_idx, len(lines),
        )
        return "\n".join(lines)
    if highlight_mix:
        # 高光混剪：入选段共用输出文件名（同 name -> 引擎同组顺序 concat）；
        # mix_output_count>1 时按组分名输出 N 个混剪文件（见下方分组填充）
        segs = []
        trimmed_long = 0
        for c in accepted:
            start = c.adjusted_start if c.adjusted_start is not None else c.start_time
            end = c.adjusted_end if c.adjusted_end is not None else c.end_time
            if start is None or end is None or end <= start:
                continue
            dur = end - start
            if max_clip_duration is not None and dur > max_clip_duration:
                # 单段超长：只裁不丢（裁到单段上限后纳入）。原先「整段跳过」在全部候选
                # 超长时会静默返回空 cutlist -> 引擎兜底整片切片（2026-09 生产事故根因）
                end = start + float(max_clip_duration)
                dur = float(max_clip_duration)
                trimmed_long += 1
            segs.append((start, end, dur, c))
        if not segs:
            logger.warning("高光混剪无有效段（候选 %d 个时间轴均无效），cutlist 将为空", len(accepted))
            return ""
        if order == "score":
            segs.sort(key=lambda s: (s[3].score if s[3].score is not None else 0.0), reverse=True)
        elif order == "random":
            # 随机抽取模式：打乱候选后贪心累计；单段会超额时跳过并继续尝试更短的段，
            # 尽量贴近每文件的时长上限（而非 time/score 的「到上限即停」）。
            # 每次切片抽取组合不同（业务预期：同素材多次切片产出不同混剪）。
            import random as _random
            _random.shuffle(segs)
        else:  # 默认 time：按源时间顺序
            segs.sort(key=lambda s: s[0])

        # ── 分组填充：output_count>1 时产出 N 个混剪文件 ──
        output_count = max(1, int(mix_output_count or 1))
        if output_count > 1 and max_duration is None:
            # 未设每文件时长上限：按段数均分到 N 个文件
            per = -(-len(segs) // output_count)
            groups = [segs[i * per:(i + 1) * per] for i in range(output_count)]
        elif order == "random" and max_duration is not None:
            # 随机抽取 + 每文件时长上限：**必须凑满 N 个文件**——素材允许跨文件复用
            # （业务规则：只要各文件组合顺序不同即可），每组独立洗牌贪心抽取贴近上限。
            # 背景：素材总时长不足 N×上限时，顺序填充只能产出「素材够分」的组数
            # （2026-11-20 余生践一诺：52 段/485s 上限 60s 只出 9 个），业务要求
            # 输出个数是硬指标而非上限。
            groups = []
            seen_sigs = set()
            attempts = 0
            while len(groups) < output_count and attempts < output_count * 25:
                attempts += 1
                pool = segs[:]
                _random.shuffle(pool)
                group = []
                g_total = 0.0
                for seg in pool:
                    if g_total + seg[2] > max_duration:
                        continue  # 超额段跳过，继续尝试更短的段凑近上限
                    group.append(seg)
                    g_total += seg[2]
                if not group:
                    # 全部段都超每文件上限：裁剪洗牌后首段保底（不出空组）
                    start, _end, _dur, _c = pool[0]
                    group = [(start, start + float(max_duration), float(max_duration), _c)]
                sig = tuple((s[0], s[1]) for s in group)
                if sig in seen_sigs:
                    continue  # 与已有文件的段组合完全相同：重洗重抽（防「相同顺序使用」）
                seen_sigs.add(sig)
                groups.append(group)
            # 重试耗尽仍凑不满（概率极低）：接受重复补齐，保证精确 N 个文件
            while len(groups) < output_count:
                groups.append(list(groups[-1]) if groups else segs[:1])
        else:
            groups = [[] for _ in range(output_count)]
            gi = 0
            for seg in segs:
                if gi >= output_count:
                    break  # 组满：剩余段丢弃（用户要求精确 N 个文件）
                if max_duration is not None and sum(s[2] for s in groups[gi]) + seg[2] > max_duration:
                    gi += 1  # 本文件已到时长上限：开下一个文件
                    if gi >= output_count:
                        break
                groups[gi].append(seg)

        lines = []
        total = 0.0
        out_idx = 0
        for g in groups:
            if not g:
                continue
            out_idx += 1
            g_name = build_clip_name(episode_title, out_idx)
            g_total = 0.0
            for start, end, dur, _c in g:
                if max_duration is not None and g_total + dur > max_duration:
                    if order == "random":
                        continue  # 随机抽取：超额段跳过，继续尝试后续更短的段凑近上限
                    break  # time/score：该文件到上限即停
                lines.append(f"{format_time(start)} {format_time(end)} {g_name}")
                g_total += dur
            total += g_total
        if not lines:
            # 全部段都超每文件上限：保底裁剪纳入排序后首段，保证 cutlist 非空
            # （对齐 duration_hard_limit「不出 0 候选」的兜底哲学，杜绝静默整片）
            start, end, _dur, _c = segs[0]
            if max_duration is not None and end - start > max_duration:
                end = start + float(max_duration)
            lines.append(f"{format_time(start)} {format_time(end)} {build_clip_name(episode_title, 1)}")
            total = end - start
            logger.warning(
                "高光混剪全部段超每文件上限(max_duration=%s)，保底裁剪纳入首段 %s-%s",
                max_duration, format_time(start), format_time(end),
            )
        logger.info(
            "高光混剪 cutlist：候选 %d 段，超长裁剪 %d 段(max_clip_duration=%s)，"
            "输出 %d 个文件共 %d 段，总时长 %.1fs",
            len(accepted), trimmed_long, max_clip_duration, out_idx, len(lines), total,
        )
        return "\n".join(lines)
    # 非混剪路径：可选时长硬规整（duration_hard_limit=true 时由 api/slice.py 传入）
    segs = []
    for clip in accepted:
        start = clip.adjusted_start if clip.adjusted_start is not None else clip.start_time
        end = clip.adjusted_end if clip.adjusted_end is not None else clip.end_time
        if start is None or end is None or end <= start:
            continue
        # 超长裁剪：只裁不丢，段数不变，避免「硬过滤砍成 0 候选」（P1 #228 的安全替代）
        if trim_over_duration is not None and trim_over_duration > 0 and (end - start) > trim_over_duration:
            end = start + float(trim_over_duration)
        segs.append((start, end, clip))
    kept = segs
    # 过短丢弃：若全部段都过短则保留最长一段，保证 cutlist 非空（不出 0 候选）
    if drop_under_duration is not None and drop_under_duration > 0 and segs:
        filtered = [s for s in segs if (s[1] - s[0]) >= drop_under_duration]
        kept = filtered if filtered else [max(segs, key=lambda s: s[1] - s[0])]
    for i, (start, end, _clip) in enumerate(kept):
        name = build_clip_name(episode_title, i + 1)
        lines.append(f"{format_time(start)} {format_time(end)} {name}")
    return "\n".join(lines)


def generate_intervals_file(intervals: List[DetectedInterval]) -> str:
    """Generate intervals content from enabled detected intervals.

    Format per line:
        start_time end_time
    """
    lines = []
    enabled = [i for i in intervals if i.enabled]
    for interval in enabled:
        if interval.start_time is not None and interval.end_time is not None:
            lines.append(f"{format_time(interval.start_time)} {format_time(interval.end_time)}")
    return "\n".join(lines)


def write_temp_file(content: str, suffix: str = ".txt") -> str:
    """Write content to a temporary file and return the path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(content)
        return f.name


def write_temp_json(data: dict, suffix: str = ".json") -> str:
    """Write a dict as JSON to a temporary file and return the path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        json.dump(data, f)
        return f.name


def ensure_dir(path: str) -> str:
    """Ensure a directory exists, creating it if necessary."""
    os.makedirs(path, exist_ok=True)
    return path


def generate_signed_url_headers() -> dict:
    """Generate headers for MinIO presigned URL requests."""
    return {}


def human_readable_size(size_bytes: Optional[int]) -> str:
    """Convert bytes to human-readable string."""
    if size_bytes is None:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}PB"

def utc_iso(dt) -> str:
    """naive UTC datetime → 带时区标记的 ISO 字符串。

    全库时间列均为 timestamp without time zone（应用写入 utcnow()），
    若直接 isoformat() 输出不带时区，前端 dayjs 会按浏览器本地时区解析，
    导致时间少 8 小时。统一补上 +00:00 让前端正确换算本地时间。
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
