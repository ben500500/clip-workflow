"""去水印引擎执行模块。

封装三套开源去水印方案的本地执行：
1. remove-ai-watermarks（RAiW）：`remove-ai-watermarks video all/visible ...` CLI
   - 支持 Sora / Veo / Seedance / Dola / Hailuo / Kling 等可见 AI 水印 + AI 元数据清除
2. seedance 2.0 watermark remover：`engines/seedance_watermark_remover.py`
   - Seedance "AI生成" 角标自动检测 + OpenCV TELEA 修补，无需 GPU
3. seedance_wm（5 阶段流水线）：`engines/seedance_wm_runner.py`
   - 集成自 ben500500/remover 仓库的 seedance_wm 包：抽帧 → 检测（降级链）→ mask
     → 修复（LaMa→cv2）+ 时序平滑 → 合成，支持分段检测与移动水印

所有引擎均通过子进程执行，从 stdout 解析 `PROGRESS:<pct>` 行上报进度
（与切片引擎约定一致），输出视频写回 MinIO 后删除本地临时文件。
"""

import asyncio
import logging
import os
import uuid
from typing import Callable, Optional

from app.config import settings

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], None]]


async def _run_cmd(
    cmd: list[str],
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
) -> tuple[int, str, str]:
    """Run a subprocess, parse PROGRESS: lines, and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    last_progress_at = asyncio.get_event_loop().time()
    last_progress_pct = 0

    async def read_stream(stream, sink):
        nonlocal last_progress_at, last_progress_pct
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
                    pct = min(max(pct, 0), 100)
                    last_progress_at = asyncio.get_event_loop().time()
                    last_progress_pct = pct
                    progress_cb(pct, f"处理中 {pct}%")
                except ValueError:
                    pass

    async def progress_pulse():
        """对于不输出 PROGRESS 的引擎（如 RAiW CLI），周期性推进进度避免长时间卡在低位。"""
        if not progress_cb:
            return
        nonlocal last_progress_at, last_progress_pct
        while True:
            await asyncio.sleep(15)
            if proc.returncode is not None:
                break
            now = asyncio.get_event_loop().time()
            if now - last_progress_at >= 15:
                last_progress_at = now
                last_progress_pct = min(last_progress_pct + 5, 90)
                progress_cb(last_progress_pct, f"处理中 {last_progress_pct}%")

    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(proc.stdout, stdout_lines),
                read_stream(proc.stderr, stderr_lines),
                progress_pulse(),
                proc.wait(),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError(f"Watermark engine timed out after {timeout}s: {' '.join(cmd)}")

    return proc.returncode or 0, "".join(stdout_lines), "".join(stderr_lines)


def _script_path(name: str) -> str:
    """Resolve an engine script path relative to ENGINES_DIR or absolute."""
    path = name
    if not os.path.isabs(path):
        path = os.path.join(settings.ENGINES_DIR, name)
    return os.path.abspath(path)


async def run_remove_ai_watermarks(
    source_path: str,
    output_path: str,
    options: Optional[dict] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
) -> tuple[int, str, str]:
    """调用 remove-ai-watermarks CLI 清理视频可见水印 + AI 元数据。

    options 支持：
    - mark: auto/sora/veo/seedance/dola/hailuo/kling
    - backend: auto/cv2/migan/lama
    - temporal_consistency: True/False
    - region: x,y,w,h（手动区域擦除，通用兜底：可处理非 6 家厂商的任意
      logo/文字水印。RAiW 的 `erase` 命令仅支持单张图片，故这里委托给
      seedance 视频级引擎（其修补层复用 RAiW 的 LaMa/MI-GAN CPU 模型，
      与 `--backend` 语义一致））
    """
    options = options or {}
    cli = settings.WATERMARK_RAIW_CLI or "remove-ai-watermarks"
    if options.get("region"):
        # 通用区域擦除：用户显式指定水印位置，跳过厂商自动检测。
        # 复用 seedance 视频级区域擦除脚本（底层补丁为 RAiW LaMa/MI-GAN）。
        return await run_seedance_watermark_remover(
            source_path, output_path, options, progress_cb, timeout
        )
    cmd = [
        cli,
        "video",
        "all",
        source_path,
        "-o",
        output_path,
        "--mark",
        str(options.get("mark") or "auto"),
        "--backend",
        str(options.get("backend") or "auto"),
    ]
    if options.get("temporal_consistency") is False:
        cmd.append("--no-temporal-consistency")
    logger.info("Running remove-ai-watermarks: %s", " ".join(cmd))
    return await _run_cmd(cmd, progress_cb, timeout)


async def run_seedance_watermark_remover(
    source_path: str,
    output_path: str,
    options: Optional[dict] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
) -> tuple[int, str, str]:
    """调用 Seedance 2.0 Watermark Remover 脚本去水印。

    options 支持：
    - region: "x,y,w,h"（手动指定水印区域，跳过自动检测）
    - backend: auto/lama/migan/cv2（CPU 修补；auto 默认，优先 RAiW LaMa/MI-GAN）
    - use_lama: True 兼容旧前端（等价 backend=lama）
    - segments: int（分段检测段数，默认 4；水印在视频中移动时调大）
    """
    options = options or {}
    script = _script_path(settings.WATERMARK_SEEDANCE_SCRIPT)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"Seedance watermark script not found: {script}")
    cmd = ["python", script, source_path, "-o", output_path]
    if options.get("region"):
        cmd.extend(["-r", str(options["region"])])
    backend = options.get("backend") or "auto"
    if backend not in ("auto", "lama", "migan", "cv2"):
        backend = "auto"
    if options.get("use_lama"):
        backend = "lama"
    cmd.extend(["--backend", backend])
    # 分段检测段数（移动水印分段处理）
    try:
        seg = int(options.get("segments") or 4)
    except (TypeError, ValueError):
        seg = 4
    seg = max(1, min(seg, 32))
    cmd.extend(["--segments", str(seg)])
    logger.info("Running seedance watermark remover: %s", " ".join(cmd))
    return await _run_cmd(cmd, progress_cb, timeout)


async def run_seedance_wm(
    source_path: str,
    output_path: str,
    options: Optional[dict] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
) -> tuple[int, str, str]:
    """调用 seedance_wm（remover 仓库 5 阶段流水线）执行入口去水印。

    options 支持：
    - region: "x,y,w,h"（手动指定水印区域，跳过自动检测）
    - backend: auto/lama/migan/cv2（CPU 修补；auto 默认，lama 缺失时自动降级 cv2）
    - segments: int（分段检测段数，默认 4；水印移动时调大）
    - detector: matchTemplate/yolov8_seg/paddleocr（可选，默认 matchTemplate）
    - inpainter: lama/cv2_telea/cv2_ns（可选，覆盖 config.yaml）
    - keep_audio: bool（默认保留原音轨）
    """
    options = options or {}
    script = _script_path(settings.WATERMARK_SEEDANCE_WM_SCRIPT)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"seedance_wm runner not found: {script}")
    cmd = ["python", script, source_path, "-o", output_path, "--yes"]
    if options.get("region"):
        cmd.extend(["-r", str(options["region"])])
    backend = options.get("backend") or "auto"
    if backend not in ("auto", "lama", "migan", "cv2"):
        backend = "auto"
    cmd.extend(["--backend", backend])
    try:
        seg = int(options.get("segments") or 4)
    except (TypeError, ValueError):
        seg = 4
    seg = max(1, min(seg, 32))
    cmd.extend(["--segments", str(seg)])
    if options.get("detector"):
        cmd.extend(["--detector", str(options["detector"])])
    if options.get("inpainter"):
        cmd.extend(["--inpainter", str(options["inpainter"])])
    if options.get("keep_audio") is False:
        cmd.append("--no-audio")
    logger.info("Running seedance_wm: %s", " ".join(cmd))
    return await _run_cmd(cmd, progress_cb, timeout)


async def run_watermark_engine(
    engine: str,
    source_path: str,
    output_path: str,
    options: Optional[dict] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
) -> tuple[int, str, str]:
    """按 engine 分发到对应的去水印实现。"""
    if engine == "remove_ai":
        return await run_remove_ai_watermarks(
            source_path, output_path, options, progress_cb, timeout
        )
    if engine == "seedance":
        return await run_seedance_watermark_remover(
            source_path, output_path, options, progress_cb, timeout
        )
    if engine == "seedance_wm":
        return await run_seedance_wm(
            source_path, output_path, options, progress_cb, timeout
        )
    raise ValueError(f"Unsupported watermark engine: {engine}")


def temp_video_path(prefix: str = "wm") -> str:
    """Generate a temp file path with a unique name. Caller creates parent dir as needed."""
    return f"/tmp/watermark/{prefix}_{uuid.uuid4().hex}"
