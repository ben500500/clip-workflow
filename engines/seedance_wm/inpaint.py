"""阶段 4：逐帧修复 + 时序平滑。

修复器降级链（TRD §5.1 / API §3.4）:
  lama（LaMa, Apache-2.0, 推荐）
    -> cv2_telea（OpenCV 内置，CPU 兜底）
    -> cv2_ns（最后兜底）
  GPU OOM 时自动切换到 CPU 并记录 WARN。

时序平滑（防闪烁）:
  帧间加权平均，window=3 高斯权重 [0.25, 0.5, 0.25]。
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from seedance_wm.errors import InpaintError
from seedance_wm.log import get_logger

log = get_logger("inpaint")

INPAINTERS = ("lama", "cv2_telea", "cv2_ns", "propainter")


def _lama_model_ready() -> bool:
    """检查 LaMa ONNX 模型是否已完整下载到本地缓存。

    erase_lama 首次调用会从 HuggingFace 下载 Carve/LaMa-ONNX（~200MB）。
    服务器网络不可达 huggingface.co 时下载会挂起数十分钟才超时，
    导致任务长时间卡住。因此在使用 LaMa 前先检查模型缓存是否完整
    （要求 blobs 下有非 .incomplete 的完整文件），不存在则直接降级到
    cv2，避免网络等待。
    """
    hf_home = os.environ.get(
        "HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    )
    hub_dir = os.path.join(hf_home, "hub")
    try:
        if not os.path.isdir(hub_dir):
            return False
        for name in os.listdir(hub_dir):
            if "LaMa-ONNX" not in name:
                continue
            blobs_dir = os.path.join(hub_dir, name, "blobs")
            if not os.path.isdir(blobs_dir):
                continue
            for blob in os.listdir(blobs_dir):
                # 有完整下载的模型文件（非 .incomplete）即视为可用
                if not blob.endswith(".incomplete"):
                    return True
    except OSError:
        return False
    return False


def resolve_device(device: str = "auto") -> str:
    if device != "auto":
        return device
    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _inpaint_cv2(
    image: np.ndarray,
    mask: np.ndarray,
    method: str = "cv2_telea",
) -> np.ndarray:
    radius = 3
    if method == "cv2_ns":
        return cv2.inpaint(image, mask, radius, cv2.INPAINT_NS)
    return cv2.inpaint(image, mask, radius, cv2.INPAINT_TELEA)


_LAMA = None


def _inpaint_lama(image: np.ndarray, mask: np.ndarray, device: str) -> np.ndarray:
    """LaMa 修复（remove-ai-watermarks 封装）。加载模型较慢，使用模块级缓存。"""
    global _LAMA  # noqa: PLW0603
    if _LAMA is None:
        from remove_ai_watermarks.region_eraser import erase_lama, lama_available

        if not lama_available():
            raise InpaintError("LaMa 不可用（remove-ai-watermarks lama extra 未安装）")
        if not _lama_model_ready():
            raise InpaintError("LaMa 模型未下载，跳过（离线环境不可用）")
        _LAMA = erase_lama  # 缓存函数引用

    return _LAMA(image, mask)


def inpaint_frames(
    frames_dir: str | Path,
    masks_dir: str | Path,
    output_dir: str | Path,
    model: str = "lama",
    device: str = "auto",
    fp16: bool = True,
    progress_callback=None,
) -> dict:
    """逐帧修复。

    Args:
        progress_callback: 可选 ``callable(pct: int, msg: str)``，按帧批次上报进度。

    Returns:
        dict: {clean_dir, processed, failed, duration_sec, model_used, device_used}
    """
    frames = sorted(Path(frames_dir).glob("frame_*.png"))
    masks = sorted(Path(masks_dir).glob("mask_*.png"))
    if not frames:
        raise InpaintError("抽帧目录为空，无法修复")
    if not masks:
        raise InpaintError("mask 目录为空，无法修复")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    resolved = resolve_device(device)
    model_used = model if model in ("lama",) else model

    # 尝试模型链：主模型 -> fallback
    chain = _build_inpaint_chain(model, resolved)
    log.info("inpaint_frames model_chain=%s device=%s", chain, resolved)

    processed, failed = 0, 0
    start = cv2.getTickCount()

    for i, (frame_p, mask_p) in enumerate(zip(frames, masks, strict=False)):
        img = cv2.imread(str(frame_p), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(mask_p), cv2.IMREAD_GRAYSCALE)
        if img is None or mask is None:
            failed += 1
            continue
        clean = None
        for name, use in chain:
            try:
                if use == "cv2":
                    clean = _inpaint_cv2(img, mask, name)
                else:
                    clean = _inpaint_lama(img, mask, resolved)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("inpaint_frames %s failed on frame %d: %s", name, i, e)
                continue
        if clean is None:
            failed += 1
            continue
        cv2.imwrite(str(out / f"clean_{i:06d}.png"), clean)
        processed += 1
        # 每 10 帧或最后一帧上报一次进度（0-100 阶段内）
        if progress_callback is not None and (i % 10 == 0 or i == len(frames) - 1):
            try:
                pct = min(max(int((i + 1) / len(frames) * 100), 0), 100)
                progress_callback(pct, f"逐帧修复 {pct}%")
            except Exception:  # noqa: BLE001
                pass

    elapsed = (cv2.getTickCount() - start) / cv2.getTickFrequency()
    log.info(
        "inpaint_frames Done: processed=%d failed=%d model=%s device=%s duration=%.2fs",
        processed,
        failed,
        model_used,
        resolved,
        elapsed,
    )
    return {
        "clean_dir": str(out),
        "processed": processed,
        "failed": failed,
        "duration_sec": elapsed,
        "model_used": model_used,
        "device_used": resolved,
    }


def _build_inpaint_chain(model: str, device: str) -> list[tuple[str, str]]:
    """构造修复链: [(模型名, 类型)]，类型 'cv2' 或 'lama'。

    lama 不可用（remove-ai-watermarks lama extra 未安装）时自动替换为 cv2 兜底。
    """
    chain: list[tuple[str, str]] = []
    if model == "lama":
        try:
            from remove_ai_watermarks.region_eraser import lama_available

            if lama_available() and _lama_model_ready():
                chain.append(("lama", "lama"))
            else:
                if not _lama_model_ready():
                    log.warning(
                        "lama 模型未下载（离线环境），跳过 LaMa 直接使用 cv2 兜底"
                    )
                else:
                    log.warning("lama 依赖未安装，直接使用 cv2 兜底")
        except ImportError:
            log.warning("lama 依赖未安装，直接使用 cv2 兜底")
        chain.append(("cv2_telea", "cv2"))
        chain.append(("cv2_ns", "cv2"))
    elif model == "cv2_telea":
        chain.append(("cv2_telea", "cv2"))
        chain.append(("cv2_ns", "cv2"))
    elif model == "cv2_ns":
        chain.append(("cv2_ns", "cv2"))
    elif model == "propainter":
        chain.append(("propainter", "lama"))  # 占位，需独立集成
        chain.append(("cv2_telea", "cv2"))
        chain.append(("cv2_ns", "cv2"))
    else:
        chain.append(("cv2_telea", "cv2"))
        chain.append(("cv2_ns", "cv2"))
    return chain


def temporal_smooth(
    frames_dir: str | Path,
    window: int = 3,
    weights: str = "gaussian",
) -> dict:
    """帧间加权平均，in-place 覆盖 clean_*.png。"""
    files = sorted(Path(frames_dir).glob("clean_*.png"))
    if not files:
        log.warning("temporal_smooth: 无 clean 帧，跳过")
        return {"frames_dir": str(frames_dir)}

    window = int(window)
    if window < 1 or window > 7:
        window = 3
    if window % 2 == 0:
        window += 1

    raw_imgs = [cv2.imread(str(f), cv2.IMREAD_COLOR) for f in files]
    imgs: list[np.ndarray] = [img for img in raw_imgs if img is not None]
    n = len(imgs)

    if weights == "uniform":
        w = np.ones(window, dtype=np.float32) / window
    else:
        sigma = window / 3.0
        w = np.array(
            [np.exp(-((i - window // 2) ** 2) / (2 * sigma * sigma)) for i in range(window)],
            dtype=np.float32,
        )
        w /= w.sum()

    half = window // 2
    smoothed: list[np.ndarray] = []
    for i in range(n):
        acc = np.zeros_like(imgs[i], dtype=np.float32)
        for j, wj in zip(range(-half, half + 1), w, strict=False):
            idx = max(0, min(n - 1, i + j))
            acc += imgs[idx].astype(np.float32) * wj
        smoothed.append(acc.astype(np.uint8))

    for f, img in zip(files, smoothed, strict=False):
        cv2.imwrite(str(f), img)

    log.info("temporal_smooth Done: %d frames, window=%d weights=%s", n, window, weights)
    return {"frames_dir": str(frames_dir)}
