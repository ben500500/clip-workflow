import asyncio
import json
import logging
import os
from typing import Callable, Optional

from app.config import settings

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], None]]


async def _run_cmd(
    cmd: list[str],
    timeout: float,
    progress_cb: ProgressCallback = None,
) -> tuple[int, str, str]:
    """Run an engine subprocess with timeout and optional PROGRESS: line parsing."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def read_stream(stream, sink):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace")
            sink.append(text)
            stripped = text.strip()
            if progress_cb and stripped.startswith("PROGRESS:"):
                try:
                    pct = int(stripped.split(":", 1)[1])
                    progress_cb(min(max(pct, 0), 100), f"Slicing {pct}%")
                except ValueError:
                    pass

    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(proc.stdout, stdout_lines),
                read_stream(proc.stderr, stderr_lines),
                proc.wait(),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.terminate()  # SIGTERM
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()  # SIGKILL as fallback
        except ProcessLookupError:
            pass
        raise TimeoutError(f"Engine timed out after {timeout}s: {' '.join(cmd)}")

    return proc.returncode or 0, "".join(stdout_lines), "".join(stderr_lines)


def _engine_path(name: str) -> str:
    return os.path.join(settings.ENGINES_DIR, name)


def _require_engine(engine_path: str) -> None:
    if not os.path.isfile(engine_path):
        raise FileNotFoundError(
            f"Video engine not found: {engine_path}. "
            "请确认 engines/ 目录已挂载或包含在镜像中。"
        )


async def run_slice(
    source_path: str,
    cutlist_path: str,
    output_dir: str,
    mode: str,
    intervals_path: Optional[str] = None,
    engine_path: Optional[str] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
    watermark_config: Optional[dict] = None,
    encoder: Optional[str] = None,
    vert2horiz_config: Optional[dict] = None,
    badges_config: Optional[list] = None,
    badge_default_width: int = 0,
    subtitle_srt_path: Optional[str] = None,
    subtitle_font_ratio: Optional[float] = None,
) -> tuple[int, str, str]:
    """Run the ffmpeg slice engine.

    Returns (return_code, stdout, stderr). Stdout contains OUTPUT:<name>:<duration>
    manifest lines and PROGRESS:<pct> lines.

    encoder: 三期 GPU 加速编码。可选 h264_nvenc/hevc_nvenc/\
        h264_videotoolbox/hevc_videotoolbox/libx264；不传则引擎自动探测。
    vert2horiz_config: 竖屏转横屏预处理配置（切片前把竖屏素材转成横屏）。
    badges_config: 图片角标配置（切片后在成品上叠加角标）。
    badge_default_width: 角标默认宽度（px，0=保持原图尺寸；角标未单独设 width 时生效）。
    subtitle_srt_path: 源视频 SRT 字幕文件路径（切片时烧录到成品，可选）。
    subtitle_font_ratio: 字幕字号（相对输出视频高度的比例，可选；不传用引擎默认值）。
    """
    engine_path = engine_path or _engine_path("slice.py")
    _require_engine(engine_path)

    cmd = ["python", engine_path, source_path, cutlist_path, output_dir, "--mode", mode]
    if intervals_path:
        cmd.extend(["--intervals", intervals_path])
    if watermark_config:
        cmd.extend(["--watermark", json.dumps(watermark_config)])
    if encoder:
        cmd.extend(["--encoder", encoder])
    if vert2horiz_config:
        cmd.extend(["--vert2horiz", json.dumps(vert2horiz_config)])
    if badges_config:
        cmd.extend(["--badges", json.dumps(badges_config)])
    if badge_default_width:
        cmd.extend(["--badge-default-width", str(int(badge_default_width))])
    if subtitle_srt_path:
        cmd.extend(["--subtitle", subtitle_srt_path])
    if subtitle_font_ratio and subtitle_font_ratio > 0:
        cmd.extend(["--subtitle-font-ratio", str(float(subtitle_font_ratio))])
    logger.info("Running slice: %s", " ".join(cmd))

    return await _run_cmd(cmd, timeout, progress_cb)


async def run_slice_scrub(
    source_path: str,
    cutlist_path: str,
    intervals_path: str,
    output_dir: str,
    engine_path: Optional[str] = None,
    progress_cb: ProgressCallback = None,
    watermark_config: Optional[dict] = None,
    encoder: Optional[str] = None,
    vert2horiz_config: Optional[dict] = None,
    badges_config: Optional[list] = None,
    badge_default_width: int = 0,
    subtitle_srt_path: Optional[str] = None,
    subtitle_font_ratio: Optional[float] = None,
) -> tuple[int, str, str]:
    """Run scrub-mode slicing (cutlist minus removed intervals)."""
    return await run_slice(
        source_path,
        cutlist_path,
        output_dir,
        "scrub",
        intervals_path=intervals_path,
        engine_path=engine_path,
        progress_cb=progress_cb,
        watermark_config=watermark_config,
        encoder=encoder,
        vert2horiz_config=vert2horiz_config,
        badges_config=badges_config,
        badge_default_width=badge_default_width,
        subtitle_srt_path=subtitle_srt_path,
        subtitle_font_ratio=subtitle_font_ratio,
    )


async def run_slice_fast(
    source_path: str,
    cutlist_path: str,
    output_dir: str,
    mode: str = "fast",
    engine_path: Optional[str] = None,
    progress_cb: ProgressCallback = None,
    watermark_config: Optional[dict] = None,
    encoder: Optional[str] = None,
    vert2horiz_config: Optional[dict] = None,
    badges_config: Optional[list] = None,
    badge_default_width: int = 0,
    subtitle_srt_path: Optional[str] = None,
    subtitle_font_ratio: Optional[float] = None,
) -> tuple[int, str, str]:
    """Run fast/dedupe mode slicing."""
    if mode not in ("fast", "dedupe"):
        raise ValueError(f"Unsupported slice mode: {mode}")
    return await run_slice(
        source_path,
        cutlist_path,
        output_dir,
        mode,
        intervals_path=None,
        engine_path=engine_path,
        progress_cb=progress_cb,
        watermark_config=watermark_config,
        encoder=encoder,
        vert2horiz_config=vert2horiz_config,
        badges_config=badges_config,
        badge_default_width=badge_default_width,
        subtitle_srt_path=subtitle_srt_path,
        subtitle_font_ratio=subtitle_font_ratio,
    )


async def run_preview(
    source_path: str,
    output_dir: str,
    engine_path: Optional[str] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 600,
) -> tuple[int, str, str]:
    """Run preview frame extraction."""
    engine_path = engine_path or _engine_path("preview.py")
    _require_engine(engine_path)

    cmd = ["python", engine_path, source_path, output_dir]
    logger.info("Running preview: %s", " ".join(cmd))

    return await _run_cmd(cmd, timeout, progress_cb)
