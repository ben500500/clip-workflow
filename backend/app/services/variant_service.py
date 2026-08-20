"""多视频号素材去重：素材变体生成服务（圆桌定稿 Phase 1 核心工作流）。

职责：
- build_variant_recipes(count, base_dedupe)：基于基础去重配置生成 N 套"结构性差异"参数。
  结构性差异 = 变速/裁切/偏色/噪点/扫描线/暗角/水印 等随机组合，确保各变体在
  画面指纹 + 音频指纹 + 时域序列上同时拉开距离（覆盖平台 L3/L4 盲区）。
- generate_variants_for_output(output, count, recipes)：对基准切片输出派生 N 个变体文件
  （复用 slice 引擎 dedupe 模式），落库 ClipVariant + VideoFingerprint。
- 撞车自动换参重试：每套配方生成后计算指纹，与同组/历史指纹比对，撞车则换参重试（≤N 次）。

护栏：
- count=1 或未配置多版本时完全等同现状（零侵入，可回滚）。
- 撞车失败宁可标记 collision 交给人工处理，绝不把同素材原样发多号。
"""
from __future__ import annotations

import json
import logging
import os
import random
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory
from app.models.models import (
    SliceOutput,
    SliceTask,
    ClipVariant,
    VideoFingerprint,
)
from app.services import fingerprint_service as fp

logger = logging.getLogger(__name__)

# 结构性差异配方生成上限（避免配方爆炸）
MAX_VARIANTS = 20
MAX_RETRY = 5

# 各结构维度的随机取值池（用于组合出差异化配方）
# 裁切保底 ≥0.09、上限 0.13：用保底替换原均匀随机（原 0.04~0.08），
# 保证每个常规配方画面差异都够拉开（稳过 phash 阈值），同时守住画质优先护栏。
_CROP_POOL = [0.09, 0.10, 0.11, 0.12, 0.13]
_SPEED_POOL = [1.03, 1.04, 1.05, 1.06]
_SATURATION_POOL = [0.78, 0.82, 0.85, 0.88, 0.92]
# 画质优先：明显影响画质的颗粒噪点/扫描线/暗角/滚动暗带/抖动在变体配方中
# 统一降到最低值（噪点 ≤2、无扫描线、无暗角、无滚动暗带、无抖动），
# 差异化改由裁切/变速/降饱和/锐化/偏色微量/水印/音频指纹承担。
_NOISE_POOL = [0, 1, 2]
_SCANLINE_POOL = [None]
_VIGNETTE_POOL = [None]
_ROLLBAND_POOL = [0]
_JITTER_POOL = [0]
_SHARPEN_POOL = [0.0, 0.4, 0.6, 0.8]
_WATERMARK_POOL = [
    None,
    {"text": "Clip", "opacity": 0.18},
    {"text": "Dedupe", "opacity": 0.15},
]
_COLORBALANCE_POOL = [
    "rs=0:gs=0:bs=0:rm=0:gm=0:bm=0",
    "rs=.02:gs=.01:bs=-.02:rm=.02:gm=.01:bm=-.02",
    "rs=0:gs=0:bs=0:rm=0:gm=0:bm=0",
    "rs=.02:gs=.02:bs=.02:rm=.02:gm=.02:bm=.02",
]
_TEMP_POOL = ["temperature=6500", "temperature=6400", "temperature=6500", "temperature=6450"]
# 音频指纹差异化模式（L3 盲区覆盖）：每种模式都会改变音频声纹，且人耳几乎无感。
# 已按 audio_v2 指纹在真实素材上复验，均能把音频距离拉过 0.15 阈值（撞车判定线）。
# volume 模式已从 1.12 提至 1.28（engines/slice.py），实测在真实素材上稳定过 0.15。
# 注意：不放入 None —— 派生变体必须始终差异化音频，否则与基准在音频维度距离为 0
# 必然被撞车判定拦下（这正是本迭代修复的音频短板）。
_AUDIO_POOL = ["eq_mild", "eq_strong", "pitch_down", "pitch_up", "bandpass", "bass_boost", "vocal_boost", "volume"]
# L4 时域结构差异：是否把整段拆成多片段并漂移/重排（改场景切分序列指纹）
_STRUCTURAL_SEGMENT_OPTIONS = [False, True]
# 方向一扩展特效：随机给部分派生变体叠加若隐若现星星点/小光环，进一步拉开画面特征。
# 部分为 None（不叠加），部分带参数；固定用低位噪声，透明度极低以保持画面几乎无感。
# 已知项：sparkle 非默认开启（仅 40% 派生变体随机启用），如批量生成性能受影响，下轮可做轻量优化。
# 生产安全开关：geq 全分辨率渲染约 0.5fps，批量切片/生产侧默认不叠加 sparkle（全 None），
# 避免拖慢吞吐。如需启用在配方池里手动放回带参条目即可。
_SPARKLE_ENABLED = False  # 生产默认关闭；True 时按 _SPARKLE_POOL 随机叠加 sparkle
_SPARKLE_POOL = [None] * 5 if not _SPARKLE_ENABLED else [
    None,
    None,
    None,
    {"enabled": True, "count": 3, "size": 3, "opacity": 8},
    {"enabled": True, "count": 5, "size": 2, "opacity": 6},
]


def _pick_audio_mode(used_audio: list) -> str:
    """在同组已用音频模式之外选一个（音频差异化，避免音频维度撞车）。

    优先选尚未用过的模式；池被耗尽时退化为随机。分配后写入 used_audio。
    """
    avail = [m for m in _AUDIO_POOL if m not in used_audio]
    mode = random.choice(avail or _AUDIO_POOL)
    used_audio.append(mode)
    return mode


def build_variant_recipes(count: int, base_dedupe: Optional[dict] = None) -> list[dict]:
    """基于基础去重配置生成 count 套结构性差异配方。

    每套配方 = 一份 dedupe_config（含 preset + manual 手动覆盖），
    各维度在取值池内随机组合，保证任意两套之间存在多处结构差异。
    count 已含基准版（index=1 用基础配置，index>=2 用随机结构差异）。
    """
    count = max(1, min(int(count or 1), MAX_VARIANTS))
    base = base_dedupe or {}
    recipes: list[dict] = []
    # 同组内音频模式去重：保证任意两套派生变体不在音频维度用同一模式，
    # 避免两套变体音频指纹过近被撞车判定拦下（音频差异化是本迭代修复的短板）。
    used_audio: list[str] = []
    for i in range(count):
        if i == 0:
            # 基准版：用基础配置（默认 std_crop_desat 保守裁切降饱和，画质优先）
            recipes.append({"preset": str(base.get("preset") or "std_crop_desat"),
                            "manual": dict(base.get("manual") or {})})
            continue
        # 派生变体：随机组合结构差异，确保与基准及彼此拉开距离。
        # 音频指纹差异化（L3 盲区覆盖）：在同组内优先选择尚未用过的音频模式，
        # 避免重复模式导致两套变体音频维度过近被撞车判定拦下。
        audio_mode = _pick_audio_mode(used_audio)
        manual = {
            "crop": random.choice(_CROP_POOL),
            "hflip": False,  # 全系统默认不做镜像（与推荐配方一致，保持画面可读）
            "speed": random.choice(_SPEED_POOL),
            "saturation": random.choice(_SATURATION_POOL),
            "noise": random.choice(_NOISE_POOL),
            "scanline": random.choice(_SCANLINE_POOL),
            "vignette": random.choice(_VIGNETTE_POOL),
            "roll_band": random.choice(_ROLLBAND_POOL),
            "jitter": random.choice(_JITTER_POOL),
            "sharpen": random.choice(_SHARPEN_POOL),
            "colorbalance": random.choice(_COLORBALANCE_POOL),
            "colortemperature": random.choice(_TEMP_POOL),
            "watermark": random.choice(_WATERMARK_POOL),
            "sparkle": random.choice(_SPARKLE_POOL),
            "audio": audio_mode,
        }
        # 结构性差异（覆盖 L4 时域序列盲区 + L3 音频）：
        #  - structural_diff.segment: 是否把整段拆成多片段并漂移/重排，改场景切分指纹
        #  - structural_diff.reorder: 是否对片段顺序重排（改变时域序列）
        # P3 落地：默认带重排（唯一撞车对全是拆段不重排，reorder=True 变体两两全过）。
        # 运营开关控制（STRUCTURAL_REORDER_DEFAULT，默认开）；segment 仍维持随机 [False,True] 不变。
        # reorder 依赖拆段：仅在 segment=True 且片段数≥3 时生效，故保留 True 作为默认值即可。
        recipes.append({
            "preset": "standard",
            "manual": manual,
            "structural": {
                "segment": random.choice(_STRUCTURAL_SEGMENT_OPTIONS),
                "reorder": settings.STRUCTURAL_REORDER_DEFAULT,
            },
        })
    # A3 性能护栏：无论调用方传入的 base_dedupe/manual 是否带 sparkle（基准版 manual
    # 直接拷贝可能泄漏 sparkle，派生池理论上全 None 但兜底再强制清零一次），统一置 None。
    # sparkle 走 ffmpeg geq 全分辨率渲染约 0.5fps，极易把批量任务拖到超时/进程被杀，
    # 生产默认关闭（_SPARKLE_ENABLED=False），这里从源头保证不再进入配方。
    for r in recipes:
        m = r.get("manual")
        if m and isinstance(m, dict):
            m["sparkle"] = None
    return recipes


def _recipe_fingerprint_key(recipe: dict) -> str:
    """配方指纹 key，用于碰撞重试时换参（保证重试配方不同）。"""
    return json.dumps(recipe, sort_keys=True)


async def _load_output(output_id) -> Optional[SliceOutput]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(SliceOutput).where(SliceOutput.id == uuid.UUID(str(output_id)))
        )
        output = result.scalar_one_or_none()
        # 只读块：async with 退出 close() 会自动回滚事务并归还连接（expire_on_commit=False
        # 不会过期已加载属性），这里显式 rollback() 反而会 expire 返回的 ORM 对象，
        # 导致调用方在会话外访问 output 属性时抛 DetachedInstanceError（#230），故移除。
        return output


async def _load_output_video_path(output: SliceOutput) -> Optional[str]:
    """获取基准切片的本地视频路径（从 MinIO 下载）。"""
    from app.config import settings
    from app.services.minio_service import download_to_file
    from app.utils.helpers import ensure_dir

    if not output.file_key:
        return None
    local = ensure_dir(f"/tmp/variant_src/{output.id}")
    target = os.path.join(local, output.file_name or "base.mp4")
    ok = await download_to_file(settings.MINIO_BUCKET_SLICED, output.file_key, target)
    if not ok or not os.path.isfile(target):
        return None
    return target


async def _save_variant_row(
    output: SliceOutput,
    variant_index: int,
    recipe: dict,
    created_by=None,
    variant_group_id=None,
) -> uuid.UUID:
    async with async_session_factory() as session:
        v = ClipVariant(
            output_id=output.id,
            variant_group_id=variant_group_id,
            variant_index=variant_index,
            dedupe_config=recipe,
            status="pending",
            created_by=uuid.UUID(str(created_by)) if created_by else None,
        )
        session.add(v)
        await session.flush()
        vid = v.id
        await session.commit()
        return vid


async def _update_variant(variant_id, **fields):
    from sqlalchemy import update
    async with async_session_factory() as session:
        await session.execute(
            update(ClipVariant).where(ClipVariant.id == variant_id).values(**fields)
        )
        await session.commit()


async def mark_output_variants_failed(output_id: str, error_message: str) -> int:
    """A1 兜底收敛：把某切片输出下仍处于 running/pending 的变体统一回写 failed。

    generate_variants_task 失败（异常/进程被杀/超时）时调用，杜绝变体永久 running。
    返回被回写的变体数。
    """
    from sqlalchemy import update
    async with async_session_factory() as session:
        result = await session.execute(
            update(ClipVariant)
            .where(ClipVariant.output_id == uuid.UUID(str(output_id)))
            .where(ClipVariant.status.in_(["running", "pending"]))
            .values(status="failed", error_message=error_message)
        )
        await session.commit()
        return result.rowcount or 0


async def _save_fingerprint(
    variant_id, output_id, variant_group_id, file_key, algo, hash_value, vector,
    duration, resolution,
):
    async with async_session_factory() as session:
        session.add(VideoFingerprint(
            variant_id=variant_id,
            output_id=output_id,
            variant_group_id=variant_group_id,
            file_key=file_key,
            algorithm=algo,
            hash_value=hash_value,
            vector=vector,
            duration=duration,
            resolution=resolution,
        ))
        await session.commit()


async def _load_group_fingerprints(variant_group_id) -> list[dict]:
    """加载同组所有已完成的变体指纹（用于撞车比对）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(VideoFingerprint)
            .where(VideoFingerprint.variant_group_id == uuid.UUID(str(variant_group_id)))
            .where(VideoFingerprint.algorithm.in_(["phash_v1", "audio_v2", "seq_v1"]))
        )
        rows = result.scalars().all()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 rows 被 expire，退出会话后访问 r.algorithm 会抛 DetachedInstanceError（#230）。
    return [{
        "algorithm": r.algorithm,
        "hash_value": r.hash_value,
        "vector": r.vector,
    } for r in rows]


async def _check_against_history(full_fp: dict, variant_group_id=None, exclude_variant_id=None) -> dict:
    """把新指纹与同组历史指纹比对，返回最小距离与是否撞车。

    仅与**同变体组**的已生成变体比对（排除自身），避免跨素材误报撞车。
    variant_group_id 为空时仅与自身组比对（实为无历史，返回安全）。
    """
    async with async_session_factory() as session:
        query = (
            select(VideoFingerprint)
            .where(VideoFingerprint.algorithm.in_(["phash_v1", "audio_v2", "seq_v1"]))
        )
        if variant_group_id:
            query = query.where(
                VideoFingerprint.variant_group_id == uuid.UUID(str(variant_group_id))
            )
        if exclude_variant_id:
            query = query.where(
                VideoFingerprint.variant_id != uuid.UUID(str(exclude_variant_id))
            )
        result = await session.execute(query)
        rows = result.scalars().all()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 rows 被 expire，退出会话后访问 r.algorithm 会抛 DetachedInstanceError（#230）。
    if not rows:
        return {"phash_distance": 1.0, "audio_distance": 1.0, "seg_distance": 1.0,
                "combined_distance": 1.0, "collision": False, "collision_reason": ""}
    best = {"phash_distance": 1.0, "audio_distance": 1.0, "seg_distance": 1.0,
            "combined_distance": 1.0}
    for r in rows:
        rfp = {"algorithm": r.algorithm, "hash_value": r.hash_value, "vector": r.vector}
        d = fp.compare_fingerprints(full_fp, rfp)
        best["phash_distance"] = min(best["phash_distance"], d["phash_distance"])
        best["audio_distance"] = min(best["audio_distance"], d["audio_distance"])
        best["seg_distance"] = min(best["seg_distance"], d["seg_distance"])
        best["combined_distance"] = min(best["combined_distance"], d["combined_distance"])
    coll, reason = fp.is_collision(best)
    return {**best, "collision": coll, "collision_reason": reason}


def _build_variant_cutlist(dur: float, structural: dict) -> list[tuple]:
    """生成变体切片列表（L4 时域结构差异）。

    默认返回整段 [(0, dur)]。
    当 structural.segment=True 时，把整段拆成 3~5 个片段，对边界做轻微漂移
    （±0.5~1.5s，避开场景切换点打散时域序列），并可选重排顺序（reorder=True），
    从而改变场景切分序列指纹（平台 L4 比对盲区）。片段均保证正时长、不越界。
    """
    if dur <= 0:
        return [(0.0, 1.0)]
    if not structural.get("segment"):
        return [(0.0, dur)]
    n_parts = random.randint(3, 5)
    n_parts = max(2, min(n_parts, max(1, int(dur) // 3)))
    if n_parts < 2 or dur < 6:
        # 太短/太少不宜拆段，回退整段，避免产生过短片段
        return [(0.0, dur)]
    # 生成 n_parts+1 个切点（含 0 与 dur），每段边界轻微漂移
    pts = [0.0]
    step = dur / n_parts
    for i in range(1, n_parts):
        base = i * step
        # 漂移 ±1.5s，但保留至少 1.5s 缓冲避免片段过短/越界
        drift = random.uniform(-1.5, 1.5)
        pts.append(max(pts[-1] + 1.0, min(dur - 1.0, base + drift)))
    pts.append(dur)
    segs = []
    for i in range(n_parts):
        s = pts[i]
        e = pts[i + 1]
        if e - s >= 0.8:
            segs.append((s, e))
    if len(segs) < 2:
        return [(0.0, dur)]
    # 可选重排：交换末尾两段或打乱相邻两段（保持整体时长近似，避免内容语义跳跃过大）
    if structural.get("reorder") and len(segs) >= 3:
        i = random.randint(0, len(segs) - 2)
        segs[i], segs[i + 1] = segs[i + 1], segs[i]
    return segs


async def _generate_variant_file(source_path: str, recipe: dict, out_name: str) -> str:
    """对基准切片源文件应用一套去重配方，输出一个变体文件，返回本地路径。"""
    from app.services.slice_service import run_slice_fast

    out_dir = f"/tmp/variant_out/{uuid.uuid4()}"
    os.makedirs(out_dir, exist_ok=True)
    # 探测时长
    dur = _probe_duration_sec(source_path)
    # 结构性差异（L4 时域）：把整段拆成多片段并漂移/重排，改变场景切分序列指纹。
    # 引擎对同 name 的多段按顺序拼接为单一输出（dedupe 模式），从而改变 L4 指纹。
    structural = (recipe or {}).get("structural") or {}
    segments = _build_variant_cutlist(dur, structural)
    cutlist_path = os.path.join(out_dir, "cutlist.txt")
    with open(cutlist_path, "w", encoding="utf-8") as f:
        for (s, e) in segments:
            f.write(f"{s:.3f} {e:.3f} variant\n")
    try:
        rc, stdout, stderr = await run_slice_fast(
            source_path, cutlist_path, out_dir, mode="dedupe",
            dedupe_config=recipe,
        )
        if rc != 0:
            raise RuntimeError(stderr or "variant slice failed")
        # 从 manifest 找输出文件
        for line in stdout.splitlines():
            if line.startswith("OUTPUT:"):
                parts = line.split(":", 3)
                if len(parts) >= 2:
                    fpath = os.path.join(out_dir, parts[1])
                    if os.path.isfile(fpath):
                        # 拷贝到稳定的输出路径（避免 finally 清理目录后文件丢失）
                        final_path = f"/tmp/variant_out/{uuid.uuid4()}.mp4"
                        os.makedirs(os.path.dirname(final_path), exist_ok=True)
                        import shutil
                        shutil.copyfile(fpath, final_path)
                        return final_path
        raise RuntimeError("variant engine produced no output file")
    finally:
        import shutil
        try:
            shutil.rmtree(out_dir)
        except OSError:
            pass


def _probe_duration_sec(path: str) -> float:
    try:
        import subprocess
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 10.0)
    except Exception:
        return 10.0


async def generate_variants_for_output(
    output_id: str,
    count: int = 1,
    base_dedupe: Optional[dict] = None,
    created_by: Optional[str] = None,
    thresholds: Optional[dict] = None,
    bucket: str = "sliced",
) -> dict:
    """为基准切片输出生成 count 个变体（含基准 index=1）。

    流程：建立变体组 → 逐套配方生成变体文件 → 计算指纹 → 与同组历史比对 →
    撞车则换参重试（≤MAX_RETRY）→ 落库 ClipVariant + VideoFingerprint。
    返回 {variant_count, variants: [...], collisions: [...]}。
    """
    output = await _load_output(output_id)
    if output is None:
        return {"error": "output not found", "variant_count": 0, "variants": []}
    if int(count or 1) <= 1:
        # 零侵入：不生成派生变体，直接返回基准
        return {"variant_count": 1, "variants": [{"index": 1, "output_id": str(output.id)}], "collisions": []}

    source_path = await _load_output_video_path(output)
    if source_path is None:
        return {"error": "source video not found", "variant_count": 0, "variants": []}

    # 建立变体组（与基准输出同组）
    variant_group_id = uuid.uuid4()
    async with async_session_factory() as session:
        await session.execute(
            __import__("sqlalchemy").update(SliceOutput)
            .where(SliceOutput.id == output.id)
            .values(variant_group_id=variant_group_id)
        )
        await session.commit()

    recipes = build_variant_recipes(int(count), base_dedupe)
    # 收集同组已分配的音频模式：撞车换参重试需沿用同一去重集（而非重建空池），
    # 否则重试配方可能在音频维度随机到已用模式，导致音频距离不足被撞车判定拦下。
    used_audio: list = [r["manual"]["audio"] for r in recipes if r.get("manual", {}).get("audio")]
    results = []
    collisions = []
    used_recipes: set[str] = set()

    for idx, recipe in enumerate(recipes, start=1):
        variant_id = await _save_variant_row(output, idx, recipe, created_by, variant_group_id)
        await _update_variant(variant_id, status="running")
        ok = False
        retry = 0
        recipe_attempt = recipe
        while retry <= MAX_RETRY:
            try:
                key = _recipe_fingerprint_key(recipe_attempt)
                if key in used_recipes:
                    recipe_attempt = _regenerate_recipe(base_dedupe, recipe, used_audio)
                    retry += 1
                    continue
                used_recipes.add(key)
                local = await _generate_variant_file(source_path, recipe_attempt, f"variant_{idx}.mp4")
                # 上传 MinIO
                from app.config import settings
                from app.services.minio_service import upload_file_from_path
                file_key = f"variants/{output.id}/{variant_id}/variant_{idx}.mp4"
                up_ok = await upload_file_from_path(bucket, file_key, local)
                if not up_ok:
                    raise RuntimeError("variant upload failed")
                fsize = os.path.getsize(local)
                import subprocess
                from app.services.fingerprint_service import _probe_duration, _probe_resolution
                dur = _probe_duration(local)
                res = _probe_resolution(local)
                # 指纹
                full_fp = fp.compute_full_fingerprint(local)
                await _save_fingerprint(
                    variant_id, output.id, variant_group_id, file_key,
                    "phash_v1", full_fp["phash"], full_fp["phash_vector"], dur, res,
                )
                await _save_fingerprint(
                    variant_id, output.id, variant_group_id, file_key,
                    "audio_v2", full_fp["audio_hash"], full_fp["audio_vector"], dur, None,
                )
                await _save_fingerprint(
                    variant_id, output.id, variant_group_id, file_key,
                    "seq_v1", full_fp["seg_hash"], full_fp["seg_vector"], dur, None,
                )
                # 撞车比对
                chk = await _check_against_history(full_fp, variant_group_id=variant_group_id, exclude_variant_id=variant_id)
                await _update_variant(
                    variant_id,
                    file_key=file_key, file_name=f"variant_{idx}.mp4",
                    file_size=fsize, duration=dur, resolution=res,
                    dedupe_config=recipe_attempt,
                    structural_diff=(recipe_attempt or {}).get("structural"),
                    phash_distance=chk["phash_distance"],
                    audio_distance=chk["audio_distance"],
                    seg_distance=chk.get("seg_distance"),
                    collision=chk["collision"],
                    collision_reason=chk["collision_reason"],
                    status="completed",
                )
                if chk["collision"]:
                    collisions.append({"index": idx, "variant_id": str(variant_id),
                                       "reason": chk["collision_reason"]})
                results.append({"index": idx, "variant_id": str(variant_id),
                                "file_key": file_key, "collision": chk["collision"],
                                "phash_distance": chk["phash_distance"],
                                "audio_distance": chk["audio_distance"]})
                # 清理本地变体文件（已上传 MinIO）
                try:
                    os.unlink(local)
                except OSError:
                    pass
                ok = True
                break
            except Exception as e:
                logger.warning("variant %s recipe %s failed: %s (retry %s)", idx, recipe_attempt, e, retry)
                recipe_attempt = _regenerate_recipe(base_dedupe, recipe, used_audio)
                retry += 1
                if retry > MAX_RETRY:
                    await _update_variant(variant_id, status="failed", error_message=str(e))
                    break
        if not ok:
            continue

    # 清理源文件
    try:
        os.unlink(source_path)
    except OSError:
        pass
    return {"variant_count": len(results), "variants": results, "collisions": collisions}


def _regenerate_recipe(base: Optional[dict], prev: dict, used_audio: list) -> dict:
    """换参：在配方各维度上随机扰动，生成一个与 prev 不同的配方。

    音频维度沿用同组 used_audio 去重集（优先选未用过的音频模式），
    不重建空池，避免重试配方随机回已用模式导致音频维度撞车。
    """
    new = build_variant_recipes(2, base)[1]
    # 音频沿用同组去重集：强制分配一个尚未用过的音频模式
    new["manual"]["audio"] = _pick_audio_mode(used_audio)
    # 确保与 prev 不同
    if _recipe_fingerprint_key(new) == _recipe_fingerprint_key(prev):
        new["manual"]["speed"] = float(new["manual"]["speed"]) + 0.01
    return new


async def verify_variant_fingerprint(variant_id: str, thresholds: Optional[dict] = None) -> dict:
    """发布前复核变体指纹（确认其与同组其它变体拉开距离）。

    供发布前调用，返回 {safe, distances, reason}；不安全则要求人工处理。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(ClipVariant).where(ClipVariant.id == uuid.UUID(str(variant_id)))
        )
        variant = result.scalar_one_or_none()
        if variant is None:
            await session.rollback()
            return {"safe": False, "reason": "variant not found"}
        vgid = variant.variant_group_id
        # 事务内只读：显式结束事务
        await session.rollback()
    if not vgid:
        return {"safe": True, "distances": {"combined_distance": 1.0}, "reason": "standalone variant"}
    group_fps = await _load_group_fingerprints(vgid)
    # 构造该变体的指纹（从库中取）
    async with async_session_factory() as session:
        result = await session.execute(
            select(VideoFingerprint).where(VideoFingerprint.variant_id == uuid.UUID(str(variant_id)))
        )
        rows = result.scalars().all()
        # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
        # 否则 rows 被 expire，退出会话后访问 r.algorithm 会抛 DetachedInstanceError（#230）。
    fp_map = {r.algorithm: {"algorithm": r.algorithm, "hash_value": r.hash_value, "vector": r.vector}
              for r in rows}
    # 与同组其它变体比对
    best = {"phash_distance": 1.0, "audio_distance": 1.0, "seg_distance": 1.0,
            "combined_distance": 1.0}
    for g in group_fps:
        mine = fp_map.get(g["algorithm"])
        if not mine:
            continue
        d = fp.compare_fingerprints(mine, g)
        best["phash_distance"] = min(best["phash_distance"], d["phash_distance"])
        best["audio_distance"] = min(best["audio_distance"], d["audio_distance"])
        best["seg_distance"] = min(best["seg_distance"], d["seg_distance"])
        best["combined_distance"] = min(best["combined_distance"], d["combined_distance"])
    coll, reason = fp.is_collision(best, thresholds)
    return {"safe": not coll, "distances": best, "reason": reason or "ok"}


async def guard_account_variant_unique(account_id, output_id=None, variant_group_id=None) -> dict:
    """发布护栏：校验「一个账号只绑定一个变体」。

    在发布/绑定前调用。语义如下：
    - 账号未绑定任何变体，或目标素材未开多版本（无变体组）→ 允许（发布基准）。
    - 账号已绑定变体，且该变体属于目标素材所在变体组 → 允许（该账号发布自己的去重变体）。
    - 账号已绑定**其它素材**（异变体组）的变体 → 拒绝（账号已专用于另一素材，
      继续发本素材会退化为"基准裸发"，违背"绝不把同一素材原样发多号"）。

    返回 {allowed, reason, occupied_variant_id}。
    """
    if not account_id:
        return {"allowed": True, "reason": "", "occupied_variant_id": None}
    try:
        acc = uuid.UUID(str(account_id))
    except (ValueError, AttributeError):
        return {"allowed": True, "reason": "", "occupied_variant_id": None}

    async with async_session_factory() as session:
        # 该账号当前绑定的变体
        occupied = (await session.execute(
            select(ClipVariant).where(ClipVariant.account_id == acc)
        )).scalar_one_or_none()
        if occupied is None:
            await session.rollback()
            return {"allowed": True, "reason": "", "occupied_variant_id": None}

        # 确定目标变体组：优先用传入的 group，其次由 output_id 推导
        target_group = variant_group_id
        if not target_group and output_id:
            try:
                out = (await session.execute(
                    select(SliceOutput).where(SliceOutput.id == uuid.UUID(str(output_id)))
                )).scalar_one_or_none()
                if out:
                    target_group = out.variant_group_id
            except (ValueError, AttributeError):
                target_group = None

        # 账号已绑定变体：同组 → 发布自己的去重变体（允许）；异组 → 该账号专用于其它素材，拒绝
        if target_group and occupied.variant_group_id:
            if str(occupied.variant_group_id) == str(target_group):
                # 同素材组：该账号发布自己的变体（一账号一变体），正常放行
                await session.rollback()
                return {
                    "allowed": True,
                    "reason": "",
                    "occupied_variant_id": str(occupied.id),
                }
            # 异组：账号已绑定其它素材的变体，不能再来发本素材（避免基准裸发）
            await session.rollback()
            return {
                "allowed": False,
                "reason": f"该账号已绑定其它素材的变体（{occupied.variant_index} 号），请先解绑或另选未绑定账号",
                "occupied_variant_id": str(occupied.id),
            }
        await session.rollback()
    return {"allowed": True, "reason": "", "occupied_variant_id": None}
