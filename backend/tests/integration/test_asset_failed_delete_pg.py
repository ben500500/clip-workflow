import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

AUDIT_DATABASE_URL = "postgresql+asyncpg://audit@127.0.0.1:55432/audit_failed_delete"
os.environ.setdefault("DATABASE_URL", AUDIT_DATABASE_URL)
os.environ.setdefault("JWT_SECRET", "t" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")
os.environ.setdefault("WECHAT_DL_ZHILING_KEY", "fake-key")

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.assets import misc
from app.database import Base
from app.models.asset import (
    JB_QUEUED,
    JB_RUNNING,
    JOB_FRAMES,
    PR_CANCELLED,
    PR_FAILED,
    PR_ORDER_READY,
    PR_QUEUED,
    PR_SUPERSEDED,
    PR_SUCCESS,
    AssetBatch,
    AssetItem,
    AssetJob,
    AssetOutput,
    AssetProduction,
    AssetSummary,
)
from app.models.audit import AuditLog
from app.models.user import User

pytestmark = pytest.mark.skipif(
    os.environ.get("CLIP_AUDIT_PG") != "1",
    reason="Set CLIP_AUDIT_PG=1 only for the disposable localhost audit database",
)


@pytest.fixture
def pg_url():
    url = make_url(os.environ["DATABASE_URL"])
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "127.0.0.1"
    assert url.port == 55432
    assert url.database == "audit_failed_delete"
    assert url.username == "audit"
    return url.render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def engine(pg_url):
    eng = create_async_engine(
        pg_url,
        pool_size=8,
        max_overflow=4,
        connect_args={"server_settings": {"statement_timeout": "10000", "lock_timeout": "4000"}},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_production(db, status=PR_FAILED):
    suffix = uuid.uuid4().hex
    operator = User(username=f"audit-op-{suffix}", password_hash="x", role="operator")
    db.add(operator)
    await db.flush()
    batch = AssetBatch(code=f"AB-{suffix[:16]}", name="audit")
    db.add(batch)
    await db.flush()
    item = AssetItem(code=f"AS-{suffix[:16]}", batch_id=batch.id, source_kind="file")
    db.add(item)
    await db.flush()
    summary = AssetSummary(asset_id=item.id, seq=1, text="audit", audit_status="approved")
    db.add(summary)
    await db.flush()
    production = AssetProduction(
        asset_id=item.id,
        summary_id=summary.id,
        batch_id=batch.id,
        seq=1,
        status=status,
        error="板面判失败",
        started_at=misc.datetime.utcnow(),
    )
    db.add(production)
    await db.commit()
    return production, operator


async def _wait_for_lock(engine):
    async def locked():
        async with engine.connect() as conn:
            count = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            )
            return count > 0

    async with asyncio.timeout(4):
        while not await locked():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancel_and_manual_status_are_serialized_both_directions(engine, sessions, monkeypatch):
    async def scenario(cancel_first):
        async with sessions() as db:
            production, operator = await _seed_production(db, PR_QUEUED if cancel_first else PR_FAILED)
            pid = str(production.id)

        locked = asyncio.Event()
        release = asyncio.Event()
        original_audit = misc._write_audit

        async def paused_audit(db, **kwargs):
            await original_audit(db, **kwargs)
            locked.set()
            await release.wait()

        monkeypatch.setattr(misc, "_write_audit", paused_audit)
        first_db, second_db = sessions(), sessions()
        try:
            if cancel_first:
                first = asyncio.create_task(
                    misc.cancel_inflight_production(pid, operator, first_db, operator)
                )
                await locked.wait()
                second = asyncio.create_task(
                    misc.update_production_status(
                        misc.ProductionStatusRequest(ids=[pid], status=PR_SUCCESS),
                        operator,
                        second_db,
                    )
                )
                await _wait_for_lock(engine)
                assert not second.done()
                release.set()
                cancel_result, status_result = await asyncio.gather(first, second, return_exceptions=True)
                assert cancel_result["status"] == PR_CANCELLED
                assert status_result["blocked"][0]["from"] == PR_CANCELLED
                expected = PR_CANCELLED
            else:
                first = asyncio.create_task(
                    misc.update_production_status(
                        misc.ProductionStatusRequest(ids=[pid], status=PR_SUCCESS),
                        operator,
                        first_db,
                    )
                )
                await locked.wait()
                second = asyncio.create_task(
                    misc.cancel_inflight_production(pid, operator, second_db, operator)
                )
                await _wait_for_lock(engine)
                assert not second.done()
                release.set()
                _, cancel_result = await asyncio.gather(first, second, return_exceptions=True)
                assert isinstance(cancel_result, HTTPException)
                assert cancel_result.status_code == 409
                expected = PR_SUCCESS
        finally:
            release.set()
            await first_db.close()
            await second_db.close()

        async with sessions() as db:
            final = await db.get(AssetProduction, uuid.UUID(pid))
            assert final.status == expected

    await scenario(True)
    await scenario(False)


@pytest.mark.asyncio
async def test_cancel_cannot_be_overwritten_by_concurrent_supersede(engine, sessions, monkeypatch):
    async def scenario(supersede_first):
        async with sessions() as db:
            production, operator = await _seed_production(db, PR_FAILED)
            pid = production.id
            summary = await db.get(AssetSummary, production.summary_id)

        locked = asyncio.Event()
        release = asyncio.Event()
        original_audit = misc._write_audit
        action = (
            "asset.production.supersede"
            if supersede_first
            else "asset.production.cancel"
        )

        async def paused_audit(db, **kwargs):
            await original_audit(db, **kwargs)
            if kwargs["action"] == action:
                locked.set()
                await release.wait()

        monkeypatch.setattr(misc, "_write_audit", paused_audit)
        first_db, second_db = sessions(), sessions()
        try:
            if supersede_first:
                first = asyncio.create_task(
                    misc._supersede_productions(first_db, summary, operator=operator, reason="撤审")
                )
                await locked.wait()
                second = asyncio.create_task(
                    misc.cancel_inflight_production(str(pid), operator, second_db, operator)
                )
            else:
                first = asyncio.create_task(
                    misc.cancel_inflight_production(str(pid), operator, first_db, operator)
                )
                await locked.wait()
                second = asyncio.create_task(
                    misc._supersede_productions(second_db, summary, operator=operator, reason="撤审")
                )
            await _wait_for_lock(engine)
            assert not second.done()
            release.set()
            if supersede_first:
                first_result = await first
                await first_db.commit()
                second_result = (await asyncio.gather(second, return_exceptions=True))[0]
                assert isinstance(second_result, HTTPException)
                assert second_result.status_code == 409
                assert first_result == 1
                expected = PR_SUPERSEDED
            else:
                first_result, second_result = await asyncio.gather(first, second, return_exceptions=True)
                assert second_result == 0
                await second_db.commit()
                assert first_result["status"] == PR_CANCELLED
                expected = PR_CANCELLED
        finally:
            release.set()
            await first_db.close()
            await second_db.close()

        async with sessions() as db:
            final = await db.get(AssetProduction, pid)
            assert final.status == expected

    await scenario(True)
    await scenario(False)


@pytest.mark.asyncio
async def test_cancel_rolls_back_when_audit_insert_fails(engine, sessions):
    async with sessions() as db:
        production, operator = await _seed_production(db, PR_FAILED)
        pid = production.id

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION clip_audit_reject_insert() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit injected failure'; END $$"
            )
        )
        await conn.execute(text("DROP TRIGGER IF EXISTS clip_audit_reject ON audit_logs"))
        await conn.execute(
            text(
                "CREATE TRIGGER clip_audit_reject BEFORE INSERT ON audit_logs "
                "FOR EACH ROW EXECUTE FUNCTION clip_audit_reject_insert()"
            )
        )

    try:
        async with sessions() as db:
            with pytest.raises(Exception, match="audit injected failure|PendingRollbackError"):
                await misc.cancel_inflight_production(str(pid), operator, db, operator)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TRIGGER IF EXISTS clip_audit_reject ON audit_logs"))
            await conn.execute(text("DROP FUNCTION IF EXISTS clip_audit_reject_insert()"))

    async with sessions() as db:
        final = await db.get(AssetProduction, pid)
        assert final.status == PR_FAILED
        audits = await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.target_id == str(pid))
        )
        assert audits == 0


class _EmptyJobPayload(BaseModel):
    pass


@pytest.mark.asyncio
async def test_concurrent_twin_job_submission_creates_only_one_job(engine, sessions, monkeypatch):
    async with sessions() as db:
        batch = AssetBatch(code=f"AB-{uuid.uuid4().hex[:16]}", name="audit")
        db.add(batch)
        await db.commit()
        batch_id = batch.id
        _, operator = await _seed_production(db, PR_QUEUED)

    original_check = misc._assert_no_running_twin
    second_checked = asyncio.Event()
    release_first = asyncio.Event()
    checked = 0

    async def synchronized_check(db, **kwargs):
        nonlocal checked
        await original_check(db, **kwargs)
        checked += 1
        if checked == 1:
            try:
                await asyncio.wait_for(second_checked.wait(), 0.2)
            except TimeoutError:
                pass
            release_first.set()
        else:
            second_checked.set()
            await release_first.wait()

    monkeypatch.setattr(misc, "_assert_no_running_twin", synchronized_check)
    monkeypatch.setattr(misc, "_schedule_asset_job", lambda *args, **kwargs: None)
    async with sessions() as first_db, sessions() as second_db:
        results = await asyncio.gather(
            misc._start_asset_job(
                first_db,
                kind=JOB_FRAMES,
                data=_EmptyJobPayload(),
                operator=operator,
                batch_id=str(batch_id),
                planned_units=1,
            ),
            misc._start_asset_job(
                second_db,
                kind=JOB_FRAMES,
                data=_EmptyJobPayload(),
                operator=operator,
                batch_id=str(batch_id),
                planned_units=1,
            ),
            return_exceptions=True,
        )

    async with sessions() as db:
        jobs = (
            await db.scalars(select(AssetJob).where(AssetJob.batch_id == batch_id))
        ).all()
    assert len(jobs) == 1
    assert sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results) == 1


@pytest.mark.asyncio
async def test_concurrent_job_execution_claims_row_only_once(engine, sessions, monkeypatch):
    async with sessions() as db:
        _, operator = await _seed_production(db, PR_QUEUED)
        job = AssetJob(kind=JOB_FRAMES, status=JB_QUEUED, params={}, created_by=operator.id)
        db.add(job)
        await db.commit()
        job_id = str(job.id)

    claimed = asyncio.Event()
    release_claim = asyncio.Event()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    pause_user_read = False
    original_get = AsyncSession.get

    async def paused_user_get(session, model, ident, **kwargs):
        if pause_user_read and model is User:
            claimed.set()
            await release_claim.wait()
        return await original_get(session, model, ident, **kwargs)

    async def endpoint(data, user, db):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"ok": True}

    monkeypatch.setattr(AsyncSession, "get", paused_user_get)
    monkeypatch.setattr(misc._database, "async_session_factory", sessions)
    monkeypatch.setattr(misc, "_job_endpoint", lambda kind: (_EmptyJobPayload, endpoint, "audit"))
    pause_user_read = True
    first = asyncio.create_task(misc._run_asset_job(job_id, JOB_FRAMES, {}, str(operator.id)))
    second = None
    try:
        await asyncio.wait_for(claimed.wait(), 2)
        second = asyncio.create_task(misc._run_asset_job(job_id, JOB_FRAMES, {}, str(operator.id)))
        await _wait_for_lock(engine)
        assert not second.done()
        assert calls == 0
        release_claim.set()
        await asyncio.wait_for(entered.wait(), 2)
        assert not second.done()
        assert calls == 1
        release.set()
        await asyncio.gather(first, second)
    finally:
        release_claim.set()
        release.set()
        if second is not None:
            await asyncio.gather(first, second, return_exceptions=True)
        else:
            await asyncio.gather(first, return_exceptions=True)

    async with sessions() as db:
        final = await db.get(AssetJob, uuid.UUID(job_id))
        assert final.status == misc.JB_SUCCEEDED
    assert calls == 1


@pytest.mark.asyncio
async def test_dispatch_cannot_revive_production_voided_during_board_create(
    engine, sessions, monkeypatch
):
    async with sessions() as db:
        production, operator = await _seed_production(db, PR_ORDER_READY)
        pid = production.id
        summary = await db.get(AssetSummary, production.summary_id)
        production.board_date = misc.datetime.utcnow()
        await db.commit()

    created = asyncio.Event()
    release = asyncio.Event()

    class FakeBoard:
        def __init__(self):
            self.rows = {}

        def days_to_query(self, board_dates):
            return 3

        async def readback(self, days, tag):
            return dict(self.rows)

        async def create_task(self, payload):
            created.set()
            await release.wait()
            self.rows["T-AUDIT-1"] = {"rgid": "R-AUDIT-1"}

    fake_board = FakeBoard()
    monkeypatch.setattr(misc, "board", fake_board)

    async def stop_before_real_poll(db, tracked, *, recover_only):
        return {"outputs": [], "prods": {}, "summary": {}, "gap": {}}

    monkeypatch.setattr(misc, "_poll_and_collect", stop_before_real_poll)
    async with sessions() as dispatch_db, sessions() as supersede_db:
        production = await dispatch_db.get(AssetProduction, pid)
        dispatch = asyncio.create_task(
            misc._execute_dispatch(
                dispatch_db,
                to_create=[production],
                to_recover=[],
                payloads_by_id={str(pid): {"payload": {"tag": "audit"}}},
                operator=operator,
                gate={"cross_person": None, "forced_ids": [], "forced_reason": None},
                blocked=[],
                card_warnings=[],
                recover_only=False,
            )
        )
        await asyncio.wait_for(created.wait(), 2)
        await misc._supersede_productions(supersede_db, summary, operator=operator, reason="撤审")
        await supersede_db.commit()
        release.set()
        result = await dispatch

    async with sessions() as db:
        final = await db.get(AssetProduction, pid)
        assert final.status == PR_SUPERSEDED
        assert final.board_tid == "T-AUDIT-1"
        assert final.started_at is not None
        assert final.attempts == 1
        assert final.error == "撤审"
    assert result["created"] == []
    assert result["blocked"][0]["reason"]


@pytest.mark.asyncio
async def test_concurrent_auto_concat_inserts_only_one_composed_output(engine, sessions, monkeypatch):
    async with sessions() as db:
        production, operator = await _seed_production(db, PR_SUCCESS)
        material = AssetItem(
            code=f"AS-{uuid.uuid4().hex[:16]}",
            batch_id=production.batch_id,
            source_kind="file",
            media_kind="video",
            file_key="asset/audit/material.mp4",
            file_name="拼接段.mp4",
            created_by=operator.id,
        )
        db.add(material)
        await db.flush()
        production.concat_asset_id = material.id
        production.concat_order = "hook_first"
        raw_id = uuid.uuid4()
        db.add(AssetOutput(
            id=raw_id,
            production_id=production.id,
            asset_id=production.asset_id,
            kind="doubao_raw",
            file_key=f"asset/board/{raw_id}.mp4",
            bucket="raw",
            file_name="钩子.mp4",
            duration=10.08,
            resolution="720x1280",
        ))
        await db.commit()
        pid = production.id
        outcome = {
            "outputs": [{
                "production_id": str(pid),
                "_inserted": True,
                "_output_id": str(raw_id),
                "file_key": f"asset/board/{raw_id}.mp4",
                "bucket": "raw",
                "file_name": "钩子.mp4",
            }],
            "prods": {str(pid): production},
        }

    both_rendered = asyncio.Event()
    release = asyncio.Event()
    rendered = 0

    async def synchronized_render(*args, **kwargs):
        nonlocal rendered
        rendered += 1
        if rendered == 2:
            both_rendered.set()
        await release.wait()
        return {
            "output_kwargs": {
                "file_key": f"asset/composed/audit/{uuid.uuid4().hex}.mp4",
                "bucket": "raw",
                "file_name": "拼接产物.mp4",
                "duration": 16.08,
                "resolution": "720x1280",
                "sha256": uuid.uuid4().hex * 2,
            },
            "elapsed_seconds": 0.01,
        }

    async def no_frames(*args, **kwargs):
        return {"queued": False, "note": ""}

    monkeypatch.setattr(misc, "_concat_render", synchronized_render)
    monkeypatch.setattr(misc, "_enqueue_frames", no_frames)
    async with sessions() as first_db, sessions() as second_db:
        first = asyncio.create_task(misc._auto_concat_recovered(first_db, outcome, operator=operator))
        second = asyncio.create_task(misc._auto_concat_recovered(second_db, outcome, operator=operator))
        try:
            await asyncio.wait_for(both_rendered.wait(), 2)
            release.set()
            notes = await asyncio.gather(first, second)
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)

    async with sessions() as db:
        composed = (
            await db.scalars(
                select(AssetOutput).where(
                    AssetOutput.kind == misc.compose.KIND_COMPOSED,
                    AssetOutput.composed_from_output_id == raw_id,
                )
            )
        ).all()
    assert len(composed) == 1
    assert sum(note["composed"] + note["already"] for note in notes) == 2
