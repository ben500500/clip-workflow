"""Remotion 高光混剪增强渲染器（后端编排层）。

职责：把一条切片的「高光混剪增强」请求（remotion_mix_config + cutlist 高光段时间轴）
编排成 Remotion 容器可消费的渲染任务：
  1. 从 cutlist 解析各高光段的时间轴 → 组装 HighlightMixProps 的 segments；
  2. 下载源视频到本地临时目录（Remotion <OffthreadVideo> 需要本地文件）；
  3. 写 props.json（与 remotion/src/types.ts 数据契约一一对应）；
  4. 用子进程调用 `node dist/render.js`（Remotion 容器内），解析 PROGRESS 行回传进度；
  5. 返回渲染产物本地路径，由 Celery 任务负责上传 MinIO 与回写状态。

MVP 只做「单条混剪成品 + 包装增强」（片头/片尾/转场/动态字幕），不拆分多段独立文件。
渲染动作抽成可独立 mock 的函数，便于单元测试。
"""
import asyncio
import json
import logging
import os
import uuid
from typing import Optional

from app.config import settings
from app.services.minio_service import download_to_file

logger = logging.getLogger(__name__)

# Remotion 渲染入口脚本（配置化，默认 /remotion/dist/render.js）
REMOTION_RENDER_SCRIPT = settings.REMOTION_RENDER_SCRIPT

ProgressCallback = Optional[object]  # 与 slice_service 对齐，实际签名见 render_highlight_mix


def parse_mix_segments(cutlist: str) -> list[dict]:
    """从高光混剪 cutlist（每行 `start end name`，所有段共用一个 name）解析高光段时间轴。

    返回 [{start, end, file}]，file 由调用方后续填充为源视频本地路径。
    仅保留 start < end 的合法段，并转成秒数（cutlist 时间格式 HH:MM:SS 或 MM:SS）。
    """
    segments: list[dict] = []
    for line in (cutlist or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        start = _parse_ts(parts[0])
        end = _parse_ts(parts[1])
        if start is None or end is None or end <= start:
            continue
        segments.append({"start": start, "end": end})
    return segments


def _parse_ts(raw: str) -> Optional[float]:
    """解析 cutlist 时间戳：支持 HH:MM:SS(.xxx) 或 MM:SS(.xxx)，返回秒数；非法返回 None。"""
    if not raw:
        return None
    try:
        tokens = raw.strip().split(":")
        if len(tokens) == 3:
            h, m, s = tokens
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(tokens) == 2:
            m, s = tokens
            return int(m) * 60 + float(s)
        return float(raw)
    except (ValueError, TypeError):
        return None


def _parse_progress_stdout(stdout: str) -> None:
    """解析 render.js 的 PROGRESS: <pct>% 输出（预留：未来可透传进度回调）。"""
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("PROGRESS:"):
            try:
                logger.info("remotion render progress: %s", int(stripped.split(":", 1)[1]))
            except ValueError:
                pass


def _build_props(segments: list[dict], config: dict, source_path: str) -> dict:
    """把后端 remotion_mix_config + 高光段时间轴组装成 render.ts 期望的 HighlightMixProps。

    config 字段（来自 _build_remotion_mix_config）：
      enabled / template / intro / outro / transition_frames / subtitle_style / output_tier
    """
    fps = 30
    # 逐段本地文件统一指向已下载的源视频，用 start/end 在源内取子段
    seg_props = []
    for seg in segments:
        item = {"file": source_path, "start": seg["start"], "end": seg["end"]}
        if config.get("intro") and config["intro"].get("title"):
            item["title"] = config["intro"]["title"]
        seg_props.append(item)

    transition_frames = int(config.get("transition_frames", 12) or 0)

    # 帧数估算：片头 90 帧 + 各段 + 段间转场 + 片尾 60 帧（与 remotion HighlightMix 编排一致）
    intro_frames = 90 if config.get("intro") else 0
    outro_frames = 60 if config.get("outro") else 0
    total_frames = intro_frames + outro_frames
    for i, seg in enumerate(seg_props):
        dur = max(1, round((seg["end"] - seg["start"]) * fps))
        total_frames += dur
        if i < len(seg_props) - 1:
            total_frames += transition_frames

    props: dict = {
        "segments": seg_props,
        "subtitles": [],  # MVP：字幕透传可后续由 ASR 时间轴填充
        "fps": fps,
        "durationInFrames": max(1, total_frames),
        "width": 1920 if config.get("output_tier") == "1080p" else 1280,
        "height": 1080 if config.get("output_tier") == "1080p" else 720,
        "transitionFrames": transition_frames,
    }
    if config.get("intro"):
        intro = dict(config["intro"])
        # cover_file_key → 本地下载路径（由 renderer 提前下载；无则省略）
        if intro.get("cover_file_key") and intro.get("cover_path"):
            intro["cover"] = intro["cover_path"]
        intro.pop("cover_file_key", None)
        intro.pop("cover_path", None)
        props["intro"] = intro
    if config.get("outro"):
        props["outro"] = config["outro"]
    if config.get("subtitle_style"):
        props["subtitleStyle"] = config["subtitle_style"]
    return props


async def render_highlight_mix(
    slice_task,
    config: dict,
    source_file_key: Optional[str] = None,
    source_bucket: Optional[str] = None,
    progress_cb: ProgressCallback = None,
) -> tuple[bool, str]:
    """编排一次 Remotion 高光混剪增强渲染，返回 (ok, 本地输出路径或错误信息)。

    - 解析 cutlist 高光段 → 下载源视频 → 组装 props → 调用 render.js → 返回产物路径。
    - 任何一步失败返回 (False, 错误信息)，由 Celery 任务负责状态回写与重试。
    - 渲染动作封装在 _run_render_media，便于单元测试 mock。
    """
    from app.models.models import SliceTask

    if not isinstance(slice_task, SliceTask) and hasattr(slice_task, "cutlist"):
        cutlist = slice_task.cutlist
    else:
        cutlist = getattr(slice_task, "cutlist", "")

    segments = parse_mix_segments(cutlist)
    if not segments:
        return False, "cutlist 无合法高光段时间轴，跳过 Remotion 渲染"

    source_key = source_file_key or getattr(slice_task, "source_file_key", None)
    if not source_key:
        return False, "缺少源视频 source_file_key，无法渲染 Remotion 增强"
    bucket = source_bucket or getattr(slice_task, "source_bucket", None) or settings.MINIO_BUCKET_RAW

    # 下载源视频到本地临时目录
    tmp_dir = settings.REMOTION_TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = os.path.splitext(source_key)[1] or ".mp4"
    source_path = os.path.join(tmp_dir, f"src_{uuid.uuid4().hex}{ext}")
    ok = await download_to_file(bucket, source_key, source_path)
    if not ok:
        return False, f"下载源视频失败: {bucket}/{source_key}"

    # 片头封面：下载 cover_file_key（若有）到本地
    cover_path = None
    if config.get("intro") and config["intro"].get("cover_file_key"):
        cover_key = config["intro"]["cover_file_key"]
        cover_path = os.path.join(tmp_dir, f"cover_{uuid.uuid4().hex}.jpg")
        if not await download_to_file(bucket, cover_key, cover_path):
            cover_path = None
    if config.get("intro"):
        config["intro"]["cover_path"] = cover_path

    try:
        props = _build_props(segments, config, source_path)
        ok, out, err = await _run_render_media(props, config)
        if not ok:
            logger.error("remotion render failed: %s", err)
            return False, f"Remotion 渲染失败: {err or '未知错误'}"
        _parse_progress_stdout(out)
        if not os.path.isfile(out):
            return False, f"Remotion 渲染产物不存在: {out}"
        return True, out
    finally:
        # 清理临时文件（源视频/封面）
        for p in (source_path, cover_path):
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass


async def _run_render_media(props: dict, config: dict) -> tuple[bool, str, str]:
    """调用 Remotion render.js 子进程，返回 (ok, 输出路径, 错误信息)。

    独立函数便于单元测试 mock 掉真实渲染。
    """
    script = REMOTION_RENDER_SCRIPT
    if not os.path.isfile(script):
        return False, "", f"Remotion 渲染脚本不存在: {script}（需在 remotion-worker 容器内运行）"

    output_dir = settings.REMOTION_TMP_DIR
    os.makedirs(output_dir, exist_ok=True)
    props_path = os.path.join(output_dir, f"props_{uuid.uuid4().hex}.json")
    output_path = os.path.join(output_dir, f"out_{uuid.uuid4().hex}.mp4")
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)

    tier = config.get("output_tier") or "720p"
    cmd = ["node", script, "--props", props_path, "--output", output_path, "--tier", tier]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=3600)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return False, "", "Remotion 渲染超时（>3600s）"
    finally:
        try:
            os.remove(props_path)
        except OSError:
            pass

    out = out_b.decode(errors="replace")
    err = err_b.decode(errors="replace")
    if proc.returncode != 0 or not os.path.isfile(output_path):
        return False, out, (err or f"render.js 退出码 {proc.returncode}")
    return True, output_path, ""
