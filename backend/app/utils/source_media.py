"""原片素材归一化工具（2026-11-23 用户需求）。

统一到 720P@30（等比降档 + 降帧，音频流拷贝）：
- 资源下载入库时自动应用（assets/misc.py 下载落桶前）
- 剧集详情列表提供手动「降档」操作（projects.py 端点）
省存储/下载带宽，并避免切片档位对 60fps 源二次降帧重编码。
"""
import json
import os
import subprocess

CAP_W = 720
CAP_FPS = 30.0


def probe_media(path: str) -> dict | None:
    """ffprobe 探视频规格：{width,height,fps,duration}；失败返回 None。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
             "-of", "json", path],
            capture_output=True, timeout=30, check=True,
        ).stdout
        meta = json.loads(out)
        st = (meta.get("streams") or [{}])[0]
        num, _, den = (st.get("r_frame_rate") or "30/1").partition("/")
        fps = float(num) / float(den or 1)
        return {
            "width": int(st.get("width") or 0),
            "height": int(st.get("height") or 0),
            "fps": fps,
            "duration": float((meta.get("format") or {}).get("duration") or 0),
        }
    except Exception:
        return None


def needs_normalize(probe: dict | None, cap_w: int = CAP_W, cap_fps: float = CAP_FPS) -> bool:
    """宽>720 或 fps>30 才需要归一化（只降档不升档）。"""
    if not probe:
        return False
    return probe.get("width", 0) > cap_w or probe.get("fps", 0) > cap_fps + 0.01


def normalize_media_file(src: str, dst: str, cap_w: int = CAP_W, cap_fps: float = CAP_FPS,
                         progress_cb=None, total_duration: float = 0.0) -> bool:
    """转码到 ≤720P@30（等比 min(720,iw) 不升档，音频流拷贝）。成功返回 True。

    progress_cb(percent 0-100)：解析 ffmpeg -progress 的 out_time_us 实时回报转码进度。
    """
    # setsar=1：避免降档产出非 1:1 SAR 的源片（会破坏后续流拷贝拼接的同签名判定）
    vf = f"scale='min({cap_w},iw)':-2,setsar=1,fps={cap_fps:g}"
    try:
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-i", src, "-vf", vf,
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "copy", "-movflags", "+faststart",
             "-progress", "pipe:1", "-nostats", dst],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        if progress_cb and total_duration > 0:
            for line in proc.stdout:
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.strip().split("=", 1)[1] or 0)
                        progress_cb(max(0.0, min(99.0, us / 1e6 / total_duration * 100)))
                    except (ValueError, ZeroDivisionError):
                        pass
        proc.wait(timeout=3600)
        return proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


async def normalize_enabled(db) -> bool:
    """读系统开关 source_normalize_enabled（默认 true；读取失败视为开启）。"""
    try:
        from sqlalchemy import select
        from app.models.material import SystemConfig
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == "source_normalize_enabled")
        )).scalar_one_or_none()
        v = row.value if row else True
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        return bool(v)
    except Exception:
        return True
