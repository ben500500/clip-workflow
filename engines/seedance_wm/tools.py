"""Agent 工具注册层（TRD §4.1 / API §3）。

5 个原子工具，可被 Agno Agent 注册调用：
  extract_frames / detect_watermark / generate_mask_sequence
  inpaint_frames / temporal_smooth / mux_video
"""

from __future__ import annotations

from seedance_wm.ffmpeg_io import extract_frames as _extract_frames
from seedance_wm.ffmpeg_io import mux_video as _mux_video
from seedance_wm.ffmpeg_io import probe_video


def extract_frames(video_path: str, output_dir: str, fps: float | None = None) -> dict:
    """从视频中抽帧并分离音轨。

    Args:
        video_path: 输入视频绝对路径
        output_dir: 输出目录，会自动创建
        fps: 抽帧帧率，None 表示与原视频一致

    Returns:
        dict: {fps, width, height, duration, has_audio, frame_count, frames_dir, audio_path}
    """
    return _extract_frames(video_path, output_dir, fps=fps)


def detect_watermark(
    frames_dir: str,
    primary: str = "matchTemplate",
    fallback: list[str] | None = None,
    bbox: list[int] | None = None,
) -> dict:
    """检测 Seedance 视频水印位置（自动降级链）。

    Returns:
        dict: {x, y, w, h, confidence, method, attempted}
    """
    from seedance_wm.detect import detect_watermark as _detect

    return _detect(frames_dir, primary=primary, fallback=fallback, bbox=bbox)


def generate_mask_sequence(
    bbox: dict, frame_count: int, width: int, height: int, output_dir: str
) -> dict:
    """基于 bbox 生成帧级 mask PNG 序列。"""
    from seedance_wm.mask import generate_mask_sequence as _gen

    return _gen(bbox, frame_count, width, height, output_dir)


def inpaint_frames(
    frames_dir: str,
    masks_dir: str,
    output_dir: str,
    model: str = "lama",
    device: str = "auto",
    fp16: bool = True,
) -> dict:
    """逐帧修复 + 帧间平滑。"""
    from seedance_wm.inpaint import inpaint_frames as _inpaint

    return _inpaint(frames_dir, masks_dir, output_dir, model=model, device=device, fp16=fp16)


def temporal_smooth(frames_dir: str, window: int = 3) -> dict:
    """帧间加权平均，in-place 覆盖。"""
    from seedance_wm.inpaint import temporal_smooth as _smooth

    return _smooth(frames_dir, window=window)


def mux_video(
    frames_dir: str,
    audio_src: str | None,
    output_path: str,
    fps: int = 30,
    crf: int = 18,
) -> dict:
    """FFmpeg 合成最终视频。"""
    return _mux_video(frames_dir, audio_src, output_path, fps=fps, crf=crf)


def video_meta(video_path: str) -> dict:
    """探测视频元信息。"""
    m = probe_video(video_path)
    return {
        "fps": m.fps,
        "width": m.width,
        "height": m.height,
        "duration": m.duration,
        "has_audio": m.has_audio,
        "nb_frames": m.nb_frames,
    }
