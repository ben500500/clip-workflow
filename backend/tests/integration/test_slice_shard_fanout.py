"""真分片一期：扇出/聚合/巡检豁免 集成测试（SQLite 临时库，端点级）。

覆盖 docs/1128-工程方案-v2 §6 的 T3/T4/T5/T7/T8 关键路径：
- 回调聚合：progress/completed/failed 分片回调 → 父行同事务重算（T3/T4）
- cancel 父行扇出 + 分片行直取消重算（T7）
- delete 父行逐分片清理（T7）
- retry 父级语义（只重跑失败/取消分片，原行复位）（T8）
- sweep 父行豁免 + 分片行收紧阈值收尸后联动重算（T5）
- 列表端点隐藏分片行（§4.1 展示口径）

直接可 python 运行（无 pytest 时跳过收集），与 test_publish_dispatch_commit_race.py
同一套 SQLite 装配（PGUUID-on-sqlite 编译钩子 + 独立引擎替换 + 临时库硬断言）。
"""
import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

try:
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

_TMP_DB = tempfile.mktemp(suffix=".db", prefix="slice_shard_fanout_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["JWT_SECRET"] = "t" * 64
os.environ["MINIO_ACCESS_KEY"] = "test"
os.environ["MINIO_SECRET_KEY"] = "testtest"

from sqlalchemy.dialects.postgresql import UUID as _PGUUID
from sqlalchemy.ext.compiler import compiles


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):  # pragma: no cover
    return "CHAR(36)"


import app.database as dbmod
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TEST_DB_URL = f"sqlite+aiosqlite:///{_TMP_DB}"
_test_engine = create_async_engine(_TEST_DB_URL)
dbmod.engine = _test_engine
dbmod.async_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)
# tasks.py 的 async_session_factory 是**导入期绑定**：若本模块之前有别的测试把
# app.celery.tasks 连同 postgres 默认 URL 一起导入（如 test_wechat_dl_direct_url_gate），
# 这里必须同步重绑，否则 sweep/watchdog 会去连 127.0.0.1:5432（合跑 OSError 实测）
import app.celery.tasks as _celery_tasks

_celery_tasks.async_session_factory = dbmod.async_session_factory

from httpx import ASGITransport, AsyncClient

from app.auth import get_password_hash
from app.database import Base
from app.main import app
from app.models.models import Episode, Project, SliceTask, User

_TMP_DIR = os.path.abspath(tempfile.gettempdir())
USERNAME = "shardy"
PASSWORD = "pw123456"


def _assert_disposable_test_engine() -> None:
    """只对「确认是临时目录下的 sqlite 测试库」的当前引擎执行破坏性操作。

    多个集成测试文件并存时（race/episode 在收集期各自重绑 dbmod.engine），
    不能断言「必须是本文件的引擎」——只断言当前绑定是一次性 sqlite 临时库。
    """
    eng = dbmod.engine
    backend = eng.url.get_backend_name()
    if backend != "sqlite":
        raise RuntimeError(f"拒绝执行 drop_all：后端 {backend!r} 非 sqlite")
    db_path = os.path.abspath(eng.url.database or "")
    if not db_path or _TMP_DIR != os.path.commonpath([db_path, _TMP_DIR]):
        raise RuntimeError(f"拒绝执行 drop_all：库路径 {db_path!r} 不在临时目录下")
    if not (os.path.basename(db_path).startswith(("slice_shard_fanout_", "publish_dispatch_race_"))):
        raise RuntimeError("拒绝执行 drop_all：库文件名无已知测试库标记")


async def _reset_db() -> None:
    # 运行期重绑：race/episode 在收集期会覆盖 dbmod.engine（导入顺序后于本文件），
    # 本文件每次用例前把共享绑定拉回自己的临时库，保证用例间隔离。
    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    import app.celery.tasks as _celery_tasks

    _celery_tasks.async_session_factory = dbmod.async_session_factory
    _assert_disposable_test_engine()
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _bootstrap() -> dict:
    """admin 用户 + 项目 + 剧集。返回各 id。"""
    await _reset_db()
    user_id, project_id, episode_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with dbmod.async_session_factory() as s:
        s.add(User(
            id=user_id, username=USERNAME, password_hash=get_password_hash(PASSWORD),
            display_name="Shardy", role="admin", data_scope="all", is_active=True,
        ))
        s.add(Project(id=project_id, name="p-shard", status="active"))
        s.add(Episode(
            id=episode_id, project_id=project_id, title="ep-shard",
            source_file_key="raw/ep-shard.mp4", duration=1200.0, status="uploaded",
        ))
        await s.commit()
    return {"user_id": user_id, "project_id": project_id, "episode_id": episode_id}


async def _make_family(db: AsyncSession, episode_id, *, statuses):
    """建 1 父 + len(statuses) 分片；statuses[i] ∈ pending/running/completed/failed/cancelled。"""
    parent_id, shard_ids = uuid.uuid4(), []
    shard_rows = []
    for i, st in enumerate(statuses, 1):
        sid = uuid.uuid4()
        shard_ids.append(sid)
        row = SliceTask(
            id=sid, episode_id=episode_id, mode="dedupe",
            status=st, progress=100.0 if st == "completed" else 0.0,
            output_count=3 if st == "completed" else 0,
            cutlist=f"00:00:{(i-1)*30:02d} 00:00:{i*30:02d} s{i}.mp4", intervals="",
            source_file_key="raw/ep-shard.mp4", source_bucket="raw-footage",
            parent_task_id=parent_id, shard_index=i, shard_total=len(statuses),
            completed_at=datetime.utcnow() if st in ("completed", "failed", "cancelled") else None,
        )
        db.add(row)
        shard_rows.append(row)
    # 父行状态走与生产一致的聚合纯函数（单一事实来源）
    from app.api.slice_helpers import compute_parent_aggregate
    agg = compute_parent_aggregate(shard_rows)
    parent = SliceTask(
        id=parent_id, episode_id=episode_id, mode="dedupe", status=agg["status"],
        progress=agg["progress"], output_count=agg["output_count"],
        error_message=agg["error_message"],
        completed_at=datetime.utcnow() if agg["completed"] else None,
        cutlist="00:00:00 00:00:30 a.mp4", intervals="",
        source_file_key="raw/ep-shard.mp4", source_bucket="raw-footage",
        output_tier="auto",
    )
    db.add(parent)
    await db.commit()
    return parent_id, shard_ids


async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ── 用例 1：列表端点隐藏分片行 ────────────────────────────────────────────
def test_list_hides_shard_rows():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            await _make_family(db, ids["episode_id"], statuses=["running", "running", "pending"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            resp = await client.get(
                f"/api/episodes/{ids['episode_id']}/slice/tasks", headers=headers
            )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1, f"应只返回父行，实际 {len(rows)} 行"
        return rows[0]

    row = _run(scenario())
    assert row["status"] == "running"  # 父行聚合态


# ── 用例 2：回调聚合（progress→completed→failed 混合终态）─────────────────
def test_callback_aggregation_partial_failure():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["pending", "pending", "pending"]
            )
        token = "tok"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.api.slice._verify_worker_token", AsyncMock(return_value=True)), \
                 patch("app.api.slice._refresh_episode_status", AsyncMock()):
                # 分片 1 完成 → 父 running（其余 pending）
                r1 = await client.post(
                    f"/api/slice-tasks/{shard_ids[0]}/callback", json={
                        "task_id": str(shard_ids[0]),
                        "status": "completed", "outputs": [
                            {"file_name": "s1.mp4", "file_key": "sliced/s1.mp4",
                             "duration": 30.0, "file_size": 100}],
                        "output_count": 1, "node_id": "w1",
                    }, headers={"X-Worker-Token": token},
                )
                # 分片 2 进度 → 父进度爬动
                r2 = await client.post(
                    f"/api/slice-tasks/{shard_ids[1]}/callback", json={
                        "task_id": str(shard_ids[1]),
                        "status": "progress", "progress": 50.0,
                    }, headers={"X-Worker-Token": token},
                )
                # 分片 3 失败 → 父 completed + partial 标注
                r3 = await client.post(
                    f"/api/slice-tasks/{shard_ids[2]}/callback", json={
                        "task_id": str(shard_ids[2]),
                        "status": "failed", "error": "boom",
                    }, headers={"X-Worker-Token": token},
                )
                assert all(r.status_code == 200 for r in (r1, r2, r3)), (r1.text, r2.text, r3.text)
                # 分片 2 仍 pending → 父行此刻应 running（有非终态分片）
                mid = (await db.execute(
                    select(SliceTask).where(SliceTask.id == parent_id)
                )).scalar_one()
                assert mid.status == "running"
                # 分片 2 完成 → 终态齐：父 completed + partial 标注
                r4 = await client.post(
                    f"/api/slice-tasks/{shard_ids[1]}/callback", json={
                        "task_id": str(shard_ids[1]),
                        "status": "completed", "outputs": [],
                        "output_count": 0, "node_id": "w2",
                    }, headers={"X-Worker-Token": token},
                )
                assert r4.status_code == 200, r4.text
        async with dbmod.async_session_factory() as db:
            parent = (await db.execute(
                select(SliceTask).where(SliceTask.id == parent_id)
            )).scalar_one()
            shards = (await db.execute(
                select(SliceTask).where(SliceTask.parent_task_id == parent_id)
            )).scalars().all()
            return parent, shards

    parent, shards = _run(scenario())
    assert parent.status == "completed"
    assert parent.error_message and "1/3 片失败" in parent.error_message
    assert parent.output_count == 1  # 分片 1 的 1 条成品
    assert parent.completed_at is not None
    assert parent.completed_at is not None
    by_status = {s.status for s in shards}
    assert by_status == {"completed", "completed", "failed"}


# ── 用例 3：cancel 父行扇出 ──────────────────────────────────────────────
def test_cancel_parent_fans_out():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["running", "running", "pending"]
            )
        cancelled_marks, removed_streams = [], []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.api.slice.mark_task_cancelled", AsyncMock(
                    side_effect=lambda tid: cancelled_marks.append(tid))), \
                 patch("app.api.slice.remove_slice_task_from_streams", AsyncMock(
                    side_effect=lambda tid: removed_streams.append(tid))), \
                 patch("app.services.slice_service.kill_slice_proc", AsyncMock(return_value=False)):
                resp = await client.post(
                    f"/api/slice-tasks/{parent_id}/cancel", headers=headers
                )
        assert resp.status_code == 200, resp.text
        async with dbmod.async_session_factory() as db:
            parent = (await db.execute(select(SliceTask).where(SliceTask.id == parent_id))).scalar_one()
            shards = (await db.execute(select(SliceTask).where(SliceTask.parent_task_id == parent_id))).scalars().all()
            return cancelled_marks, removed_streams, parent, shards

    marks, removed, parent, shards = _run(scenario())
    assert parent.status == "cancelled"
    assert parent.completed_at is not None
    assert all(s.status == "cancelled" for s in shards)
    # 三个分片都收到 Redis 取消标记；父行自身无 worker 不需要标记
    assert len(marks) == 3 and len(removed) == 3


# ── 用例 4：分片行直接取消 → 父行重算 ────────────────────────────────────
def test_cancel_shard_recalcs_parent():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["completed", "running"]
            )
            # 分片 1 的 completed_at 需要落库（_make_family 已置）
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.api.slice.mark_task_cancelled", AsyncMock()), \
                 patch("app.api.slice.remove_slice_task_from_streams", AsyncMock()), \
                 patch("app.services.slice_service.kill_slice_proc", AsyncMock(return_value=False)):
                resp = await client.post(
                    f"/api/slice-tasks/{shard_ids[1]}/cancel", headers=headers
                )
        assert resp.status_code == 200, resp.text
        async with dbmod.async_session_factory() as db:
            parent = (await db.execute(select(SliceTask).where(SliceTask.id == parent_id))).scalar_one()
            shards = (await db.execute(select(SliceTask).where(SliceTask.parent_task_id == parent_id))).scalars().all()
            return parent, shards

    parent, shards = _run(scenario())
    assert {s.status for s in shards} == {"completed", "cancelled"}
    # 混合 completed+cancelled → completed + partial 标注（拍板口径）
    assert parent.status == "completed"
    assert "1/2 片失败或取消" in (parent.error_message or "")


# ── 用例 5：retry 父级语义（只重跑失败/取消分片，原行复位）───────────────
def test_retry_parent_reruns_failed_shards():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["completed", "failed", "cancelled"]
            )
        publish_calls = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.api.slice._publish_to_worker", AsyncMock(
                    side_effect=lambda *a, **k: publish_calls.append(a[1].id) or True)), \
                 patch("app.api.slice.get_redis", AsyncMock()), \
                 patch("app.api.slice.remove_slice_task_from_streams", AsyncMock()):
                resp = await client.post(
                    f"/api/slice-tasks/{parent_id}/retry", headers=headers
                )
        assert resp.status_code == 200, resp.text
        async with dbmod.async_session_factory() as db:
            parent = (await db.execute(select(SliceTask).where(SliceTask.id == parent_id))).scalar_one()
            shards = (await db.execute(select(SliceTask).where(SliceTask.parent_task_id == parent_id))).scalars().all()
            return publish_calls, parent, shards, shard_ids

    publish_calls, parent, shards, shard_ids = _run(scenario())
    # 只重投 2 个非终态分片（completed 不动）
    assert len(publish_calls) == 2
    assert parent.status == "running"
    by = {s.id: s for s in shards}
    assert [by[sid].status for sid in shard_ids] == ["completed", "pending", "pending"]


# ── 用例 6：分片行上点重试 = 只重投该片 ──────────────────────────────────
def test_retry_shard_row_reruns_only_it():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["completed", "failed", "completed"]
            )
        publish_calls = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.api.slice._publish_to_worker", AsyncMock(
                    side_effect=lambda *a, **k: publish_calls.append(a[1].id) or True)), \
                 patch("app.api.slice.get_redis", AsyncMock()), \
                 patch("app.api.slice.remove_slice_task_from_streams", AsyncMock()):
                resp = await client.post(
                    f"/api/slice-tasks/{shard_ids[1]}/retry", headers=headers
                )
        assert resp.status_code == 200, resp.text
        async with dbmod.async_session_factory() as db:
            parent = (await db.execute(select(SliceTask).where(SliceTask.id == parent_id))).scalar_one()
            shards = (await db.execute(select(SliceTask).where(SliceTask.parent_task_id == parent_id))).scalars().all()
            return publish_calls, parent, shards, shard_ids

    publish_calls, parent, shards, shard_ids = _run(scenario())
    assert publish_calls == [shard_ids[1]]
    assert parent.status == "running"
    assert {s.status for s in shards} == {"completed", "pending", "completed"}


# ── 用例 7：delete 父行逐分片清理 ────────────────────────────────────────
def test_delete_parent_removes_shard_rows_and_prefixes():
    ids = _run(_bootstrap())

    async def scenario():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["failed", "failed", "completed"]
            )
        prefixes = []
        async def _fake_list_files(bucket, prefix=""):
            prefixes.append(("list", prefix))
            return [{"key": prefix + "out.mp4"}]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.api.slice.list_files", AsyncMock(side_effect=_fake_list_files)), \
                 patch("app.api.slice.delete_file", AsyncMock(side_effect=lambda b, k: prefixes.append(("del", k)))), \
                 patch("app.api.slice.mark_task_cancelled", AsyncMock()), \
                 patch("app.api.slice.remove_slice_task_from_streams", AsyncMock()):
                resp = await client.delete(
                    f"/api/slice-tasks/{parent_id}", headers=headers
                )
        assert resp.status_code == 200, resp.text
        async with dbmod.async_session_factory() as db:
            n_left = (await db.execute(
                select(func.count(SliceTask.id)).where(
                    (SliceTask.id == parent_id) | (SliceTask.parent_task_id == parent_id)
                )
            )).scalar()
            return prefixes, n_left, shard_ids

    prefixes, n_left, shard_ids = _run(scenario())
    assert n_left == 0  # 父行+分片行全部删除
    deleted_keys = [k for tag, k in prefixes if tag == "del"]
    # 每个分片前缀都被清理（file key 形态 slices/{eid}/{shard_id}/...）
    for sid in shard_ids:
        assert any(str(sid) in k for k in deleted_keys), f"分片 {sid} 前缀未清理"


# ── 用例 8：sweep 父行豁免 + 分片行收紧阈值收尸联动重算 ──────────────────
def test_sweep_exempts_parent_and_reaps_stale_shard():
    ids = _run(_bootstrap())

    async def prepare():
        async with dbmod.async_session_factory() as db:
            parent_id, shard_ids = await _make_family(
                db, ids["episode_id"], statuses=["running", "pending"]
            )
            stale = datetime.utcnow() - timedelta(hours=8)
            parent = (await db.execute(select(SliceTask).where(SliceTask.id == parent_id))).scalar_one()
            parent.created_at = stale
            parent.status = "running"
            shard = (await db.execute(select(SliceTask).where(SliceTask.id == shard_ids[0]))).scalar_one()
            shard.started_at = datetime.utcnow() - timedelta(hours=2)
            shard.status = "running"
            shard2 = (await db.execute(select(SliceTask).where(SliceTask.id == shard_ids[1]))).scalar_one()
            shard2.started_at = datetime.utcnow() - timedelta(hours=2)
            await db.commit()
        return parent_id, shard_ids

    parent_id, shard_ids = _run(prepare())

    # sweep 自带事件循环（run_async），必须在无嵌套 loop 的同步栈调用
    redis_mock = AsyncMock()
    redis_mock.hgetall = AsyncMock(return_value={})
    redis_mock.expire = AsyncMock()
    with patch("app.services.redis_stream.get_redis", AsyncMock(return_value=redis_mock)), \
         patch("app.services.redis_stream.remove_slice_task_from_streams", AsyncMock()):
        from app.celery.tasks import slice_stuck_sweep_task
        result = slice_stuck_sweep_task()

    async def verify():
        async with dbmod.async_session_factory() as db:
            parent = (await db.execute(select(SliceTask).where(SliceTask.id == parent_id))).scalar_one()
            shards = (await db.execute(select(SliceTask).where(SliceTask.parent_task_id == parent_id))).scalars().all()
            return parent, shards

    parent, shards = _run(verify())
    swept = result["swept"]
    # 父行豁免：绝不被 sweep 回收
    assert str(parent.id) not in swept
    # 两片都超 45min 分片阈值 → 都被收尸
    assert str(shard_ids[0]) in swept and str(shard_ids[1]) in swept
    # 收尸联动重算：全部分片 failed → 父行 failed
    assert parent.status == "failed"
    assert all(s.status == "failed" for s in shards)


if __name__ == "__main__":  # pragma: no cover
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            print(f"== {name}")
            fn()
            print("   OK")
    print("ALL PASS")
