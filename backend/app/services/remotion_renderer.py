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
import shutil
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import SystemConfig
from app.services.minio_service import download_to_file

logger = logging.getLogger(__name__)

# Remotion 渲染入口脚本（配置化，默认 /remotion/dist/render.js）
REMOTION_RENDER_SCRIPT = settings.REMOTION_RENDER_SCRIPT

# 系统配置键：Remotion 渲染能力总开关（系统设置页实体开关驱动，不再读 env）
REMOTION_ENABLED_CONFIG_KEY = "remotion_enabled"

ProgressCallback = Optional[object]  # 与 slice_service 对齐，实际签名见 render_highlight_mix


async def is_remotion_enabled(db: AsyncSession) -> bool:
    """Remotion 渲染能力总开关——由系统设置页的实体开关驱动。

    读取 system_configs.remotion_enabled（JSON bool）；未配置 = 关闭。
    历史 env REMOTION_ENABLED 已弃用（2026-11-20 起改为界面实体开关）。
    """
    row = await db.execute(
        select(SystemConfig).where(SystemConfig.key == REMOTION_ENABLED_CONFIG_KEY)
    )
    cfg = row.scalar_one_or_none()
    if cfg is None or cfg.value is None:
        return False
    if isinstance(cfg.value, bool):
        return cfg.value
    return str(cfg.value).strip().lower() in ("true", "1", "yes")


def parse_mix_groups(cutlist: str) -> list[dict]:
    """解析高光混剪 cutlist，按输出文件名（name）分组。

    cutlist 每行 `start end name`；mix_output_count>1 时含多组 name（= 多个输出文件）。
    返回 [{"name": <name>, "segs": [{"start": s, "end": e}]}, ...]（按首次出现顺序）。
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for line in (cutlist or "").splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        s_raw, e_raw, name = parts
        start, end = _parse_ts(s_raw), _parse_ts(e_raw)
        if start is None or end is None or end <= start:
            continue
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append({"start": start, "end": end})
    return [{"name": n, "segs": groups[n]} for n in order]


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


def _build_props(segments: list[dict], config: dict, source_name: str,
                 portrait: bool = False) -> dict:
    """把后端 remotion_mix_config + 高光段时间轴组装成 render.ts 期望的 HighlightMixProps。

    config 字段（来自 _build_remotion_mix_config）：
      enabled / template / intro / outro / transition_frames / subtitle_style / output_tier

    媒体路径契约：file/cover 一律传 public 目录相对名——Remotion compositor 只从
    内部 HTTP 服务拉流，绝对路径会被当成 URL 而 fatally 404。
    portrait：源视频是否竖屏——画布跟随源方向（短剧源均为竖屏 9:16，横屏画布
    会把竖屏素材 cover 裁掉上下大半画面，2026-11-20 生产反馈）。
    """
    fps = 30
    # 逐段统一指向 public 目录里的源视频符号链接，用 start/end 在源内取子段
    seg_props = []
    for seg in segments:
        item = {"file": source_name, "start": seg["start"], "end": seg["end"]}
        if config.get("intro") and config["intro"].get("title"):
            item["title"] = config["intro"]["title"]
        seg_props.append(item)

    transition_frames = int(config.get("transition_frames", 12) or 0)

    # 帧数估算与 remotion computeMixLayout 算法保持一致：
    # 片头（默认 3s，钳 2~6）+ 各段 + 段间转场 + 片尾（默认 2.5s，钳 2~5）
    def _clamped_seconds(cfg_entry: dict, lo: float, hi: float, dflt: float) -> float:
        raw = cfg_entry.get("duration_seconds")
        if raw is None:
            return dflt
        try:
            return max(lo, min(hi, float(raw)))
        except (TypeError, ValueError):
            return dflt

    intro_frames = round(_clamped_seconds(config.get("intro") or {}, 2, 6, 3) * fps) if config.get("intro") else 0
    outro_frames = round(_clamped_seconds(config.get("outro") or {}, 2, 5, 2.5) * fps) if config.get("outro") else 0
    total_frames = intro_frames + outro_frames
    for i, seg in enumerate(seg_props):
        dur = max(1, round((seg["end"] - seg["start"]) * fps))
        total_frames += dur
        if i < len(seg_props) - 1:
            total_frames += transition_frames

    if portrait:
        width, height = (1080, 1920) if config.get("output_tier") == "1080p" else (720, 1280)
    else:
        width, height = (1920, 1080) if config.get("output_tier") == "1080p" else (1280, 720)

    props: dict = {
        "segments": seg_props,
        "subtitles": [],  # MVP：字幕透传可后续由 ASR 时间轴填充
        "fps": fps,
        "durationInFrames": max(1, total_frames),
        "width": width,
        "height": height,
        "transitionFrames": transition_frames,
    }
    if config.get("intro"):
        intro = dict(config["intro"])
        # cover → public 目录相对名（由 renderer 预先硬链接；无则省略）
        if intro.get("cover_name"):
            intro["cover"] = intro["cover_name"]
        # snake → 前端契约驼峰（duration_seconds → durationSeconds，秒）
        if intro.get("duration_seconds") is not None:
            intro["durationSeconds"] = float(intro["duration_seconds"])
        for k in ("cover_file_key", "cover_path", "cover_name", "duration_seconds"):
            intro.pop(k, None)
        props["intro"] = intro
    if config.get("outro"):
        outro = dict(config["outro"])
        if outro.get("duration_seconds") is not None:
            outro["durationSeconds"] = float(outro["duration_seconds"])
        outro.pop("duration_seconds", None)
        props["outro"] = outro
    if config.get("subtitle_style"):
        props["subtitleStyle"] = config["subtitle_style"]
    return props


async def render_highlight_mix(
    slice_task,
    config: dict,
    progress_cb=None,
    on_progress=None,
) -> tuple[bool, list[str] | str]:
    """按高光混剪 cutlist 分组，逐文件渲染 Remotion 增强混剪。

    职责分离（2026-11-20 重构）：高光选点/混剪规划（cutlist：哪些段、什么顺序、
    分几个文件）完成后，**拼接与增强由 Remotion 一次性完成**——从源视频按各段
    时间轴截取、段间转场、字幕/段标题/片头片尾，产出 N 个成品文件。
    ffmpeg concat 派发在该模式下被跳过，不存在两遍拼接的重复劳动。

    - progress_cb：总进度回调 `async def(pct: float, message: str)`（0-100），
      由 Celery flow 回写 slice_tasks.progress，让前端能看到多文件渲染的推进
      （下载 5% → 渲染 5~92% 按组均分 → 上传由 flow 推进 92~99%）。
    - on_progress：单文件组内进度回调 `async def(pct: int)`（render.js 的
      PROGRESS 行，0-100），由 render_highlight_mix 映射到总进度。
    - 返回 (True, 本地输出路径列表) 或 (False, 错误信息)，由 Celery 任务负责
      上传 MinIO、状态回写（completed/failed）与重试。
    - 渲染动作封装在 _run_render_media，便于单元测试 mock。
    """
    cutlist = getattr(slice_task, "cutlist", "") or ""
    groups = parse_mix_groups(cutlist)
    if not groups:
        return False, "cutlist 无合法高光段时间轴，跳过 Remotion 渲染"

    source_key = getattr(slice_task, "source_file_key", None)
    if not source_key:
        return False, "缺少源视频 source_file_key，无法渲染 Remotion 增强"
    bucket = getattr(slice_task, "source_bucket", None) or settings.MINIO_BUCKET_RAW

    # 下载源视频到本地临时目录（一次下载，多组共用）
    tmp_dir = settings.REMOTION_TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = os.path.splitext(source_key)[1] or ".mp4"
    source_path = os.path.join(tmp_dir, f"src_{uuid.uuid4().hex}{ext}")
    ok = await download_to_file(bucket, source_key, source_path)
    if not ok:
        return False, f"下载源视频失败: {bucket}/{source_key}"
    if progress_cb:
        await progress_cb(5.0, f"源视频已下载，共 {len(groups)} 个文件待渲染")

    # 画布跟随源视频方向：短剧源均为竖屏 9:16，横屏画布会把竖屏素材
    # cover 裁掉上下大半（2026-11-20 生产反馈「全是横屏」）。探测失败默认竖屏。
    portrait = await _probe_portrait(source_path)

    # Remotion 媒体供给：compositor 只从内部 HTTP 服务拉流，绝对路径会 404；
    # 且其静态服务（serve-handler）默认拒绝符号链接（lstat + symlinks: false），
    # 所以 public 目录里必须放**硬链接**（同盘零拷贝；跨盘退回真实拷贝）。
    public_dir = os.path.join(tmp_dir, "public")
    os.makedirs(public_dir, exist_ok=True)
    source_name = f"source{ext}"
    _ensure_public_file(source_path, os.path.join(public_dir, source_name))

    # 片头封面：下载 cover_file_key（若有）并放进 public 目录
    cover_path = None
    cover_name = None
    if config.get("intro") and config["intro"].get("cover_file_key"):
        cover_key = config["intro"]["cover_file_key"]
        cover_path = os.path.join(tmp_dir, f"cover_{uuid.uuid4().hex}.jpg")
        if await download_to_file(bucket, cover_key, cover_path):
            cover_name = f"cover_{uuid.uuid4().hex}.jpg"
            _ensure_public_file(cover_path, os.path.join(public_dir, cover_name))
        else:
            cover_path = None
    if config.get("intro"):
        config["intro"]["cover_path"] = cover_path
        config["intro"]["cover_name"] = cover_name

    outputs: list[str] = []
    n_groups = len(groups)

    def _group_progress(gi: int):
        """第 gi 组的组内进度 → 总进度映射：渲染段占 5%~92%，按组数均分。"""
        async def _cb(pct: int):
            if not progress_cb:
                return
            clamped = max(0, min(100, int(pct)))
            total = 5.0 + 87.0 * ((gi - 1) + clamped / 100.0) / n_groups
            await progress_cb(total, f"正在渲染第 {gi}/{n_groups} 个文件（{clamped}%）")
        return _cb

    try:
        for gi, group in enumerate(groups, start=1):
            props = _build_props(group["segs"], config, source_name, portrait=portrait)
            ok, out, err = await _run_render_media(
                props, config, public_dir, on_progress=_group_progress(gi)
            )
            if not ok:
                logger.error(
                    "remotion render failed (file %d/%d, name=%s): %s",
                    gi, len(groups), group["name"], err,
                )
                return False, f"Remotion 渲染失败: {err or '未知错误'}"
            if progress_cb:
                await progress_cb(5.0 + 87.0 * gi / n_groups, f"第 {gi}/{n_groups} 个文件渲染完成")
            _parse_progress_stdout(out)
            if not os.path.isfile(out):
                return False, f"Remotion 渲染产物不存在: {out}"
            outputs.append(out)
        if progress_cb:
            await progress_cb(92.0, "全部文件渲染完成，开始上传")
        return True, outputs
    finally:
        # 清理临时文件（源视频/封面本体 + public 目录及其符号链接）
        for p in (source_path, cover_path):
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        try:
            shutil.rmtree(public_dir, ignore_errors=True)
        except Exception:
            pass


async def _probe_portrait(video_path: str) -> bool:
    """ffprobe 探测视频方向（30s 超时）：宽<高为竖屏。

    短剧业务源全部为竖屏 9:16，探测失败时按竖屏兜底（宁竖勿横——横屏画布
    会把竖屏素材上下裁掉大半画面）。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0",
            video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        dims = out_b.decode(errors="replace").strip().split(",")
        if len(dims) >= 2:
            return int(dims[1]) > int(dims[0])
    except Exception as e:
        logger.warning("ffprobe 探测视频方向失败 %s: %s", video_path, e)
    return True  # 兜底竖屏


def _ensure_public_file(target: str, link_path: str) -> None:
    """把媒体文件放进 public 目录：优先硬链接（零拷贝），跨设备等失败时退回真实拷贝。

    注意不能用符号链接——Remotion 内部静态服务 serve-handler 用 lstat 判定，
    默认拒绝服务 symlink（404）。
    """
    try:
        if os.path.islink(link_path) or os.path.exists(link_path):
            os.remove(link_path)
    except OSError:
        pass
    try:
        os.link(target, link_path)
    except OSError:
        shutil.copy2(target, link_path)


async def _run_render_media(
    props: dict,
    config: dict,
    public_dir: str | None = None,
    on_progress=None,
) -> tuple[bool, str, str]:
    """调用 Remotion render.js 子进程，返回 (ok, 输出路径, 错误信息)。

    public_dir：Remotion public 目录（含源视频/封面硬链接），经 --public-dir
    传给 bundle()，由内部 HTTP 服务按 /<相对名> 提供。
    on_progress：组内进度回调 `async def(pct: int)`——render.js 的 stdout 每输出
    一行 `PROGRESS: <pct>%` 即触发一次（流式逐行读取，非等进程结束）。
    stderr 必须并发排空：chromium 日志量大，管道缓冲写满会阻塞子进程。
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
    if public_dir:
        cmd += ["--public-dir", public_dir]
    # render.js 的 bundle entry（src/index.ts）按**子进程 cwd** 相对解析：
    # worker-remotion 容器 cwd=/app（backend 代码），必须切到 remotion 源码目录
    # （REMOTION_WORK_DIR=/remotion），否则 ENOENT /app/src/index.ts。
    work_dir = (settings.REMOTION_WORK_DIR or "").strip() or None
    out_lines: list[str] = []
    err_lines: list[str] = []

    async def _pump_stdout(stream) -> None:
        async for raw in stream:
            line = raw.decode(errors="replace").rstrip()
            out_lines.append(line)
            stripped = line.strip()
            if stripped.startswith("PROGRESS:") and on_progress:
                try:
                    pct = int(stripped.split(":", 1)[1].strip().rstrip("%").strip())
                except ValueError:
                    continue
                try:
                    await on_progress(pct)
                except Exception as cb_e:  # 进度回调失败不影响渲染主流程
                    logger.warning("remotion progress callback failed: %s", cb_e)

    async def _pump_stderr(stream) -> None:
        async for raw in stream:
            err_lines.append(raw.decode(errors="replace").rstrip())

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _pump_stdout(proc.stdout),
                    _pump_stderr(proc.stderr),
                    proc.wait(),
                ),
                timeout=3600,
            )
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

    out = "\n".join(out_lines)
    err = "\n".join(err_lines)
    if proc.returncode != 0 or not os.path.isfile(output_path):
        return False, out, (err or f"render.js 退出码 {proc.returncode}")
    return True, output_path, ""
