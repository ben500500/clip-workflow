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

**2026-11-25 改口径：转码配方不再由本模块持有，改为调切片线引擎。**
用户原话：「拼接你可不可以直接用短剧切片的那套现成的代码？就是那边我更新了，
你这边也无需再动。」此前本模块自带一套 `filter_complex`（`build_concat_filter` /
`build_concat_cmd`），与 `engines/slice.py::concat_segments` 是同一件事的两份写法，
切片线 11-23 加的「同规格免重编码（concat demuxer 流拷贝）」和 11-22 的
「剔 `LC_*`/`LANG` 防中文豆腐块」都到不了素材库这一侧——两份必然漂移。
现在本模块只剩**适配层**：闸门（2～3 段、必须探到视频流）、把阻塞的 ffmpeg 放线程池、
把引擎异常翻成能给人看的原话。配方只在 `engines/slice.py` 一处。

这条改动的分发前提（决定"那边更新这边不用动"成不成立）：backend 容器是
`./engines:/app/engines:ro` **只读绑定挂载**（docker-compose.yml:358），改仓库根
`engines/slice.py` **不需要重建镜像**，但 uvicorn 没有 `--reload`，**必须重启容器**
才加载新模块；切片节点侧另有自己的 engines 副本（由 `api/workers.py` 推送）。
唯一事实来源是**仓库根 `engines/`**，`slice-worker/engines/` 是 .gitignore 的构建副本。

两条继承下来的硬口径（引擎侧同样成立，见 `engines/tests/test_concat_graph_regression.py`）：
混规格**绝不流拷贝**——引擎先探各段 AV 签名，完全一致才走 demuxer 流拷贝，
且拼完校验时长≈各段之和，不符就回退重编码；段与段之间**可能缺音轨**——
缺音轨的段补一条 `anullsrc`（按该段视频时长 `atrim`），接缝不崩、也不静默丢音轨。
"""

import asyncio
import functools
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
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
# 一次拼接最多几段。**2＝11-04 的手工口，3＝11-24 需求三加了「片尾」**。
# 上限钉在 3 不是技术原因（引擎的滤镜图按段数通写，天然支持任意段数），
# 是**语义**原因：需求三列的输入就是
# 「钩子成片 ＋ 正片 ＋ 片尾」这三件，再多一段就属于「拿两条正片拼一条」那种
# 真正的混剪需求，那需要选点/剪切——11-04 用户已经明确否掉过一次。
# 放开这个数之前先回去问口径，别顺手改成 10。
# ⚠️ MIN_SEGMENTS=2 同时是**引擎侧那道护栏**：`concat_segments` 收到单段会直接
# `shutil.move` **搬走输入文件**（切片线传的是临时件，本来就要清；我们传的是
# 下载缓存件／已入库产物，被搬走就是数据事故）。别下调到 1。
MAX_SEGMENTS = 3
MIN_SEGMENTS = 2


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


# ───────────────────────  引擎子口（转码配方只此一份）  ───────────────────────
#
# 这里不持有 ffmpeg 命令：拼接配方在仓库根 `engines/slice.py::concat_segments`。
# 本模块的职责只剩三道——闸门（段数／是不是视频）、把阻塞的 ffmpeg 放线程池、
# 把引擎异常翻成能给人看的原话。
#
# 为什么不复用 `asset_overlay_service._load_engine()`（它加载的是**同一个 slice.py**）：
# 那层的缓存与必检函数（`apply_badges`/`apply_text_overlays`）属于叠加用例，
# 单测直接拨它的 `_ENGINE`/`_engine_path` 全局（test_asset_overlay.py:237-280）。
# 共用一份缓存＝拼接挂了会连累叠加、反之亦然，两边的打桩还会互相踩。
_ENGINE: Any = None
_ENGINE_ERROR: Optional[str] = None


def _settings_engines_dir() -> str:
    """读 ENGINES_DIR 配置，延迟到调用时。

    不在模块顶部 `from app.config import settings`：本模块被单测直接 import 时
    不该把配置校验链（必填的 MINIO/JWT 那几项）一起拖进来——拼接口径的几个纯函数
    （`_fps_expr` 等）值得能被裸 import。
    """
    try:
        from app.config import settings

        return (settings.ENGINES_DIR or "").strip()
    except Exception:  # noqa: BLE001 - 配置读不到回空，由 _engine_path 报人话
        return ""


def _engine_path() -> Optional[str]:
    """在 ENGINES_DIR 里找 slice.py。相对路径按 backend 容器 cwd（/app）解析。"""
    candidates = []
    configured = _settings_engines_dir()
    if configured:
        candidates.append(os.path.join(configured, "slice.py"))
        if not os.path.isabs(configured):
            # 本机从 backend/ 跑 pytest 时 ENGINES_DIR="engines" 指不到，兜一层 ../engines
            candidates.append(os.path.join("..", configured, "slice.py"))
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def _load_engine() -> Tuple[Any, Optional[str]]:
    """懒加载引擎模块，失败回 (None, 人话)。成功与失败都缓存（别每次重导）。

    用 `spec_from_file_location` 而不是 `sys.path.insert + import slice`：后者把整个
    engines 目录顶到 sys.path 最前面，`slice` 这名字太通用（backend 里已有一个
    `app.engines` 包），万一日后被别的模块抢走，拼的就是**另一个文件**里的函数。

    连 `SystemExit` 一起接：`engines/slice.py` 顶部对 Python<3.10 是**直接 sys.exit(1)**，
    那是 BaseException 不是 Exception——不接住会把整个请求进程带走。
    """
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None or _ENGINE_ERROR is not None:
        return _ENGINE, _ENGINE_ERROR
    path = _engine_path()
    if path is None:
        _ENGINE_ERROR = (
            f"这台机器上找不到切片引擎（{_settings_engines_dir() or 'engines'}/slice.py）。"
            "现网 backend 容器是挂载 ./engines 进来的，本地开发机没挂——"
            "所以拼接只能在线上验，本地跑请把本模块的 concat_segments 打桩"
        )
        logger.warning("%s", _ENGINE_ERROR)
        return None, _ENGINE_ERROR
    try:
        spec = importlib.util.spec_from_file_location("asset_concat_engine", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法从 {path} 载入引擎模块")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if not callable(getattr(module, "concat_segments", None)):
            raise ImportError(f"引擎 {path} 里没有可调用的 concat_segments()")
        _ENGINE = module
        logger.info("拼接引擎已载入：%s", path)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - 引擎载入失败不能让接口 500
        _ENGINE_ERROR = f"拼接引擎载入失败（{type(exc).__name__}: {exc}）"
        logger.exception("%s", _ENGINE_ERROR)
        sys.modules.pop("asset_concat_engine", None)
    return _ENGINE, _ENGINE_ERROR


def engine_available() -> Tuple[bool, Optional[str]]:
    """老实回答「这台机器能不能自动拼接」，不抛异常（给界面/诊断用）。"""
    module, err = _load_engine()
    return module is not None, err


def _run_engine_concat(engine: Any, paths: List[str], out_path: str) -> None:
    """线程里同步跑引擎拼接（run_in_executor 的执行体，别在事件循环里直接调）。

    参数口径：
    - `threads=0`＝交给 ffmpeg 自适应。引擎默认 1（切片线为并发切片限 CPU），
      而素材库一次只拼一条，照默认跑会把几秒的活儿拉成几十秒——本口是同步等
      ffmpeg 的请求，慢就等于占着连接不放。
    - `copy_if_possible=True`＝各段 AV 签名完全一致时走 concat demuxer 流拷贝
      （引擎自己校验拼接时长，不符则回退重编码）。豆包成片＋同参切片这种常见组合
      能免掉一次重编码，画质不掉。
    - `faststart=True`＝产物 `moov` 前置，浏览器边下边播。引擎默认关是为了不动
      切片线既有产物字节；素材库这一侧要挂网页上播，所以显式打开。
    """
    engine.concat_segments(
        list(paths), out_path, threads=0, encoder="libx264",
        copy_if_possible=True, faststart=True,
    )


async def concat_segments(paths: List[str], target: Dict[str, Any], out_path: str) -> Optional[str]:
    """把 paths 按给定顺序拼成 out_path；成功回 None，失败回一句能给人看的原话。

    **素材库三处拼接口（手工口／回收自动拼／组合导出矩阵）都经 `_concat_render`
    汇到这里**，函数名保留是为了让现有用例
    （`patch("app.services.asset_compose_service.concat_segments", ...)`）照样打得通。

    `target` 是调用方按**顺序第一段**探到的规格（宽/高/帧率）。引擎自己也会探首段
    几何（同一个「排在最前那一段＝目标画幅」口径），所以这里保留形参只为两件事：
    调用点签名不必改、以及引擎探测万一回退这里还能顶上。**不再用 `target` 拼滤镜串。**

    段数区间 `MIN_SEGMENTS..MAX_SEGMENTS`（2～3）。11-24 需求三从 2 放宽到 3 是为了
    「＋片尾」；段数通写这件事现在在引擎里，本模块只守门。
    **全仓只此一份 concat 实现**（§9.3 收口，现在这一份在 `engines/slice.py`），
    另一处 `api/upload.py::_ffmpeg_concat` 已标死为「仅限多文件合并上传」。
    """
    if not MIN_SEGMENTS <= len(paths) <= MAX_SEGMENTS:
        return (
            f"一次拼 {MIN_SEGMENTS}～{MAX_SEGMENTS} 段（钩子片／正片／片尾），现在是 {len(paths)} 段"
            "（要更多段属于混剪需求，先回文档确认口径，别改这条）"
        )
    if not shutil.which("ffmpeg"):
        return "服务器里没有 ffmpeg，拼不了（找运维持容器镜像）"
    if not shutil.which("ffprobe"):
        return "服务器里没有 ffprobe，探不了规格"
    for p in paths:
        info = await probe_media(p)
        if info is None:
            return f"这一段探不出视频流，不是能拼的视频文件：{p.rsplit('/', 1)[-1]}"
    engine, err = _load_engine()
    if engine is None:
        return err
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None, functools.partial(_run_engine_concat, engine, list(paths), out_path)
        )
    except Exception as exc:  # noqa: BLE001 - 引擎把 ffmpeg stderr 尾部塞在异常里
        tail = " ".join(str(exc).split())[-800:] or "无错误输出"
        logger.exception("拼接失败（引擎通道）：%s", tail)
        return f"ffmpeg 拼接失败：{tail}"
    if not _nonempty(out_path):
        return "引擎报成功但产物文件不存在或是空的（别当成功交付）"
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
