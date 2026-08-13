#!/usr/bin/env python3
"""clip-workflow 孤儿资源自查 / 清理工具。

扫描以下三类「数据库已不存在、但存储里还留着」的孤儿资源并清理：
  1. MinIO raw-footage 桶：对象 key 不在任何 episode / slice_task 的 source_file_key 中
  2. MinIO sliced 桶：slices/{episode_id}/ 下的 episode_id 在 episodes 表中已不存在
  3. media 卷（/app/media）：
       - {uuid}.mp4                        不在 autoclip_projects.autoclip_project_id
       - data/output/metadata/{uuid}/      不在 autoclip_projects.autoclip_project_id
       - data/asr_cache/{uuid}-*           不在 autoclip_projects.autoclip_project_id

运行方式（在 backend 容器内，复用其 DB / MinIO 配置）：
    docker compose exec backend python scripts/cleanup_orphans.py            # 默认 dry-run，只报告
    docker compose exec backend python scripts/cleanup_orphans.py --delete   # 删除前交互确认
    docker compose exec backend python scripts/cleanup_orphans.py --delete --yes  # 直接删除

注意：
  - 默认不删除，只打印待清理清单与可释放空间，请先 review。
  - 运行时若 media 删除报 PermissionError，说明 autoclip 镜像尚未应用 0777 权限修复，
    请先 `docker compose up -d --build autoclip` 重建后再跑本工具。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

# backend 应用内模块（脚本在 backend 容器内以 /app 为工作目录运行）
from app.config import settings
from app.database import async_session_factory
from app.models.models import Episode, SliceTask, AutoClipProject
from app.services.minio_service import list_files, delete_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cleanup] %(levelname)s %(message)s",
)
logger = logging.getLogger("cleanup_orphans")

MEDIA_BASE = Path("/app/media")


def human_size(n: int) -> str:
    n = max(0, int(n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n}B"


def media_path_size(p: Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for root, _dirs, files in os.walk(p):
            for f in files:
                fp = Path(root) / f
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


async def _collect_valid() -> tuple[set[str], set[str], set[str]]:
    valid_raw_keys: set[str] = set()
    valid_episode_ids: set[str] = set()
    valid_media_ids: set[str] = set()
    async with async_session_factory() as session:
        rs = await session.execute(select(Episode.source_file_key))
        for (k,) in rs.all():
            if k:
                valid_raw_keys.add(k)
        rs = await session.execute(select(SliceTask.source_file_key))
        for (k,) in rs.all():
            if k:
                valid_raw_keys.add(k)
        rs = await session.execute(select(Episode.id))
        for (i,) in rs.all():
            valid_episode_ids.add(str(i))
        rs = await session.execute(
            select(AutoClipProject.autoclip_project_id).where(
                AutoClipProject.autoclip_project_id.is_not(None)
            )
        )
        for (k,) in rs.all():
            if k:
                valid_media_ids.add(k)
    return valid_raw_keys, valid_episode_ids, valid_media_ids


async def _scan_raw(valid_raw_keys: set[str]) -> tuple[list[dict], int]:
    orphans: list[dict] = []
    total = 0
    objs = await list_files(settings.MINIO_BUCKET_RAW, "")
    for o in objs:
        if o["key"] not in valid_raw_keys:
            orphans.append(o)
            total += int(o.get("size") or 0)
    return orphans, total


async def _scan_sliced(valid_episode_ids: set[str]) -> tuple[list[dict], int]:
    orphans: list[dict] = []
    total = 0
    objs = await list_files(settings.MINIO_BUCKET_SLICED, "")
    for o in objs:
        parts = o["key"].split("/")
        # 仅处理 slices/{episode_id}/... 结构
        if len(parts) >= 2 and parts[0] == "slices":
            if parts[1] not in valid_episode_ids:
                orphans.append(o)
                total += int(o.get("size") or 0)
        # 其它前缀（非 slices/）保持不动，避免误删未知结构
    return orphans, total


def _scan_media(valid_media_ids: set[str]) -> tuple[list[tuple[Path, int]], int]:
    orphans: list[tuple[Path, int]] = []
    total = 0
    if not MEDIA_BASE.is_dir():
        return orphans, total

    for p in MEDIA_BASE.glob("*.mp4"):
        if p.stem not in valid_media_ids:
            sz = media_path_size(p)
            orphans.append((p, sz))
            total += sz

    md = MEDIA_BASE / "data/output/metadata"
    if md.is_dir():
        for d in md.glob("*"):
            if d.is_dir() and d.name not in valid_media_ids:
                sz = media_path_size(d)
                orphans.append((d, sz))
                total += sz

    ad = MEDIA_BASE / "data/asr_cache"
    if ad.is_dir():
        for f in ad.glob("*"):
            if f.name.split("-")[0] not in valid_media_ids:
                sz = media_path_size(f)
                orphans.append((f, sz))
                total += sz
    return orphans, total


def _remove_media(p: Path) -> bool:
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return True
    except PermissionError as e:
        logger.error("权限不足，无法删除 %s: %s（请先重建 autoclip 镜像以应用 0777 权限修复）", p, e)
        return False
    except OSError as e:
        logger.error("删除失败 %s: %s", p, e)
        return False


async def main() -> int:
    parser = argparse.ArgumentParser(description="clip-workflow 孤儿资源清理")
    parser.add_argument("--delete", action="store_true", help="实际删除（默认仅 dry-run 报告）")
    parser.add_argument("--yes", action="store_true", help="删除前不交互确认（需配合 --delete）")
    args = parser.parse_args()

    logger.info("开始扫描孤儿资源 ...")
    valid_raw, valid_ep, valid_media = await _collect_valid()
    logger.info(
        "有效引用: raw/slice 源 key %d 个, episode %d 个, media 项目 %d 个",
        len(valid_raw), len(valid_ep), len(valid_media),
    )

    raw_orphans, raw_size = await _scan_raw(valid_raw)
    sliced_orphans, sliced_size = await _scan_sliced(valid_ep)
    media_orphans, media_size = _scan_media(valid_media)

    print("\n================ 孤儿资源报告 ================")
    print(f"[MinIO raw-footage] 桶={settings.MINIO_BUCKET_RAW}")
    print(f"    孤儿对象 {len(raw_orphans)} 个, 可释放 {human_size(raw_size)}")
    for o in raw_orphans[:50]:
        print(f"      - {o['key']}  ({human_size(int(o.get('size') or 0))})")
    if len(raw_orphans) > 50:
        print(f"      ... 其余 {len(raw_orphans) - 50} 个省略")

    print(f"\n[MinIO sliced] 桶={settings.MINIO_BUCKET_SLICED}")
    print(f"    孤儿对象 {len(sliced_orphans)} 个, 可释放 {human_size(sliced_size)}")
    for o in sliced_orphans[:50]:
        print(f"      - {o['key']}  ({human_size(int(o.get('size') or 0))})")
    if len(sliced_orphans) > 50:
        print(f"      ... 其余 {len(sliced_orphans) - 50} 个省略")

    print(f"\n[media 卷] 路径={MEDIA_BASE}")
    print(f"    孤儿条目 {len(media_orphans)} 个, 可释放 {human_size(media_size)}")
    for p, sz in media_orphans[:50]:
        print(f"      - {p}  ({human_size(sz)})")
    if len(media_orphans) > 50:
        print(f"      ... 其余 {len(media_orphans) - 50} 个省略")

    total_size = raw_size + sliced_size + media_size
    total_count = len(raw_orphans) + len(sliced_orphans) + len(media_orphans)
    print("\n==============================================")
    print(f"合计孤儿 {total_count} 项, 可释放空间 {human_size(total_size)}")
    print("==============================================\n")

    if not args.delete:
        print("（dry-run）未做任何删除。确认无误后加 --delete 执行；需跳过确认再加 --yes。")
        return 0

    if not args.yes:
        ans = input(f"确认删除以上 {total_count} 项孤儿资源？[y/N] ").strip().lower()
        if ans != "y":
            print("已取消。")
            return 0

    removed = 0
    # MinIO raw
    for o in raw_orphans:
        if await delete_file(settings.MINIO_BUCKET_RAW, o["key"]):
            removed += 1
    # MinIO sliced
    for o in sliced_orphans:
        if await delete_file(settings.MINIO_BUCKET_SLICED, o["key"]):
            removed += 1
    # media
    for p, _sz in media_orphans:
        if _remove_media(p):
            removed += 1

    logger.info("已删除 %d / %d 项孤儿资源", removed, total_count)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
