"""组合导出（需求三）的**叠加层**：把切片引擎里那两个「成品视频加角标 / 加固定文字」的
纯函数接到素材库上（2026-11-24 S3）。

用户口径（1123 需求评审 §需求三）：「多选钩子成片 × 多选正片 ＝ 组合投放素材；
角标／警示语／剧名／片尾」。所以叠加不是独立功能，是组合导出矩阵每一格上的一道工序。

三条设计约束，都是踩过或看过才写下的：

1. **不调 `SliceTask`、不造 `Episode`**。引擎侧 `apply_badges(src, out, badges)` 与
   `apply_text_overlays(src, out, text_overlays)` 本身就是 `(src, out, cfg)` 三个参数的
   纯函数（engines/slice.py:1291 / :1719），完全不需要父行。素材库历史上被点名过
   「禁止为素材库造假父行」（1123 §9.5b），这里就是那条禁令的执行现场。

2. **参数结构与引擎侧逐字同名**（`path/position/width/offset/opacity`、
   `text/position/font_size/color/border_color/vertical/offset`）。不在中间层改名——
   一改名就要在两边各维护一张映射表，表漏一行时引擎那边 `badge.get("width") or 0`
   拿到 None 会**静默按"保持原图尺寸"出片**，那种错只有眼睛看片才能发现。

3. **位置非法当场 400，不许像引擎那样悄悄回落 top-left**。
   `build_badges_overlay_args` 对未知位置是 `if position not in BADGE_POSITIONS:
   position = "top-left"`（slice.py:1253-1254）——切片线里那是"别把整条任务搞挂"的容错，
   放到出包线上就是"用户选了右下角、片子上却在左上角，而且系统报成功"。
   叠加是给人看的成品外观，宁可拒收。

角标图引用的是**素材库里的图片行 id**，不是 MinIO key。这是批 G 那条教训的直接沿用
（投板弹窗让一线手填角色卡 key，打错字符照样建单，投出去是没卡的片，见
`AssetCardPicker` 取代手填框那次改动）。

引擎目录在现网是 `./engines:/app/engines:ro` 挂进 backend 的（compose:358），
本机 pytest 跑的时候 `ENGINES_DIR` 指不到真文件——所以 `_load_engine()` 只在**第一次
真的要用叠加时**才导入，且失败回一句人话而不是让接口 500。
"""

import asyncio
import importlib.util
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.asset import MEDIA_IMAGE, AssetItem

logger = logging.getLogger(__name__)

# 与 engines/slice.py::BADGE_POSITIONS / TEXT_OVERLAY_POSITIONS 的键**逐字一致**。
# 这里的顺序就是界面上从上到下的选项顺序（横排三位先给，符合一线习惯）。
BADGE_POSITIONS = (
    "top-left", "top-center", "top-right",
    "left",
    "bottom-left", "bottom-center", "bottom-right",
)
TEXT_POSITIONS = BADGE_POSITIONS  # 引擎两处是同一套七位（slice.py:1176 / :1310）

# 单条片子最多叠几个角标 / 几行字。不是性能考虑（每个角标只是多一路 overlay），
# 是**版面**考虑：7 个位置叠满，画面和剧名都看不清了。超了让人删而不是让人猜。
MAX_BADGES = 6
MAX_TEXT_OVERLAYS = 6
# 一行叠加文字最多几个字（剧名/警示语场景下 30 字已经会顶到画面边缘）
MAX_TEXT_CHARS = 30

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _bad(detail: str) -> None:
    raise HTTPException(status_code=400, detail=detail)


def _int_in_range(raw: Any, *, name: str, low: int, high: int, default: int) -> int:
    """把 JSON 里的数字收进区间；坏值报人话，不静默取默认。

    为什么不学引擎那样 `try: int(...) except: default`：那是"渲染不能停"的取舍
    （切片任务因为一个偏移量写错就整条失败不值当）。叠加预设是**存下来反复用**的东西，
    `offset: "abc"` 存进去后每次出片都悄悄按默认值走，改的人永远不知道自己没生效。
    """
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _bad(f"{name} 得是整数（现在是 {raw!r}）")
    if not low <= value <= high:
        _bad(f"{name} 只能在 {low}～{high} 之间（现在是 {value}）")
    return value


def _position(raw: Any, *, kind: str) -> str:
    table = BADGE_POSITIONS if kind == "角标" else TEXT_POSITIONS
    value = str(raw or "").strip()
    if not value:
        _bad(f"{kind}没选位置（可选：{'、'.join(table)}）")
    if value not in table:
        _bad(f"{kind}位置「{value}」不认识（可选：{'、'.join(table)}）")
    return value


def validate_overlay(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把前端/预设里的叠加参数清洗成引擎能直接吃的形状，坏值当场 400。

    返回 `{"badges": [...], "text_overlays": [...]}`，两侧都允许为空列表
    （＝这一格不叠加）。**未知键一律丢掉**：预设 JSON 是存库的，留着 `{"width ": 80}`
    这种手滑键，等于把一次拼写错误变成永久生效的静默默认值。
    """
    data = raw if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        _bad("叠加参数得是一个对象（含 badges / text_overlays 两个列表）")

    badges_raw = data.get("badges") or []
    texts_raw = data.get("text_overlays") or []
    if not isinstance(badges_raw, list) or not isinstance(texts_raw, list):
        _bad("badges 和 text_overlays 都必须是列表")
    if len(badges_raw) > MAX_BADGES:
        _bad(f"角标最多 {MAX_BADGES} 个（现在 {len(badges_raw)} 个），多了画面就糊了")
    if len(texts_raw) > MAX_TEXT_OVERLAYS:
        _bad(f"叠加文字最多 {MAX_TEXT_OVERLAYS} 行（现在 {len(texts_raw)} 行）")

    badges: List[Dict[str, Any]] = []
    for idx, item in enumerate(badges_raw, start=1):
        if not isinstance(item, dict):
            _bad(f"第{idx}个角标格式不对")
        asset_id = str(item.get("asset_id") or "").strip()
        if not asset_id:
            _bad(
                f"第{idx}个角标没挑图。角标要从素材库里挑（图片类型的素材），"
                "不是填 MinIO 路径——填错一个字符照样能存，出片时才发现没卡"
            )
        badges.append(
            {
                "asset_id": asset_id,
                "position": _position(item.get("position"), kind="角标"),
                "width": _int_in_range(item.get("width"), name=f"第{idx}个角标宽度", low=0, high=2000, default=0),
                "offset": _int_in_range(item.get("offset"), name=f"第{idx}个角标边距", low=0, high=600, default=10),
                "opacity": _opacity(item.get("opacity"), idx),
            }
        )

    text_overlays: List[Dict[str, Any]] = []
    for idx, item in enumerate(texts_raw, start=1):
        if not isinstance(item, dict):
            _bad(f"第{idx}行叠加文字格式不对")
        text = str(item.get("text") or "").strip()
        if not text:
            _bad(f"第{idx}行叠加文字是空的，空文字别存（引擎会整层跳过，看着像没生效）")
        if len(text) > MAX_TEXT_CHARS:
            _bad(f"第{idx}行叠加文字 {len(text)} 字，最多 {MAX_TEXT_CHARS} 字（长了会顶出画面）")
        color = str(item.get("color") or "#FFFFFF").strip()
        border = str(item.get("border_color") or "#000000").strip()
        for label, value in (("颜色", color), ("描边颜色", border)):
            if not _HEX_COLOR.match(value):
                _bad(f"第{idx}行叠加文字的{label}「{value}」不是 #RGB / #RRGGBB 写法")
        vertical = bool(item.get("vertical"))
        text_overlays.append(
            {
                "text": text,
                "position": _position(item.get("position"), kind="文字"),
                "font_size": _int_in_range(
                    item.get("font_size"), name=f"第{idx}行文字字号", low=12, high=200, default=36
                ),
                "color": color,
                "border_color": border,
                "vertical": vertical,
                "offset": _int_in_range(item.get("offset"), name=f"第{idx}行文字边距", low=0, high=600, default=10),
            }
        )

    return {"badges": badges, "text_overlays": text_overlays}


def _opacity(raw: Any, idx: int) -> float:
    if raw in (None, ""):
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _bad(f"第{idx}个角标透明度得是 0～1 的小数（现在是 {raw!r}）")
    if not 0.05 <= value <= 1.0:
        # 下限不是 0：0 透明＝一层完全看不见的图占着位置，用户以为叠上了。
        # 引擎侧 clamp 到 0~1（slice.py:1213），这里比它严一档。
        _bad(f"第{idx}个角标透明度只能在 0.05～1 之间（现在是 {value}，0 等于叠了张看不见的图）")
    return round(value, 3)


def overlay_is_empty(params: Optional[Dict[str, Any]]) -> bool:
    badges = (params or {}).get("badges") or []
    texts = (params or {}).get("text_overlays") or []
    return not badges and not texts


def overlay_summary(params: Optional[Dict[str, Any]]) -> str:
    """一行大白话，供界面预告和审计回显（别让人觉得"叠了什么"只有机器知道）。"""
    if overlay_is_empty(params):
        return "不叠加"
    parts: List[str] = []
    badges = (params or {}).get("badges") or []
    if badges:
        parts.append(f"{len(badges)} 个角标（{'、'.join(str(b.get('position')) for b in badges)}）")
    texts = (params or {}).get("text_overlays") or []
    if texts:
        shown = "、".join(str(t.get("text"))[:8] for t in texts)
        parts.append(f"{len(texts)} 行字（{shown}）")
    return " ＋ ".join(parts)


# ─────────────────────────────  引擎子口  ─────────────────────────────

_ENGINE: Any = None
_ENGINE_ERROR: Optional[str] = None


def _engine_path() -> Optional[str]:
    """在 ENGINES_DIR 里找 slice.py。相对路径按 backend 容器 cwd（/app）解析。"""
    candidates = []
    configured = (settings.ENGINES_DIR or "").strip()
    if configured:
        candidates.append(os.path.join(configured, "slice.py"))
        if not os.path.isabs(configured):
            # 本机从仓库根跑 pytest 时 ENGINES_DIR="engines" 指不到，兜一层 ../engines
            candidates.append(os.path.join("..", configured, "slice.py"))
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def _load_engine() -> Tuple[Any, Optional[str]]:
    """懒加载引擎模块，失败回 (None, 人话)。结果缓存（成功或失败都缓存，别每次重导）。

    用 `spec_from_file_location` 而不是 `sys.path.insert + import slice`：
    后者会把整个 engines 目录顶到 sys.path 最前面，`slice` 这个名字太通用
    （且 backend 里已有一个 `app.engines` 包），万一日后被别的模块抢走，
    叠加就会用到**另一个文件**里的函数——那种 bug 查起来极其费眼。
    """
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None or _ENGINE_ERROR is not None:
        return _ENGINE, _ENGINE_ERROR
    path = _engine_path()
    if path is None:
        _ENGINE_ERROR = (
            f"这台机器上找不到切片引擎（{settings.ENGINES_DIR}/slice.py）。"
            "现网 backend 容器是挂载 ./engines 进来的，本地开发机没挂——"
            "所以叠加只能在线上验，本地跑请把这层打桩"
        )
        logger.warning("%s", _ENGINE_ERROR)
        return None, _ENGINE_ERROR
    try:
        spec = importlib.util.spec_from_file_location("asset_overlay_engine", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法从 {path} 载入引擎模块")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for fn in ("apply_badges", "apply_text_overlays"):
            if not hasattr(module, fn):
                raise ImportError(f"引擎 {path} 里没有 {fn}()")
        _ENGINE = module
        logger.info("叠加引擎已载入：%s", path)
    except Exception as exc:  # noqa: BLE001 - 引擎导入失败不能让接口 500
        _ENGINE_ERROR = f"叠加引擎载入失败（{type(exc).__name__}: {exc}）"
        logger.exception("%s", _ENGINE_ERROR)
        sys.modules.pop("asset_overlay_engine", None)
    return _ENGINE, _ENGINE_ERROR


def engine_available() -> Tuple[bool, Optional[str]]:
    """给接口/界面用来老实回答「这台机器能不能自动叠角标」，不抛异常。"""
    module, err = _load_engine()
    return module is not None, err


async def resolve_badges(
    db: AsyncSession, badges: List[Dict[str, Any]], work_dir: str
) -> List[Dict[str, Any]]:
    """把角标从「素材库图片行」翻成引擎要的「本地文件路径」。

    逐张校验：必须是图片（视频当角标 ffmpeg 会当一路视频输入去解码，报一堆看不懂的错）、
    桶里必须有文件。**任何一张取不到就整格失败**——这里不学"跳过无效角标继续叠"
    （引擎 slice.py:1240-1246 那套 `valid` 过滤），因为那是静默交付缺卡的片，
    正是批 G 之后一直在这条线上堵的那类坑。
    """
    if not badges:
        return []
    pairs = await resolve_badge_refs(db, badges)

    from app.services.minio_service import download_to_file  # 延迟导入：单测好打桩

    resolved: List[Dict[str, Any]] = []
    for idx, (badge, asset) in enumerate(pairs):
        ext = os.path.splitext(asset.file_key)[1] or ".png"
        local = os.path.join(work_dir, f"badge_{idx}{ext}")
        ok = await download_to_file(asset.bucket or settings.MINIO_BUCKET_RAW, asset.file_key, local)
        if not ok or not _nonempty(local):
            raise HTTPException(
                status_code=502,
                detail=f"角标「{asset.code}」取回失败（{asset.file_key[:60]}），稍后重试",
            )
        resolved.append({**badge, "path": local})
    return resolved


async def resolve_badge_refs(
    db: AsyncSession, badges: List[Dict[str, Any]]
) -> List[Tuple[Dict[str, Any], AssetItem]]:
    """只查库、不碰桶：把每个角标的 `asset_id` 翻成**已校验过的素材行**。

    为什么单独拆这一层（11-24 需求三 S3，缺口 4b「校验先于投出」）：
    「选了张视频当角标」是**入参错**，不是运行故障。原来只有渲染时才查得出来，于是
    默认后台档会先落一行台账、跑起来第一步才发现叠不了——一线看到的是「组合导出 失败」，
    而不是一句「第 1 个角标不是图片」。拆出来后：接口在 `_start_asset_job` **之前**调它，
    当场 400 白话拒收、台账一行不留；渲染时 `resolve_badges` 再调一次是**二次确认**
    （从提交到真跑之间隔着一段时间，图可能已被人删掉），话术两边同源，不会说岔。
    """
    if not badges:
        return []
    ids = [str(b.get("asset_id")) for b in badges]
    rows = (
        await db.execute(select(AssetItem).where(AssetItem.id.in_(_uuid_list(ids))))
    ).scalars().all()
    by_id = {str(r.id): r for r in rows}

    pairs: List[Tuple[Dict[str, Any], AssetItem]] = []
    for idx, badge in enumerate(badges):
        asset = by_id.get(str(badge.get("asset_id")))
        if asset is None:
            _bad(f"第{idx + 1}个角标对应的图片不在素材库里了（可能已被删除），请重新挑一张")
        if asset.media_kind != MEDIA_IMAGE:
            _bad(f"第{idx + 1}个角标「{asset.code}」不是图片，当不了角标")
        if not asset.file_key:
            _bad(f"第{idx + 1}个角标「{asset.code}」桶里没有文件，换一张")
        pairs.append((badge, asset))
    return pairs


def _uuid_list(values: List[str]) -> List[Any]:
    """自己判 uuid，不去 import `api/assets/misc.py::_as_uuid`。

    service 反过来依赖 api 层是个环（misc.py 正要 import 本模块）。
    校验逻辑就三行，抄一份的代价远小于把分层搞反——但坏值话术保持一致。
    """
    import uuid as _uuid

    out = []
    for value in values:
        try:
            out.append(_uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            _bad(f"角标图片「{value}」不是合法的素材 id")
    return out


def _nonempty(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


async def apply_overlay(
    src: str,
    out: str,
    badges: List[Dict[str, Any]],
    text_overlays: List[Dict[str, Any]],
    *,
    threads: int = 1,
) -> Optional[str]:
    """对一条已拼好的视频叠角标＋文字。成功回 None，失败回**一句给人看的话**。

    两层各跑一次 ffmpeg（重编码两次）。为什么不在这里自己拼一条 filter_complex：
    那是把引擎的两个函数重抄一遍，抄的人不知道 `apply_text_overlays` 今天走
    ASS/libass、drawtext 只是回退档（slice.py:1723-1739 那条 11-22 修复），
    三个月后就会退化成"素材库的字还是用 drawtext，个别字是豆腐"。

    角标先、文字后：文字是剧名/警示语，压在角标之上才看得清。
    """
    if not badges and not text_overlays:
        return None
    engine, err = _load_engine()
    if engine is None:
        return err or "叠加引擎不可用"
    loop = asyncio.get_running_loop()

    def _run() -> Optional[str]:
        current = src
        try:
            if badges:
                stage = out + ".badged.mp4"
                engine.apply_badges(current, stage, badges, threads=threads)
                if not _nonempty(stage):
                    return "角标叠加没有产出文件（ffmpeg 静默失败），请检查角标图"
                current = stage
            if text_overlays:
                stage = out + ".texted.mp4" if badges else out
                engine.apply_text_overlays(current, stage, text_overlays, threads=threads)
                if not _nonempty(stage):
                    return "文字叠加没有产出文件（ffmpeg 静默失败），请检查文字与字体"
                current = stage
            if current != out:
                os.replace(current, out)
            return None
        except Exception as exc:  # noqa: BLE001 - 引擎抛 RuntimeError 带 ffmpeg stderr 尾巴
            logger.exception("叠加渲染异常")
            # 只回原因、不带「叠加失败：」前缀——前缀由调用方统一加，
            # 否则日志里会出现两层前缀，而接口话术和审计话术各说各的。
            return f"{type(exc).__name__}: {exc}"

    return await loop.run_in_executor(None, _run)
