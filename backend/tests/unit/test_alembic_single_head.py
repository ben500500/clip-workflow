"""迁移链必须单头（2026-11-23 加）。

为什么要有这条：11-23 两条并行线各自从 0074 分叉新增迁移（极简模式 `0075_asset_scripts_ui_config`
与切片线 `0075_autoclip_run_reuse`），`down_revision` 都写了 0074——alembic 立刻双头。
163 的迁移容器靠 `stamp head` 记版本，双头会报 Multiple head revisions（那条命令失败被
`|| echo` 吞掉、不拦部署），结果是版本表永远停在旧值、以后任何一条迁移都接不准。

本用例直接读 alembic 的脚本目录（不连库、不 import 业务代码，毫秒级）：
- 头必须恰好 1 个；
- 从头往回走必须能走到底（链不断、没有指向不存在版本的 down_revision）。
谁后提交迁移，谁把自己的 down_revision 接到当时的头上。
"""

import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# 让 backend 作为根包可导入，并补齐 conftest 的 autouse 夹具导入 settings 时要求的四个键
# （本用例自己不碰库，但 conftest 对所有用例生效——单跑本文件时没有别的测试模块替它设）
# backend/ 是 app.* 的根；alembic/ 在**仓库根**（比 backend 高一层）
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")


def _scripts() -> ScriptDirectory:
    cfg = Config(str(_REPO / "alembic" / "alembic.ini"))
    # ini 里的 script_location 是相对路径（相对 cwd）；这里钉成绝对路径，测试在哪个目录跑都一样
    cfg.set_main_option("script_location", str(_REPO / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_alembic_has_exactly_one_head():
    heads = _scripts().get_heads()
    assert len(heads) == 1, (
        f"alembic 出现了 {len(heads)} 个头：{sorted(heads)}——两条线各自新增迁移时都接在了同一个"
        " down_revision 上。谁后提交谁改接到当时的头后面（只改 down_revision 一行）。"
    )


def test_alembic_chain_is_contiguous():
    scripts = _scripts()
    # walk_revisions 从头往回走；链里若有指向不存在版本的 down_revision，alembic 会在这里抛错
    revisions = [rev.revision for rev in scripts.walk_revisions()]
    assert revisions, "迁移目录是空的"
    assert len(revisions) == len(set(revisions)), "revision id 有重复"
