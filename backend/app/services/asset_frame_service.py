"""抽帧（11-04 批 F）：把一条视频抽成「3 张单帧 ＋ 1 张九宫格」，供审核台卡片与封面图用。

为什么单独一个 service（不复用 `app/api/upload.py` 的 `_run_ffmpeg`）：
那个函数是上传接口的私有家什（在 api 层里），service 反向 import api 层会把依赖画反；
这里只借它的**做法**（`create_subprocess_exec` ＋ 失败记 stderr 尾部），不借它的名字。

⚠️ 这一层**不知道数据库、不知道 MinIO、也不做业务判定**：
入参是本地文件路径，出参是本地图片路径＋元信息。落库与上传在 `app/api/assets.py`
的抽帧任务里做。这么切的好处是——所有命令拼装都能在单测里直接跑真 ffmpeg 验。

取值口径（全部来自 `settings.ASSET_FRAME_*`，见 config.py 的注释）：
- 单帧取在 `duration` 的 10% / 45% / 80%（`.env.example` 里说的「3 张」），
  **不取 0 秒**——短片第一帧常常是黑帧或台标，卡片上一片黑会被一线当成「抽帧坏了」；
- 九宫格按 `interval = duration / tiles` 等间隔取，起点抬半个间隔，同样为了躲黑帧；
- 时长探不到（`duration` 为 None/0）就**只出九宫格都不出**：连时间轴都没有，
  等间隔无从谈起，单帧的百分比也算不出来。这时回 skip 原因，让上层记进台账。
"""
import asyncio
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.models.asset import FRAME_GRID, FRAME_THUMB

# 九宫格的行列数：`ASSET_FRAME_GRID_TILES` 改数时要同步这里（3x3 才叫九宫格）。
GRID_COLS = 3

# 抽出来的帧统一 JPEG：比 PNG 小一个量级（九宫格 PNG 能到 1~2MB），
# 而卡片图不需要无损——反正原片就在桶里，要看清楚点播放。
CONTENT_TYPE = "image/jpeg"
EXT = "jpg"

# JPEG 质量（ffmpeg -q:v，2 最好 31 最差）：3 是「放大到能看清屏内字幕」的档位，
# 一致性判读要看的就是字幕/台标这类细节，压太狠图就白抽了。
JPEG_QA = "3"


def _positive_int(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


# 注意**没有** `_positive_float` 的对应物：抽帧上限的 0 是"关掉抽帧"这个有意义的取值，
# 不能像上面那样把它当非法值换成默认档（`should_skip` 里写明了原因）。


def plan_offsets(duration: float, count: Optional[int] = None) -> List[float]:
    """单帧取哪些时间点（秒）：按 10%/45%/80% 分，均匀偏后，避开片头黑帧。

    少于 2 秒的片子不值得抽多张——三张会是同一帧，直接给一张。
    """
    n = _positive_int(count, settings.ASSET_FRAME_THUMB_COUNT)
    if duration <= 0:
        return []
    if duration < 2:
        return [round(duration / 2, 2)]
    ratios = [0.10, 0.45, 0.80]
    if n <= 3:
        picks = ratios[:max(1, n)]
    else:
        # 想要更多帧就在 10%~90% 之间等分，仍然不碰首尾
        picks = [0.10 + 0.80 * i / (n - 1) for i in range(n)]
    return [round(min(max(duration * r, 0.05), duration - 0.05), 2) for r in picks]


def grid_interval(duration: float, tiles: Optional[int] = None) -> float:
    """九宫格等间隔（秒）= 时长 / 格数。"""
    n = _positive_int(tiles, settings.ASSET_FRAME_GRID_TILES)
    return round(duration / n, 3) if duration > 0 else 0.0


def build_thumb_cmd(src: str, t: float, out: str, width: Optional[int] = None) -> List[str]:
    """单帧：`-ss` 放在 `-i` 前＝关键帧快速定位（抽缩略图不需要帧级精确）。"""
    w = _positive_int(width, settings.ASSET_FRAME_THUMB_WIDTH)
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, float(t)):.2f}", "-i", src,
        "-frames:v", "1", "-vf", f"scale={w}:-2", "-q:v", JPEG_QA, out,
    ]


def build_grid_cmd(src: str, duration: float, out: str, tiles: Optional[int] = None,
                   width: Optional[int] = None) -> List[str]:
    """九宫格：等间隔取 `tiles` 帧拼成一张 3×3。

    每格宽 = 整图宽 / 3（`scale` 在 `tile` **之前**，所以它管的是单格尺寸）；
    `-ss 半格` 抬到第一格中间，躲开 t=0 的黑帧/台标。
    """
    n = _positive_int(tiles, settings.ASSET_FRAME_GRID_TILES)
    cols = GRID_COLS
    total_w = _positive_int(width, settings.ASSET_FRAME_GRID_WIDTH)
    cell_w = max(64, total_w // cols)
    interval = grid_interval(duration, n)
    if interval <= 0:
        raise ValueError("时长无效，无法等间隔拼图")
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{interval / 2:.2f}", "-i", src,
        "-t", f"{interval * n:.2f}",
        "-vf", f"fps=1/{interval},scale={cell_w}:-2,tile={cols}x{cols}",
        "-frames:v", "1", "-q:v", JPEG_QA, out,
    ]


def should_skip(duration: Optional[float]) -> Optional[str]:
    """该不该跳过抽帧，回**人话原因**（None＝照抽）。

    两种跳过：没时长（算不出时间点）、超长（整集片不值得钉住一个 worker）。
    都是"没图看"，不是错误——上层把它记成 skip，素材状态一点不受影响。
    """
    if duration is None:
        return "时长未知，算不出抽帧时间点（这条先点「查视频时长」或等反推回填）"
    try:
        d = float(duration)
    except (TypeError, ValueError):
        return f"时长字段不是数（{duration!r}），没抽"
    if not math.isfinite(d) or d <= 0:
        return "时长为 0 或负数，没抽"
    # ⚠️ 这里**不能**用 `_positive_float(..., 900.0)`：那个函数把 0 当"非法值"换成默认 900，
    # 于是配置里写明的「设 0 = 关掉抽帧」这个总开关会变成死代码（单测第一次跑到就抓出来了）。
    # 0 是**有意义的取值**，只有真正解析不出数才回退默认档。
    try:
        cap = float(settings.ASSET_FRAME_MAX_SOURCE_SECONDS)
    except (TypeError, ValueError):
        cap = 900.0
    if not math.isfinite(cap):
        return f"ASSET_FRAME_MAX_SOURCE_SECONDS 不是有效数（{cap}），抽帧整体关着"
    if cap <= 0:
        return "ASSET_FRAME_MAX_SOURCE_SECONDS=0，抽帧整体关着"
    if d > cap:
        return f"这条 {d:.0f}s 超过抽帧上限 {cap:.0f}s（整集片不值得钉住 worker 抽帧）"
    return None


async def _run(cmd: List[str], timeout: Optional[int] = None) -> Tuple[int, str]:
    """跑一条 ffmpeg，超时也当失败返回（不抛）。返回 (returncode, stderr 尾部)。"""
    limit = _positive_int(timeout, settings.ASSET_FRAME_TIMEOUT_SECONDS)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        # 容器里没 ffmpeg：这是部署问题不是数据问题，说清去查镜像
        return 127, "本机/容器内没有 ffmpeg 可执行文件"
    except Exception as exc:  # noqa: BLE001 — 起进程本身炸了（fork 超限等）
        return 126, f"{type(exc).__name__}: {exc}"
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=limit)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, f"ffmpeg 超过 {limit}s 没回（坏文件？已杀掉）"
    tail = (stderr or b"").decode(errors="replace").strip()
    return int(proc.returncode or 0), tail[-500:]


def _usable(path: str) -> bool:
    """ffmpeg 退出码 0 但**没落字节**是素材库真踩过的坑（0 字节对象照样 200），这里挡一道。"""
    return os.path.isfile(path) and os.path.getsize(path) > 0


async def extract(local_path: str, duration: float, out_dir: str,
                  with_grid: bool = True) -> Dict[str, Any]:
    """把一条本地视频抽成帧。

    返回 `{"thumbs": [...], "grid": {...|None}, "errors": [...]}`，每项是
    `{"kind","seq","t_offset","path","file_size"}`。

    **不抛异常**：单帧失败只少一张图，剩下的照给；全失败才由上层记任务失败。
    这样一条坏文件不会把整批导入的抽帧一起带崩。
    """
    thumbs: List[Dict[str, Any]] = []
    errors: List[str] = []
    os.makedirs(out_dir, exist_ok=True)

    for seq, t in enumerate(plan_offsets(duration)):
        out = os.path.join(out_dir, f"thumb_{seq}.{EXT}")
        code, tail = await _run(build_thumb_cmd(local_path, t, out))
        if code == 0 and _usable(out):
            thumbs.append({"kind": FRAME_THUMB, "seq": seq, "t_offset": t,
                           "path": out, "file_size": os.path.getsize(out)})
        else:
            errors.append(f"第{seq + 1}帧（{t}s）没抽出来：{tail or f'ffmpeg 退出码 {code}'}")

    grid: Optional[Dict[str, Any]] = None
    if with_grid:
        out = os.path.join(out_dir, f"grid.{EXT}")
        code, tail = await _run(build_grid_cmd(local_path, duration, out))
        if code == 0 and _usable(out):
            grid = {"kind": FRAME_GRID, "seq": 0, "t_offset": grid_interval(duration) / 2,
                    "path": out, "file_size": os.path.getsize(out)}
        else:
            errors.append(f"九宫格没拼出来：{tail or f'ffmpeg 退出码 {code}'}")

    return {"thumbs": thumbs, "grid": grid, "errors": errors}
