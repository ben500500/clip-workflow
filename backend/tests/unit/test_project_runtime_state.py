"""项目列表 owner 过滤与持久化运行状态聚合（不连接数据库）。"""

import inspect
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.params import Query as QueryParam
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 仅满足导入期 Settings 校验；本文件所有数据库调用均由 mock 接管。
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_project_runtime_state.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.api import projects as projects_api
from app.auth import get_current_user
from app.database import get_db


def _user(uid=None, *, role="operator", data_scope="own"):
    return SimpleNamespace(id=uid or uuid.uuid4(), role=role, data_scope=data_scope)


def _project(pid, *, owner=None):
    return SimpleNamespace(
        id=pid,
        name="测试项目",
        description=None,
        status="draft",
        config={},
        created_by=owner,
        created_at=datetime(2026, 11, 27),
        updated_at=datetime(2026, 11, 27),
        episodes=[],
    )


def _result(*, scalar=None, rows=None, projects=None):
    result = MagicMock()
    result.scalar.return_value = scalar
    result.all.return_value = rows or []
    result.scalars.return_value.all.return_value = projects or []
    return result


def _sql(statement):
    if statement is None:
        return ""
    return str(statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))


@pytest.mark.parametrize(
    ("counts", "expected_state", "expected_label"),
    [
        ({"remotion_rendering": 1}, "remotion_rendering", "混剪渲染中"),
        ({"selecting": 1}, "selecting", "选点中"),
        ({"detecting": 1}, "detecting", "区间检测中"),
        ({"slicing": 1}, "slicing", "切片中"),
        ({}, "idle", "空闲"),
        (
            {"selecting": 1, "detecting": 1, "slicing": 1, "remotion_rendering": 1},
            "remotion_rendering",
            "混剪渲染中",
        ),
        (
            {"selecting": 1, "detecting": 1, "slicing": 1},
            "selecting",
            "选点中",
        ),
        ({"detecting": 1, "slicing": 1}, "detecting", "区间检测中"),
    ],
)
def test_runtime_state_priority_and_idle(counts, expected_state, expected_label):
    runtime = projects_api._project_runtime_state(**counts)
    assert runtime["run_state"] == expected_state
    assert runtime["run_state_label"] == expected_label


def test_runtime_counts_keep_overlapping_stage_details_without_double_counting_total():
    runtime = projects_api._project_runtime_state(
        selecting=2,
        detecting=2,
        slicing=4,
        remotion_rendering=1,
    )
    assert runtime["run_counts"] == {
        "selecting": 2,
        "detecting": 2,
        "slicing": 4,
        "remotion_rendering": 1,
        # 兼容旧字段：含 detect/remotion 在内的全部活跃 SliceTask。
        "slice_running": 4,
        # detect/remotion 已包含在 slice_running 中，不重复计入 total。
        "total": 6,
    }


def test_runtime_counts_default_to_zero_and_ignore_negative_values():
    runtime = projects_api._project_runtime_state(selecting=-1, slicing=-2)
    assert runtime["run_state"] == "idle"
    assert runtime["run_counts"] == {
        "selecting": 0,
        "detecting": 0,
        "slicing": 0,
        "remotion_rendering": 0,
        "slice_running": 0,
        "total": 0,
    }


def test_owner_query_is_optional_and_only_accepts_me_or_all():
    """不传 owner 必须保持现网既有行为（＝ all），不能默认收窄。

    前端「仅看自己」是显式传 owner=me 的 UI 默认值；接口默认值一旦设成 me，
    所有未升级的调用方（脚本、旧前端、导入链路）都会静默少看无主公共项目。
    """
    owner = inspect.signature(projects_api.list_projects).parameters["owner"]
    assert owner.default.default is None
    assert isinstance(owner.default, QueryParam)
    assert get_args(owner.annotation) == (Literal["me", "all"], type(None))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "owner", "owner_equalities", "includes_public"),
    [
        # operator 的 RBAC scope 本身就含「自己创建的 ∪ 无主公共」，
        # owner=me 再叠一层同向条件（等值式多一个，公共仍在）。
        (None, "me", 2, True),
        (None, "all", 1, True),
        (None, None, 1, True),
        # admin 无 scope 过滤，owner=me 只加「我创建的 ∪ 无主公共」一条 or_，
        # 无主公共项目在任何视图都可见——这是既有隔离口径，不是本批新规则。
        ("all", "me", 1, True),
        ("all", "all", 0, False),
        ("all", None, 0, False),
    ],
)
async def test_owner_filter_narrows_existing_rbac_scope(
    user, owner, owner_equalities, includes_public,
):
    current_user = _user(
        role="operator" if user is None else "admin",
        data_scope="own" if user is None else "all",
    )
    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalar=0),
        _result(projects=[]),
    ]

    response = await projects_api.list_projects(
        page=1,
        page_size=20,
        search=None,
        status=None,
        owner=owner,
        current_user=current_user,
        db=db,
    )

    assert response == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert db.execute.await_count == 2  # 空页不扫描存储和任务表
    equality = f"PROJECTS.CREATED_BY = '{current_user.id}'".upper()
    for call in db.execute.await_args_list:
        where_sql = _sql(call.args[0].whereclause).upper()
        assert where_sql.count(equality) == owner_equalities
        assert ("PROJECTS.CREATED_BY IS NULL" in where_sql) is includes_public


@pytest.mark.asyncio
async def test_list_projects_aggregates_runtime_state_only_for_page_projects():
    current_user = _user(role="admin", data_scope="all")
    pid = uuid.uuid4()
    project = _project(pid)
    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalar=1),
        _result(projects=[project]),
        _result(rows=[(pid, 100)]),
        _result(rows=[(pid, 200)]),
        _result(rows=[(pid, 2)]),
        _result(rows=[(pid, 4, 2, 1)]),
    ]

    response = await projects_api.list_projects(
        page=1,
        page_size=20,
        search=None,
        status=None,
        owner="all",
        current_user=current_user,
        db=db,
    )

    item = response["items"][0]
    assert item["storage_bytes"] == 300
    assert item["slice_running"] == 4
    assert item["run_state"] == "remotion_rendering"
    assert item["run_state_label"] == "混剪渲染中"
    assert item["run_counts"] == {
        "selecting": 2,
        "detecting": 2,
        "slicing": 4,
        "remotion_rendering": 1,
        "slice_running": 4,
        "total": 6,
    }

    assert db.execute.await_count == 6
    for call in db.execute.await_args_list[2:]:
        sql = _sql(call.args[0])
        assert "episodes.project_id IN" in sql
        assert str(pid) in sql

    selecting_sql = _sql(db.execute.await_args_list[4].args[0])
    assert "autoclip_runs.status IN ('pending', 'running')" in selecting_sql
    slice_sql = _sql(db.execute.await_args_list[5].args[0])
    assert "slice_tasks.status IN ('running', 'pending', 'processing'" in slice_sql
    assert "slice_tasks.mode LIKE 'detect_" in slice_sql
    assert "slice_tasks.remotion_status IN ('pending', 'rendering'" in slice_sql


@pytest.mark.asyncio
async def test_project_without_active_tasks_is_idle():
    current_user = _user(role="admin", data_scope="all")
    pid = uuid.uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalar=1),
        _result(projects=[_project(pid)]),
        _result(rows=[]),
        _result(rows=[]),
        _result(rows=[]),
        _result(rows=[]),
    ]

    response = await projects_api.list_projects(
        page=1,
        page_size=20,
        search=None,
        status=None,
        owner="all",
        current_user=current_user,
        db=db,
    )

    item = response["items"][0]
    assert item["run_state"] == "idle"
    assert item["run_state_label"] == "空闲"
    assert item["slice_running"] == 0
    assert item["run_counts"]["total"] == 0


def test_invalid_owner_is_rejected_before_database_access():
    db = AsyncMock()
    app = FastAPI()
    app.include_router(projects_api.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as client:
        response = client.get("/api/projects?owner=someone_else")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "owner"]
    db.execute.assert_not_awaited()
