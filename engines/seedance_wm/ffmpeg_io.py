"""FFmpeg I/O 层（阶段 1 抽帧 + 阶段 5 合成）。

使用 ffmpeg-python 绑定，封装:
  - ffmpeg 可用性探测
  - 视频探测 (probe)
  - 抽帧 + 抽音轨
  - 帧序列 + 音轨合成最终视频
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import ffmpeg

from seedance_wm.errors import (
    FfmpegMissingError,
    MuxError,
    VideoReadError,
)
from seedance_wm.log import get_logger

log = get_logger("ffmpeg_io")

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v"}


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise FfmpegMissingError(
            "FFmpeg 未安装，请先安装：Linux `sudo apt install ffmpeg` / macOS `brew install ffmpeg`"
        )


def _parse_rational(value: str) -> float:
    try:
        if "/" in value:
            num, den_str = value.split("/")
            den = float(den_str) or 1.0
            return float(num) / den
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


@dataclass
class VideoMeta:
    fps: float
    width: int
    height: int
    duration: float
    has_audio: bool
    nb_frames: int = 0


def probe_video(video_path: str | Path) -> VideoMeta:
    """探测视频元信息，失败抛 VideoReadError。"""
    path = Path(video_path)
    if not path.exists():
        raise VideoReadError(f"输入文件不存在: {path}")
    if path.stat().st_size == 0:
        raise VideoReadError(f"输入文件为空: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise VideoReadError(
            f"不支持的格式: {path.suffix}（支持: {', '.join(sorted(SUPPORTED_EXTENSIONS))}）"
        )

    try:
        info = ffmpeg.probe(str(path))
    except ffmpeg.Error as e:
        raise VideoReadError(f"FFmpeg 无法解码视频: {path} ({e.stderr.decode(errors='ignore')[:300]})") from e
    except FileNotFoundError:
        raise FfmpegMissingError("FFmpeg 未安装，请先安装 ffmpeg") from None

    video_stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video_stream is None:
        raise VideoReadError(f"视频中无视频流: {path}")
    audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]

    fps = _parse_rational(video_stream.get("avg_frame_rate", video_stream.get("r_frame_rate", "0/1")))
    if fps <= 0:
        fps = _parse_rational(video_stream.get("r_frame_rate", "0/1"))

    return VideoMeta(
        fps=fps,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        duration=float(info.get("format", {}).get("duration", 0) or 0),
        has_audio=bool(audio_streams),
        nb_frames=int(video_stream.get("nb_frames", 0) or 0),
    )


def extract_frames(
    video_path: str | Path,
    output_dir: str | Path,
    fps: float | None = None,
    threads: int = 0,
) -> dict:
    """抽帧为 PNG 序列并分离音轨。

    Returns:
        dict: {fps, width, height, duration, has_audio, frame_count, frames_dir, audio_path}
    """
    check_ffmpeg()
    src = Path(video_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    meta = probe_video(src)
    target_fps = fps or meta.fps or 30.0

    log.info("extract_frames Started: %s", src)
    try:
        stream = ffmpeg.input(str(src))
        stream = stream.output(
            str(out / "frame_%06d.png"),
            vf=f"fps={target_fps:.6f}",
            qscale=2,
            threads=threads,
        )
        stream.run(quiet=True, overwrite_output=True)
    except ffmpeg.Error as e:
        raise VideoReadError(f"抽帧失败: {src} ({e.stderr.decode(errors='ignore')[:300]})") from e
    except FileNotFoundError:
        raise FfmpegMissingError("FFmpeg 未安装，请先安装 ffmpeg") from None

    frame_files = sorted(out.glob("frame_*.png"))
    frame_count = len(frame_files)

    audio_path = None
    if meta.has_audio:
        try:
            ffmpeg.input(str(src)).output(
                str(out / "audio.aac"), acodec="copy"
            ).run(quiet=True, overwrite_output=True)
            audio_path = str(out / "audio.aac")
        except ffmpeg.Error as e:
            log.warning("抽音轨失败（将跳过音频）: %s", e.stderr.decode(errors="ignore")[:200])
            audio_path = None

    log.info(
        "extract_frames Done: %d frames @ %.3ffps, has_audio=%s",
        frame_count,
        target_fps,
        meta.has_audio,
    )
    return {
        "fps": float(target_fps),
        "width": meta.width,
        "height": meta.height,
        "duration": meta.duration,
        "has_audio": meta.has_audio,
        "frame_count": frame_count,
        "frames_dir": str(out),
        "audio_path": audio_path,
    }


def mux_video(
    frames_dir: str | Path,
    audio_src: str | Path | None,
    output_path: str | Path,
    fps: int | float = 30,
    crf: int = 18,
    codec: str = "libx264",
    pix_fmt: str = "yuv420p",
    movflags: str = "+faststart",
    keep_audio: bool = True,
) -> dict:
    """帧序列 + 原音轨合成最终视频。"""
    check_ffmpeg()
    frames = Path(frames_dir)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    pattern = str(frames / "clean_%06d.png")
    if not list(frames.glob("clean_*.png")):
        pattern = str(frames / "frame_%06d.png")

    stream = ffmpeg.input(pattern, framerate=fps)

    use_audio = keep_audio and audio_src and Path(audio_src).exists()
    try:
        if use_audio:
            audio = ffmpeg.input(str(audio_src))
            stream = ffmpeg.output(
                stream,
                audio,
                str(out),
                vcodec=codec,
                pix_fmt=pix_fmt,
                crf=crf,
                acodec="aac",
                movflags=movflags,
            )
        else:
            stream = ffmpeg.output(
                stream,
                str(out),
                vcodec=codec,
                pix_fmt=pix_fmt,
                crf=crf,
                movflags=movflags,
            )
        stream.run(overwrite_output=True, quiet=True)
    except ffmpeg.Error as e:
        raise MuxError(f"视频合成失败: {e.stderr.decode(errors='ignore')[:300]}") from e
    except FileNotFoundError:
        raise FfmpegMissingError("FFmpeg 未安装，请先安装 ffmpeg") from None

    result = {
        "output_path": str(out),
        "size_bytes": out.stat().st_size if out.exists() else 0,
        "duration_sec": float(fps) and 0.0,
        "has_audio": use_audio,
    }
    try:
        m = probe_video(out)
        result["duration_sec"] = m.duration
    except VideoReadError:
        pass
    log.info("mux_video Done: %s (size=%d bytes)", out, result["size_bytes"])
    return result


def get_available_disk_gb(path: str | Path) -> float:
    """获取目录所在磁盘可用空间（GB）。"""
    st = os.statvfs(str(Path(path).resolve().parent if Path(path).exists() else Path(path)))
    return (st.f_bavail * st.f_frsize) / (1024**3)


def run_cmd(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)
