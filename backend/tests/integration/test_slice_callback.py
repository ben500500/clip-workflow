"""切片回调终态与 cutlist/clip_id 内容绑定回归（隔离 SQLite）。"""
import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

_fd, _TMP_DB = tempfile.mkstemp(suffix=".db", prefix="slice_callback_test_")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["JWT_SECRET"] = "t" * 64
os.environ["MINIO_ACCESS_KEY"] = "test"
os.environ["MINIO_SECRET_KEY"] = "testtest"

from sqlalchemy.dialects.postgresql import UUID as _PGUUID
from sqlalchemy.ext.compiler import compiles


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


import app.database as dbmod
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TEST_DB_URL = f"sqlite+aiosqlite:///{_TMP_DB}"
_test_engine = create_async_engine(_TEST_DB_URL)


@event.listens_for(_test_engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _assert_disposable_test_engine():
    assert _test_engine.url.get_backend_name() == "sqlite"
    path = os.path.abspath(_test_engine.url.database or "")
    assert os.path.commonpath([path, tempfile.gettempdir()]) == tempfile.gettempdir()
    assert os.path.basename(path).startswith("slice_callback_test_")
    assert str(dbmod.engine.url) == str(_test_engine.url)


async def _bootstrap():
    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    _assert_disposable_test_engine()
    # Celery 模块在 import 时绑定了 async_session_factory；全套 pytest 会由其它
    # SQLite 模块改写 app.database 单例，因此每个用例也要把 Celery 的引用重置。
    import app.celery.tasks as celery_tasks
    celery_tasks.async_session_factory = dbmod.async_session_factory
    from app.database import Base
    from app.models.material import ClipCandidate, Episode, Project, SliceTask

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    project_id, episode_id, task_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    clips = [
        ClipCandidate(
            id=uuid.uuid4(), episode_id=episode_id, clip_index=1,
            start_time=0.0, end_time=20.0, status="accepted",
        ),
        ClipCandidate(
            id=uuid.uuid4(), episode_id=episode_id, clip_index=2,
            start_time=100.0, end_time=120.0, status="accepted",
        ),
        ClipCandidate(
            id=uuid.uuid4(), episode_id=episode_id, clip_index=3,
            start_time=200.0, end_time=220.0, status="accepted",
        ),
    ]
    async with dbmod.async_session_factory() as s:
        s.add(Project(id=project_id, name="p", status="active"))
        s.add(Episode(
            id=episode_id, project_id=project_id, title="ep", status="slicing"
        ))
        s.add(SliceTask(
            id=task_id, episode_id=episode_id, status="running", progress=10.0,
            cutlist=(
                "00:03:20.000 00:03:40.000 out_001\n"
                "00:01:40.000 00:02:00.000 mixed\n"
                "00:02:00.000 00:02:20.000 mixed\n"
            ),
        ))
        s.add_all(clips)
        await s.commit()
    return task_id, clips


def _callback(task_id, db, status="completed", outputs=None, node_id="worker-112", progress=None, error=""):
    from app.api.slice import slice_task_callback
    from app.api.slice_helpers import SliceTaskCallback

    return slice_task_callback(
        str(task_id),
        SliceTaskCallback(
            task_id=str(task_id), status=status, outputs=outputs or [],
            output_count=len(outputs or []), node_id=node_id, progress=progress, error=error,
        ),
        x_worker_token="test-token",
        db=db,
    )


async def _call_callback(db, task_id, **kwargs):
    from app.api import slice as slice_api

    redis = AsyncMock()
    with patch.object(slice_api, "_verify_worker_token", AsyncMock(return_value=True)), \
         patch.object(slice_api, "_refresh_episode_status", AsyncMock()), \
         patch.object(slice_api, "get_redis", AsyncMock(return_value=redis)):
        return await _callback(task_id, db=db, **kwargs)


async def _read_task(task_id):
    from app.models.material import SliceOutput, SliceTask

    async with dbmod.async_session_factory() as s:
        task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
        outputs = (await s.execute(
            select(SliceOutput).where(SliceOutput.task_id == task_id).order_by(SliceOutput.file_name)
        )).scalars().all()
        return task, outputs


def test_completed_maps_by_cutlist_content_and_leaves_mix_unbound():
    async def scenario():
        task_id, clips = await _bootstrap()
        dotted_name = "S01.E02_1127_001"
        outputs = [
            {"file_name": "mixed.mp4", "file_key": "sliced/mixed.mp4"},
            {"file_name": f"{dotted_name}.mp4", "file_key": f"sliced/{dotted_name}.mp4"},
        ]
        async with dbmod.async_session_factory() as s:
            from app.models.material import SliceTask

            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.output_clip_ids = {dotted_name: str(clips[2].id), "mixed": None}
            await s.commit()
            result = await _call_callback(s, task_id, outputs=outputs)
            assert result == {"ok": True}
            await s.commit()
        task, rows = await _read_task(task_id)
        assert task.status == "completed"
        assert task.node_id == "worker-112"
        by_name = {row.file_name: row for row in rows}
        assert by_name[f"{dotted_name}.mp4"].clip_id == clips[2].id
        assert by_name["mixed.mp4"].clip_id is None

    asyncio.run(scenario())


def test_celery_finalization_preserves_dotted_output_binding():
    async def scenario():
        from app.celery.tasks import _save_slice_outputs
        from app.models.material import SliceTask

        task_id, clips = await _bootstrap()
        name = "S01.E02_1127_001"
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.output_clip_ids = {name: str(clips[0].id)}
            episode_id = task.episode_id
            await s.commit()

        with patch("app.celery.variant_tasks.generate_variants_task.delay"):
            await _save_slice_outputs(
                str(task_id), str(episode_id),
                [{"file_name": f"{name}.mp4", "file_key": f"sliced/{name}.mp4", "file_size": 123}],
                "fast",
            )

        task, rows = await _read_task(task_id)
        assert task.status == "completed"
        assert len(rows) == 1 and rows[0].clip_id == clips[0].id

    asyncio.run(scenario())


def test_cancelled_late_callbacks_keep_outputs_without_resurrecting():
    async def scenario():
        from app.api.slice import cancel_slice_task

        task_id, _clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            with patch("app.api.slice.check_project_access_by_episode", AsyncMock()), \
                 patch("app.api.slice.mark_task_cancelled", AsyncMock()), \
                 patch("app.services.slice_service.kill_slice_proc", AsyncMock(return_value=False)):
                await cancel_slice_task(str(task_id), current_user=None, db=s)
            await s.commit()
        task, _ = await _read_task(task_id)
        cancelled_at = task.completed_at
        assert task.status == "cancelled" and cancelled_at is not None
        async with dbmod.async_session_factory() as s:
            from app.models.material import Episode
            episode = (await s.execute(select(Episode).where(Episode.id == task.episode_id))).scalar_one()
            assert episode.status == "failed"

        output = {"file_name": "kept.mp4", "file_key": "sliced/kept.mp4"}
        for status in ("completed", "failed"):
            async with dbmod.async_session_factory() as s:
                result = await _call_callback(
                    s, task_id, status=status, outputs=[output], error="late failure"
                )
                assert result["suppressed"] is True
                await s.commit()
        task, rows = await _read_task(task_id)
        assert task.status == "cancelled"
        assert task.completed_at == cancelled_at
        assert task.node_id == "worker-112"
        assert len(rows) == 1 and task.output_count == 1

    asyncio.run(scenario())


def test_failed_task_is_not_resurrected_by_late_completed_callback():
    async def scenario():
        from app.models.material import SliceTask

        task_id, _clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.status = "failed"
            task.completed_at = task.created_at
            await s.commit()
        output = {"file_name": "late.mp4", "file_key": "sliced/late.mp4"}
        async with dbmod.async_session_factory() as s:
            result = await _call_callback(s, task_id, outputs=[output])
            assert result["suppressed"] is True and result["kept_outputs"] == 1
            await s.commit()
        task, rows = await _read_task(task_id)
        assert task.status == "failed"
        assert task.node_id == "worker-112"
        assert len(rows) == 1

    asyncio.run(scenario())


def test_callback_uses_frozen_binding_after_candidate_changes():
    async def scenario():
        from app.models.material import ClipCandidate, SliceTask

        task_id, clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.output_clip_ids = {"out_001": str(clips[2].id), "mixed": None}
            clip = (await s.execute(select(ClipCandidate).where(ClipCandidate.id == clips[2].id))).scalar_one()
            clip.status = "rejected"
            clip.start_time = 500.0
            await s.commit()
        async with dbmod.async_session_factory() as s:
            await _call_callback(
                s, task_id,
                outputs=[{"file_name": "out_001.mp4", "file_key": "sliced/out_001.mp4"}],
            )
            await s.commit()
        _task, rows = await _read_task(task_id)
        assert rows[0].clip_id == clips[2].id

    asyncio.run(scenario())


def test_callback_survives_candidate_deleted_after_snapshot():
    async def scenario():
        from app.models.material import ClipCandidate, SliceTask

        task_id, clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.output_clip_ids = {"out_001": str(clips[2].id)}
            clip = (await s.execute(select(ClipCandidate).where(ClipCandidate.id == clips[2].id))).scalar_one()
            await s.delete(clip)
            await s.commit()
        async with dbmod.async_session_factory() as s:
            result = await _call_callback(
                s, task_id,
                outputs=[{"file_name": "out_001.mp4", "file_key": "sliced/out_001.mp4"}],
            )
            await s.commit()
        assert result == {"ok": True}
        task, rows = await _read_task(task_id)
        assert task.status == "completed"
        assert rows[0].clip_id is None

    asyncio.run(scenario())


def test_failed_late_failure_preserves_first_error_and_timestamp():
    async def scenario():
        from app.models.material import SliceTask

        task_id, _clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.status = "failed"
            task.error_message = "first failure"
            task.completed_at = task.created_at
            await s.commit()
        first_finished = task.completed_at
        async with dbmod.async_session_factory() as s:
            result = await _call_callback(s, task_id, status="failed", error="late failure")
            assert result["suppressed"] is True
            await s.commit()
        task, _rows = await _read_task(task_id)
        assert task.error_message == "first failure"
        assert task.completed_at == first_finished

    asyncio.run(scenario())


def test_duplicate_completed_callback_does_not_duplicate_outputs():
    async def scenario():
        task_id, _clips = await _bootstrap()
        output = {"file_name": "out_001.mp4", "file_key": "sliced/out_001.mp4"}
        for _ in range(2):
            async with dbmod.async_session_factory() as s:
                result = await _call_callback(s, task_id, outputs=[output])
                await s.commit()
                assert result["ok"] is True
        task, rows = await _read_task(task_id)
        assert task.status == "completed" and task.output_count == 1
        assert len(rows) == 1

    asyncio.run(scenario())


def test_late_progress_is_suppressed_for_terminal_states():
    async def scenario():
        from app.api.slice import update_slice_progress

        for terminal in ("completed", "failed", "cancelled"):
            task_id, _clips = await _bootstrap()
            async with dbmod.async_session_factory() as s:
                from app.models.material import SliceTask

                task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
                task.status = terminal
                task.progress = 100.0 if terminal == "completed" else 25.0
                await s.commit()
            async with dbmod.async_session_factory() as s:
                result = await _call_callback(s, task_id, status="progress", progress=99.0)
                assert result.get("suppressed") is True
                with patch("app.api.slice._verify_worker_token", AsyncMock(return_value=True)):
                    result = await update_slice_progress(
                        str(task_id), {"progress": 99.0}, x_worker_token="test-token", db=s
                    )
                assert result.get("suppressed") is True
                await s.commit()
            task, _ = await _read_task(task_id)
            assert task.status == terminal
            assert task.progress == (100.0 if terminal == "completed" else 25.0)

    asyncio.run(scenario())


def test_celery_finalization_keeps_cancelled_terminal_and_episode_status():
    async def scenario():
        from app.celery.tasks import _save_slice_outputs
        from app.models.material import Episode, SliceTask

        task_id, _clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            task.status = "cancelled"
            task.progress = 40.0
            task.completed_at = task.created_at
            task.error_message = "cancelled by user"
            task.variant_count = 2
            episode_id = task.episode_id
            episode = (await s.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
            episode.status = "failed"
            await s.commit()
            cancelled_at = task.completed_at

        with patch("app.celery.variant_tasks.generate_variants_task.delay") as variants:
            await _save_slice_outputs(
                str(task_id), str(episode_id),
                [{"file_name": "kept.mp4", "file_key": "sliced/kept.mp4", "file_size": 123}],
                "fast",
            )
            variants.assert_not_called()

        task, rows = await _read_task(task_id)
        assert task.status == "cancelled"
        assert task.progress == 40.0
        assert task.completed_at == cancelled_at
        assert task.error_message == "cancelled by user"
        assert task.output_count == 1 and len(rows) == 1
        async with dbmod.async_session_factory() as s:
            episode = (await s.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
            assert episode.status == "failed"

    asyncio.run(scenario())


def test_celery_failure_and_progress_do_not_overwrite_terminal_states():
    async def scenario():
        from app.celery.tasks import _fail_slice_task, _update_slice_task_progress
        from app.models.material import SliceTask

        for terminal in ("cancelled", "completed", "failed"):
            task_id, _clips = await _bootstrap()
            async with dbmod.async_session_factory() as s:
                task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
                task.status = terminal
                task.progress = 25.0
                task.error_message = "first terminal state"
                task.completed_at = task.created_at
                await s.commit()
                finished_at = task.completed_at
            await _update_slice_task_progress(str(task_id), 99.0)
            await _fail_slice_task(str(task_id), "late failure")
            task, _ = await _read_task(task_id)
            assert task.status == terminal
            assert task.progress == 25.0
            assert task.completed_at == finished_at
            assert task.error_message == "first terminal state"

    asyncio.run(scenario())


def test_orm_candidate_delete_preserves_output_and_nulls_reference():
    async def scenario():
        from app.models.material import ClipCandidate, SliceOutput, SliceTask

        task_id, clips = await _bootstrap()
        clip_id = clips[2].id
        output_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(SliceOutput(
                id=output_id, task_id=task_id, clip_id=clip_id,
                file_name="existing.mp4", file_key="sliced/existing.mp4", file_size=123,
            ))
            await s.commit()
        async with dbmod.async_session_factory() as s:
            clip = (await s.execute(select(ClipCandidate).where(ClipCandidate.id == clip_id))).scalar_one()
            await s.delete(clip)
            await s.commit()
        async with dbmod.async_session_factory() as s:
            output = (await s.execute(select(SliceOutput).where(SliceOutput.id == output_id))).scalar_one()
            assert output is not None
            assert output.clip_id is None
            assert (await s.execute(select(ClipCandidate).where(ClipCandidate.id == clip_id))).scalar_one_or_none() is None
            assert (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one() is not None

    asyncio.run(scenario())


def test_legacy_null_snapshot_is_not_rebound_to_current_candidates():
    async def scenario():
        from app.models.material import SliceTask

        task_id, clips = await _bootstrap()
        async with dbmod.async_session_factory() as s:
            task = (await s.execute(select(SliceTask).where(SliceTask.id == task_id))).scalar_one()
            assert task.output_clip_ids is None
            await s.commit()
        async with dbmod.async_session_factory() as s:
            await _call_callback(
                s, task_id,
                outputs=[{"file_name": "out_001.mp4", "file_key": "sliced/out_001.mp4"}],
            )
            await s.commit()
        _task, rows = await _read_task(task_id)
        assert len(rows) == 1
        assert rows[0].clip_id is None
        assert rows[0].clip_id != clips[2].id

    asyncio.run(scenario())
