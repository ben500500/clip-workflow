import os
import json
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


def generate_cutlist(clips: List[ClipCandidate]) -> str:
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
            name = f"clip_{i + 1:02d}"
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