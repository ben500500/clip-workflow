"""批X-补：存量候选文案补镜像到极简脚本库（11-25 用户口径「可以，这个补一下」）。

一次性数据脚本，在 163 clip-backend 容器里用
`cat 本文件 | ssh 163 'docker exec -i clip-backend python -'` 执行：
只复用生产同款 `_mirror_scripts_for_summaries` 写 asset_scripts（插入/收编挂载体），
不改代码、不重启容器、不碰在途任务。

默认 DRY：全流程真跑（含 twin 命中与载体收编），最后 rollback，只出报表。
带 `--write` 才 commit。幂等：need_mirror 判据（carrier_summary_id 不存在）+
函数内部 twin 检查，重复执行不会双写。
"""
import asyncio
import sys

from sqlalchemy import func, or_, select, text
from app.database import async_session_factory, engine
from app.models.asset import AssetBatch, AssetItem, AssetScript, AssetSummary
from app.models.user import User
from app.api.assets.misc import _mirror_scripts_for_summaries

WRITE = "--write" in sys.argv


def _need_mirror_cond():
    return (
        or_(AssetSummary.is_shell.is_(False), AssetSummary.is_shell.is_(None)),
        AssetSummary.text.isnot(None),
        func.length(func.trim(AssetSummary.text)) > 0,
        ~select(AssetScript.id)
        .where(AssetScript.carrier_summary_id == AssetSummary.id)
        .exists(),
    )


async def main():
    print("MODE:", "WRITE(commit)" if WRITE else "DRY(rollback)")
    async with engine.connect() as c:
        p = dict(
            (
                await c.execute(
                    text(
                        "select status, count(*) from asset_productions "
                        "where status in ('queued','running') group by 1"
                    )
                )
            ).fetchall()
        )
        j = dict(
            (
                await c.execute(
                    text(
                        "select status, count(*) from asset_jobs "
                        "where status in ('pending','running') group by 1"
                    )
                )
            ).fetchall()
        )
    print("在途核查(本脚本不重启容器，仅作记录):", "productions:", p or "无", "| jobs:", j or "无")

    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(AssetSummary, AssetItem.created_by, AssetBatch.created_by)
                .join(AssetItem, AssetItem.id == AssetSummary.asset_id)
                .outerjoin(AssetBatch, AssetBatch.id == AssetItem.batch_id)
                .where(*_need_mirror_cond())
                .order_by(AssetSummary.created_at)
            )
        ).all()
        print("need_mirror 候选总数:", len(rows))

        buckets = {}
        orphan = 0
        for summary, item_owner, batch_owner in rows:
            owner = item_owner or batch_owner
            if owner is None:
                orphan += 1
                continue
            buckets.setdefault(owner, []).append(summary)
        if orphan:
            print("无归属(素材与批次都查不到上传者)，跳过:", orphan)

        users = {
            str(u.id): u
            for u in (
                await db.execute(select(User).where(User.id.in_([str(k) for k in buckets])))
            ).scalars()
        }
        for owner, sums in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            user = users.get(str(owner))
            if user is None:
                print("owner", owner, "候选", len(sums), "→ users 表无此行，跳过")
                continue
            made = await _mirror_scripts_for_summaries(db, sums, operator=user)
            print(
                "owner",
                owner,
                f"({getattr(user, 'username', None) or getattr(user, 'display_name', '?')})",
                "候选",
                len(sums),
                "→ 新建镜像",
                len(made),
                "收编/命中twin",
                len(sums) - len(made),
            )
        await db.flush()

        left = (
            await db.execute(select(func.count()).select_from(AssetSummary).where(*_need_mirror_cond()))
        ).scalar()
        print("执行后仍缺镜像:", left)
        print("mirror 脚本总行数:", (await db.execute(select(func.count()).select_from(AssetScript).where(AssetScript.source_kind == "mirror"))).scalar())

        if WRITE:
            await db.commit()
            print("COMMITTED")
        else:
            await db.rollback()
            print("ROLLED BACK (dry)")
    await engine.dispose()
    print("BACKFILL_DONE")


asyncio.run(main())
