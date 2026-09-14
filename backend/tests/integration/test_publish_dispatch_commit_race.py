"""Issue #355 回归：投递到另一进程/队列前，业务写必须已提交。

根因（与已合并的 #350 / #354 同源）：业务写只 flush()，而 get_db() 的 commit()
位于 `yield` 之后。投递（Celery delay / Redis Stream xadd）发生后，**被投递方**是
独立进程 / 独立连接，它按 id 回查数据库：
  - 若本次 flush 的行尚未提交 → 它**查不到**该行（或读到旧值）；
  - 若投递时旧值还在 → worker 按旧状态走进错误分支。

本 Issue 覆盖三处：
  1. publish_tasks.confirm_publish_task：先 delay() 后改 status="publishing"，且只 flush；
  2. publish_tasks.requeue_publish_task：先 delay() 后写 celery_task_id，只 flush；
  3. slice_helpers._publish_to_worker：publish_slice_task() 投 Redis Stream 前未 commit，
     Go slice-worker 会立刻按 task_id 回查 slice_tasks。
     调用点 2 处：slice.py _dispatch_slice_task（run 接口）、retry_slice_task。

修法：在**业务写路径内、投递之前**显式 await db.commit()（同 #346 / #354 约定）。
不改 get_db() 的 yield 结构（commit 挪到 yield 之前会让端点抛异常时无法回滚）。
投递失败分支必须把已提交的行显式置为失败/可重试并提交，不留悬挂行。

判据（探针）：把「投递动作」本身替换成探针——在投递发生的**那一瞬间**，用
**独立 session / 独立连接**（等价于另一个进程的 worker）回查目标行。
修复前读到旧值/查不到 → FAIL；修复后读到新值 → PASS。这是真实执行，不是空转。

本用例在**没有 pytest-asyncio** 的环境下也真实执行：用 asyncio.run() 驱动，
每个用例都是普通 `def test_xxx()`（不是 async def），pytest 无需任何 async 插件。

运行：cd backend && python -m pytest tests/integration/test_publish_dispatch_commit_race.py -v
   或  cd backend && python tests/integration/test_publish_dispatch_commit_race.py

数据库：aiosqlite **临时文件**（不依赖外部 PostgreSQL）；独立 _test_engine 替换
app.database.engine / async_session_factory；DATABASE_URL 用强制覆盖（非 setdefault）。
drop_all 前有硬断言，只对「确认是临时目录下的 sqlite 测试库」的引擎执行。
"""
import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:  # 允许在未安装 pytest 的环境下直接 python 运行本文件
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

# ── 测试环境：SQLite(async) 临时文件 + 最小必填配置（须在建 app 之前设置）──
_TMP_DB = tempfile.mktemp(suffix=".db", prefix="publish_dispatch_race_")
# 强制覆盖：不是 setdefault。必须在导入 app.config / app.database 之前生效。
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["JWT_SECRET"] = "t" * 64
os.environ["MINIO_ACCESS_KEY"] = "test"
os.environ["MINIO_SECRET_KEY"] = "testtest"

from sqlalchemy.dialects.postgresql import UUID as _PGUUID
from sqlalchemy.ext.compiler import compiles


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):  # pragma: no cover - 编译期钩子
    """让 PostgreSQL 专属 UUID 类型可在 SQLite 上建表（CHAR(36) 存字符串）。"""
    return "CHAR(36)"


import app.database as dbmod
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 测试专用引擎（生产引擎带 server_settings/pool_size 等 PG 专属参数，SQLite 不接受）
_TEST_DB_URL = f"sqlite+aiosqlite:///{_TMP_DB}"
_test_engine = create_async_engine(_TEST_DB_URL)
dbmod.engine = _test_engine
dbmod.async_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)

from httpx import ASGITransport, AsyncClient

from app.auth import get_password_hash
from app.database import Base
from app.main import app
from app.models.models import (
    Episode,
    Project,
    PublishTask,
    SliceOutput,
    SliceTask,
    User,
)

_TMP_DIR = os.path.abspath(tempfile.gettempdir())
USERNAME = "benny"
PASSWORD = "pw123456"


def _assert_disposable_test_engine() -> None:
    """drop_all 前的硬断言：只对「确认是临时目录下的 sqlite 测试库」的引擎执行破坏性操作。

    任何不匹配都直接 RuntimeError 终止——宁可测试跑不起来，也绝不误删真实库。
    """
    backend = _test_engine.url.get_backend_name()
    if backend != "sqlite":
        raise RuntimeError(f"拒绝执行 drop_all：测试引擎后端为 {backend!r}，非 sqlite")
    db_path = os.path.abspath(_test_engine.url.database or "")
    if not db_path or _TMP_DIR != os.path.commonpath([db_path, _TMP_DIR]):
        raise RuntimeError(
            f"拒绝执行 drop_all：库路径 {db_path!r} 不在临时目录 {_TMP_DIR!r} 下，"
            "无法证明它是测试库"
        )
    if not os.path.basename(db_path).startswith("publish_dispatch_race_"):
        raise RuntimeError(
            f"拒绝执行 drop_all：库文件名 {db_path!r} 无测试库标记，无法证明它是测试库"
        )
    if str(dbmod.engine.url) != str(_test_engine.url):
        raise RuntimeError("app.database.engine 未被测试引擎替换，拒绝执行 drop_all")


# ─────────────────────────────────────────────────────────────
# 驱动工具：无 pytest-asyncio 也能真跑
# ─────────────────────────────────────────────────────────────

def _run(coro):
    """用 asyncio.run() 驱动协程——不依赖任何 pytest async 插件。"""
    return asyncio.run(coro)


async def _reset_db():
    """整库重建（先过硬断言，确保只碰临时 sqlite 测试库）。"""
    # 同一 pytest 进程里若还有别的 sqlite 测试模块，它们也会改 dbmod.engine。
    # 故每次 bootstrap 都重新把 app 的会话工厂指回本模块的测试引擎，
    # 保证本模块用例与执行顺序无关。
    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    _assert_disposable_test_engine()
    from wechat_download.base import WechatDownloadBase

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(WechatDownloadBase.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(WechatDownloadBase.metadata.create_all)


async def _bootstrap() -> dict:
    """建表 + 造好一条可被确认/重发的发布任务、一条可立即投递的切片任务。"""
    await _reset_db()

    project_id, episode_id = uuid.uuid4(), uuid.uuid4()
    slice_task_id, output_id = uuid.uuid4(), uuid.uuid4()
    confirm_task_id, requeue_task_id = uuid.uuid4(), uuid.uuid4()

    async with dbmod.async_session_factory() as s:
        s.add(
            User(
                id=uuid.uuid4(),
                username=USERNAME,
                password_hash=get_password_hash(PASSWORD),
                display_name="Benny",
                role="admin",
                data_scope="all",
                is_active=True,
            )
        )
        s.add(Project(id=project_id, name="p", status="active"))
        # duration 必填：no_cut（快速转换）整片切片靠它生成 cutlist，
        # 避免测试去打 MinIO / ffprobe。
        s.add(
            Episode(
                id=episode_id,
                project_id=project_id,
                title="ep1",
                source_file_key="raw/ep1.mp4",
                duration=120.0,
                status="uploaded",
            )
        )
        s.add(SliceOutput(id=output_id, task_id=slice_task_id, file_key="sliced/out.mp4"))
        # 已存在的切片任务（retry 接口的“原任务”，必须已完成/失败才可重试）
        s.add(
            SliceTask(
                id=slice_task_id,
                episode_id=episode_id,
                status="completed",
                mode="fast",
                cutlist="00:00:00 00:02:00 ep1",
                intervals="",
                source_file_key="raw/ep1.mp4",
                source_bucket="raw-footage",
            )
        )
        s.add(
            PublishTask(
                id=confirm_task_id,
                output_id=output_id,
                platform="wechat",
                status="pending_confirm",
                require_manual_confirm=True,
            )
        )
        s.add(
            PublishTask(
                id=requeue_task_id,
                output_id=output_id,
                platform="wechat",
                status="failed",
                dead_letter=True,
                dead_letter_reason="boom",
            )
        )
        await s.commit()

    return {
        "episode_id": episode_id,
        "slice_task_id": slice_task_id,
        "output_id": output_id,
        "confirm_task_id": confirm_task_id,
        "requeue_task_id": requeue_task_id,
    }


async def _read_publish_task(task_id) -> dict:
    """用**独立 session / 独立连接**读 publish_tasks——等价于 celery worker 进程。"""
    async with dbmod.async_session_factory() as s:
        row = (
            await s.execute(select(PublishTask).where(PublishTask.id == task_id))
        ).scalar_one_or_none()
        if row is None:
            return {"_missing": True}
        return {
            "_missing": False,
            "status": row.status,
            "celery_task_id": row.celery_task_id,
            "dead_letter": row.dead_letter,
            "error_message": row.error_message,
        }


async def _read_slice_task(task_id) -> dict:
    """用**独立 session / 独立连接**读 slice_tasks——等价于 Go slice-worker 的回查。"""
    async with dbmod.async_session_factory() as s:
        row = (
            await s.execute(select(SliceTask).where(SliceTask.id == task_id))
        ).scalar_one_or_none()
        if row is None:
            return {"_missing": True}
        return {
            "_missing": False,
            "status": row.status,
            "error_message": row.error_message,
        }


# ─────────────────────────────────────────────────────────────
# 「另一个进程」式的同步探针
# ─────────────────────────────────────────────────────────────
# Celery 的 .delay() 是同步 API，探针在同步栈里被调用，内部无法 await。
# 于是探针在**独立线程**里跑一个**独立事件循环 + 独立 engine/连接**去读库——
# 这比同进程共享连接更贴近真实：celery worker / Go slice-worker 本来就是别的进程、
# 别的连接池。线程内自建 engine，避免跨事件循环复用连接。

def _probe_in_independent_thread(read_coro_factory) -> dict:
    """在独立线程 + 独立事件循环 + 独立 engine 中执行一次读库，返回结果。"""
    import threading

    box: dict = {}

    def _worker():
        async def _main():
            eng = create_async_engine(_TEST_DB_URL)
            maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
            try:
                return await read_coro_factory(maker)
            finally:
                await eng.dispose()

        try:
            box["value"] = asyncio.run(_main())
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=30)
    if "error" in box:
        raise box["error"]
    return box["value"]


def _probe_read_publish_task_sync(task_id) -> dict:
    async def _read(maker):
        async with maker() as s:
            row = (
                await s.execute(select(PublishTask).where(PublishTask.id == task_id))
            ).scalar_one_or_none()
            if row is None:
                return {"_missing": True}
            return {
                "_missing": False,
                "status": row.status,
                "celery_task_id": row.celery_task_id,
                "dead_letter": row.dead_letter,
                "error_message": row.error_message,
            }

    return _probe_in_independent_thread(_read)


def _probe_read_slice_task_sync(task_id) -> dict:
    async def _read(maker):
        async with maker() as s:
            row = (
                await s.execute(select(SliceTask).where(SliceTask.id == task_id))
            ).scalar_one_or_none()
            if row is None:
                return {"_missing": True}
            return {
                "_missing": False,
                "status": row.status,
                "error_message": row.error_message,
            }

    return _probe_in_independent_thread(_read)


async def _probe_read_slice_task_async(maker_or_task_id, task_id=None):
    """供 async 探针（publish_slice_task 替身）复用：同进程独立 session 采样。"""
    async with dbmod.async_session_factory() as s:
        row = (
            await s.execute(select(SliceTask).where(SliceTask.id == maker_or_task_id))
        ).scalar_one_or_none()
        if row is None:
            return {"_missing": True}
        return {
            "_missing": False,
            "status": row.status,
            "error_message": row.error_message,
        }


async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _patch_broker(delay_target: str, probe):
    """把 Celery 投递动作替换成**同步**探针（.delay 是同步 API）。

    探针内部用 `probe_sync()` 取独立连接的采样结果——因为探针在同步栈里被调用，
    不能在 .delay 里 await。故用「同步探针 + 预先在同事件循环里可 await 的入口」：
    这里统一用 `asyncio.get_event_loop().run_until_complete` 陷阱会死锁，
    改为探针只记录「谁在何时被调用」，真正的采样放到 awaitable 包装里（见各用例）。
    """
    return patch(delay_target, probe)


# ─────────────────────────────────────────────────────────────
# 用例 1：confirm_publish_task 投递那一刻，publishing 已对独立连接可见
# ─────────────────────────────────────────────────────────────
def test_confirm_publish_task_status_visible_at_dispatch_time():
    """修复前：投递瞬间独立连接读到的还是 pending_confirm → FAIL。
    修复后：投递前已提交 status='publishing' → PASS。
    """
    seen: dict = {}

    def probe_delay(task_id, *a, **kw):
        # ← 投递瞬间（Celery broker 收到任务的那一刻）在独立线程/连接采样
        assert isinstance(task_id, str), "投递应传 task id 字符串（独立进程按 id 回查）"
        seen.update(_probe_read_publish_task_sync(uuid.UUID(task_id)))
        return SimpleNamespace(id="stub-celery-id")

    async def _case():
        ids = await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.celery.tasks.confirm_publish_worker.delay", probe_delay):
                resp = await client.post(
                    f"/api/publish/tasks/{ids['confirm_task_id']}/confirm",
                    headers=headers,
                )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "publishing", resp.text
        return await _read_publish_task(ids["confirm_task_id"])

    final = _run(_case())
    assert not seen.get("_missing"), (
        "投递瞬间独立连接查不到该行：worker 按 id 回查不到任务"
    )
    assert seen["status"] == "publishing", (
        f"投递瞬间 status 对独立连接仍为 {seen['status']!r}（应为 'publishing'）："
        "worker 读到旧状态 → 走进错误分支"
    )
    # celery_task_id 是「投递的返回值」，投递那一刻本就还不存在——不做投递瞬间断言，
    # 只校验请求收尾后已落库（见用例 5）。
    assert final["status"] == "publishing"
    assert final["celery_task_id"] == "stub-celery-id"


# ─────────────────────────────────────────────────────────────
# 用例 2：requeue_publish_task 投递那一刻，重置后的 pending 已对独立连接可见
# ─────────────────────────────────────────────────────────────
def test_requeue_publish_task_reset_visible_at_dispatch_time():
    """修复前：投递瞬间独立连接读到的仍是 dead_letter=True / failed → FAIL。
    修复后：投递前已提交 dead_letter=False / status='pending' → PASS。
    """
    seen: dict = {}

    def probe_delay(task_id, *a, **kw):
        assert isinstance(task_id, str), "投递应传 task id 字符串（独立进程按 id 回查）"
        seen.update(_probe_read_publish_task_sync(uuid.UUID(task_id)))
        return SimpleNamespace(id="stub-celery-id")

    async def _case():
        ids = await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.celery.tasks.task_publish_video.delay", probe_delay):
                resp = await client.post(
                    f"/api/publish/tasks/{ids['requeue_task_id']}/requeue",
                    headers=headers,
                )
            assert resp.status_code == 200, resp.text
        return await _read_publish_task(ids["requeue_task_id"])

    final = _run(_case())
    assert not seen.get("_missing"), "投递瞬间独立连接查不到该行"
    assert seen["status"] == "pending", (
        f"投递瞬间 status 对独立连接仍为 {seen['status']!r}（应为 'pending'）："
        "worker 读到旧行 → 按旧状态直接返回"
    )
    assert seen["dead_letter"] is False, (
        "投递瞬间 dead_letter 对独立连接仍为 True（死信重置未提交）"
    )
    assert seen["error_message"] is None
    assert final["status"] == "pending"
    assert final["celery_task_id"] == "stub-celery-id"


# ─────────────────────────────────────────────────────────────
# 用例 3：_publish_to_worker 投递那一刻，slice_tasks 行已对独立连接可见
#         （覆盖 slice.py 的两个调用点）
# ─────────────────────────────────────────────────────────────
def test_publish_to_worker_run_entry_slice_task_visible_at_dispatch_time():
    """run_slice → _dispatch_slice_task → _publish_to_worker 调用点。

    投递函数 publish_slice_task() 被调用的瞬间，用独立连接回查 slice_tasks。
    修复前：新任务行尚未 commit → 查不到（_missing）→ FAIL；
    修复后：可见 status='pending' → PASS。
    """
    seen: dict = {}

    async def probe_publish_slice_task(task_data, priority="normal"):
        seen.update(
            await _read_slice_task(uuid.UUID(task_data["task_id"]))
        )
        return "1700000000000-0"

    async def _case():
        ids = await _bootstrap()
        from app.api import slice as slice_module
        from app.api import slice_helpers

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch.object(
                slice_helpers, "publish_slice_task", probe_publish_slice_task
            ), patch.object(
                slice_helpers, "store_task_callback_token",
                lambda *a, **k: asyncio.sleep(0),
            ), patch.object(
                slice_module, "ensure_bucket", lambda *a, **k: asyncio.sleep(0),
            ), patch.object(
                slice_module, "get_presigned_url",
                lambda *a, **k: asyncio.sleep(0, result="http://minio/x"),
            ):
                resp = await client.post(
                    f"/api/episodes/{ids['episode_id']}/slice/run",
                    json={"engine": "worker", "no_cut": True},
                    headers=headers,
                )
            return resp

    resp = _run(_case())
    assert resp.status_code != 401, f"鉴权失败: {resp.text}"
    assert not seen.get("_missing"), (
        "投递瞬间独立连接在 slice_tasks 中查不到该任务："
        "Go slice-worker 立刻按 task_id 回查会读不到行 → 任务或永久悬挂"
    )
    assert seen["status"] == "pending", (
        f"投递瞬间 status 对独立连接为 {seen['status']!r}（应为 'pending'）"
    )


def test_publish_to_worker_retry_entry_slice_task_visible_at_dispatch_time():
    """retry_slice_task → _publish_to_worker 调用点（第二个调用点，约 L1694）。"""
    seen: dict = {}

    async def probe_publish_slice_task(task_data, priority="normal"):
        seen.update(
            await _read_slice_task(uuid.UUID(task_data["task_id"]))
        )
        return "1700000000000-0"

    async def _case():
        ids = await _bootstrap()
        from app.api import slice as slice_module
        from app.api import slice_helpers

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch.object(
                slice_helpers, "publish_slice_task", probe_publish_slice_task
            ), patch.object(
                slice_helpers, "store_task_callback_token",
                lambda *a, **k: asyncio.sleep(0),
            ), patch.object(
                slice_module, "ensure_bucket", lambda *a, **k: asyncio.sleep(0),
            ), patch.object(
                slice_module, "get_presigned_url",
                lambda *a, **k: asyncio.sleep(0, result="http://minio/x"),
            ):
                resp = await client.post(
                    f"/api/slice-tasks/{ids['slice_task_id']}/retry",
                    headers=headers,
                )
            return resp

    resp = _run(_case())
    assert resp.status_code != 401, f"鉴权失败: {resp.text}"
    assert not seen.get("_missing"), (
        "重试投递瞬间独立连接在 slice_tasks 中查不到新任务行："
        "Go slice-worker 回查读不到 → 重试任务永久悬挂"
    )
    assert seen["status"] == "pending", (
        f"投递瞬间 status 对独立连接为 {seen['status']!r}（应为 'pending'）"
    )


# ─────────────────────────────────────────────────────────────
# 用例 4：投递失败分支不留悬挂行
# ─────────────────────────────────────────────────────────────
def test_dispatch_failure_marks_slice_task_failed_no_orphan():
    """publish_slice_task() 返回空 msg_id（Redis 不可用）时：
    行已按「投递前 commit」提交，失败分支必须把它显式置 failed + error_message 并提交，
    绝不留下「已提交但无人消费」的 pending 悬挂行。
    """
    dispatch_seen: dict = {}

    async def probe_failing_publish(task_data, priority="normal"):
        # 投递瞬间：行应已提交可见（「先提交再投递」的另一面证据）
        sampled = await _read_slice_task(uuid.UUID(task_data["task_id"]))
        dispatch_seen.update(sampled)
        # 记下本次新建的任务 id，避免后面误读库里预置的那条 completed 行
        dispatch_seen["task_id"] = uuid.UUID(task_data["task_id"])
        return None  # 模拟 Redis 不可用

    async def _case():
        ids = await _bootstrap()
        from app.api import slice as slice_module
        from app.api import slice_helpers

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch.object(
                slice_helpers, "publish_slice_task", probe_failing_publish
            ), patch.object(
                slice_helpers, "store_task_callback_token",
                lambda *a, **k: asyncio.sleep(0),
            ), patch.object(
                slice_module, "ensure_bucket", lambda *a, **k: asyncio.sleep(0),
            ):
                resp = await client.post(
                    f"/api/episodes/{ids['episode_id']}/slice/run",
                    json={"engine": "worker", "no_cut": True},
                    headers=headers,
                )
        return resp

    resp = _run(_case())
    assert resp.status_code == 500, resp.text
    assert not dispatch_seen.get("_missing"), (
        "投递瞬间独立连接查不到新建的任务行：行未在投递前提交"
    )
    # 端点返回后，用独立连接读**本次新建的**任务行：必须是终态 failed，不能停在 pending
    row = _run(_read_slice_task(dispatch_seen["task_id"]))
    assert not row.get("_missing"), "任务行在投递失败后消失"
    assert row["status"] == "failed", (
        f"投递失败后任务行仍为 {row['status']!r}（悬挂行：已提交但无人消费）"
    )
    assert row["error_message"], "投递失败后未写入 error_message，前端无法感知失败"


# ─────────────────────────────────────────────────────────────
# 用例 5：显式 commit 后 get_db 尾部 commit 幂等空操作（不丢数据/不报错）
# ─────────────────────────────────────────────────────────────
def test_explicit_commit_tail_commit_is_idempotent_noop():
    def probe_delay(*a, **kw):
        return SimpleNamespace(id="stub-celery-id")

    async def _case():
        ids = await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            with patch("app.celery.tasks.confirm_publish_worker.delay", probe_delay):
                resp = await client.post(
                    f"/api/publish/tasks/{ids['confirm_task_id']}/confirm",
                    headers=headers,
                )
            assert resp.status_code == 200, resp.text
        # 整条请求（含 get_db 尾部 commit）收尾后，行仍应保持 publishing
        return await _read_publish_task(ids["confirm_task_id"])

    row = _run(_case())
    assert row["status"] == "publishing"
    assert row["celery_task_id"] == "stub-celery-id"


if __name__ == "__main__":
    # 无需 pytest 也能直接跑：python tests/integration/test_publish_dispatch_commit_race.py
    _here = sys.modules[__name__]
    _tests = sorted(
        (n, f) for n, f in vars(_here).items()
        if n.startswith("test_") and callable(f)
    )
    _failed = 0
    for _name, _fn in _tests:
        try:
            if _fn.__code__.co_argcount:
                _fn(None)  # pytest.mark 参数化用例此处不跑
            else:
                _fn()
            print(f"PASS  {_name}")
        except Exception as _exc:  # noqa: BLE001
            _failed += 1
            print(f"FAIL  {_name}: {_exc}")
    print(f"\n{len(_tests) - _failed} passed, {_failed} failed, {len(_tests)} collected")
    sys.exit(1 if _failed else 0)
