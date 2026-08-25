import asyncio
import json
import logging
import os
import signal
from typing import Callable, Optional

from app.config import settings

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], None]]


async def _run_cmd(
    cmd: list[str],
    timeout: float,
    progress_cb: ProgressCallback = None,
    task_id: Optional[str] = None,
) -> tuple[int, str, str]:
    """Run an engine subprocess with timeout and optional PROGRESS: line parsing."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # 独立进程组，便于取消时整树 kill（含 ffmpeg 子进程）
    )
    # 登记当前任务在跑的引擎子进程，供「停止任务」时查杀
    if task_id:
        RUNNING_SLICE_PROCS[task_id] = proc
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
        await _terminate_proc(proc)
        raise TimeoutError(f"Engine timed out after {timeout}s: {' '.join(cmd)}")
    finally:
        if task_id:
            RUNNING_SLICE_PROCS.pop(task_id, None)

    return proc.returncode or 0, "".join(stdout_lines), "".join(stderr_lines)


# ── 本地引擎子进程登记：供「停止任务」取消时查杀（见 api/slice.cancel_slice_task）──
# key: slice_task.id，value: asyncio 子进程对象
RUNNING_SLICE_PROCS: dict = {}


async def _terminate_proc(proc) -> None:
    """向引擎子进程所在进程组发送 SIGTERM（SIGKILL 兜底），确保连带杀掉 ffmpeg 子进程。

    引擎进程用 start_new_session=True 独立成组，killpg 可整树终止（含 python 子进程 ffmpeg）。
    使用 asyncio 原生方式等待退出：asyncio.subprocess.Process 无 poll()（那是 multiprocessing 的 API），
    以 returncode is None 判断存活，并用 asyncio.wait_for(proc.wait(), ...) 实现超时强杀兜底。
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        # 短暂宽限后仍未退出则强杀（避免 ffmpeg 忽略 SIGTERM 拖住）
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.3)
            except asyncio.TimeoutError:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


async def kill_slice_proc(task_id: str) -> bool:
    """终止指定切片任务在本地进程内运行的引擎子进程（含其 ffmpeg 子进程）。

    供「停止任务/取消」接口调用：任务在排队中（未认领）时无进程登记，返回 False 由调用方兜底。
    Returns:
        True=已找到并终止进程；False=无该任务在跑的进程（可能已结束/在 Worker 端）。
    """
    proc = RUNNING_SLICE_PROCS.get(task_id)
    if proc is None:
        return False
    try:
        await _terminate_proc(proc)
    except Exception:
        logger.exception("kill_slice_proc 失败 task=%s", task_id)
    return True


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
    subtitle_spacing: Optional[int] = None,
    subtitle_bold: Optional[int] = None,
    subtitle_style: Optional[str] = None,
    subtitle_color: Optional[str] = None,
    subtitle_border_color: Optional[str] = None,
    text_overlays_config: Optional[list] = None,
    dedupe_config: Optional[dict] = None,
    subtitle_mask_config: Optional[dict] = None,
    watermark_mask_config: Optional[dict] = None,
    subtitle_align_mask: bool = True,
    cover_path: Optional[str] = None,
    output_tier: Optional[str] = None,
    hook_path: Optional[str] = None,
    task_id: Optional[str] = None,
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
    subtitle_spacing: 字幕字间距（ASS Spacing 像素，可选；不传用引擎默认值）。
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
    if subtitle_spacing is not None:
        cmd.extend(["--subtitle-spacing", str(int(subtitle_spacing))])
    if subtitle_bold is not None:
        cmd.extend(["--subtitle-bold", str(int(subtitle_bold))])
    if subtitle_style:
        cmd.extend(["--subtitle-style", subtitle_style])
    if subtitle_color:
        cmd.extend(["--subtitle-color", subtitle_color])
    if subtitle_border_color:
        cmd.extend(["--subtitle-border-color", subtitle_border_color])
    # 字幕对齐源字幕打码区域开关（默认开启）：关闭时显式传 0 覆盖引擎默认开启
    if subtitle_align_mask is False:
        cmd.extend(["--subtitle-align-mask", "0"])
    if text_overlays_config:
        cmd.extend(["--text-overlays", json.dumps(text_overlays_config)])
    if dedupe_config:
        cmd.extend(["--dedupe-config", json.dumps(dedupe_config)])
    if subtitle_mask_config:
        cmd.extend(["--subtitle-mask", json.dumps(subtitle_mask_config)])
    if watermark_mask_config:
        cmd.extend(["--watermark-mask", json.dumps(watermark_mask_config)])
    if cover_path:
        cmd.extend(["--cover", cover_path])
    if hook_path:
        cmd.extend(["--hook", hook_path])
        # 钩子注入所有切片片段：每个候选片段都带 [封面][钩子][本体] 片头（2026-08-25 需求）
        cmd.append("--hook-all")
    if output_tier:
        cmd.extend(["--output-tier", output_tier])
    logger.info("Running slice: %s", " ".join(cmd))

    return await _run_cmd(cmd, timeout, progress_cb, task_id=task_id)


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
    subtitle_spacing: Optional[int] = None,
    subtitle_bold: Optional[int] = None,
    subtitle_style: Optional[str] = None,
    subtitle_color: Optional[str] = None,
    subtitle_border_color: Optional[str] = None,
    text_overlays_config: Optional[list] = None,
    dedupe_config: Optional[dict] = None,
    subtitle_mask_config: Optional[dict] = None,
    watermark_mask_config: Optional[dict] = None,
    subtitle_align_mask: bool = True,
    cover_path: Optional[str] = None,
    output_tier: Optional[str] = None,
    hook_path: Optional[str] = None,
    task_id: Optional[str] = None,
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
        subtitle_spacing=subtitle_spacing,
        subtitle_bold=subtitle_bold,
        subtitle_style=subtitle_style,
        subtitle_color=subtitle_color,
        subtitle_border_color=subtitle_border_color,
        text_overlays_config=text_overlays_config,
        dedupe_config=dedupe_config,
        subtitle_mask_config=subtitle_mask_config,
        watermark_mask_config=watermark_mask_config,
        subtitle_align_mask=subtitle_align_mask,
        cover_path=cover_path,
        output_tier=output_tier,
        hook_path=hook_path,
        task_id=task_id,
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
    subtitle_spacing: Optional[int] = None,
    subtitle_bold: Optional[int] = None,
    subtitle_style: Optional[str] = None,
    subtitle_color: Optional[str] = None,
    subtitle_border_color: Optional[str] = None,
    text_overlays_config: Optional[list] = None,
    dedupe_config: Optional[dict] = None,
    subtitle_mask_config: Optional[dict] = None,
    watermark_mask_config: Optional[dict] = None,
    subtitle_align_mask: bool = True,
    cover_path: Optional[str] = None,
    output_tier: Optional[str] = None,
    hook_path: Optional[str] = None,
    task_id: Optional[str] = None,
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
        subtitle_spacing=subtitle_spacing,
        subtitle_bold=subtitle_bold,
        subtitle_style=subtitle_style,
        subtitle_color=subtitle_color,
        subtitle_border_color=subtitle_border_color,
        text_overlays_config=text_overlays_config,
        dedupe_config=dedupe_config,
        subtitle_mask_config=subtitle_mask_config,
        watermark_mask_config=watermark_mask_config,
        subtitle_align_mask=subtitle_align_mask,
        cover_path=cover_path,
        output_tier=output_tier,
        hook_path=hook_path,
        task_id=task_id,
    )

