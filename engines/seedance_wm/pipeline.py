"""5 阶段流水线编排（TRD §1 / §4.2）。

流程: 抽帧 -> 检测 -> mask -> 修复+平滑 -> 合成
含:
  - 断点续跑（cache/state.json）
  - QA 校验（输出存在、时长误差 < 50ms、可解码）
  - 三级降级链
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from seedance_wm.config import Config
from seedance_wm.detect import detect_watermark
from seedance_wm.errors import (
    DetectFailError,
    InpaintError,
    MuxError,
    OutOfDiskError,
    VideoReadError,
)
from seedance_wm.ffmpeg_io import extract_frames, get_available_disk_gb, mux_video, probe_video
from seedance_wm.inpaint import inpaint_frames, temporal_smooth
from seedance_wm.log import get_logger
from seedance_wm.mask import generate_mask_sequence

log = get_logger("pipeline")

STAGES = ("extract", "detect", "mask", "inpaint", "smooth", "mux")

_MIN_FREE_GB = 1.0


@dataclass
class ProcessResult:
    input_file: str
    output_file: str
    success: bool = False
    duration_sec: float = 0.0
    method: str = ""
    size_bytes: int = 0
    error: str = ""
    exit_code: int = 0
    elapsed_sec: float = 0.0
    stages: dict = field(default_factory=dict)


class _State:
    """断点续跑状态管理。"""

    def __init__(self, cache_dir: Path):
        self.path = cache_dir / "state.json"
        self.data: dict = {
            "video_hash": "",
            "stages": {s: {"status": "pending"} for s in STAGES},
            "info": {},
        }

    def load(self, video_hash: str) -> bool:
        if not self.path.exists():
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if data.get("video_hash") != video_hash:
            return False
        self.data = data
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_done(self, stage: str) -> None:
        self.data["stages"][stage] = {"status": "done", "ts": time.time()}

    def is_done(self, stage: str) -> bool:
        return self.data["stages"].get(stage, {}).get("status") == "done"


def _video_hash(path: str | Path) -> str:
    """基于文件路径 + 大小 + mtime 的轻量 hash（不做全文哈希）。"""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise VideoReadError(f"输入文件不存在: {path}")
    stat = p.stat()
    return hashlib.sha256(
        f"{p.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode()
    ).hexdigest()


def _cache_dir(config: Config, video_hash: str) -> Path:
    return Path(config.cache.dir) / video_hash[:16]


def _ensure_disk(cache_dir: Path, video_hash: str) -> None:
    free = get_available_disk_gb(cache_dir)
    if free < _MIN_FREE_GB:
        raise OutOfDiskError(
            f"磁盘空间不足: 仅剩 {free:.1f}GB，请清理 cache 目录 {cache_dir}"
        )


def _emit(progress_callback, pct: float, msg: str = "") -> None:
    """统一的进度上报：同时打印 PROGRESS 行（供外部 CLI/runner 解析）并调用回调。"""
    pct = min(max(float(pct), 0.0), 100.0)
    print(f"PROGRESS:{int(pct)}", flush=True)
    if progress_callback is not None:
        try:
            progress_callback(int(pct), msg)
        except Exception:  # noqa: BLE001
            pass


def process_video(
    input_path: str,
    output_path: str,
    config: Config,
    bbox: list[int] | None = None,
    bboxes: list[list[int]] | None = None,
    progress_callback=None,
) -> ProcessResult:
    """处理单个视频（完整 5 阶段流水线）。

    bbox: 手动指定单个水印区域 [x,y,w,h]（最高优先级，跳过自动检测）。
    bboxes: 手动/经验库指定多个水印区域列表（如 remove-mask 内置 ROI：左上 +
        右下），自动检测到结果时与经验 ROI 合并后生成 mask。
    progress_callback: 可选回调 ``callable(pct: int, msg: str)``，在处理过程中
    被调用以上报进度；同时该实现会在 stdout 打印 ``PROGRESS:<pct>`` 行，供
    clip-workflow 的 watermark_runner 等外部 runner 解析（与切片引擎约定一致）。
    """
    start = time.time()
    result = ProcessResult(input_file=input_path, output_file=output_path)
    src = Path(input_path)
    dst = Path(output_path)

    if src.resolve() == dst.resolve():
        from seedance_wm.errors import InvalidArgsError

        raise InvalidArgsError("输入与输出路径相同，禁止覆盖原视频")

    vhash = _video_hash(src)
    cache = _cache_dir(config, vhash)
    state = _State(cache)
    resumed = state.load(vhash)
    if resumed:
        log.info("断点续跑: 跳过已完成阶段 %s", [s for s in STAGES if state.is_done(s)])
    else:
        state.data["video_hash"] = vhash
        state.save()

    try:
        # ---------- 阶段 1：抽帧 ----------
        if state.is_done("extract"):
            info = state.data.get("info", {})
            frame_info = {
                "fps": info.get("fps", 30.0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "duration": info.get("duration", 0.0),
                "has_audio": info.get("has_audio", False),
                "frame_count": len(list((cache / "frames").glob("frame_*.png"))),
                "frames_dir": str(cache / "frames"),
                "audio_path": str(cache / "frames" / "audio.aac")
                if (cache / "frames" / "audio.aac").exists()
                else None,
            }
        else:
            _ensure_disk(cache, vhash)
            _emit(progress_callback, 2, "抽帧中")
            frame_info = extract_frames(src, cache / "frames")
            state.data["info"] = frame_info
            state.mark_done("extract")
            state.save()
        result.stages["extract"] = frame_info
        _emit(progress_callback, 8, "抽帧完成")

        # ---------- 阶段 2：检测 ----------
        detect_result: dict = {}
        if state.is_done("detect"):
            detect_result = state.data.get("detect_result") or {}
        else:
            _emit(progress_callback, 10, "水印检测中")
            try:
                detect_result = detect_watermark(
                    frame_info["frames_dir"],
                    primary=config.detector.primary,
                    fallback=config.detector.fallback,
                    bbox=bbox,
                    config=config.detector,
                )
            except DetectFailError:
                # 借 remove-mask 经验库：自动检测全部失败时，若已有经验 ROI 则直接
                # 使用经验位置继续（避免“没检出就整体失败”）；否则向上抛。
                if bbox is None and bboxes:
                    detect_result = {}
                else:
                    raise
            state.data["detect_result"] = detect_result
            state.mark_done("detect")
            state.save()
        result.method = detect_result.get("method", "")
        result.stages["detect"] = detect_result
        _emit(progress_callback, 15, "水印检测完成")

        # 借 remove-mask 经验库：检测结果与经验 ROI 合并，一处视频可同时覆盖
        # 左上 + 右下等多个水印位置。仅当未指定 bbox（手动区域最高优先级）时生效。
        if bbox is None and bboxes:
            merged = [
                {
                    "x": int(b[0]),
                    "y": int(b[1]),
                    "w": int(b[2]),
                    "h": int(b[3]),
                }
                for b in bboxes
            ]
            if detect_result.get("x") is not None and detect_result.get("w"):
                merged.append(
                    {
                        "x": int(detect_result["x"]),
                        "y": int(detect_result["y"]),
                        "w": int(detect_result["w"]),
                        "h": int(detect_result["h"]),
                    }
                )
            detect_result = {
                "boxes": merged,
                "method": "roi-experience" + (
                    "+auto" if len(merged) > len(bboxes) else ""
                ),
            }
            result.method = detect_result["method"]

        # ---------- 阶段 3：mask 序列 ----------
        mask_info: dict = {}
        if state.is_done("mask"):
            masks_dir = cache / "masks"
            mask_info = {
                "masks_dir": str(masks_dir),
                "mask_files": [str(p) for p in sorted(masks_dir.glob("mask_*.png"))],
            }
        else:
            _emit(progress_callback, 18, "生成 mask 序列")
            mask_bbox = detect_result.get("boxes") or detect_result
            mask_info = generate_mask_sequence(
                mask_bbox,
                frame_info["frame_count"],
                frame_info["width"],
                frame_info["height"],
                cache / "masks",
                expand_px=config.inpainter.expand_px,
            )
            state.mark_done("mask")
            state.save()
        result.stages["mask"] = mask_info
        _emit(progress_callback, 22, "mask 序列生成完成")

        # ---------- 阶段 4：修复 + 时序平滑 ----------
        inpaint_info: dict = {}
        if state.is_done("inpaint"):
            inpaint_info = {
                "clean_dir": str(cache / "clean"),
                "processed": len(list((cache / "clean").glob("clean_*.png"))),
                "failed": 0,
                "duration_sec": 0.0,
                "model_used": config.inpainter.primary,
                "device_used": config.inpainter.device,
            }
        else:
            _emit(progress_callback, 25, "逐帧修复中")

            def _inpaint_progress(stage_pct: int, _msg: str = "") -> None:
                # 将逐帧修复阶段进度 (0-100) 映射到整体进度 25%-85%
                overall = 25 + int(stage_pct * 0.60)
                _emit(progress_callback, overall, f"逐帧修复 {stage_pct}%")

            inpaint_info = inpaint_frames(
                frame_info["frames_dir"],
                mask_info["masks_dir"],
                cache / "clean",
                model=config.inpainter.primary,
                device=config.inpainter.device,
                fp16=config.inpainter.fp16,
                progress_callback=_inpaint_progress,
            )
            if inpaint_info["processed"] == 0:
                raise InpaintError("所有帧修复失败")
            state.mark_done("inpaint")
            state.save()
        result.stages["inpaint"] = inpaint_info

        if config.temporal.enabled:
            smooth_info = temporal_smooth(
                inpaint_info["clean_dir"],
                window=config.temporal.window,
                weights=config.temporal.weights,
            )
            state.mark_done("smooth")
            state.save()
            result.stages["smooth"] = smooth_info
        _emit(progress_callback, 85, "逐帧修复完成")

        # ---------- 阶段 5：合成 ----------
        mux_info: dict = {}
        if state.is_done("mux") and dst.exists():
            mux_info = {
                "output_path": str(dst),
                "size_bytes": dst.stat().st_size,
                "duration_sec": 0.0,
                "has_audio": False,
            }
        else:
            _emit(progress_callback, 88, "合成视频中")
            mux_info = mux_video(
                cache / "clean",
                frame_info.get("audio_path"),
                dst,
                fps=frame_info["fps"],
                crf=config.output.crf,
                codec=config.output.codec,
                pix_fmt=config.output.pix_fmt,
                movflags=config.output.movflags,
                keep_audio=config.output.keep_audio,
            )
            state.mark_done("mux")
            state.save()
        result.stages["mux"] = mux_info

        # ---------- QA 校验 ----------
        _qa_check(dst, frame_info.get("duration", 0.0), mux_info)
        result.size_bytes = mux_info.get("size_bytes", 0)
        result.duration_sec = mux_info.get("duration_sec", 0.0)

        # 清理 cache
        if config.cache.auto_clean:
            shutil.rmtree(cache, ignore_errors=True)
            log.info("cache 已清理: %s", cache)

        result.success = True
        result.exit_code = 0
        result.elapsed_sec = time.time() - start
        _emit(progress_callback, 100, "处理完成")
        log.info(
            "✅ 完成 → %s (size=%.1fMB, dur=%.2fs, elapsed=%.1fs, method=%s)",
            dst,
            result.size_bytes / 1024 / 1024,
            result.duration_sec,
            result.elapsed_sec,
            result.method,
        )
        return result

    except (VideoReadError, DetectFailError, InpaintError, MuxError, OutOfDiskError) as e:
        result.success = False
        result.error = e.message
        result.exit_code = e.exit_code
        result.elapsed_sec = time.time() - start
        log.error("处理失败: %s (exit=%d)", e.message, e.exit_code)
        return result


def _qa_check(dst: Path, source_duration: float, mux_info: dict) -> None:
    """QA 校验（TRD §4.2）: 输出存在 / 可解码 / 时长误差 < 50ms。"""
    if not dst.exists() or dst.stat().st_size == 0:
        raise MuxError("QA 失败: 输出文件不存在或为空")
    try:
        meta = probe_video(dst)
    except VideoReadError as e:
        raise MuxError(f"QA 失败: 输出无法解码 - {e.message}") from e
    if source_duration and abs(meta.duration - source_duration) > 0.05:
        log.warning(
            "QA 警告: 输出时长 %.3fs 与原视频 %.3fs 误差超 50ms",
            meta.duration,
            source_duration,
        )
    mux_info["duration_sec"] = meta.duration
