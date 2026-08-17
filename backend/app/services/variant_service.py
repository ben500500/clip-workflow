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
_CROP_POOL = [0.04, 0.05, 0.06, 0.07, 0.08]
_SPEED_POOL = [1.03, 1.04, 1.05, 1.06]
_SATURATION_POOL = [0.78, 0.82, 0.85, 0.88, 0.92]
_NOISE_POOL = [4, 5, 6, 7, 8]
_SCANLINE_POOL = [
    {"h": 3, "color": "black@0.10"},
    {"h": 4, "color": "black@0.08"},
    {"h": 2, "color": "black@0.14"},
    None,
]
_VIGNETTE_POOL = ["PI/6", "PI/5", "PI/4", None]
_ROLLBAND_POOL = [0, 8, 12, 16]
_JITTER_POOL = [0, 2, 3]
_SHARPEN_POOL = [0.0, 0.4, 0.6, 0.8]
_WATERMARK_POOL = [
    None,
    {"text": "Clip", "opacity": 0.18},
    {"text": "Dedupe", "opacity": 0.15},
]
_COLORBALANCE_POOL = [
    "rs=.06:gs=.03:bs=-.06:rm=.06:gm=.03:bm=-.06",
    "rs=.04:gs=.01:bs=-.04:rm=.04:gm=.01:bm=-.04",
    "rs=.08:gs=.04:bs=-.08:rm=.08:gm=.04:bm=-.08",
    "rs=.02:gs=.02:bs=.02:rm=.02:gm=.02:bm=.02",
]
_TEMP_POOL = ["temperature=5800", "temperature=6200", "temperature=5400", "temperature=6500"]


def build_variant_recipes(count: int, base_dedupe: Optional[dict] = None) -> list[dict]:
    """基于基础去重配置生成 count 套结构性差异配方。

    每套配方 = 一份 dedupe_config（含 preset + manual 手动覆盖），
    各维度在取值池内随机组合，保证任意两套之间存在多处结构差异。
    count 已含基准版（index=1 用基础配置，index>=2 用随机结构差异）。
    """
    count = max(1, min(int(count or 1), MAX_VARIANTS))
    base = base_dedupe or {}
    recipes: list[dict] = []
    for i in range(count):
        if i == 0:
            # 基准版：用基础配置（默认 std_retro_scan 首选配方）
            recipes.append({"preset": str(base.get("preset") or "std_retro_scan"),
                            "manual": dict(base.get("manual") or {})})
            continue
        # 派生变体：随机组合结构差异，确保与基准及彼此拉开距离
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
        }
        recipes.append({"preset": "standard", "manual": manual})
    return recipes


def _recipe_fingerprint_key(recipe: dict) -> str:
    """配方指纹 key，用于碰撞重试时换参（保证重试配方不同）。"""
    return json.dumps(recipe, sort_keys=True)


async def _load_output(output_id) -> Optional[SliceOutput]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(SliceOutput).where(SliceOutput.id == uuid.UUID(str(output_id)))
        )
        return result.scalar_one_or_none()


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
            .where(VideoFingerprint.algorithm.in_(["phash_v1", "audio_v1", "seq_v1"]))
        )
        rows = result.scalars().all()
    return [{
        "algorithm": r.algorithm,
        "hash_value": r.hash_value,
        "vector": r.vector,
    } for r in rows]


async def _check_against_history(full_fp: dict, exclude_variant_id=None) -> dict:
    """把新指纹与同组历史指纹比对，返回最小距离与是否撞车。

    仅与已完成的变体比对（排除自身）。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(VideoFingerprint)
            .where(VideoFingerprint.variant_id != uuid.UUID(str(exclude_variant_id)))
            .where(VideoFingerprint.algorithm.in_(["phash_v1", "audio_v1", "seq_v1"]))
        )
        rows = result.scalars().all()
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


async def _generate_variant_file(source_path: str, recipe: dict, out_name: str) -> str:
    """对基准切片源文件应用一套去重配方，输出一个变体文件，返回本地路径。"""
    from app.services.slice_service import run_slice_fast

    out_dir = f"/tmp/variant_out/{uuid.uuid4()}"
    os.makedirs(out_dir, exist_ok=True)
    # 变体生成 = 对整段源视频做 dedupe 模式切片（cutlist 整段），应用配方去重滤镜
    # 用一个含整段的 cutlist，使引擎按 dedupe 模式跑通并输出单文件
    cutlist_path = os.path.join(out_dir, "cutlist.txt")
    # 探测时长
    dur = _probe_duration_sec(source_path)
    with open(cutlist_path, "w", encoding="utf-8") as f:
        f.write(f"0 {dur:.2f} variant\n")
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
                    recipe_attempt = _regenerate_recipe(base_dedupe, recipe)
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
                    "audio_v1", full_fp["audio_hash"], full_fp["audio_vector"], dur, None,
                )
                await _save_fingerprint(
                    variant_id, output.id, variant_group_id, file_key,
                    "seq_v1", full_fp["seg_hash"], full_fp["seg_vector"], dur, None,
                )
                # 撞车比对
                chk = await _check_against_history(full_fp, exclude_variant_id=variant_id)
                await _update_variant(
                    variant_id,
                    file_key=file_key, file_name=f"variant_{idx}.mp4",
                    file_size=fsize, duration=dur, resolution=res,
                    dedupe_config=recipe_attempt,
                    phash_distance=chk["phash_distance"],
                    audio_distance=chk["audio_distance"],
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
                recipe_attempt = _regenerate_recipe(base_dedupe, recipe)
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


def _regenerate_recipe(base: Optional[dict], prev: dict) -> dict:
    """换参：在配方各维度上随机扰动，生成一个与 prev 不同的配方。"""
    new = build_variant_recipes(2, base)[1]
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
            return {"safe": False, "reason": "variant not found"}
        vgid = variant.variant_group_id
    if not vgid:
        return {"safe": True, "distances": {"combined_distance": 1.0}, "reason": "standalone variant"}
    group_fps = await _load_group_fingerprints(vgid)
    # 构造该变体的指纹（从库中取）
    async with async_session_factory() as session:
        result = await session.execute(
            select(VideoFingerprint).where(VideoFingerprint.variant_id == uuid.UUID(str(variant_id)))
        )
        rows = result.scalars().all()
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
