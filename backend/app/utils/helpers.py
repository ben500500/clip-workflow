import os
import json
import re
from datetime import datetime, timedelta, timezone
import tempfile
from typing import List, Optional

from app.models.models import ClipCandidate, DetectedInterval


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


def generate_cutlist(clips: List[ClipCandidate], episode_title: Optional[str] = None) -> str:
    """Generate cutlist content from accepted clip candidates.

    Format per line:
        start_time end_time clip_name
    """
    lines = []
    accepted = [c for c in clips if c.status == "accepted"]
    for i, clip in enumerate(accepted):
        start = clip.adjusted_start if clip.adjusted_start is not None else clip.start_time
        end = clip.adjusted_end if clip.adjusted_end is not None else clip.end_time
        if start is not None and end is not None:
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
