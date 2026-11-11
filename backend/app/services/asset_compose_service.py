"""素材库拼接服务（P2 的**简化口径**，2026-11-04 用户改口径后重写）。

用户原话：「我说的最后的剪切，只是说把他们上传素材库的这个片段，以及他们可以选择
本地或者哪里的一个切片，然后把这两个东西拼起来。其实不需要什么智能选点、智能剪切
这种东西……拼贴的话，可能是需要可以选择顺序，比如说拼在前或者拼在后。」

所以这里的口径只有一条：**两段视频，按人选的顺序，拼成一条**。
不做智能选点、不做智能剪切、不接切片引擎（`SliceTask.hook_video_keys` /
`hook_mix_mode` 那一套一概不调）。昨天设计方案 §八 把拼接挂在切片引擎上，是把它做重了。

为什么不复用 `api/upload.py::_ffmpeg_concat`（现网"多文件合并上传"用的那个）：
它重编码回退档**硬编码 `scale=1920:1080`**（upload.py:644），而我们全链路是 9:16 竖屏
（豆包成片恒 720×1280，切片产物绝大多数也是竖屏），那条回退一旦触发，
会把竖屏片加左右黑边塞进横屏框——**"拼接成功但构图坏"**，正是设计方案 §八 自己
点名过的那类坑。这里改成**以排在最前那一段的规格为准**归一：用户选顺序，
等于顺带选了目标画幅，不需要再多一个"选画幅"的控件。

第二条继承的结论：混规格**绝不流拷贝**。切片引擎历史上踩过（"混规格走流拷贝 →
concat 出坏片"，`slice-worker/engines/slice.py:4577-4580` 因此含钩子时强制
`filter_complex` 重编码），这里同样一律走 `filter_complex concat` + 显式重编码。

第三条继承的结论：段与段之间音频可能缺失。任一段没有音轨时直接 `-c:a aac` 会整条命令
失败，所以探到缺音轨的那一段补一条 `anullsrc` 静音轨（时长按该段视频时长），
接缝处不会崩，也不静默丢音轨。
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 拼接产物的 kind（asset_outputs.kind 注释里已登记的四个取值之一，11-04 起有写入方）
KIND_COMPOSED = "composed"

# 支持作为拼接输入的取值（来源＝哪张表，不是"本地/NAS"这种物理位置）
SOURCE_ASSET = "asset"     # asset_items（素材库已入库片段，含"本地上传后落库"的那条路径）
SOURCE_SLICE = "slice"     # slice_outputs（现网切片产物，sliced 桶）
INPUT_SOURCES = (SOURCE_ASSET, SOURCE_SLICE)

# 顺序取值：拼在前 / 拼在后（用户明确要求可选）
ORDER_ASSET_FIRST = "asset_first"    # 素材库片段在前，第二段在后
ORDER_SECOND_FIRST = "second_first"  # 第二段在前，素材库片段在后
INPUT_ORDERS = (ORDER_ASSET_FIRST, ORDER_SECOND_FIRST)

# 自动拼接（11-10 批 Q）的顺序取值。**故意不和上面那对共用**：
# 手工口的两段是「素材库片段(A) + 另一段(B)」，自动口的两段是「钩子成片 + 素材库片段」，
# 同一个 `asset_first` 字面量在两处指的不是同一段片子——共用一套词表迟早拼反，
# 而"拼反了"这种事没人会在验收里发现（片子能播、时长对、就是前 10 秒不对）。
ORDER_HOOK_FIRST = "hook_first"          # 钩子片在前、素材片段在后（引流→正文）
ORDER_TAIL_AFTER_HOOK = "material_first"  # 素材片段在前、钩子片在后
AUTO_CONCAT_ORDERS = (ORDER_HOOK_FIRST, ORDER_TAIL_AFTER_HOOK)
DEFAULT_AUTO_CONCAT_ORDER = ORDER_HOOK_FIRST

# 兜底帧率：探不到 avg_frame_rate（容器内 ffprobe 偶发回 N/A）时用 25，与切片档位一致
DEFAULT_FPS = "25"
# 单段最长允许多少秒（拼接是同步等 ffmpeg 的 HTTP 请求，纯防御，别拿它当队列用）
MAX_SEGMENT_SECONDS = 600.0


def _fail(status: int, detail: str) -> None:
    """统一抛 HTTPException。

    延迟 import：本模块被单测直接 import 时不应依赖 FastAPI 的异常链之外的东西，
    而 HTTPException 只在真走接口时才用得到。
    """
    from fastapi import HTTPException

    raise HTTPException(status_code=status, detail=detail)


def _parse_resolution(value: Optional[str]) -> Optional[Tuple[int, int]]:
    """把 `resolution` 文本（"1080x1920" / "720*1280" / "1080×1920"）解析成 (宽, 高)。

    解析不出来回 None，调用方按"没有规格线索"处理，**不猜**——猜成 1920x1080 就是
    upload.py 那个横屏 bug 的成因。
    """
    if not value:
        return None
    text = str(value).strip().lower().replace("×", "x").replace("*", "x")
    parts = text.split("x")
    if len(parts) != 2:
        return None
    try:
        w, h = int(float(parts[0])), int(float(parts[1]))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return (w, h)


def resolve_input_order(order: Optional[str], asset_label: str, second_label: str) -> List[str]:
    """把"拼在前/拼在后"翻成两段的路径占位顺序说明（供 UI/审计回显，不参与 ffmpeg）。"""
    normalized = (order or ORDER_ASSET_FIRST).strip()
    if normalized not in INPUT_ORDERS:
        _fail(400, f"order 只能是 {' 或 '.join(INPUT_ORDERS)}（拼在前／拼在后）")
    if normalized == ORDER_SECOND_FIRST:
        return [second_label, asset_label]
    return [asset_label, second_label]


def resolve_auto_order(order: Optional[str]) -> str:
    """自动拼接（批 Q）的顺序校验：非法值 400，留空回默认档。

    判据放在服务层而不是接口层，是因为投板口和将来的重拼口都要用同一个说法——
    两处各写一遍 `if order not in (...)` 必然出现"一处认 material_first、
    另一处不认"，那种 bug 只在生产单已经投出去之后才暴露。
    """
    normalized = (order or DEFAULT_AUTO_CONCAT_ORDER).strip()
    if normalized not in AUTO_CONCAT_ORDERS:
        _fail(
            400,
            f"拼接顺序只能是 {' 或 '.join(AUTO_CONCAT_ORDERS)}"
            "（hook_first＝钩子片在前 / material_first＝素材片段在前）",
        )
    return normalized


def check_inputs_differ(asset_id: str, source: str, second_id: str) -> None:
    """两段不能是同一个文件——自己拼自己只会得到一条时长翻倍、画面重复的废片。"""
    if source == SOURCE_ASSET and str(asset_id) == str(second_id):
        _fail(400, "两段素材是同一个文件，拼出来是重复播放的废片，请换一段")


# ─────────────────────────  ffprobe / ffmpeg ─────────────────────────

def _ffprobe_json_sync(path: str) -> Optional[Dict[str, Any]]:
    """同步跑 ffprobe（调用方放线程里跑）。探不到回 None，不抛。"""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    try:
        proc = subprocess_run(cmd)
    except Exception as exc:  # ffprobe 不在 PATH / 文件损坏
        logger.warning("ffprobe 启动失败 %s: %s", path, exc)
        return None
    if proc.returncode != 0:
        logger.warning("ffprobe 返回 %s：%s", proc.returncode, proc.stderr[-500:])
        return None
    try:
        return json.loads(proc.stdout.decode(errors="replace") or "{}")
    except json.JSONDecodeError:
        logger.warning("ffprobe 输出不是 JSON：%s", path)
        return None


def subprocess_run(cmd: List[str]):
    """单独抽出来，方便单测替换（本模块的探测与拼接都走这两个口子）。"""
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def parse_probe(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从 ffprobe JSON 里取拼接要用的四件事：时长、宽、高、帧率、有无音轨。

    取不到视频流＝不是能拼的东西，回 None 让调用方报 400，而不是带着 None 往下走
    在 ffmpeg 那里炸一个看不懂的错。
    """
    if not data:
        return None
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        return None
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    width = video.get("width")
    height = video.get("height")
    if not width or not height:
        return None
    fps = _fps_expr(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    duration: Optional[float] = None
    for candidate in (data.get("format", {}) or {}).get("duration"), video.get("duration"):
        try:
            value = float(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if value > 0:
            duration = round(value, 2)
            break
    return {
        "duration": duration,
        "width": int(width),
        "height": int(height),
        "fps": fps,
        "has_audio": audio is not None,
    }


def _fps_expr(raw: Optional[str]) -> str:
    """`"30000/1001"` 这类分数帧率原样给 ffmpeg 的 fps 滤镜最准；坏值回默认 25。"""
    text = (raw or "").strip()
    if not text or text in ("0/0", "N/A"):
        return DEFAULT_FPS
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            if float(den) == 0 or float(num) <= 0:
                return DEFAULT_FPS
        except ValueError:
            return DEFAULT_FPS
        return text
    try:
        value = float(text)
    except ValueError:
        return DEFAULT_FPS
    return f"{value:.6f}".rstrip("0").rstrip(".") if value > 0 else DEFAULT_FPS


async def probe_media(path: str) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _ffprobe_json_sync, path)
    return parse_probe(data)


def build_concat_filter(target: Dict[str, Any], segments: List[Dict[str, Any]]) -> Tuple[str, int]:
    """按目标规格给每段生成 scale/pad/fps/setsar，缺音轨的段接一条静音轨。

    返回 `(filter_complex 串, 要追加的 lavfi 输入个数)`。
    target 是**排在最前那一段**探到的 {width,height,fps}——选顺序＝选画幅。

    输入索引约定：两段视频占 0 和 1，缺音轨的段按顺序在后面追加 `anullsrc` 输入
    （索引从 2 起）。追加的输入**本身就带音频流**，所以图里引用 `[j:a]` 再 atrim 到
    该段时长；在滤镜图里裸写 `anullsrc` 是错的（那是 source 滤镜，没有输入可接）。
    """
    w, h = int(target["width"]), int(target["height"])
    fps = target.get("fps") or DEFAULT_FPS
    chain: List[str] = [
        f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p[v{i}]"
        for i in range(len(segments))
    ]
    extra_inputs = 0
    for i, seg in enumerate(segments):
        if seg.get("has_audio"):
            chain.append(f"[{i}:a]aresample=async=1:first_pts=0[a{i}]")
            continue
        index = len(segments) + extra_inputs
        extra_inputs += 1
        dur = float(seg.get("duration") or target.get("duration") or 0.1)
        chain.append(
            f"[{index}:a]atrim=0:{max(0.1, round(dur, 3))},"
            f"asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0[a{i}]"
        )
    labels = "".join(f"[v{i}][a{i}]" for i in range(len(segments)))
    chain.append(f"{labels}concat=n={len(segments)}:v=1:a=1[outv][outa]")
    return ";".join(chain), extra_inputs


def build_concat_cmd(paths: List[str], out_path: str, target: Dict[str, Any],
                     segments: List[Dict[str, Any]]) -> Tuple[List[str], str]:
    """拼一条完整 ffmpeg 命令（单测就断这条，不依赖真装 ffmpeg）。"""
    filter_body, extra_inputs = build_concat_filter(target, segments)
    cmd: List[str] = ["ffmpeg", "-y"]
    for p in paths:
        cmd += ["-i", p]
    for _ in range(extra_inputs):
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += [
        "-filter_complex", filter_body,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    return cmd, filter_body


async def _run(cmd: List[str]) -> Tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    return proc.returncode or 0, stderr.decode(errors="replace")


async def concat_segments(paths: List[str], target: Dict[str, Any], out_path: str) -> Optional[str]:
    """把 paths 按给定顺序拼成 out_path；成功回 None，失败回一句能给人看的原话。

    `target` 是调用方按**顺序第一段**探到的规格（宽/高/帧率），本函数只补音轨有无与时长。
    """
    if len(paths) != 2:
        return f"拼接固定两段，现在是 {len(paths)} 段（要三段以上再说，别改这条口径）"
    if not shutil.which("ffmpeg"):
        return "服务器里没有 ffmpeg，拼不了（找运维持容器镜像）"
    if not shutil.which("ffprobe"):
        return "服务器里没有 ffprobe，探不了规格"
    segments: List[Dict[str, Any]] = []
    for p in paths:
        info = await probe_media(p)
        if info is None:
            return f"这一段探不出视频流，不是能拼的视频文件：{p.rsplit('/', 1)[-1]}"
        segments.append(info)
    cmd, _ = build_concat_cmd(paths, out_path, target, segments)
    code, err = await _run(cmd)
    if code != 0 or not _nonempty(out_path):
        tail = err[-800:] if err else "无 stderr"
        logger.error("拼接失败 code=%s：%s", code, tail)
        return f"ffmpeg 拼接失败（退出码 {code}）：{tail}"
    return None


def _nonempty(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def sha256_of(path: str) -> Optional[str]:
    """产物指纹（asset_outputs.sha256 有列没人写过，11-04 起写）。读失败回 None，不挡交付。"""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        logger.warning("sha256 计算失败 %s: %s", path, exc)
        return None
