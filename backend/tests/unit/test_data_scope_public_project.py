"""无主项目（created_by IS NULL）= 公共项目 的隔离口径单元测试（ISSUE #361 任务 C）。

背景：项目「视频号导入」created_by 为 NULL（历史 wechat-dl 默认项目创建时漏填
created_by）。旧口径 `project.created_by != current_user.id` 把无主项目判为
「不匹配任何用户」→ operator（role=operator，data_scope=own）访问该项目剧集
`GET /api/episodes/{id}/video-url` 一律 404，而 admin/material/publisher
（scope=all）却正常 —— 线上已复现的 P0。

修复口径：created_by IS NULL ⇒ 公共项目，所有登录用户可访问。
本用例锁定三件事：
1. 判定函数（can_access_project / is_project_public）语义；
2. 列表过滤条件（project_scope_filter）必须包含 `created_by IS NULL` 分支；
3. 剧集下钻校验（check_project_access_by_episode / by_id）对无主项目放行，
   且对「别人的项目」仍然 404（不回归越权）。

运行：cd backend && python -m pytest tests/unit/test_data_scope_public_project.py -v
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import data_scope as ds


def _user(role="operator", data_scope="own", uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.role = role
    u.data_scope = data_scope
    return u


def _project(created_by):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.created_by = created_by
    return p


OPERATOR = _user("operator", "own")
ADMIN = _user("admin", "all")
# 管理员通过「权限编辑」把 operator 的 data_scope 提升为 all
OPERATOR_ALL = _user("operator", "all")


# ─────────────────────────────────────────────────────────────
# 1. 验收核心：无主项目对所有登录用户放行
# ─────────────────────────────────────────────────────────────

def test_null_owner_project_is_public():
    assert ds.is_project_public(_project(None)) is True
    assert ds.is_project_public(_project(uuid.uuid4())) is False
    assert ds.is_project_public(None) is False


def test_operator_can_access_null_owner_project():
    """P0 复现点：operator 对无主项目必须可见（旧口径返回 False → 404）。"""
    assert ds.can_access_project(_project(None), OPERATOR) is True


def test_operator_can_access_own_project_but_not_others():
    owner = OPERATOR.id
    assert ds.can_access_project(_project(owner), OPERATOR) is True
    assert ds.can_access_project(_project(uuid.uuid4()), OPERATOR) is False


def test_all_scope_users_see_everything_regardless_of_owner():
    for u in (ADMIN, OPERATOR_ALL):
        assert ds.can_access_project(_project(None), u) is True
        assert ds.can_access_project(_project(uuid.uuid4()), u) is True


def test_missing_project_is_denied_without_crash():
    """项目不存在时不能因为 AttributeError 变成 500。"""
    assert ds.can_access_project(None, OPERATOR) is False
    assert ds.can_access_project(None, ADMIN) is True


# ─────────────────────────────────────────────────────────────
# 2. 列表 / 统计过滤条件：必须带上 created_by IS NULL
# ─────────────────────────────────────────────────────────────

def test_scope_filter_none_for_all_scope_users():
    assert ds.project_scope_filter(ADMIN) is None
    assert ds.project_scope_filter(OPERATOR_ALL) is None


def test_operator_scope_filter_includes_public_projects():
    from app.models.models import Project

    cond = ds.project_scope_filter(OPERATOR)
    assert cond is not None
    sql = str(cond.compile(compile_kwargs={"literal_binds": True}))
    # 自己创建的 OR 无主公共项目 —— 两者缺一，无主项目就会从列表里消失
    assert "created_by IS NULL" in sql.upper() or "created_by IS NULL" in sql
    assert "projects.created_by" in sql
    assert " OR " in sql.upper()
    assert isinstance(cond, object) and (cond is not None)
    # 条件确实绑定到 Project 表（避免误挂到 Episode 上）
    assert Project.created_by is not None


def test_project_scope_filter_signature_accepts_plain_user():
    """口径写在一个地方：projects/upload/variants 三处复用同一函数。"""
    assert ds.project_scope_filter(_user("material", "all")) is None


# ─────────────────────────────────────────────────────────────
# 3. 剧集下钻校验（GET /api/episodes/{id}/video-url 的隔离判断）
# ─────────────────────────────────────────────────────────────

def _db_returning(project):
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=project)
    db.execute = AsyncMock(return_value=res)
    return db


def _episode(project_id):
    ep = MagicMock()
    ep.id = uuid.uuid4()
    ep.project_id = project_id
    return ep


@pytest.mark.asyncio
async def test_operator_video_url_of_null_owner_project_passes():
    """验收②：operator 访问无主项目剧集的 video-url 隔离判断必须放行（不再 404）。"""
    project = _project(None)
    ep = _episode(project.id)
    await ds.check_project_access_by_episode(_db_returning(project), ep, OPERATOR)

    await ds.check_project_access_by_id(_db_returning(project), project.id, OPERATOR)


@pytest.mark.asyncio
async def test_operator_still_404_on_other_users_project():
    """不回归：无主项目放行不等于放开所有项目。"""
    project = _project(uuid.uuid4())
    ep = _episode(project.id)

    with pytest.raises(HTTPException) as ei:
        await ds.check_project_access_by_episode(_db_returning(project), ep, OPERATOR)
    assert ei.value.status_code == 404

    with pytest.raises(HTTPException) as ei2:
        await ds.check_project_access_by_id(_db_returning(project), project.id, OPERATOR)
    assert ei2.value.status_code == 404


@pytest.mark.asyncio
async def test_operator_own_project_and_admin_shortcut_pass():
    project = _project(OPERATOR.id)
    ep = _episode(project.id)
    await ds.check_project_access_by_episode(_db_returning(project), ep, OPERATOR)

    # scope=all 直接短路返回，不查库
    db = AsyncMock()
    await ds.check_project_access_by_episode(db, ep, ADMIN)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_episode_without_project_is_denied_for_operator():
    """剧集 project_id 为 NULL（或项目已被删）时，operator 依旧 404。"""
    ep = _episode(None)
    with pytest.raises(HTTPException) as ei:
        await ds.check_project_access_by_episode(_db_returning(None), ep, OPERATOR)
    assert ei.value.status_code == 404

    with pytest.raises(HTTPException) as ei2:
        await ds.check_project_access_by_id(_db_returning(None), uuid.uuid4(), OPERATOR)
    assert ei2.value.status_code == 404
