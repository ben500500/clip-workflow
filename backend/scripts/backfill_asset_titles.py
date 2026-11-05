"""历史素材标题一次性补回填（11-06 承诺审计⑤的落地脚本）。

88a7f67 起反推成功会自动回填标题，但已经反推成功、之后再不会被轮询的老素材
永远补不上。本脚本一次性扫完：stage_prompt=success 且 title 为空的素材，
从反推详规起标题（与运行时同一套 `_derive_asset_title_from_script`，宁缺勿滥）。

用法（163 后端容器内）：
    docker exec clip-backend python -c "
        import asyncio; import sys; sys.path.insert(0, '/app')
        from scripts.backfill_asset_titles import main
        asyncio.run(main())"
干跑（只看会起什么标题，不写库）：把 DRY_RUN=True 改环境变量 BACKFILL_TITLES_DRY_RUN=1。
"""

import asyncio
import os

from sqlalchemy import select

from app.api.assets import _derive_asset_title_from_script
from app.database import async_session_factory
from app.models import AssetItem
from wechat_download.models import WechatDlPromptTask

DRY_RUN = os.environ.get("BACKFILL_TITLES_DRY_RUN", "") == "1"


async def main() -> None:
    async with async_session_factory() as s:
        rows = (
            await s.execute(select(AssetItem).where(AssetItem.stage_prompt == "success"))
        ).scalars().all()
        changed = 0
        for a in rows:
            if (a.title or "").strip():
                continue
            task = None
            if a.prompt_task_id:
                task = (
                    await s.execute(
                        select(WechatDlPromptTask).where(WechatDlPromptTask.id == a.prompt_task_id)
                    )
                ).scalar_one_or_none()
            title = _derive_asset_title_from_script(task.content) if task and task.content else None
            print(f"{a.code} -> {title!r}" + ("（dry run，未写库）" if DRY_RUN else ""))
            if title and not DRY_RUN:
                a.title = title
                changed += 1
        if not DRY_RUN:
            await s.commit()
        print(f"done: {changed} 条补上标题")


if __name__ == "__main__":
    asyncio.run(main())
