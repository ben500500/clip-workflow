"""去水印引擎执行模块。

封装三套开源去水印方案的本地执行：
1. remove-ai-watermarks（RAiW）：`remove-ai-watermarks video all/visible ...` CLI
   - 支持 Sora / Veo / Seedance / Dola / Hailuo / Kling 等可见 AI 水印 + AI 元数据清除
2. seedance 2.0 watermark remover：`engines/seedance_watermark_remover.py`
   - Seedance "AI生成" 角标自动检测 + OpenCV TELEA 修补，无需 GPU
3. seedance_wm（5 阶段流水线）：`engines/seedance_wm_runner.py`
   - 集成自 ben500500/remover 仓库的 seedance_wm 包：抽帧 → 检测（降级链）→ mask
     → 修复（LaMa→cv2）+ 时序平滑 → 合成，支持分段检测与移动水印
4. remove_mask（ROI + cv2.inpaint TELEA）：`engines/remove_mask_remover.py`
   - 集成自 ben500500/remove-mask 仓库的「去水印经验总结」方案：直接把整个水印
     ROI 矩形当掩码，cv2.INPAINT_TELEA 快速行进法插值填充；按视频文件名匹配
     内置 ROI（覆盖 TL / BR，Seedance 水印规律），支持手动区域，参数保真

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
    """Run a subprocess, parse PROGRESS: lines, and return (returncode, stdout, stderr).

    超时实现：watchdog 协程每 5s 检查一次总耗时，超时直接 kill 子进程。
    不能依赖 asyncio.wait_for(gather(...))——read_stream 阻塞在不可取消的
    pipe readline 上时，gather 的取消会被卡住，TimeoutError 永不抛出，
    子进程会无限挂起（实测 LaMa 模型下载时任务卡 8 小时不退出）。
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    start_ts = asyncio.get_event_loop().time()
    last_progress_at = start_ts
    last_progress_pct = 0
    timed_out = False

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

    async def watchdog():
        """总耗时超时兜底：直接 kill 子进程（不依赖 wait_for 取消语义）。"""
        nonlocal timed_out
        while True:
            await asyncio.sleep(5)
            if proc.returncode is not None:
                return
            if asyncio.get_event_loop().time() - start_ts > timeout:
                timed_out = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                logger.error(
                    "Watermark engine exceeded %ss timeout, killed: %s",
                    timeout,
                    " ".join(cmd),
                )
                return

    try:
        await asyncio.gather(
            read_stream(proc.stdout, stdout_lines),
            read_stream(proc.stderr, stderr_lines),
            progress_pulse(),
            watchdog(),
            proc.wait(),
        )
    finally:
        # 若子进程残留（如内部 fork 的下载进程），确保清掉
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    if timed_out:
        raise TimeoutError(f"Watermark engine timed out after {timeout}s: {' '.join(cmd)}")

    return proc.returncode or 0, "".join(stdout_lines), "".join(stderr_lines)


def _script_path(name: str) -> str:
    """Resolve an engine script path relative to ENGINES_DIR or absolute."""
    path = name
    if not os.path.isabs(path):
        path = os.path.join(settings.ENGINES_DIR, name)
    return os.path.abspath(path)


def _load_roi_experience(source_name: str):
    """加载 remove-mask 内置 ROI 经验库并匹配原始文件名。

    返回命中经验库（dict，如 {'TL': (y0,y1,x0,x1), 'BR': ...}）或 None。
    引擎目录（engines/）不在默认 sys.path 上，这里临时加入以便共享模块可导入。
    """
    import sys

    engines_dir = os.path.abspath(settings.ENGINES_DIR)
    if engines_dir not in sys.path:
        sys.path.insert(0, engines_dir)
    try:
        from remove_mask_rois import match_rois

        return match_rois(source_name)
    except Exception as e:  # noqa: BLE001
        logger.warning("load remove-mask ROI experience failed: %s", e)
        return None


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
    - source_name: 原始文件名（借 remove-mask 内置 ROI 经验库。RAiW 厂商自动
      检测失败时，回退到确认过的 ROI 经验位置重试，避免“没检出就空跑”）
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
    returncode, stdout, stderr = await _run_cmd(cmd, progress_cb, timeout)
    if returncode != 0 and options.get("source_name"):
        # 借 remove-mask 经验库：RAiW 厂商检测失败时，按原始文件名匹配内置 ROI
        # 回退重试（复用 seedance 引擎，其修补层与 RAiW 同一套 LaMa/MI-GAN）。
        if _load_roi_experience(options["source_name"]):
            logger.warning(
                "remove-ai-watermarks failed (exit=%s), retrying with remove-mask ROI experience",
                returncode,
            )
            return await run_seedance_watermark_remover(
                source_path, output_path, options, progress_cb, timeout
            )
    return returncode, stdout, stderr


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
    - source_name: 原始文件名（借 remove-mask 内置 ROI 经验库，自动检测时合并
      左上+右下等确认过的水印位置）
    """
    options = options or {}
    script = _script_path(settings.WATERMARK_SEEDANCE_SCRIPT)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"Seedance watermark script not found: {script}")
    cmd = ["python", script, source_path, "-o", output_path]
    if options.get("region"):
        cmd.extend(["-r", str(options["region"])])
    elif options.get("source_name"):
        # 借 remove-mask 经验库：未指定手动区域时按原始文件名匹配内置 ROI
        cmd.extend(["--roi-experience", str(options["source_name"])])
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


async def run_remove_mask(
    source_path: str,
    output_path: str,
    options: Optional[dict] = None,
    progress_cb: ProgressCallback = None,
    timeout: float = 2 * 3600,
) -> tuple[int, str, str]:
    """调用 remove_mask（ROI + cv2.inpaint TELEA）引擎去水印。

    集成自 ben500500/remove-mask 仓库：直接把整个水印 ROI 矩形当掩码，
    cv2.INPAINT_TELEA 快速行进法插值填充，覆盖 TL / BR（Seedance 水印规律）。

    options 支持：
    - source_name: 原始文件名（用于匹配内置 ROI 表，如 648BC321）
    - region: "x,y,w,h"（手动指定水印区域，覆盖文件名匹配）
    - scope: "small"|"large"（水印 ROI 范围，默认 small：收紧贴合水印文字；large：整角大框）
    - radius: 修补半径（默认 3）
    - iterations: 修补迭代次数（默认 1）
    """
    options = options or {}
    script = _script_path(settings.WATERMARK_REMOVE_MASK_SCRIPT)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"remove_mask script not found: {script}")
    cmd = ["python", script, source_path, "-o", output_path]
    if options.get("region"):
        cmd.extend(["-r", str(options["region"])])
    if options.get("source_name"):
        cmd.extend(["--source-name", str(options["source_name"])])
    scope = options.get("scope") or "small"
    if scope not in ("small", "large"):
        scope = "small"
    cmd.extend(["--scope", scope])
    if options.get("radius"):
        try:
            radius = max(1, min(int(options["radius"]), 20))
            cmd.extend(["--radius", str(radius)])
        except (TypeError, ValueError):
            pass
    if options.get("iterations"):
        try:
            it = max(1, min(int(options["iterations"]), 5))
            cmd.extend(["--iterations", str(it)])
        except (TypeError, ValueError):
            pass
    logger.info("Running remove_mask: %s", " ".join(cmd))
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
    - source_name: 原始文件名（借 remove-mask 内置 ROI 经验库，自动检测时合并
      左上+右下等确认过的水印位置）
    """
    options = options or {}
    script = _script_path(settings.WATERMARK_SEEDANCE_WM_SCRIPT)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"seedance_wm runner not found: {script}")
    cmd = ["python", script, source_path, "-o", output_path, "--yes"]
    if options.get("region"):
        cmd.extend(["-r", str(options["region"])])
    elif options.get("source_name"):
        # 借 remove-mask 经验库：未指定手动区域时按原始文件名匹配内置 ROI
        cmd.extend(["--roi-experience", str(options["source_name"])])
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
    if engine == "remove_mask":
        return await run_remove_mask(
            source_path, output_path, options, progress_cb, timeout
        )
    raise ValueError(f"Unsupported watermark engine: {engine}")


def temp_video_path(prefix: str = "wm") -> str:
    """Generate a temp file path with a unique name. Caller creates parent dir as needed."""
    return f"/tmp/watermark/{prefix}_{uuid.uuid4().hex}"
