"""素材库 P0 API 流集成测试（ISSUE 素材库-20261103）。

智令反推、autoclip 文案服务、MinIO 读写**全部 mock**（不打真实网络、不扣费），
但走**真实 FastAPI app + 真实 SQLAlchemy 会话 + 真实 asset_* 5 张表**（SQLite 临时库），
验证的是单测覆盖不到的接线正确性：

1. 链接批量导入：跨批次去重命中（默认跳过并回「谁传过」）/ force_duplicates 强制入库 / 超单批上限 400；
2. 文件批量上传：逐文件 fail-soft（非法扩展名单独失败，整批不连坐）、全失败不留孤儿批次、
   `batch_id` 追加进同一批次、失败文件走 `/assets/upload/retry` 补投回原批、并发封顶 3、
   content type 跟扩展名走、ffprobe 回写 duration；
3. 反推闸门三档：blocked（余额不足）只有 admin 能 force、need_approval 必须 admin+confirmed、
   已 success/running 的素材绝不重复提交（重复＝重复扣费）、文件素材必走 doc/125；
3b. 一线排队列（A4-1/A4-6）：超单批上限**自动拆批**并回 split_into（不是 400 打回）、
   `batch_id + limit + offset` 分段续排（提交成功的自动离开队列，前端不自己攒 id）、
   `/assets/analyze/refresh-batch` 一次收敛整批在跑的（含「running 却没有任务行」的残留判 failed）、
   `waiting_prompt`（待反推）与 `analyzing`（在跑）是两个态；
4. 文案生成：反推脚本没就绪就硬拦、候选落库带字数/风险词/一致性三条校验；
5. 审核队列：**过审/投产跑同一套复核**（形态+block 风险词+一致性），生产者不得自审、驳回必填理由、
   改后通过留痕；admin 才能带理由豁免且豁免内容入审计；撤销过审把未投递单整批作废并禁导出；
   风险词表来自 system_config（加词不发版、可配豁免正则）；
6. 生产单：未过审进不来、N 上限、N 条差异化 variant_basis 互不相同、展开改词标 drift、
   作废单导不出正文、导出/下载都留交付痕迹；
7. 可见范围口径（11-03 用户拍板改定）：**素材内容全量可见、不分权限** —— 原先「审核跨人 +
   素材列表按 data_scope」两套口径一并取消，谁能看不再受限，谁能**写**（审核/投产）仍按角色，
   生产者不得自审判据照旧；
8. 列表可用性（A4-3/A4-4）：创建人 / CST 日期区间 / 审核态 / **阶段级** 四个筛选 + `sort=failed_first`
   把卡住的顶到最前；素材**原文件**有下载口（文件素材 presigned + 审计，链接素材如实回 external）；
9. 抽帧（11-04 批 F）：文件入库**自动排** frames 任务（真跑 ffmpeg，桶 mock）→ 3 单帧 + 1 九宫格
   落 `asset_frames` 并首次给 `cover_image_key` 写上值；重抽是**覆盖**不是叠加（部分唯一索引
   让同一素材的两个产物各占一行而不是撞 `(asset_id,kind,seq)`）；链接素材/超上限/时长未知一律
   `skipped` 带人话原因、不拦任何业务步骤；`GET /assets/frames` 批量取图（inline presign、
   不写审计）且必须排在 `/assets/{asset_id}` **之前**；任务台账默认不列抽帧。

运行：cd backend && python -m pytest tests/integration/test_asset_library_api.py -v
"""

import asyncio
import json
import re
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import socket
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:  # 允许在未安装 pytest 的环境下直接 python 运行
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

_TMPDIR = Path(tempfile.mkdtemp(prefix="asset-library-"))
_DB_PATH = _TMPDIR / "asset_library.db"
_DB_URL = f"sqlite+aiosqlite:///{_DB_PATH}"

_TEST_ENV = {
    "DATABASE_URL": _DB_URL,
    "JWT_SECRET": "t" * 64,
    "MINIO_ACCESS_KEY": "test",
    "MINIO_SECRET_KEY": "testtest",
    "WECHAT_DL_ZHILING_KEY": "fake-key",
}


class _EnvOverride:
    def __init__(self, values):
        self._values = values
        self._saved = {}

    def __enter__(self):
        for k, v in self._values.items():
            self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k, prev in self._saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        return False


for _k, _v in _TEST_ENV.items():
    if _k != "DATABASE_URL":
        os.environ.setdefault(_k, _v)


atexit.register(lambda: shutil.rmtree(_TMPDIR, ignore_errors=True))

from sqlalchemy.dialects.postgresql import UUID as _PGUUID  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):  # pragma: no cover - 编译期钩子
    return "CHAR(36)"


with _EnvOverride(_TEST_ENV):
    import app.database as dbmod
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.api import assets as assets_api
    from app.asset_main import create_asset_app
    from app.auth import get_password_hash
    from app.config import settings
    from app.database import Base
    from fastapi import HTTPException
    from app.main import app
    from app.models.asset import (
        AS_READY_TO_PRODUCE,
        FRAME_GRID,
        FRAME_OUTPUT_THUMB,
        FRAME_THUMB,
        JB_INTERRUPTED,
        PRODUCTION_STATES,
        RV_APPROVED,
        RV_PENDING,
        RV_PASSED_EDITED,
        RV_REJECTED,
        AssetBatch,
        AssetCard,
        AssetCategory,
        AssetFrame,
        AssetItem,
        AssetJob,
        AssetOutput,
        AssetOverlayPreset,
        AssetProduction,
        AssetScript,
        AssetSummary,
        JB_QUEUED,
        JB_RUNNING,
        JB_SUCCEEDED,
        JOB_COMPOSE,
        JOB_FRAMES,
        JOB_PRODUCE,
        JOB_SUMMARY_GENERATE,
        DEFAULT_ASSET_CATEGORIES,
        OVERLAY_PRESET_SHARED,
        OVERLAY_PRESET_USER,
    )
    from app.models.audit import AuditLog
    from app.models.material import Episode, Project, SliceOutput, SliceTask, SystemConfig
    from app.models.models import User
    from app.services import asset_service as svc

_test_engine = create_async_engine(_DB_URL)

PASSWORD = "pw123456"
MATERIAL_USER = "asset_mat"      # 素材专员（导入 + 反推 + 出文案）
OPERATOR_USER = "asset_op"       # 运营专员（审核 + 投产；11-03 起 data_scope 不再过滤素材库读口）
ADMIN_USER = "asset_ad"          # 管理员（放批 / 强推 / 自审逃生门）

VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096

# 反推详规（=智令 doc/120 的 content）：钩子文案里的实体必须能在这一段命中
SCRIPT = (
    "镜头1：王总推开康华医院的大门，脸色铁青，站了三个小时没人出来见他。\n"
    "镜头2：护士把病历摔在桌上，一句「你签字的时候可不是这个态度」。\n"
    "口播：王总在康华医院门口从白天站到黑夜，最后等来一张病危通知。"
)

# 三条候选：1 条推荐且实体可命中 / 1 条实体对不上（一致性 False）/ 1 条含高风险词
CANDIDATES = [
    {"text": "王总在康华医院门口站了三小时，谁也没想到他会当场翻脸", "style_tag": "statement",
     "formula_tag": "悬念前置", "is_recommended": True},
    {"text": "李姐把合同撕了，围观的人一个都不敢出声", "style_tag": "question",
     "formula_tag": "反问起手"},
    {"text": "这药百分百根治，谁都不敢说", "style_tag": "dialogue", "formula_tag": "反常识"},
]

DOUYIN_1 = "https://v.douyin.com/iAbcDeF/"
DOUYIN_2 = "https://www.douyin.com/video/7412345678901234567?utm_source=share&timestamp=1"
DOUYIN_1_TRACKED = "https://v.douyin.com/iAbcDeF/?utm_source=copy&from=mobile&secuid=MS4w"
# 第三部**真正不同**的片子。需要"再建一条素材"时用这个，别拿 DOUYIN_1_TRACKED 顶——
# 它归一化后就是 DOUYIN_1，跨批次会被判重、建不出行。
DOUYIN_3 = "https://www.douyin.com/video/7511222333444555666"


def _run(coro, *, with_frames: bool = False):
    """跑一个测试场景。

    默认把导入/拼接后**自动排的抽帧任务**按住（`_enqueue_frames` 打桩）。原因不是抽帧
    有问题，而是它是批 F 起第一次出现在这条链路里的后台任务：真排上去就会在同一个 loop 上
    并发跑，抢别的用例挂在 `download_to_file` / `compose.probe_media` 上的 mock（拼接
    「第几段坏了」的 side_effect 序列会被抽帧吃掉一格），还会对着本机没有的 MinIO:9000
    重试。抽帧自己的用例传 `with_frames=True` 走真链路。

    批 J 起同样的按法也罩住两个新搭车任务（`_enqueue_download`/`_enqueue_preview`）：
    反推默认搭车下载原片、审核搭车备提示词——真排上去同样会在 loop 上并发跑，
    抢掉各用例自己挂的 `dispatch_parse`/`_call_autoclip` mock。要测搭车链路的用例
    自己在这两个名字上另挂替身。
    """
    if with_frames:
        return asyncio.run(coro)
    with patch("app.api.assets._enqueue_frames", AsyncMock(
            return_value={"queued": False, "job_id": None, "note": "测试侧默认不排抽帧"})), \
         patch("app.api.assets._enqueue_download", AsyncMock(
            return_value={"queued": False, "job_id": None, "queued_count": 0,
                          "note": "测试侧默认不排下载"})), \
         patch("app.api.assets._enqueue_preview", AsyncMock(
            return_value={"queued": False, "job_id": None, "note": "测试侧默认不排预览"})):
        return asyncio.run(coro)


async def _bootstrap():
    """建表（走真实 create_all —— 部署侧新表唯一生效路径）+ 三个角色账号。"""
    import wechat_download.models  # noqa: F401
    from wechat_download.base import WechatDownloadBase

    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    # 风险词表缓存是进程级的（TTL 300s）：不清就会把上一个测试写的 SystemConfig
    # 带进下一个，测出来的"热更生效"其实是被缓存骗了。
    from app.api import assets as assets_api
    assets_api._RISK_CACHE["at"], assets_api._RISK_CACHE["payload"] = 0.0, None

    # 抽帧/下载这类后台任务的连接**不会跟着 `asyncio.run` 一起收**：上一条用例的 loop 关掉了，
    # 池子里那条连接还活着并握着写锁，于是本条用例的 `DROP TABLE` 撞上
    # `sqlite3.OperationalError: database is locked`（11-24 全套里偶发一次，单跑必绿）。
    # 先把引擎池子放掉再建表；仍被锁就短重试几次——这是测试基建的时序问题，不是被测代码。
    await _test_engine.dispose()
    for attempt in range(4):
        try:
            async with _test_engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(WechatDownloadBase.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(WechatDownloadBase.metadata.create_all)
            break
        except Exception as exc:  # noqa: BLE001 — 只认"库被占着"这一种，别的照抛
            if "database is locked" not in str(exc) or attempt == 3:
                raise
            await asyncio.sleep(0.25)
            await _test_engine.dispose()
    async with dbmod.async_session_factory() as s:
        s.add_all([
            User(id=uuid.uuid4(), username=MATERIAL_USER, password_hash=get_password_hash(PASSWORD),
                 display_name="素材专员", role="material", data_scope="all", is_active=True),
            User(id=uuid.uuid4(), username=OPERATOR_USER, password_hash=get_password_hash(PASSWORD),
                 display_name="运营专员", role="operator", data_scope="own", is_active=True),
            User(id=uuid.uuid4(), username=ADMIN_USER, password_hash=get_password_hash(PASSWORD),
                 display_name="管理员", role="admin", data_scope="all", is_active=True),
        ])
        # 钩子原型字典（11-04 拍板①）：现网是 init_db() 启动时种这 7 行，
        # 测试侧不走 init_db（直接 create_all），所以在这里点同名函数——
        # 种入本身也顺带被每条用例验一遍"跑两次不会插出第二份"。
        await dbmod.ensure_default_asset_categories(s)
        await s.commit()


async def _client_and_headers(target_app=None):
    """一个 client + 三个角色的 Authorization 头；可指定主 app 或独立 asset app。"""
    client = AsyncClient(transport=ASGITransport(app=target_app or app), base_url="http://test", timeout=30)
    headers = {}
    for name, key in ((MATERIAL_USER, "material"), (OPERATOR_USER, "operator"), (ADMIN_USER, "admin")):
        r = await client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
        assert r.status_code == 200, r.text
        headers[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return client, headers


async def _rows(model, *where):
    stmt = select(model)
    for w in where:
        stmt = stmt.where(w)
    async with dbmod.async_session_factory() as s:
        return list((await s.execute(stmt.order_by(model.created_at))).scalars().all())


async def _count(model):
    async with dbmod.async_session_factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def _row_of(model, row_id):
    """按 id 回读一行（`_rows` 返回的是已 detach 的旧快照，改完状态再拿它会读到写回前的值）。"""
    async with dbmod.async_session_factory() as s:
        return await s.get(model, uuid.UUID(str(row_id)))


@pytest.mark.asyncio
async def test_standalone_asset_app_has_auth_and_only_asset_business_routes():
    """独立入口能独立登录/访问素材库，但不能借它访问主系统业务路由。"""
    await _bootstrap()
    standalone = create_asset_app(run_job_sweep=False)
    client, headers = await _client_and_headers(standalone)

    assert (await client.get("/api/health")).json() == {
        "status": "ok", "service": "clip-asset-backend"
    }
    assert (await client.get("/api/assets/scripts", headers=headers["material"])).status_code == 200
    assert (await client.get("/api/assets/scripts")).status_code == 401
    me = await client.get("/api/auth/me", headers=headers["material"])
    assert me.status_code == 200 and me.json()["username"] == MATERIAL_USER
    assert "/api/auth/refresh" in standalone.openapi()["paths"]
    # SQLite 夹具的 expires_at 为 naive UTC，主 auth 的 refresh 比较面向 Postgres；
    # 本用例只钉独立入口的会话路由集合，不重复验证主登录模块的数据库适配。
    assert (await client.get("/api/projects", headers=headers["admin"])).status_code == 404

    # 独立 API 不接管主系统用户/角色/职能管理，也不能顺手暴露改密入口。
    assert (await client.get("/api/auth/users", headers=headers["admin"])).status_code == 404
    assert (await client.post("/api/auth/register", headers=headers["admin"], json={})).status_code == 404
    assert (await client.put("/api/auth/profile", headers=headers["admin"], json={})).status_code == 404
    assert (await client.post("/api/auth/logout", headers=headers["material"])).status_code == 200


def test_external_main_app_does_not_register_asset_routes():
    """在干净解释器里构建 external 主 app，防止全局 app 的 embedded 状态掩盖漏配。"""
    env = os.environ.copy()
    env.update(_TEST_ENV)
    env["ASSET_API_MODE"] = "external"
    probe = (
        "import json; from app.main import app; "
        "print(json.dumps(sorted(app.openapi()['paths'])))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout.strip().splitlines()[-1])
    assert any(path.startswith("/api/projects") for path in paths)
    assert not any(path.startswith("/api/assets") for path in paths)


@pytest.mark.asyncio
async def test_asset_startup_sweep_has_one_owner_per_mode():
    """embedded 由主 app 清扫；external 主 app 不碰，独立 asset-api 才清扫。"""
    import app.asset_main as asset_main

    standalone = create_asset_app(run_job_sweep=False)
    with patch.object(assets_api, "sweep_interrupted_asset_jobs", new_callable=AsyncMock) as sweep, \
            patch.object(asset_main, "close_db", new_callable=AsyncMock):
        async with standalone.router.lifespan_context(standalone):
            pass
        sweep.assert_not_awaited()

    standalone = create_asset_app(run_job_sweep=True)
    with patch.object(assets_api, "sweep_interrupted_asset_jobs", new_callable=AsyncMock) as sweep, \
            patch.object(asset_main, "close_db", new_callable=AsyncMock):
        async with standalone.router.lifespan_context(standalone):
            pass
        sweep.assert_awaited_once()

    with patch.object(settings, "ASSET_API_MODE", "external"), \
            patch("app.main.init_db", new_callable=AsyncMock), \
            patch("app.main._create_seed_users", new_callable=AsyncMock), \
            patch("app.main._create_seed_platform_profiles", new_callable=AsyncMock), \
            patch("app.main._create_seed_alert_rules", new_callable=AsyncMock), \
            patch("app.main._sweep_wechat_dl_zombies_at_startup", new_callable=AsyncMock), \
            patch("app.main._sweep_asset_jobs_at_startup", new_callable=AsyncMock) as main_sweep, \
            patch("app.main.close_db", new_callable=AsyncMock):
        async with app.router.lifespan_context(app):
            pass
        main_sweep.assert_not_awaited()


async def _import(client, h, links, **extra):
    resp = await client.post("/api/assets/import/batch", json={"links": links, **extra}, headers=h)
    return resp


async def _make_ready_asset(client, h, url=DOUYIN_2, *, script=SCRIPT, category_id=None):
    """导入一条链接，并把它的反推任务伪造成**已成功**（直接写 prompt 任务行 + 阶段态），
    返回 (asset_id, task_id)。文案生成/审核/生产这一段只依赖 content，不依赖智令网络。

    `category_id`（11-04 拍板①）：带上就是"导入抽屉选了整批默认原型"，用于验文案继承。
    """
    resp = await _import(
        client, h, [url], **({"category_id": category_id} if category_id else {})
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()["items"][0]
    asset_id = item["id"]

    from wechat_download.models import PT_SUCCESS, WechatDlPromptTask

    task_id = uuid.uuid4()
    async with dbmod.async_session_factory() as s:
        s.add(WechatDlPromptTask(
            id=task_id, created_by=None, source_type="url", source_url=url,
            provider_task_id="fake-provider-1", status=PT_SUCCESS, content=script,
            max_duration=180,
        ))
        asset = await s.get(AssetItem, uuid.UUID(asset_id))
        asset.prompt_task_id = task_id
        asset.stage_prompt = "success"
        # 11-09 拆态：这一步只是稿就位，出文案还没提交
        asset.status = "waiting_summary"
        await s.commit()
    return asset_id, task_id


def _fake_autoclip(*, candidates=None, expand_prompt=None, expand_error=None, generate_error=None,
                   expand_deviation=None, web_error=None, web_prompts=None, gen_title=None,
                   expand_titles=None, slots_items=None, slots_error=None):
    """autoclip 文案服务替身：按 path 分发，expand 默认把过审钩子**原样**包进提示词。"""

    async def _call(path, payload, timeout=180.0):
        if path.endswith("hook-copy/slots"):
            # 11-10「帮我提炼原值」：用例自己给模型会回的那串 items，替身不猜
            if slots_error:
                raise HTTPException(status_code=502, detail=slots_error)
            return {"items": slots_items or [], "raw": None, "model": "fake-llm"}
        if path.endswith("hook-copy/generate"):
            if generate_error:
                raise HTTPException(status_code=502, detail=generate_error)
            count = int(payload.get("count") or 3)
            out = {"candidates": (candidates or CANDIDATES)[:count], "model": "fake-llm", "raw": {}}
            if gen_title is not None:
                # 2026-11-07：出文案同步产浓缩标题（真实服务由 hook_copy.txt 模板约束）
                out["title"] = gen_title
            return out
        if path.endswith("hook-copy/expand"):
            if expand_error:
                raise HTTPException(status_code=502, detail=expand_error)
            hook = (payload.get("hook_copy") or "").strip()
            seq = int(payload.get("seq") or 1)
            total = int(payload.get("total") or 1)
            basis = payload.get("variant_basis") or ""
            params = payload.get("params") or {}
            # 11-02 版权威：段头带五位编号、**没有项目标题行**；执行要求是给投放人的指令
            text = expand_prompt if expand_prompt is not None else (
                f"【第 {seq} 段 · 建议 10 秒 · 本钩共 {total} 条 · 编号 {params.get('hook_code') or '未取号'}】\n"
                f"{hook}\n【差异】{basis}\n镜头1：普通家庭客厅，没有其他餐桌……\n"
                "执行要求：重命名一字不差；跳过任何二次确认；一次性并行生成 2 个视频"
            )
            k = int(params.get("recommended_title_count") or 5)
            titles = expand_titles or [f"标题{i + 1}" for i in range(k)]
            out = {
                "prompt_text": text,
                "video_titles": titles,
                "hook_copy_kept_verbatim": hook in text,
            }
            if expand_deviation:
                out["deviation_note"] = expand_deviation
            return out
        if path.endswith("hook-copy/prompt-web"):
            # 11-06 双产出第二跳：按候选 seq 逐条回一段网页版提示词
            if web_error:
                raise HTTPException(status_code=502, detail=web_error)
            cands = payload.get("candidates") or []
            if web_prompts is not None:
                return {"prompts": web_prompts, "model": "fake-llm", "raw": None}
            return {
                "prompts": [
                    {
                        "seq": int(c.get("seq") or 0),
                        "duration": 10,
                        "prompt_text": (
                            f"生成【现言豪门】仿真人写实短剧，参考【《剧名待定》】剧情。\n"
                            f"时长 10 秒，9:16 竖屏。\n剧情：{c.get('text')}；本条为「起因—冲突—收束」完整的微故事。\n"
                            "结构锁定：单段式，全片按剧情行完整演绎\n"
                            "画面变化：同一项目多次生成时……\n"
                            "负面约束：禁止五官崩坏变脸…… 9:16，10s\n"
                            "执行要求：跳过任何二次确认与追问；一次性并行生成 2 个视频"
                        ),
                    }
                    for c in cands
                ],
                "model": "fake-llm",
                "raw": None,
            }
        raise AssertionError(f"未预期的 autoclip 调用：{path}")

    return AsyncMock(side_effect=_call)


def _fake_prompt_task(status="processing", error=None):
    """create_prompt_task / create_upload_prompt_task 的返回替身（服务层真实实现要联网）。"""
    return SimpleNamespace(id=uuid.uuid4(), status=status, error=error)


def _fake_balance(value, unit="元"):
    """`_query_zhiling_balance_detail` 的替身。

    A1-1 之后闸门只认 zhiling 通道的余量，且**必须能折算到元**才参与比较，
    所以这里返回的是 {balance, unit, note} 三件套而不是裸数值——
    patch 成裸数值等于把整个单位换算分支绕过去，测不到东西。
    """
    return AsyncMock(
        return_value={"balance": value, "unit": unit if value is not None else None, "note": None}
    )


def _fake_download_writer(payload=VIDEO_BYTES):
    async def _dl(bucket, object_key, local_path):
        with open(local_path, "wb") as fh:
            fh.write(payload)
        return True

    return AsyncMock(side_effect=_dl)


# ─────────────────────────  1. 链接批量导入  ─────────────────────────


def test_import_dedupes_across_batches_and_allows_force():
    """跨批次同素材：默认跳过并回「几月几日 谁 导入（AS-XXXX）」；放行有整批与逐条两档（A4-2）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]

        first = await _import(client, hm, [DOUYIN_1, "  ", "不是链接"])
        assert first.status_code == 201, first.text
        b1 = first.json()
        assert len(b1["items"]) == 1
        assert b1["items"][0]["source_kind"] == "link"
        assert b1["items"][0]["status"] == "waiting_prompt"  # A4-6：import success → 待反推（不是在跑）
        assert any("空链接" in s for s in b1["skipped"])
        assert any("无法识别" in s for s in b1["skipped"])
        assert first.json()["batch"]["source_kind"] == "link"

        # 同一条链接换一种埋点写法：归一化后必须命中（宁可漏合，不可误合）
        second = await _import(client, hm, [DOUYIN_1_TRACKED, DOUYIN_2])
        assert second.status_code == 201, second.text
        b2 = second.json()
        assert len(b2["items"]) == 1, "只有新链接入库"
        assert len(b2["duplicates"]) == 1
        dup = b2["duplicates"][0]
        assert dup["existing"]["code"] == b1["items"][0]["code"]
        assert dup["existing"]["created_at"]
        # 「是谁导入的」是这一提示能不能被用起来的关键：只有 code + 日期，一线还得自己去查库
        assert dup["existing"]["imported_by"] == "素材专员"
        assert re.search(r"\d{2}月\d{2}日 素材专员 导入（AS-\w+）", dup["hint"]), dup["hint"]
        assert dup["source_url_norm"], "回传归一化键，force_urls 逐条放行时前端不必再归一"

        # 逐条放行：只投点名那一条，其余重复照旧拦（别拉整批陪跑）
        per_one = await _import(client, hm, [DOUYIN_1_TRACKED, DOUYIN_2], force_urls=[DOUYIN_1])
        assert per_one.status_code == 201, per_one.text
        assert len(per_one.json()["items"]) == 1, "只有被点名的 DOUYIN_1 重复入库"
        dups = per_one.json()["duplicates"]
        assert len(dups) == 1 and dups[0]["source_url"].startswith(DOUYIN_2[:30]), dups
        assert await _count(AssetItem) == 3

        # 强制入库：业务上不同人要各用一次，重复不是错误
        third = await _import(client, hm, [DOUYIN_1_TRACKED], force_duplicates=True)
        assert third.status_code == 201, third.text
        assert len(third.json()["items"]) == 1
        assert third.json()["duplicates"] == []

        assert await _count(AssetItem) == 4
        await client.aclose()

    _run(_scenario())


def test_import_same_video_two_share_forms_creates_only_one_row():
    """R-2（11-04 第二轮审核）：**同一次提交里**同一部片子的两种写法只能建一行。

    `normalize_source_list` 只按**原始字符串**去同批重复，而 `https://v.douyin.com/iAbcDeF/`
    与它带埋点参数的长版归一化后是同一条（`douyin:iabcdef`）。原来两条都会建素材行，
    反推**按行计费**＝同一部片子付两遍钱（实测 0.0972 元/条）；库里 `source_url_norm`
    没有唯一约束（硬唯一会静默丢素材，审核席位明确反对），所以拦不住，只能在建之前拦。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]

        both = await _import(client, hm, [DOUYIN_1, DOUYIN_1_TRACKED, DOUYIN_2])
        assert both.status_code == 201, both.text
        body = both.json()
        assert len(body["items"]) == 2, (
            f"同一部片子建了两行：{[i['source_url'] for i in body['items']]}"
        )
        assert any("另一种写法" in s for s in body["skipped"]), body["skipped"]
        urls = [i["source_url"] for i in body["items"]]
        assert len(set(urls)) == len(urls), "同批内不许出现两条同素材"
        assert await _count(AssetItem) == 2

        # 换一种写法的第三条：跨批次仍按归一化键命中（与埋点参数、host 写法无关）
        again = await _import(client, hm, ["https://www.douyin.com/video/7412345678901234567"])
        assert again.status_code == 201, again.text
        assert len(again.json()["items"]) == 0
        assert len(again.json()["duplicates"]) == 1, again.json()["duplicates"]

        await client.aclose()

    _run(_scenario())


def test_import_auto_splits_over_limit_and_rejects_bad_tier():
    """超单批上限 → **服务端自动拆批**并明示拆成几批（A4-1）；非法计时档位仍要 400。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        limit = int(settings.ASSET_IMPORT_BATCH_MAX)
        over = [f"https://www.douyin.com/video/{7400000000000000000 + i}" for i in range(limit + 1)]
        resp = await _import(client, hm, over)
        assert resp.status_code == 201, "旧行为在这里回 400「请拆批提交」，把人工劳动推给一线"
        body = resp.json()
        assert body["split_into"]["shards"] == 2
        assert body["split_into"]["per_shard"] == [limit, 1]
        assert len(body["batches"]) == 2 and len(body["items"]) == limit + 1
        assert body["batch"]["code"] == body["batches"][0]["code"], "batch 字段保持兼容＝第一批"
        assert "第1/2批" in body["batches"][0]["name"] and "第2/2批" in body["batches"][1]["name"]
        assert body["batches"][1]["item_count"] == 1
        # 成本与闸门逐批各算一份：合在一起算等于把单批预算墙变成摆设
        assert len(body["budgets"]) == 2
        assert body["budget"]["cost_estimate"] == round(
            (body["budgets"][0]["cost_estimate"] + body["budgets"][1]["cost_estimate"]), 4)
        assert body["budget"]["batches"] == 2
        assert f"拆成 2 批" in body["message"]

        # 没超量：一条都不多建，split_into 为 null（前端据此决定要不要提示）
        single = await _import(client, hm, [DOUYIN_1])
        assert single.json()["split_into"] is None and len(single.json()["batches"]) == 1

        resp2 = await _import(client, hm, [DOUYIN_1], prompt_max_duration=120)
        assert resp2.status_code == 400
        assert "计时上限" in resp2.json()["detail"]

        resp3 = await client.get("/api/assets/cost/estimate?count=10&max_duration=600", headers=hm)
        assert resp3.status_code == 200
        body3 = resp3.json()
        assert body3["unit_cost"] == round(0.00054 * 600, 4)
        assert body3["tiers"]["60"] < body3["tiers"]["600"]
        # A1-1：余量查不到时确认单必须说实话（balance=null + note），
        # 否则前端只会显示「闸门 ok」，用户以为熔断在生效。
        assert body3["balance"] is None and body3["balance_note"]
        await client.aclose()

    _run(_scenario())


def test_import_records_real_budget_warning_on_batch():
    """A1-4：导入侧不再是硬写的绿灯——超单批预算要在批次行和响应里如实标出来。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        with patch.object(settings, "ASSET_BATCH_BUDGET_CAP", 0.05):
            resp = await _import(client, hm, [DOUYIN_1, DOUYIN_2], prompt_max_duration=600)
            assert resp.status_code == 201, resp.text
            body = resp.json()
            # 2 条 × 600s 档 = 0.648 元 > 0.05 → need_approval（导入不扣费，只是预警）
            assert body["budget"]["gate"] == "need_approval"
            assert body["budget"]["cost_estimate"] == pytest.approx(0.648, abs=1e-4)
            assert body["batch"]["budget_gate"] == "need_approval"
            assert body["batch"]["cost_estimate"] == pytest.approx(0.648, abs=1e-4)
            assert "超单批上限" in body["message"]

        batches = await client.get("/api/assets/batches", headers=hm)
        row = batches.json()["items"][0]
        assert row["budget_gate"] == "need_approval" and row["budget_note"]

        # 不超上限的普通批次仍是 ok，别把一线搞成满屏红灯
        ok = await _import(client, hm, ["https://www.douyin.com/video/7499888777666555443"], prompt_max_duration=60)
        assert ok.json()["batch"]["budget_gate"] == "ok", ok.text
        await client.aclose()

    _run(_scenario())


def test_balance_channel_only_trusts_zhiling_and_needs_a_yuan_unit():
    """A1-1：余额闸门只认 zhiling 通道，且单位必须能折算到元——否则按「未知」处理。

    这里直接打查询函数（不碰 DB）：三条口径都是"闸门是不是假保险"的根，
    拿别人的钱包设限、或把「剩 30000 次」当成「剩 3 万元」，都比没闸更危险。
    """
    from app.api.assets import _query_zhiling_balance_detail

    async def _detail(balances):
        with patch("app.api.assets.fetch_provider_balances", AsyncMock(return_value=balances)):
            return await _query_zhiling_balance_detail()

    # 元：原样
    assert _run(_detail({"zhiling": {"balance": 12.5, "unit": "元"}}))["balance"] == 12.5
    # 点：0.00054 元/秒 == 0.54 点/秒 → 1 点 = 0.001 元
    assert _run(_detail({"zhiling": {"balance": 30000, "unit": "点"}}))["balance"] == 30.0
    # 次：换算不到元 → 拒用（note 说明），绝不硬比
    unknown = _run(_detail({"zhiling": {"balance": 30000, "unit": "次"}}))
    assert unknown["balance"] is None and "换算不到元" in unknown["note"]
    # 只有别家钱包有钱 → 不兜底
    other = _run(_detail({"wxshares": {"balance": 999, "unit": "元"}}))
    assert other["balance"] is None and "余额闸门未生效" in other["note"]


def test_balance_note_says_which_link_is_broken():
    """余量取不到数时，note 要说清**卡在哪一环**（11-03 接 163 现网后加的口径）。

    起因：现网实测智令没有对外余量接口，可原来的提示一律写「未配置智令余量通道，
    需要配 QUOTA_PATH/FIELD/UNIT」——照着再配一遍还是无数，运维只会以为是自己漏配。
    三种原因分开报：适配器没建起来 / 没配 QUOTA_PATH / 配了但接口报错。
    """
    from app.api.assets import _query_zhiling_balance_detail

    def _note(env, balances):
        with patch.dict(os.environ, env, clear=False), \
             patch("app.api.assets.fetch_provider_balances", AsyncMock(return_value=balances)):
            return _run(_query_zhiling_balance_detail())["note"]

    # ① 链里没 zhiling → 适配器压根没建，配了 QUOTA_* 也没用
    assert "没建起来" in _note(
        {"WECHAT_DL_PROVIDERS": "yuanbao,preview", "WECHAT_DL_ZHILING_BASE": "https://api.17zhiling.com",
         "WECHAT_DL_ZHILING_QUOTA_PATH": "/api/user/balance"}, {})
    # ② 通道在但没配查询路径 → 不查询
    assert "未配 WECHAT_DL_ZHILING_QUOTA_PATH" in _note(
        {"WECHAT_DL_PROVIDERS": "zhiling", "WECHAT_DL_ZHILING_BASE": "https://api.17zhiling.com",
         "WECHAT_DL_ZHILING_QUOTA_PATH": ""}, {})
    # ③ 全配了、接口 404（智令现状）→ 说清不是自己的配置问题，也别说闸门开了
    assert "http 404" in _note(
        {"WECHAT_DL_PROVIDERS": "zhiling", "WECHAT_DL_ZHILING_BASE": "https://api.17zhiling.com",
         "WECHAT_DL_ZHILING_QUOTA_PATH": "/api/user/balance"},
        {"zhiling": {"error": "http 404"}})
    # 查询炸了 → 也是未知，但不 500
    with patch("app.api.assets.fetch_provider_balances", AsyncMock(side_effect=RuntimeError("网络抖动"))):
        boom = _run(_query_zhiling_balance_detail())
    assert boom["balance"] is None and "网络抖动" in boom["note"]


# ─────────────────────────  2. 文件批量上传  ─────────────────────────


def test_upload_batch_is_fail_soft_per_file():
    """多文件上传：非法扩展名/超大单独失败，其余照常入库；全失败不留孤儿批次。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        files = [
            ("files", ("第一集.mp4", VIDEO_BYTES, "video/mp4")),
            ("files", ("说明.txt", b"not a video", "text/plain")),
            ("files", ("第二集.mov", VIDEO_BYTES, "video/quicktime")),
        ]
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)) as up:
            resp = await client.post("/api/assets/upload/batch", files=files, headers=hm)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["failed"][0]["file_name"] == "说明.txt"
        assert "不支持的文件类型" in body["failed"][0]["error"]
        assert up.await_count == 2
        # content type 跟着真实扩展名走：写死 video/mp4 会让 .mov 在桶里挂错标签
        sent_types = sorted(call.kwargs.get("content_type") for call in up.await_args_list)
        assert sent_types == ["video/mp4", "video/quicktime"], sent_types
        # A1-4：文件形态反推多一笔 doc/125 中转费，批次预估要把它算进去
        budget = body["budget"]
        assert budget["gate"] == "ok"
        assert budget["unit_cost"] == pytest.approx(0.00054 * 180 + 0.001, abs=1e-6)
        assert budget["cost_estimate"] == pytest.approx((0.00054 * 180 + 0.001) * 2, abs=1e-4)
        item = body["items"][0]
        assert item["source_kind"] == "file"
        assert item["file_key"].startswith("asset/")
        assert item["bucket"] == settings.MINIO_BUCKET_RAW
        assert item["file_size"] == len(VIDEO_BYTES)

        # 全部非法：批次回滚，前端只看 failed 里的原因
        bad = [("files", ("a.txt", b"x", "text/plain")), ("files", ("b.exe", b"x", "application/x-msdownload"))]
        before = await _count(AssetItem)
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            resp2 = await client.post("/api/assets/upload/batch", files=bad, headers=hm)
        assert resp2.status_code == 201, resp2.text
        assert resp2.json()["batch"] is None and resp2.json()["items"] == []
        # 全失败：批次行也不留（batch_id 回 null），否则对账页出现一个 0 条的孤儿批次
        assert resp2.json()["batch_id"] is None
        assert len(resp2.json()["failed"]) == 2
        assert await _count(AssetItem) == before
        await client.aclose()

    _run(_scenario())


def test_upload_writes_the_actual_bytes_into_the_object():
    """落盘循环必须真的把字节写下去 —— 11-04 拼接真链路实测抓到的 P0 缺陷。

    当时那一版只有 `size += len(chunk)`、漏了 `out.write(chunk)`：接口回 201、DB 的
    `file_size` 记的是真实大小，而桶里躺着一个 **0 字节对象**（ffprobe 报
    `moov atom not found`，拼接当场判「第1段探不出视频流」才发现）。
    本文件其它用例把 `upload_file_from_path` 一律 mock 成 True，这类"计数与写入脱钩"
    在 mock 世界里是完美通过的 —— 所以这条**让对象存储把收到的字节原样抄回来核对**。

    顺带钉第二道保险：落盘不完整时必须当场失败，而不是把空壳传进桶
    （反推会拿它走 doc/125 中转上传，**白扣一次钱且必然失败**）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        seen = []

        async def _recording_put(bucket, key, path, content_type="application/octet-stream"):
            with open(path, "rb") as fh:
                seen.append(fh.read())
            return True

        files = [
            ("files", ("甲.mp4", VIDEO_BYTES, "video/mp4")),
            ("files", ("乙.mp4", VIDEO_BYTES, "video/mp4")),
        ]
        with patch("app.api.assets.upload_file_from_path", _recording_put):
            resp = await client.post("/api/assets/upload/batch", files=files, headers=hm)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["items"]) == 2
        assert len(seen) == 2, "两个文件都该真的送到对象存储"
        for got in seen:
            assert got == VIDEO_BYTES, f"桶里拿到的字节与原文件不符（{len(got)} 字节）"
        for item in body["items"]:
            assert item["file_size"] == len(VIDEO_BYTES)

        # 第二道保险：磁盘上比读到的少 → 判失败、不入库、不传空壳
        from app.api.assets import _ingest_one_video_file
        import io
        from fastapi import UploadFile

        with patch("app.api.assets.upload_file_from_path", _recording_put), \
                patch("app.api.assets.os.path.getsize", return_value=0):
            res = await _ingest_one_video_file(
                UploadFile(filename="丙.mp4", file=io.BytesIO(VIDEO_BYTES)),
                tmp_dir=str(_TMPDIR),
                batch_code="AB-TEST",
                max_bytes=10 * 1024 * 1024,
                sem=asyncio.Semaphore(1),
            )
        assert res["ok"] is False, "落盘不完整不能算成功"
        assert "落盘不完整" in res["error"], res

        # 补一条正向：同一入参在真 getsize 下必须成功，且送进对象存储的字节一个不少
        # （证明上面的失败是"少字节"造成的，不是这条路径本身不通）
        before_put = len(seen)
        with patch("app.api.assets.upload_file_from_path", _recording_put):
            ok_res = await _ingest_one_video_file(
                UploadFile(filename="丙.mp4", file=io.BytesIO(VIDEO_BYTES)),
                tmp_dir=str(_TMPDIR),
                batch_code="AB-TEST",
                max_bytes=10 * 1024 * 1024,
                sem=asyncio.Semaphore(1),
            )
        assert ok_res["ok"] is True, ok_res
        assert len(seen) == before_put + 1
        assert seen[-1] == VIDEO_BYTES
        await client.aclose()

    _run(_scenario())


def test_upload_appends_one_batch_retries_and_runs_concurrently():
    """A4-5 + A4-4：`batch_id` 追加、失败文件补投回同一批、并发 3、超限给引导语、时长回写。

    这条测的是「一线 200 个文件怎么传」这一整形态：前端一次建批次、逐段投同一 batch_id，
    批次行只有一条、item_count 与预算按追加后的全量重算——不是 200 个批次。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.models.asset import AssetBatch

        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        # ① 首投 1 个：建批次 + ffprobe 回写时长（A4-4 的「列表时长列必空」在这一处修掉）
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 33.7):
            first = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("第一集.mp4", VIDEO_BYTES, "video/mp4"))],
                data={"name": "周一收集"}, headers=hm)
        assert first.status_code == 201, first.text
        b1 = first.json()
        bid = b1["batch_id"]
        assert bid == b1["batch"]["id"]
        assert b1["batch"]["item_count"] == 1
        assert b1["items"][0]["duration"] == 33.7

        # ② 探不到时长（ffprobe 回 0.0）→ null，绝不写 0（写 0 前端显示 0:00，像空素材）
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 0.0):
            second = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("第二集.mp4", VIDEO_BYTES, "video/mp4"))],
                data={"batch_id": bid}, headers=hm)
        assert second.status_code == 201, second.text
        b2 = second.json()
        assert b2["batch_id"] == bid, "追加进同一批次，不新建批次行"
        assert b2["batch"]["name"] == "周一收集"
        assert b2["batch"]["item_count"] == 2
        assert b2["items"][0]["duration"] is None

        # ③ 并发：信号量 3 → 同时在途 3 个（串行会是 1，没上限会是 4）
        inflight = {"cur": 0, "max": 0}

        async def _slow_put(*_a, **_k):
            inflight["cur"] += 1
            inflight["max"] = max(inflight["max"], inflight["cur"])
            await asyncio.sleep(0.02)
            inflight["cur"] -= 1
            return True

        four = [("files", (f"批次外{i}.mp4", VIDEO_BYTES, "video/mp4")) for i in range(4)]
        with patch("app.api.assets.upload_file_from_path", _slow_put), \
             patch("app.api.assets._ffprobe_duration", lambda p: 8.0):
            third = await client.post(
                "/api/assets/upload/batch", files=four, data={"batch_id": bid}, headers=hm)
        assert third.status_code == 201, third.text
        assert len(third.json()["items"]) == 4
        assert inflight["max"] == 3, f"并发应封顶 3，实测 {inflight['max']}"
        assert third.json()["batch"]["item_count"] == 6

        # ④ 对象存储写失败：文件不入库，但**既有批次不回滚**（里面已有 6 条）
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=False)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 9.0):
            broken = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("掉网.mp4", VIDEO_BYTES, "video/mp4"))],
                data={"batch_id": bid}, headers=hm)
        assert broken.status_code == 201, broken.text
        bb = broken.json()
        assert bb["items"] == [] and bb["batch"] is not None
        assert bb["failed"][0]["file_name"] == "掉网.mp4"
        assert "对象存储写入失败" in bb["failed"][0]["error"] and "retry" in bb["failed"][0]["error"]
        assert bb["failed_files"] == ["掉网.mp4"]
        assert await _count(AssetItem) == 6

        # ⑤ 补投：同一个批次、item_count 追到 7，预算按批次全量重算
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 9.5):
            again = await client.post(
                "/api/assets/upload/retry",
                files=[("files", ("掉网.mp4", VIDEO_BYTES, "video/mp4"))],
                data={"batch_id": bid}, headers=hm)
        assert again.status_code == 200, again.text
        b5 = again.json()
        assert b5["batch_id"] == bid and b5["batch"]["item_count"] == 7
        assert b5["items"][0]["duration"] == 9.5
        assert b5["budget"]["cost_estimate"] == pytest.approx((0.00054 * 180 + 0.001) * 7, abs=1e-3)
        assert (await _count(AssetBatch)) == 1, "七次投递只有一条批次行"

        # ⑥ 补投全失败：批次照旧回显，只给失败清单
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            nope = await client.post(
                "/api/assets/upload/retry",
                files=[("files", ("还是坏.txt", b"x", "text/plain"))],
                data={"batch_id": bid}, headers=hm)
        assert nope.status_code == 200, nope.text
        assert nope.json()["items"] == [] and nope.json()["batch"]["item_count"] == 7

        # ⑦ batch_id 三种错法各有明确回话
        missing = await client.post(
            "/api/assets/upload/batch",
            files=[("files", ("x.mp4", VIDEO_BYTES, "video/mp4"))],
            data={"batch_id": str(uuid.uuid4())}, headers=hm)
        assert missing.status_code == 404 and "batch_id 传错" in missing.json()["detail"]

        link_batch = await _import(client, hm, [DOUYIN_1])
        assert link_batch.status_code == 201, link_batch.text
        wrong_kind = await client.post(
            "/api/assets/upload/batch",
            files=[("files", ("x.mp4", VIDEO_BYTES, "video/mp4"))],
            data={"batch_id": link_batch.json()["batch"]["id"]}, headers=hm)
        assert wrong_kind.status_code == 400 and "链接批次" in wrong_kind.json()["detail"]

        other = await client.post(
            "/api/assets/upload/retry",
            files=[("files", ("x.mp4", VIDEO_BYTES, "video/mp4"))],
            data={"batch_id": bid}, headers=ho)
        assert other.status_code == 403, other.text

        # ⑧ 超限：给「本接口不分片」的引导语，不是 nginx 那页 413 HTML
        with patch("app.api.assets.upload_max_bytes", lambda: 100), \
             patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            over = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("大片.mp4", VIDEO_BYTES, "video/mp4"))],
                data={"batch_id": bid}, headers=hm)
        assert over.status_code == 201, over.text
        assert "本接口不分片" in over.json()["failed"][0]["error"]

        # ⑨ 单请求文件数超 ASSET_IMPORT_BATCH_MAX → 400 并教怎么分
        limit = int(settings.ASSET_IMPORT_BATCH_MAX)
        many = [("files", (f"m{i}.mp4", VIDEO_BYTES, "video/mp4")) for i in range(limit + 1)]
        burst = await client.post("/api/assets/upload/batch", files=many, headers=hm)
        assert burst.status_code == 400 and "分几次投" in burst.json()["detail"]
        await client.aclose()

    _run(_scenario())


def test_source_download_and_link_duration_backfill():
    """A4-4：文件素材有 presigned 原片下载口并留审计；链接素材只回显外链，直链才补时长。"""
    _run(_bootstrap())

    async def _scenario():
        from wechat_download.models import PT_PROCESSING, WechatDlPromptTask
        from wechat_download.prompt_client import PromptStatus

        client, h = await _client_and_headers()
        hm = h["material"]

        # ── 文件素材：stored 形态给外链 ──
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 45.5):
            up = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("原片.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
        assert up.status_code == 201, up.text
        aid = up.json()["items"][0]["id"]

        presign = AsyncMock(return_value="https://minio.example/raw?X-Signature=1")
        with patch("app.api.assets.get_presigned_url", presign):
            got = await client.get(f"/api/assets/{aid}/source-download", headers=hm)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["mode"] == "stored" and body["url"].endswith("X-Signature=1")
        assert body["file_name"] == "原片.mp4" and body["duration"] == 45.5
        assert body["size"] == len(VIDEO_BYTES) and body["source_url"] is None
        assert presign.await_count == 1
        assert body["note"] is None
        logs = await _rows(AuditLog, AuditLog.action == "asset.source.download")
        assert len(logs) == 1 and logs[0].after["mode"] == "stored"

        # 没落库的文件素材（file_key 空）→ 404，不给半截链接
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(aid))
            key = a.file_key
            a.file_key = None
            await s.commit()
        empty = await client.get(f"/api/assets/{aid}/source-download", headers=hm)
        assert empty.status_code == 404 and "没有可下载的原文件" in empty.json()["detail"]
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(aid))
            a.file_key = key
            await s.commit()

        # ── 链接素材（分享页）：external 形态，url 为 null 并说清为什么 ──
        lid, _ = await _make_ready_asset(client, hm, url=DOUYIN_1)
        with patch("app.api.assets.get_presigned_url", AsyncMock(return_value="不该被调用")) as ps:
            ext = await client.get(f"/api/assets/{lid}/source-download", headers=hm)
        assert ext.status_code == 200, ext.text
        assert ext.json()["mode"] == "external" and ext.json()["url"] is None
        assert ext.json()["source_url"] == DOUYIN_1 and ps.await_count == 0
        assert "/assets/resolve" in ext.json()["note"], "note 要给出拿时长的显式出口，不是死路一条"

        # ── 反推成功时补时长：只有直链能探，分享页绝不瞎探也不写 0 ──
        async def _running_again(task_id, url):
            async with dbmod.async_session_factory() as s:
                s.add(WechatDlPromptTask(
                    id=task_id, source_type="url", source_url=url,
                    provider_task_id=f"prov-{task_id.hex[:6]}", status=PT_PROCESSING,
                    max_duration=180))
                a = await s.get(AssetItem, uuid.UUID(lid))
                a.prompt_task_id, a.stage_prompt, a.status = task_id, "running", "analyzing"
                a.source_url, a.duration = url, None
                await s.commit()

        def _fake_client():
            return SimpleNamespace(
                query=AsyncMock(return_value=PromptStatus(
                    status="success", content=SCRIPT, schedule="SUCCESS")),
                close=AsyncMock())

        direct = "https://cdn.example.com/raw/ep01.mp4"
        t1 = uuid.uuid4()
        await _running_again(t1, direct)
        # ffprobe 是**同步**函数（代码里走 run_in_executor 丢线程），替身必须也是同步的：
        # 用 AsyncMock 会让协程对象糊进 float()，探测「失败」→ 时长写空，测的就不是这条路径了
        probed: list = []

        def _probe(url):
            probed.append(url)
            return 58.234

        # SSRF 守卫（11-05 安全审计）会真解析域名；测试无网，桩一个公网解析结果
        def _public_addrinfo(host, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

        with patch("wechat_download.prompt_service.PromptClient", _fake_client), \
             patch("app.api.assets._ffprobe_duration", _probe), \
             patch("app.services.net_guard.socket.getaddrinfo", _public_addrinfo):
            r1 = await client.post(f"/api/assets/{lid}/prompt-refresh", headers=hm)
        assert r1.status_code == 200, r1.text
        assert r1.json()["asset"]["duration"] == 58.23
        assert probed == [direct]
        assert "duration_note" not in r1.json()

        t2 = uuid.uuid4()
        await _running_again(t2, DOUYIN_2)
        idle: list = []

        def _no_probe(url):
            idle.append(url)
            return 0.0

        with patch("wechat_download.prompt_service.PromptClient", _fake_client), \
             patch("app.api.assets._ffprobe_duration", _no_probe):
            r2 = await client.post(f"/api/assets/{lid}/prompt-refresh", headers=hm)
        assert r2.status_code == 200, r2.text
        assert r2.json()["asset"]["duration"] is None
        assert idle == [], "分享页链接不该拿去 ffprobe"
        assert "doc/107" in r2.json()["duration_note"]
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  3c. 回源解析（D-5 拍板：解析费计入批次成本）  ─────────────────────────


def test_resolve_charges_only_paid_channels_and_never_double_pays():
    """`POST /assets/resolve` 是**显式付费动作**，钉四件事：
    ≥2 条必须先确认、按渠道记账（免费兜底记 0）、失败不记账、
    付过一次费但没拿到时长的**不再被整批排队捞回来重扣**。
    """
    from wechat_download.provider_registry import ProviderParseError

    _run(_bootstrap())

    SHARE_1 = "https://www.douyin.com/video/7499000000000000001/"   # 付费渠道 + 给时长
    SHARE_2 = "https://www.douyin.com/video/7499000000000000002/"   # 免费渠道 + 不给时长（回退 ffprobe）
    SHARE_3 = "https://www.douyin.com/video/7499000000000000003/"   # 解析失败
    SHARE_4 = "https://www.douyin.com/video/7499000000000000004/"   # 付费渠道 + 不给时长（花过钱）
    DIRECT = "https://cdn.example.com/raw/clip.mp4"                 # 直链：本地探测，不发解析

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        imp = await _import(client, hm, [SHARE_1, SHARE_2, SHARE_3, SHARE_4, DIRECT])
        assert imp.status_code == 201, imp.text
        items = imp.json()["items"]
        batch_id = imp.json()["batch"]["id"]
        ids = [i["id"] for i in items]
        by_url = {i["source_url"]: i["id"] for i in items}

        calls: list = []

        async def _parse(url):
            calls.append(url)
            if url.endswith("003/"):
                raise ProviderParseError("智令返回 code=400：链接不可解析")
            if url.endswith("002/"):
                return SimpleNamespace(channel="yuanbao", play_url="https://c.d/a.mp4",
                                       duration=None, title=None)
            if url.endswith("004/"):
                return SimpleNamespace(channel="zhiling", play_url=None, duration=None, title=None)
            return SimpleNamespace(channel="zhiling", play_url="https://c.d/b.mp4",
                                   duration=42.5, title="示例标题")

        async def _probe(url):
            return 18.34

        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse)), \
             patch("app.api.assets._probe_url_duration", AsyncMock(side_effect=_probe)), \
             patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)):
            unconfirmed = await client.post(
                "/api/assets/resolve", json={"asset_ids": ids[:2]}, headers=hm)
            assert unconfirmed.status_code == 409, unconfirmed.text
            det = unconfirmed.json()["detail"]
            assert det["code"] == "ASSET_COST_CONFIRM_REQUIRED"
            assert det["estimate"]["total_cost"] == pytest.approx(0.02, abs=1e-9), "两条＝0.01×2"
            assert calls == [], "确认单没点，一次外呼都不该发"

            made = await client.post(
                "/api/assets/resolve", json={"asset_ids": ids, "confirmed": True}, headers=hm)
        assert made.status_code == 200, made.text
        body = made.json()
        by_id = {r["asset_id"]: r for r in body["results"]}

        paid = by_id[by_url[SHARE_1]]
        assert paid["ok"] is True and paid["channel"] == "zhiling"
        assert paid["duration"] == 42.5 and paid["charged"] == pytest.approx(0.01, abs=1e-9)
        free = by_id[by_url[SHARE_2]]
        assert free["channel"] == "yuanbao" and free["charged"] == 0.0, "免费渠道记 0＝不造假账"
        assert free["duration"] == 18.34, "接口不给时长就用 ffprobe 补"
        bad = by_id[by_url[SHARE_3]]
        assert bad["ok"] is False and bad["charged"] == 0.0 and "失败不记账" in bad["error"]
        blind = by_id[by_url[SHARE_4]]
        assert blind["charged"] == pytest.approx(0.01, abs=1e-9) and blind["duration"] is None, \
            "钱确实花了（付费渠道不会因我们读不到时长而退钱），时长照实留空"
        direct = by_id[by_url[DIRECT]]
        assert direct["channel"] == "ffprobe" and direct["charged"] == 0.0, "直链不发解析接口"
        assert body["charged"] == pytest.approx(0.02, abs=1e-9) and body["resolved"] == 3

        rows = {str(r.id): r for r in await _rows(AssetItem)}
        assert rows[by_url[SHARE_1]].cost_parse == pytest.approx(0.01, abs=1e-9)
        assert rows[by_url[SHARE_2]].cost_parse == 0.0
        assert rows[by_url[SHARE_3]].cost_parse == 0.0
        assert rows[by_url[DIRECT]].cost_parse == 0.0
        batch = (await _rows(AssetBatch, AssetBatch.id == uuid.UUID(batch_id)))[0]
        assert batch.cost_actual == pytest.approx(0.02, abs=1e-9), "解析费进批次实扣（D-5 拍板）"

        # 再点名同一条：缓存直链还在 TTL 内 → **免费回放**（channel=cache、0 元、
        # 不发解析接口）。11-06 播放直链修复前这里回空 results——用户付钱取的
        # 直链关抽屉就没了，再点还撞上「已有时长不重复付费」，死锁在播不了。
        calls.clear()
        again = await client.post(
            "/api/assets/resolve", json={"asset_ids": [by_url[SHARE_1]]}, headers=hm)
        assert again.status_code == 200, again.text
        cached = again.json()["results"][0]
        assert cached["channel"] == "cache" and cached["charged"] == 0.0
        assert cached["play_url"] == "https://c.d/b.mp4", "回放的必须是落库的那条直链"
        assert "免费" in cached["note"]
        assert calls == [], "缓存回放不该再调解析接口"

        # 整批排队：只剩「没花过钱且没时长」的那条（失败的 SHARE_3）；
        # SHARE_4 付过 0.01 但没时长 —— 它必须**离开**队列，否则每次排队都重扣一遍
        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse)), \
             patch("app.api.assets._probe_url_duration", AsyncMock(side_effect=_probe)), \
             patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)):
            queued = await client.post(
                "/api/assets/resolve", json={"batch_id": batch_id, "confirmed": True}, headers=hm)
        assert queued.status_code == 200, queued.text
        assert queued.json()["queue"]["picked"] == 1
        assert [r["code"] for r in queued.json()["results"]] == \
               [rows[by_url[SHARE_3]].code], "只有失败那条还在队列里（它没花过钱）"
        assert calls == [SHARE_3]

        # 余额不足：blocked 对谁都是 409，admin 也没有 force 后门（0.01 也要人签字）
        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse)), \
             patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(0.0)):
            blocked = await client.post(
                "/api/assets/resolve",
                json={"asset_ids": [by_url[SHARE_3]]}, headers=ha)
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "ASSET_BALANCE_BLOCKED"
        assert calls == [SHARE_3], "挡下了就不该再发外呼"

        # 单请求混传 / 空传：沿用队列口同一套入参纪律
        mixed = await client.post(
            "/api/assets/resolve", json={"asset_ids": ids[:1], "batch_id": batch_id}, headers=hm)
        assert mixed.status_code == 400 and "二选一" in mixed.json()["detail"]
        empty = await client.post("/api/assets/resolve", json={}, headers=hm)
        assert empty.status_code == 400 and "batch_id" in empty.json()["detail"]

        logs = await _rows(AuditLog, AuditLog.action == "asset.resolve")
        assert logs, "花钱的动作必须留痕"
        assert logs[-1].after["charged"] == pytest.approx(0.0, abs=1e-9)
        assert logs[-1].after["requested"] == 1, "最后一次只重跑了失败那条"
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  3. 反推闸门与跳过重复  ─────────────────────────


def test_analyze_blocked_requires_admin_force():
    """余额 < 预估×1.2 → blocked：谁都挡下，只有 admin 带 force=true 能强推。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        asset_id, _ = await _make_ready_asset(client, h["material"])
        # 清掉伪造的 success，回到「未反推」，走真实提交分支
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id = None
            a.stage_prompt = "pending"
            a.status = "waiting_prompt"
            await s.commit()

        payload = {"asset_ids": [asset_id], "max_duration": 180}
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(0.01)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())) as cpt:
            # 11-03 取消隔离：operator 也能对素材专员的素材发起反推（旧口径这里 404）；
            # 11-27 取消跨人确认：直接走统一的余额闸门
            cross = await client.post(
                "/api/assets/analyze/batch", json=payload, headers=h["operator"])
            assert cross.status_code == 409, cross.text
            assert cross.json()["detail"]["code"] == "ASSET_BALANCE_BLOCKED"
            cpt.assert_not_awaited()

            importer = await client.post("/api/assets/analyze/batch", json=payload, headers=h["material"])
            assert importer.status_code == 409, importer.text
            detail = importer.json()["detail"]
            assert detail["code"] == "ASSET_BALANCE_BLOCKED"
            assert detail["estimate"]["total_cost"] == pytest.approx(0.0972, abs=1e-4)
            cpt.assert_not_awaited()

            admin_no_force = await client.post(
                "/api/assets/analyze/batch",
                json={**payload}, headers=h["admin"])
            assert admin_no_force.status_code == 409, "admin 不表决心也不放行"
            assert cpt.await_count == 0

            admin_force = await client.post(
                "/api/assets/analyze/batch",
                json={**payload, "force": True}, headers=h["admin"])
            assert admin_force.status_code == 200, admin_force.text
            assert admin_force.json()["gate"]["level"] == "blocked"
            assert len(admin_force.json()["results"]) == 1
            assert cpt.await_count == 1

        rows = await _rows(AssetItem)
        assert rows[0].stage_prompt == "running"
        assert rows[0].prompt_max_duration == 180
        assert rows[0].cost_prompt == pytest.approx(0.0972, abs=1e-4)
        await client.aclose()

    _run(_scenario())


def test_analyze_need_approval_only_admin_with_confirmation():
    """预估超单批预算 → need_approval：必须 admin 且 confirmed=true（前端确认弹窗点过）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        asset_id, _ = await _make_ready_asset(client, h["material"])
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id, a.stage_prompt, a.status = None, "pending", "waiting_prompt"
            await s.commit()

        payload = {"asset_ids": [asset_id]}
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch.object(settings, "ASSET_BATCH_BUDGET_CAP", 0.05), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())) as cpt:
            not_admin_confirmed = await client.post(
                "/api/assets/analyze/batch", json={**payload, "confirmed": True}, headers=h["material"])
            assert not_admin_confirmed.status_code == 409
            assert not_admin_confirmed.json()["detail"]["code"] == "ASSET_BUDGET_NEED_APPROVAL", \
                "素材专员点了确认也不算放批：这条权力只在 admin"

            admin_unconfirmed = await client.post(
                "/api/assets/analyze/batch",
                json={**payload}, headers=h["admin"])
            assert admin_unconfirmed.status_code == 409, "admin 也要先确认成本"

            ok = await client.post(
                "/api/assets/analyze/batch",
                json={**payload, "confirmed": True},
                headers=h["admin"])
            assert ok.status_code == 200, ok.text
            assert cpt.await_count == 1

        # 默认档位不是 600：这是采集席位硬性反对过的成本杠杆
        assert (await _rows(AssetItem))[0].prompt_max_duration == settings.ASSET_PROMPT_MAX_DURATION
        await client.aclose()

    _run(_scenario())


def test_analyze_never_resubmits_success_and_skips_failed_without_retry():
    """已 success/running 绝不重投（重复＝重复扣费）；failed 只有 retry_failed=true 才重试。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)   # stage_prompt=success
        blocked = await client.post(
            "/api/assets/analyze/batch", json={"asset_ids": [asset_id]}, headers=hm)
        assert blocked.status_code == 400, blocked.text
        assert "没有能新提交反推的" in blocked.json()["detail"]

        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id, a.stage_prompt, a.status = None, "failed", "failed"
            await s.commit()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())) as cpt:
            skipped = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": [asset_id]}, headers=hm)
            assert skipped.status_code == 400, "失败项默认不重跑"
            cpt.assert_not_awaited()

            # 混选：一条新的 + 一条失败的（不带 retry 时只提交新的）
            new_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_1)
            async with dbmod.async_session_factory() as s2:
                n = await s2.get(AssetItem, uuid.UUID(new_id))
                n.prompt_task_id, n.stage_prompt, n.status = None, "pending", "waiting_prompt"
                await s2.commit()
            mixed = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": [asset_id, new_id]}, headers=hm)
            assert mixed.status_code == 200, mixed.text
            body = mixed.json()
            assert len(body["results"]) == 1 and len(body["skipped"]) == 1
            assert "retry_failed" in body["skipped"][0]["reason"]

            retried = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": [asset_id], "retry_failed": True}, headers=hm)
            assert retried.status_code == 200, retried.text
            assert len(retried.json()["results"]) == 1

        # 提交即失败：任务落 failed，素材也标 failed（不静默）
        third = await _import(client, hm, ["https://www.douyin.com/video/7411111222222333444"])
        fail_id = third.json()["items"][0]["id"]     # 新导入 = stage_prompt pending，允许提交
        failing = _fake_prompt_task(status="failed", error="智令返回：额度不足")
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=failing)):
            resp = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": [fail_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        assert resp.json()["results"][0]["prompt_task_status"] == "failed"
        assert "额度不足" in resp.json()["results"][0]["error"]
        rows = {r.id: r for r in await _rows(AssetItem)}
        assert rows[uuid.UUID(fail_id)].stage_prompt == "failed"
        assert rows[uuid.UUID(fail_id)].status == "failed"
        assert "反推提交失败" in (rows[uuid.UUID(fail_id)].note or "")
        assert rows[uuid.UUID(fail_id)].cost_prompt == 0.0, "失败不该记成本"
        await client.aclose()

    _run(_scenario())


def test_analyze_file_asset_goes_through_doc125_transit():
    """文件素材必须取回本地再走 doc/125 中转（自有桶在局域网内，智令拉不到）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            up = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("素材A.mp4", VIDEO_BYTES, "video/mp4"))],
                headers=hm,
            )
        assert up.status_code == 201, up.text
        asset_id = up.json()["items"][0]["id"]

        created = []

        async def _create_upload(db, **kw):
            created.append(kw)
            return _fake_prompt_task()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.download_to_file", _fake_download_writer()), \
             patch("app.api.assets.create_upload_prompt_task", AsyncMock(side_effect=_create_upload)), \
             patch("app.api.assets.create_prompt_task", AsyncMock()) as link_create:
            resp = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": [asset_id], "max_duration": 300}, headers=hm)
        assert resp.status_code == 200, resp.text
        link_create.assert_not_awaited()
        assert len(created) == 1
        assert created[0]["file_name"] == "素材A.mp4"
        assert created[0]["size_bytes"] == len(VIDEO_BYTES)
        assert created[0]["max_duration"] == 300

        # 文件素材多一笔 doc/125 中转费（0.001 元），成本按档位推算后落库
        rows = await _rows(AssetItem)
        assert rows[0].cost_prompt == pytest.approx(0.00054 * 300 + 0.001, abs=1e-4)
        await client.aclose()

    _run(_scenario())


def test_prompt_refresh_converges_stage_from_provider():
    """轮询替身把 processing 收敛成 success → 素材阶段与派生态跟着变。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)

        from wechat_download.models import PT_PROCESSING, WechatDlPromptTask
        from wechat_download.prompt_client import PromptStatus

        task_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(WechatDlPromptTask(
                id=task_id, source_type="url", source_url=DOUYIN_1,
                provider_task_id="prov-9", status=PT_PROCESSING, max_duration=180,
            ))
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id, a.stage_prompt, a.status = task_id, "running", "analyzing"
            await s.commit()

        fake = SimpleNamespace(
            query=AsyncMock(return_value=PromptStatus(status="success", content=SCRIPT, schedule="SUCCESS")),
            close=AsyncMock(),
        )
        with patch("wechat_download.prompt_service.PromptClient", lambda: fake):
            resp = await client.post(f"/api/assets/{asset_id}/prompt-refresh", headers=hm)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["asset"]["stage_prompt"] == "success"
        # 稿刚回来，出文案还没点——报「等出文案」，不是「出文案中」
        assert body["asset"]["status"] == "waiting_summary"
        assert body["prompt_task"]["status"] == "success"
        assert body["prompt_task"]["content"] == SCRIPT
        fake.query.assert_awaited_once_with("prov-9")
        await client.aclose()

    _run(_scenario())


def test_batch_queue_segments_and_refresh_batch_converges():
    """A4-6：整批排队分段提交（游标）+ 一次收敛全批 + `waiting_prompt`/`analyzing` 分开。

    这三件事是同一个坑的三面：一次排 200 条时，前端既没有"取下一段"的口（只能自己攒
    id、攒错就重复扣钱），也没有"一次收完整批"的口（200 次单条 refresh），
    列表还把「待反推」和「在跑」都显示成 analyzing，看不出谁没人管。
    """
    _run(_bootstrap())

    async def _scenario():
        from wechat_download.models import PT_PROCESSING, WechatDlPromptTask
        from wechat_download.prompt_client import PromptStatus

        client, h = await _client_and_headers()
        hm = h["material"]
        third = "https://www.douyin.com/video/7400000000000000001"
        imp = await _import(client, hm, [DOUYIN_1, DOUYIN_2, third], name="排队批")
        assert imp.status_code == 201, imp.text
        bid = imp.json()["batch"]["id"]
        assert len(imp.json()["items"]) == 3
        # 导入完成＝待反推，不是在跑（旧口径这里一律回 analyzing）
        assert all(i["status"] == "waiting_prompt" for i in imp.json()["items"])

        # ── 入参形态的三种错法 ──
        both = await client.post(
            "/api/assets/analyze/batch", json={"asset_ids": [str(uuid.uuid4())], "batch_id": bid}, headers=hm)
        assert both.status_code == 400 and "二选一" in both.json()["detail"]
        empty = await client.post("/api/assets/analyze/batch", json={}, headers=hm)
        assert empty.status_code == 400 and "整批排队" in empty.json()["detail"]
        big = await client.post("/api/assets/analyze/batch", json={"batch_id": bid, "limit": 999}, headers=hm)
        assert big.status_code == 400 and "limit 请在" in big.json()["detail"]

        cap = int(settings.ASSET_ANALYZE_MAX_PER_CALL)
        submit = AsyncMock(return_value=_fake_prompt_task())
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", submit) as cpt:
            # 第一段取 2 条：≥2 条仍是批量扣费，确认单没点 → 409，且把队列位置回给前端
            unconfirmed = await client.post(
                "/api/assets/analyze/batch",
                json={"batch_id": bid, "max_duration": 60, "limit": 2}, headers=hm)
        assert unconfirmed.status_code == 409, unconfirmed.text
        q409 = unconfirmed.json()["detail"]["queue"]
        assert q409["picked"] == 2 and q409["remaining"] == 1 and q409["offset"] == 0
        cpt.assert_not_awaited()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task",
                   AsyncMock(side_effect=lambda db, **kw: _fake_prompt_task())) as cpt:
            seg1 = await client.post(
                "/api/assets/analyze/batch",
                json={"batch_id": bid, "max_duration": 60, "limit": 2, "confirmed": True}, headers=hm)
            assert seg1.status_code == 200, seg1.text
            assert cpt.await_count == 2
            q1 = seg1.json()["queue"]
            assert q1["picked"] == 2 and q1["remaining"] == 1
            assert "还剩 1 条" in seg1.json()["message"]

            # 第二段：提交成功的两条已自动离开队列，不用前端自己挪游标
            seg2 = await client.post(
                "/api/assets/analyze/batch",
                json={"batch_id": bid, "max_duration": 60}, headers=hm)
            assert seg2.status_code == 200, seg2.text
            assert seg2.json()["queue"]["picked"] == 1
            assert seg2.json()["queue"]["remaining"] == 0
            assert cpt.await_count == 3

        # 三条都在跑 → 列表按状态能分开筛
        running = await client.get(f"/api/assets?batch_id={bid}&status=analyzing", headers=hm)
        assert running.json()["total"] == 3
        waiting = await client.get(f"/api/assets?batch_id={bid}&status=waiting_prompt", headers=hm)
        assert waiting.json()["total"] == 0

        # ── 一次收敛：两条真任务（一成一败）+ 一条残留（有 stage 无任务行）──
        rows = await _rows(AssetItem, AssetItem.batch_id == uuid.UUID(bid))
        rows = sorted(rows, key=lambda a: (a.created_at, a.code))
        t1, t2 = uuid.uuid4(), uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            for a, tid in ((rows[0], t1), (rows[1], t2)):
                fresh = await s.get(AssetItem, a.id)
                s.add(WechatDlPromptTask(
                    id=tid, source_type="url", source_url=fresh.source_url,
                    provider_task_id=f"p-{tid.hex[:6]}", status=PT_PROCESSING, max_duration=60))
                fresh.prompt_task_id = tid
            await s.commit()
        # rows[2] 保持 mock 给的悬空 prompt_task_id：提交后进程中断的真实残留形态

        fake = SimpleNamespace(
            query=AsyncMock(side_effect=[
                PromptStatus(status="success", content=SCRIPT, schedule="SUCCESS"),
                PromptStatus(status="failed", error="额度耗尽", schedule="FAIL"),
            ]),
            close=AsyncMock())
        with patch("wechat_download.prompt_service.PromptClient", lambda: fake):
            rf = await client.post("/api/assets/analyze/refresh-batch", json={"batch_id": bid}, headers=hm)
        assert rf.status_code == 200, rf.text
        body = rf.json()
        assert body["refreshed"] == 3
        assert body["tally"] == {"success": 1, "failed": 1, "running": 0, "stuck": 1, "poll_error": 0}
        assert body["remaining_running"] == 0
        assert "残留" in body["message"] or "判失败 1" in body["message"]
        stuck = [r for r in body["results"] if r["stage_prompt"] == "failed" and r["prompt_task_status"] is None]
        assert len(stuck) == 1 and "任务行缺失" in stuck[0]["error"]
        still_running = await client.get(f"/api/assets?batch_id={bid}&status=analyzing", headers=hm)
        assert still_running.json()["total"] == 0, "收敛后不能再有在跑的挂在列表上"

        # 残留判 failed 后有出口：整批 + retry_failed 把它和真失败的一起重跑
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task",
                   AsyncMock(side_effect=lambda db, **kw: _fake_prompt_task())) as cpt2:
            requeue = await client.post(
                "/api/assets/analyze/batch",
                json={"batch_id": bid, "max_duration": 60, "retry_failed": True, "confirmed": True},
                headers=hm)
        assert requeue.status_code == 200, requeue.text
        assert requeue.json()["queue"]["picked"] == 2, "只重排 failed 的两条，已成功的不重复烧钱"
        assert cpt2.await_count == 2

        # ── 出文案侧同样能整批排队（只排「反推成功且本条没出过文案」的）──
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            sq = await client.post("/api/assets/summaries/generate", json={"batch_id": bid}, headers=hm)
        assert sq.status_code == 200, sq.text
        assert sq.json()["queue"]["picked"] == 1 and sq.json()["results"][0]["created"] == 3
        drained = await client.post("/api/assets/summaries/generate", json={"batch_id": bid}, headers=hm)
        assert drained.status_code == 400 and "没有待出文案的素材" in drained.json()["detail"]

        # refresh-batch 的入参校验与单条口一致：混传/空传都是 400
        mix = await client.post(
            "/api/assets/analyze/refresh-batch",
            json={"batch_id": bid, "asset_ids": [str(rows[0].id)]}, headers=hm)
        assert mix.status_code == 400 and "二选一" in mix.json()["detail"]
        nada = await client.post("/api/assets/analyze/refresh-batch", json={}, headers=hm)
        assert nada.status_code == 400
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  4. 钩子文案生成  ─────────────────────────


def test_summaries_require_reverse_prompt_content():
    """反推没成功就硬拦：不能把「反推失败」洗成「像模像样的幻觉文案」。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        resp = await _import(client, hm, [DOUYIN_2])
        asset_id = resp.json()["items"][0]["id"]

        call = _fake_autoclip()
        with patch("app.api.assets._call_autoclip", call):
            gen = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
        assert gen.status_code == 200, gen.text
        r = gen.json()["results"][0]
        assert r["created"] == 0 and "反推脚本尚未就绪" in r["error"]
        call.assert_not_awaited()
        assert await _count(AssetSummary) == 0
        await client.aclose()

    _run(_scenario())


def test_summaries_generate_three_candidates_with_checks():
    """三条候选落库（count 显式传 3）：字数、高风险词、一致性校验各归各位，且带一个推荐条。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, task_id = await _make_ready_asset(client, hm)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call:
            gen = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "count": 3, "extra_requirements": "突出医院门口"},
                headers=hm,
            )
        assert gen.status_code == 200, gen.text
        assert gen.json()["results"][0]["created"] == 3
        # 双产出后这里其实发了两次调用（先 hook-copy/generate 再 hook-copy/prompt-web），断言取第一次
        payload = call.await_args_list[0].args[1]
        assert payload["script"] == SCRIPT and payload["count"] == 3
        assert "医院门口" in payload["params"]["extra_requirements"]

        rows = await _rows(AssetSummary, AssetSummary.asset_id == uuid.UUID(asset_id))
        assert [r.seq for r in rows] == [1, 2, 3]
        assert sum(1 for r in rows if r.is_recommended) == 1
        assert rows[0].consistency_ok is True and rows[0].risk_hit is None
        assert rows[1].consistency_ok is False and "李姐" in rows[1].consistency_note
        assert "百分百" in (rows[2].risk_hit or "") and "根治" in rows[2].risk_hit
        assert rows[0].word_count == len(rows[0].text)
        assert all(str(r.source_prompt_task_id) == str(task_id) for r in rows)

        asset = (await _rows(AssetItem))[0]
        assert asset.stage_summary == "success"
        assert asset.status == "awaiting_review"      # 概要成功 + 无过审 → 待审
        assert asset.has_approved_copy is False

        # 再来一次默认不动历史（已审/够数都不覆盖），overwrite 才重生成
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            again = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
        assert again.json()["results"][0]["created"] == 0
        assert again.json()["results"][0]["note"]
        assert await _count(AssetSummary) == 3

        # 超单次上限：400（同步等大模型，多了网关超时）
        ids = [asset_id] * 20
        too_many = await client.post(
            "/api/assets/summaries/generate", json={"asset_ids": ids}, headers=hm)
        assert too_many.status_code == 400
        assert "单次最多出文案" in too_many.json()["detail"]
        await client.aclose()

    _run(_scenario())


def test_summary_generate_default_count_is_one(monkeypatch):
    """11-06 用户拍板：不传 count 默认只出 1 条（省一半模型钱；要对照用 count 显式覆盖）。

    conftest 的测试基线把候选数钉在 3（供三候选机制用例复用），这里单独改回 1 验默认值。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.config import settings

        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        monkeypatch.setattr(settings, "ASSET_HOOK_CANDIDATE_COUNT", 1, raising=True)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call:
            gen = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
        assert gen.status_code == 200, gen.text
        assert gen.json()["results"][0]["created"] == 1
        assert call.await_args_list[0].args[1]["count"] == 1
        rows = await _rows(AssetSummary)
        assert [r.seq for r in rows] == [1]
        await client.aclose()

    _run(_scenario())


def test_overwrite_refuses_when_a_copy_already_approved():
    """过审文案已挂生产单 → overwrite 拒绝（删了会让 summary 外键悬空）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "count": 3}, headers=hm)
        summaries = await _rows(AssetSummary)
        sid = str(summaries[0].id)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        await client.post("/api/assets/produce",
                          json={"summary_ids": [sid], "n": 2, "expand": False}, headers=ho)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            resp = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "overwrite": True}, headers=hm)
        assert "已过审" in resp.json()["results"][0]["error"]
        assert await _count(AssetSummary) == 3
        assert await _count(AssetProduction) == 2
        await client.aclose()

    _run(_scenario())


def test_summary_generate_failure_keeps_old_candidates_and_marks_failed():
    """模型调不通时：旧的候选一条不许少，本条如实标 failed，整口不抬 500。

    11-03 预览栈真链路实测：mimo 出候选要 9 分钟，PG 的 idle_in_transaction=60s
    把连接掐了 → 旧写法先删旧候选、再抬 500，用户看到的是「旧文案没了、
    新文案也没来」。现在删除挪到模型返回之后，失败只标这一条。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            first = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "count": 3}, headers=hm)
        assert first.status_code == 200, first.text
        assert first.json()["results"][0]["created"] == 3

        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(generate_error="文案服务调用失败（AutoClip 502）")):
            bad = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "overwrite": True}, headers=hm)

        assert bad.status_code == 200, bad.text          # 不再是 500/502
        entry = bad.json()["results"][0]
        assert entry["created"] == 0
        assert "AutoClip" in entry["error"]
        assert await _count(AssetSummary) == 3           # 旧候选原样留着
        row = await _row_of(AssetItem, asset_id)
        assert row.stage_summary == "failed"
        assert "出文案失败" in (row.note or "")
        await client.aclose()

    _run(_scenario())


def test_produce_sets_approved_flag_only_when_orders_actually_land():
    """has_approved_copy 是列，apply_stage 只用它算派生态、不写列。

    11-03 起这行写列挪到**写单阶段**（原来在循环顶部），为的是别在等外部模型的
    几分钟里锁住 asset_items 那一行——同批素材的反推收敛写 stage 会被挡到超时报错。
    所以：真成单才置位；展开失败整条没成单时不许留下置位。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
        sid = (await _rows(AssetSummary))[0].id
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [str(sid)], "action": "approve"}, headers=ho)

        # 展开炸了：一条单都没成，列不许被提前置位
        with patch("app.api.assets._call_autoclip", _fake_autoclip(expand_error="展开服务没回话")):
            failed = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [str(sid)], "n": 2, "expand": True}, headers=ho)
        assert failed.status_code == 200, failed.text
        assert await _count(AssetProduction) == 0

        # 真的成单了：列置位，列表「有过审文案」筛选才对得上
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            ok = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [str(sid)], "n": 2, "expand": True}, headers=ho)
        assert ok.status_code == 200, ok.text
        assert ok.json()["created"] == 2
        assert await _count(AssetProduction) == 2
        row = await _row_of(AssetItem, asset_id)
        assert row.has_approved_copy is True
        await client.aclose()

    _run(_scenario())


def test_expand_deviation_note_is_surfaced_not_dropped():
    """模板自报偏差（deviation_note）必须落地到一线看得见的地方。

    hook_expand.txt 里点名的三条都走这个通道：缺剧名→提示词写《剧名待定》、
    没挂角色卡→画幅不受文字控制、K 未给→标题按 5 条兜底。11-03 真链路冒烟时
    模板照实报了、后端整包丢掉，导出 txt 与生产单详情里一个字都看不见。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        note = "输入未给剧名全称，第①行按《剧名待定》占位；未挂角色卡，成片画幅不受文字控制"
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/summaries/generate",
                              json={"asset_ids": [asset_id]}, headers=hm)
        sid = (await _rows(AssetSummary))[0].id
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [str(sid)], "action": "approve"}, headers=ho)
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_deviation=note)):
            resp = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [str(sid)], "n": 2, "expand": True}, headers=ho)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 2
        # 逐条清单：两份差异化各报一次
        assert len(body["deviations"]) == 2
        assert body["deviations"][0]["note"] == note
        # 顶栏警示里要有这一条，否则一线不会去点开详情
        assert any("模型自报了偏差" in w for w in body["warnings"]), body["warnings"]
        # 单条也要留痕：dispatch_note 是「只给人看、不进 payload」那份，导出 txt 带的就是它
        rows = await _rows(AssetProduction)
        assert all(note in (p.dispatch_note or "") for p in rows), [p.dispatch_note for p in rows]
        # 偏差不能污染投给模型的正文
        assert all(note not in (p.prompt_text or "") for p in rows)
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  5. 审核  ─────────────────────────


async def _gen_and_list(asset_id, h, client):
    """出文案（mock 文案服务）后回读**这条素材**的候选（队列默认是跨素材全量，必须带过滤）。"""
    with patch("app.api.assets._call_autoclip", _fake_autoclip()):
        resp = await client.post(
            "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=h)
    assert resp.status_code == 200, resp.text
    q = await client.get(f"/api/assets/summaries?asset_id={asset_id}", headers=h)
    assert q.status_code == 200, q.text
    return q.json()["items"], q


def _approvable(items):
    """三条候选里唯一「形态+风险+一致性」全过关的那条（推荐条）。

    CANDIDATES 的第 2、3 条是故意造的坏样本（实体对不上 / 含 block 风险词）。
    A2-1 之后含 block 词的那条**过不了审也投不了产**；R-6 之后「实体对不上」那条
    降级成**预警**（能过审，只在 consistency_ok/consistency_note 留痕）。这里仍挑
    三条全绿的那条走 happy path：测试要的是干净样本，不是"勉强能过"的样本，
    也别靠队列顺序（顺序是 created_at 倒序，等于随机）。
    """
    good = [i for i in items if not i["risk_hit"] and i["consistency_ok"]]
    assert len(good) == 1, [i["text"] for i in items]
    return good[0]


def _risky(items):
    """含 block 级风险词的那条，用来验复核真的会拦。"""
    return next(i for i in items if i["risk_hit"])


def test_review_self_review_follows_knob_and_requires_reason(monkeypatch):
    """自审闸跟 ASSET_SELF_PRODUCE_ALLOWED 走（2026-11-23 用户拍板：全局放开）。

    历史口径（11-03/11-08）：生产者不得自审，审核口硬编码拦。
    2026-11-23 用户原话「自审范围按建议开放到全局」⇒ 审核口改为读**与投产侧同一个旋钮**：
    - 旋钮 false：拦（保留纪律口径），错误码 ASSET_SELF_REVIEW_BLOCKED；
    - 旋钮 true（默认）：放行，但**逐条写 self 标记的豁免审计**（放开≠无痕）。
    另外三条与本闸无关的硬规矩照旧：驳回/需改写必填理由、素材专员无审核权限、admin 恒过。
    """
    _run(_bootstrap())
    from app.config import settings

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        assert len(items) == 3
        sid = _approvable(items)["id"]

        # 素材专员根本没有审核权限（require_roles → 403）
        self_review = await client.post(
            "/api/assets/summaries/review", json={"summary_ids": [sid], "action": "approve"}, headers=hm)
        assert self_review.status_code == 403, self_review.text

        # operator 有自己的「反推已成功」素材（自审场景的前提）
        own_asset, _ = await _make_ready_asset(client, ho, url=DOUYIN_1)
        own_items, _ = await _gen_and_list(own_asset, ho, client)
        assert own_items and all(i["asset_id"] == own_asset for i in own_items)
        # 挑「无风险词 + 一致性 ok」的干净样本：本用例验的是自审闸，不该被复核的
        # 风险词顺手拦下（own_items 里本来就混着故意造的坏样本）
        own_sid = _approvable(own_items)["id"]

        # ① 旋钮关：自审被拦（保留「质检与投产分离」纪律口径）
        monkeypatch.setattr(settings, "ASSET_SELF_PRODUCE_ALLOWED", False, raising=True)
        blocked = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [own_sid], "action": "approve"}, headers=ho)
        assert blocked.status_code == 200
        assert blocked.json()["results"][0]["ok"] is False
        assert blocked.json()["results"][0]["error_code"] == "ASSET_SELF_REVIEW_BLOCKED"
        assert "生产者不能审核自己" in blocked.json()["results"][0]["error"]

        # ② 旋钮开（默认）：自审放行，且 after.self_review 留痕（放开≠无痕）
        monkeypatch.setattr(settings, "ASSET_SELF_PRODUCE_ALLOWED", True, raising=True)
        allowed = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [own_sid], "action": "approve"}, headers=ho)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["results"][0]["ok"] is True, allowed.text
        self_audits = [
            a for a in await _rows(AuditLog, AuditLog.action == "asset.summary_review.approve")
            if (a.after or {}).get("self_review")
        ]
        assert len(self_audits) == 1 and self_audits[0].after["self_review"]["self"] is True

        # 驳回必填理由
        no_reason = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "reject"}, headers=ho)
        assert no_reason.status_code == 400 and "必须填理由" in no_reason.json()["detail"]

        # admin 可以过审（逃生门）
        ok = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "approve"}, headers=ha)
        assert ok.status_code == 200 and ok.json()["results"][0]["ok"] is True

        rows = {str(r.id): r for r in await _rows(AssetSummary)}
        assert rows[sid].audit_status == RV_APPROVED
        assert rows[sid].reviewed_by is not None
        # 只数**这条**的审计：本用例前面还让 operator 自审放行了一条（self_review 留痕），
        # 那条也是同一个 action，按 target_id 收窄才不会把别人的账算进来
        audits = [
            a for a in await _rows(AuditLog, AuditLog.action == "asset.summary_review.approve")
            if str(a.target_id) == sid
        ]
        assert len(audits) == 1
        assert audits[0].before["audit_status"] == RV_PENDING
        assert audits[0].after["text"] == rows[sid].text
        await client.aclose()

    _run(_scenario())


def test_everything_is_visible_across_people_and_review_is_still_cross_person():
    """11-03 拍板：素材内容**全量可见、不分权限**。原先「列表 own 看不见、队列跨人」
    两套口径一并取消 —— 谁能看不再受限，谁能**写**（审核/投产）仍按角色，
    且生产者不得自审照旧生效。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        await _gen_and_list(asset_id, hm, client)

        # 素材专员导入的货，运营在列表里直接看得见（旧口径这里断 ==0）
        op_assets = await client.get("/api/assets", headers=ho)
        assert op_assets.status_code == 200, op_assets.text
        assert op_assets.json()["total"] == 1, "取消 data_scope 隔离：列表全量可见"
        assert op_assets.json()["items"][0]["created_by"], "创建人仍如实回显，只是不再用来过滤"

        queue = await client.get("/api/assets/summaries?audit_status=pending", headers=ho)
        assert queue.status_code == 200, queue.text
        assert queue.json()["total"] == 3, "待审队列照旧全量（审核本来就是跨人职责）"

        # recommended_only：方案 §七「默认只过推荐条」的后端口径（前端默认勾它）
        rec_only = await client.get(
            "/api/assets/summaries?audit_status=pending&recommended_only=true", headers=ho)
        assert rec_only.json()["total"] == 1, "三条候选里只有一条是推荐条"
        assert rec_only.json()["items"][0]["is_recommended"] is True
        assert queue.json()["items"][0]["asset_code"]

        risky = await client.get("/api/assets/summaries?only_risk=true", headers=ho)
        assert [i["text"] for i in risky.json()["items"]] and len(risky.json()["items"]) == 1
        incons = await client.get("/api/assets/summaries?only_inconsistent=true", headers=ho)
        assert len(incons.json()["items"]) == 1

        # 详情同样全量可见（旧口径对 operator 是 404「不泄露存在性」）
        detail = await client.get(f"/api/assets/{asset_id}", headers=ho)
        assert detail.status_code == 200, detail.text
        assert len(detail.json()["summaries"]) == 3
        assert detail.json()["prompt_script"] == SCRIPT
        admin_detail = await client.get(f"/api/assets/{asset_id}", headers=h["admin"])
        assert admin_detail.status_code == 200
        assert len(admin_detail.json()["summaries"]) == 3

        # 发布专员（连 data_scope=own 都给了）：读得到 —— 隔离取消后 own 不再过滤任何读口；
        # 但审核/投产仍是 403，因为**取消的是"谁能看"，不是"谁能写"**
        async with dbmod.async_session_factory() as s:
            s.add(User(id=uuid.uuid4(), username="asset_pub_scope", password_hash=get_password_hash(PASSWORD),
                       display_name="发布专员（own）", role="publisher", data_scope="own", is_active=True))
            await s.commit()
        pr = await client.post(
            "/api/auth/login", json={"username": "asset_pub_scope", "password": PASSWORD})
        assert pr.status_code == 200, pr.text
        hp = {"Authorization": f"Bearer {pr.json()['access_token']}"}
        pub_list = await client.get("/api/assets", headers=hp)
        assert pub_list.status_code == 200 and pub_list.json()["total"] == 1, "读口不再分权限"
        pub_review = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [queue.json()["items"][0]["id"]], "action": "approve"}, headers=hp)
        assert pub_review.status_code == 403, "读口放开不等于把审核权给发布专员"
        await client.aclose()

    _run(_scenario())


def test_summaries_list_supports_asset_ids_and_multi_status():
    """11-09 为「② 素材与文案 → 投去 AI 生成」加的两个只读筛选。

    要点不是"能过滤"，而是**一次请求就能把两条素材的过审文案全取回**：
    approved + passed_edited 拆成两次请求拼出来的 total 不可信（前端只能猜），
    而投产闸门要的就是这一份完整清单——少一条就是少投一条，多一条是把已撤审的投出去。
    脏入参一律当场 400 点名，别让人对着空列表猜自己哪儿筛错了（与 GET /assets 同口径）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]

        # A 素材：一条 approved；B 素材：一条 passed_edited；C 素材：只有 pending（不该被捞进来）
        id_a, _ = await _make_ready_asset(client, hm, DOUYIN_2)
        id_b, _ = await _make_ready_asset(client, hm, DOUYIN_3)
        id_c, _ = await _make_ready_asset(client, hm, DOUYIN_1)
        items_a, _ = await _gen_and_list(id_a, hm, client)
        items_b, _ = await _gen_and_list(id_b, hm, client)
        await _gen_and_list(id_c, hm, client)

        ok_a = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [_approvable(items_a)["id"]], "action": "approve"}, headers=ho)
        assert ok_a.status_code == 200 and ok_a.json()["results"][0]["ok"] is True, ok_a.text

        b_good = _approvable(items_b)
        edited = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [b_good["id"]], "action": "pass_edited",
                  "new_text": f"{b_good['text']}，这方案百分百能成"}, headers=ho)
        assert edited.status_code == 200 and edited.json()["results"][0]["ok"] is True, edited.text

        # ① 多状态 + asset_ids：A、B 各一条，C 的三条 pending 一条不带
        both = await client.get(
            f"/api/assets/summaries?asset_ids={id_a},{id_b}"
            f"&audit_status=approved,passed_edited", headers=ha)
        assert both.status_code == 200, both.text
        body = both.json()
        assert body["total"] == 2, body
        assert {i["asset_id"] for i in body["items"]} == {id_a, id_b}
        assert {i["audit_status"] for i in body["items"]} == {"approved", "passed_edited"}

        # ② 只点一条素材：另一条即使已过审也不能混进来（投产弹窗按勾选取范围）
        only_a = await client.get(
            f"/api/assets/summaries?asset_ids={id_a}&audit_status=approved,passed_edited", headers=ha)
        assert only_a.json()["total"] == 1, only_a.text
        assert only_a.json()["items"][0]["asset_id"] == id_a

        # ③ 单状态行为不回归（老调用方全是单值）
        single = await client.get(
            f"/api/assets/summaries?asset_ids={id_a},{id_b},{id_c}&audit_status=approved", headers=ha)
        assert single.json()["total"] == 1, single.text

        # ④ 逗号里带空段/重复 id：去空去重后照查，不把「a,,b」判成脏输入
        sloppy = await client.get(
            f"/api/assets/summaries?asset_ids={id_a},,{id_b},{id_a}"
            "&audit_status=approved, passed_edited", headers=ha)
        assert sloppy.status_code == 200 and sloppy.json()["total"] == 2, sloppy.text

        # ⑤ 脏入参当场 400：状态拼错、id 不是 id、一次塞太多
        bad_status = await client.get(
            "/api/assets/summaries?audit_status=approved,nope", headers=ha)
        assert bad_status.status_code == 400, bad_status.text
        assert "只认" in bad_status.json()["detail"] and "pending" in bad_status.json()["detail"]

        bad_ids = await client.get("/api/assets/summaries?asset_ids=abc123", headers=ha)
        assert bad_ids.status_code == 400 and "asset_ids" in bad_ids.json()["detail"], bad_ids.text

        too_many = ",".join(str(uuid.uuid4()) for _ in range(301))
        over = await client.get(f"/api/assets/summaries?asset_ids={too_many}", headers=ha)
        assert over.status_code == 400 and "300" in over.json()["detail"], over.text
        await client.aclose()

    _run(_scenario())


def test_summaries_list_ids_returns_these_rows_whatever_their_state_is():
    """11-11 为开单屏「取最新稿子」加的 `ids`：点名的这几条，库里现在长什么样就回什么。

    这一口存在的理由不是"能过滤"，而是开单那一屏手里拿的是**进弹窗那一刻的快照**，
    文案可能刚在别的屏被重出/改过/撤审。所以两条硬判据：
      ① **不因审核态消失**——pending 的照样回（撤审那条要是查不到，界面只能报「少了一行」，
         说不出「这条已经不没过审了」，人就会以为是接口抽风）；
      ② **回的是当前值**——改后通过的正文必须变成 new_text（拿旧正文重认换皮参数＝换错词）。
    与 `audit_status` 叠加时仍以状态为准（不越权把已筛掉的塞回来）。
    未知但形状合法的 id 只当查不到（total 里没它），不 400——前端靠这个差集点名「哪几条没了」。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        id_a, _ = await _make_ready_asset(client, hm, DOUYIN_2)
        id_b, _ = await _make_ready_asset(client, hm, DOUYIN_3)
        id_c, _ = await _make_ready_asset(client, hm, DOUYIN_1)
        items_a, _ = await _gen_and_list(id_a, hm, client)
        items_b, _ = await _gen_and_list(id_b, hm, client)
        items_c, _ = await _gen_and_list(id_c, hm, client)

        sid_ok = _approvable(items_a)["id"]
        approved = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid_ok], "action": "approve"}, headers=ho)
        assert approved.status_code == 200 and approved.json()["results"][0]["ok"] is True, approved.text

        b_good = _approvable(items_b)
        new_text = f"{b_good['text']}，这方案百分百能成"
        edited = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [b_good["id"]], "action": "pass_edited", "new_text": new_text},
            headers=ho)
        assert edited.status_code == 200 and edited.json()["results"][0]["ok"] is True, edited.text

        # pending 的那条（素材 C 名下随便一条，没过审）——ids 口必须照样回它
        sid_pending = items_c[0]["id"]

        # ① 三种审核态一起点：一条不吞
        got = await client.get(
            f"/api/assets/summaries?ids={sid_ok},{b_good['id']},{sid_pending}", headers=ho)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["total"] == 3, body
        assert {i["id"] for i in body["items"]} == {sid_ok, b_good["id"], sid_pending}
        assert {i["audit_status"] for i in body["items"]} == {"approved", "passed_edited", "pending"}

        # ② 回的是**当前**正文：改后通过的那条必须已经是改后的字
        row_b = [i for i in body["items"] if i["id"] == b_good["id"]][0]
        assert row_b["text"] == new_text, row_b
        assert "prompt_preview" in row_b and "category_name" in row_b, sorted(row_b)

        # ③ 与 audit_status 叠加：状态仍然是硬筛，ids 不越权把 pending 塞回来
        only_ap = await client.get(
            f"/api/assets/summaries?ids={sid_ok},{b_good['id']},{sid_pending}"
            "&audit_status=approved,passed_edited", headers=ho)
        assert only_ap.json()["total"] == 2, only_ap.text

        # ④ 逗号里带空段/重复：去空去重后照查（抄 asset_ids 的宽容口径）
        sloppy = await client.get(
            f"/api/assets/summaries?ids={sid_ok},,{sid_ok},{b_good['id']}", headers=ho)
        assert sloppy.status_code == 200 and sloppy.json()["total"] == 2, sloppy.text

        # ⑤ 形状合法但库里没有＝查不到，不报错（前端就靠这个差集说「这几条已经不在了」）
        ghost = await client.get(f"/api/assets/summaries?ids={uuid.uuid4()}", headers=ho)
        assert ghost.status_code == 200 and ghost.json()["total"] == 0, ghost.text

        # ⑥ 脏入参当场 400 点名：不是 id、只写了逗号、一次塞太多
        bad = await client.get("/api/assets/summaries?ids=abc123", headers=ho)
        assert bad.status_code == 400 and "ids" in bad.json()["detail"], bad.text
        empty = await client.get("/api/assets/summaries?ids=,,", headers=ho)
        assert empty.status_code == 400 and "不能是空的" in empty.json()["detail"], empty.text
        too_many = ",".join(str(uuid.uuid4()) for _ in range(301))
        over = await client.get(f"/api/assets/summaries?ids={too_many}", headers=ho)
        assert over.status_code == 400 and "300" in over.json()["detail"], over.text
        await client.aclose()

    _run(_scenario())


def test_self_produce_gate_is_open_by_default_and_blocks_only_when_closed():
    """11-09 用户口径：自审自投**默认放开**（ASSET_SELF_PRODUCE_ALLOWED=true）。

    翻一个默认值必须有测试钉住，否则「放开」只是注释里的白话。三件事缺一不可：
    ① 默认放开时「同一人过审 → 同一人投产」200，且审计 owner_cross 把这条标成
       `self=true`——放开不等于无痕，事后仍查得到谁自己审自己投；
    ② 只有显式设 false 才 400，而且文案说的是「闸门当前关着＋怎么打开」，
       不能再写「默认拦」这种跟现状相反的话（写了会把人引去翻一个已经打开的闸）；
    ③ 被拦那一次**一条生产单都没落**：闸门在建单/扣费之前。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        aid, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(aid, hm, client)
        sid = _approvable(items)["id"]

        # 过审人＝后面投产的同一人（自审自投的形状）
        ok_rev = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        assert ok_rev.status_code == 200 and ok_rev.json()["results"][0]["ok"] is True, ok_rev.text

        async def _produce_self():
            with patch("app.api.assets._call_autoclip", _fake_autoclip()):
                return await client.post(
                    "/api/assets/produce",
                    json={"summary_ids": [sid], "n": 1, "async_mode": False}, headers=ho)

        # ② 先测「显式关闸」——conftest 把基线钉成 true，这里用 patch.object 临时改回 false
        orders_before = await _count(AssetProduction)
        with patch.object(settings, "ASSET_SELF_PRODUCE_ALLOWED", False):
            blocked = await _produce_self()
            assert blocked.status_code == 400, blocked.text
            msg = blocked.json()["detail"]
            assert "闸门当前是关着的" in msg, msg
            assert "默认拦" not in msg, "默认已经是放开，别再写「默认拦」把人引去翻一个开着的闸"
            assert "ASSET_SELF_PRODUCE_ALLOWED" in msg and "留豁免审计" in msg, msg
            assert await _count(AssetProduction) == orders_before, "拦在建单之前：一条都没多落"

        # ① 默认（true）同一个人过审→投产：200，且审计逐条标 self
        done = await _produce_self()
        assert done.status_code == 200, done.text
        rows = await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(aid))
        assert len(rows) == 1, "闸门放开后同一人自审自投要真建出单"
        audits = await _rows(AuditLog, AuditLog.action == "asset.produce_order")
        cross = [a.after["owner_cross"] for a in audits
                 if a.after and a.after.get("owner_cross")]
        assert cross, "自审自投也要在审计里留痕（放开≠无痕）"
        marked = [s for c in cross for s in c["summaries"] if s["summary_id"] == sid]
        assert marked and marked[-1]["self"] is True, marked
        await client.aclose()

    _run(_scenario())


def test_asset_list_filters_and_failed_first_sort():
    """A4-3 的四个筛选 + failed 优先：昨天那 200 条里谁卡住、卡在哪一步，不能靠翻页。"""
    _run(_bootstrap())

    async def _patch(asset_id, **values):
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            for k, v in values.items():
                setattr(a, k, v)
            await s.commit()

    async def _codes(resp):
        return [i["code"] for i in (await resp).json()["items"]]

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        ids = []
        for i in range(3):
            aid, _ = await _make_ready_asset(
                client, hm, url=f"https://www.douyin.com/video/749900000000000000{i}")
            ids.append(aid)
        all_items = (await client.get("/api/assets", headers=hm)).json()["items"]
        by_id = {i["id"]: i for i in all_items}
        assert len(all_items) == 3
        mat_id = (await _rows(User, User.username == MATERIAL_USER))[0].id
        op_id = (await _rows(User, User.username == OPERATOR_USER))[0].id

        # 阶段级筛选：status=failed 只说"失败了"，说不出是反推挂的还是生产挂的
        # 派生态 status 由 apply_stage 算，测试里直写两列（等价于走一次 apply_stage）
        await _patch(ids[0], stage_prompt="failed", status="failed")
        await _patch(ids[1], stage_produce="failed", status="failed")
        assert await _codes(client.get("/api/assets?status=failed", headers=hm)) == \
               [by_id[ids[1]]["code"], by_id[ids[0]]["code"]], "派生态 failed 两条都算"
        assert await _codes(client.get("/api/assets?stage_prompt=failed", headers=hm)) == \
               [by_id[ids[0]]["code"]]
        assert await _codes(client.get("/api/assets?stage_produce=failed", headers=hm)) == \
               [by_id[ids[1]]["code"]]
        assert (await client.get("/api/assets?stage_prompt=broken", headers=hm)).status_code == 400
        # 阶段态与"待反推"要能分开：running 是"在跑"，pending 是"还没排上"
        assert len((await client.get("/api/assets?stage_summary=pending", headers=hm)).json()["items"]) == 3

        # 创建人
        assert len(await _codes(client.get(f"/api/assets?created_by={mat_id}", headers=hm))) == 3
        assert await _codes(client.get(f"/api/assets?created_by={op_id}", headers=hm)) == []
        assert (await client.get("/api/assets?created_by=not-a-uuid", headers=hm)).status_code == 400

        # 日期区间（按 CST 自然日，含端点）：01 号 18:00 CST = 10:00 UTC
        for aid in ids:
            await _patch(aid, created_at=datetime(2026, 10, 1, 10, 0, 0))
        assert len(await _codes(client.get(
            "/api/assets?date_from=2026-10-01&date_to=2026-10-01", headers=hm))) == 3
        assert await _codes(client.get("/api/assets?date_from=2026-10-02", headers=hm)) == []
        assert await _codes(client.get("/api/assets?date_to=2026-09-30", headers=hm)) == []
        assert len(await _codes(client.get(
            "/api/assets?date_from=2026-09-30&date_to=2026-10-02", headers=hm))) == 3
        assert (await client.get("/api/assets?date_from=20261001", headers=hm)).status_code == 400

        # 审核态筛选（命中"这条素材的候选里有该态"）——拿没被判失败的那条出文案，
        # 出文案会把 stage_prompt 回写成 success，别把它和 failed 样本混在一起
        await _gen_and_list(ids[2], hm, client)
        pending_hit = await client.get("/api/assets?audit_status=pending", headers=hm)
        assert [i["id"] for i in pending_hit.json()["items"]] == [ids[2]], "只筛出有候选的那条"
        assert (await client.get("/api/assets?audit_status=nope", headers=hm)).status_code == 400

        # failed 优先：把最新导入但没卡住的排到卡住的前面去，必须被压回后头
        await _patch(ids[2], created_at=datetime(2026, 10, 2, 10, 0, 0))
        plain = await _codes(client.get("/api/assets", headers=hm))
        assert plain[0] == by_id[ids[2]]["code"], "默认仍按导入时间倒序"
        pushed = await _codes(client.get("/api/assets?sort=failed_first", headers=hm))
        assert set(pushed[:2]) == {by_id[ids[0]]["code"], by_id[ids[1]]["code"]}, pushed[:2]
        assert pushed[2] == by_id[ids[2]]["code"], "同组内按时间倒序，卡住的整组顶到最前"
        assert (await client.get("/api/assets?sort=random", headers=hm)).status_code == 400
        assert (await client.get("/api/assets?sort=created_asc", headers=hm)).json()["sort"] == "created_asc"
        await client.aclose()

    _run(_scenario())


def test_pass_edited_keeps_original_text_and_validates_shape():
    """改后通过＝跑同一套 recheck：超字数/block 风险词拒，warn 只留痕，原文进 text_before_edit。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        risky = _risky(items)
        sid, original = risky["id"], risky["text"]
        assert "根治" in (risky["risk_hit"] or "")

        too_long = "王" * 90
        resp = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "pass_edited", "new_text": too_long}, headers=ho)
        assert "超字数" in resp.json()["results"][0]["error"]

        # block 级风险词照拦；改后的文案里模型没说、是我们自己写的，所以成因直接给词
        still_risky = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "pass_edited",
                  "new_text": "王总在康华医院门口站了三小时，这药能根治"}, headers=ho)
        blocked = still_risky.json()["results"][0]
        assert blocked["error_code"] == "ASSET_RECHECK_FAILED"
        assert "含高风险词" in blocked["error"] and "根治" in blocked["error"]
        assert {p["code"] for p in blocked["problems"]} == {"risk"}

        # warn 级不拦（百分百＝绝对化用语，只留痕）——否则会把审核训练成"绕道改"
        warn_only = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "pass_edited",
                  "new_text": "王总在康华医院门口站了三小时，这方案百分百能成"}, headers=ho)
        assert warn_only.json()["results"][0]["ok"] is True
        rows_now = {str(r.id): r for r in await _rows(AssetSummary)}
        assert "百分百|warn" in (rows_now[sid].risk_hit or "")

        no_text = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "pass_edited"}, headers=ho)
        assert no_text.status_code == 400 and "改后通过必须提供" in no_text.json()["detail"]

        good = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "pass_edited",
                  "new_text": "王总在康华医院门口站了三小时"}, headers=ho)
        assert good.json()["results"][0]["ok"] is True
        rows = {str(r.id): r for r in await _rows(AssetSummary)}
        assert rows[sid].audit_status == RV_PASSED_EDITED
        # text_before_edit 只存**上一次**的文本（改一版覆盖一版），最初的坏文案靠审计链追溯
        assert rows[sid].text_before_edit == "王总在康华医院门口站了三小时，这方案百分百能成"
        assert rows[sid].risk_hit is None
        assert rows[sid].text == "王总在康华医院门口站了三小时"
        audits = await _rows(AuditLog, AuditLog.action == "asset.summary_review.pass_edited")
        assert original in {a.before["text"] for a in audits}, "每一次改后都留当时的原文"

        # 撤销 → 回到 pending（状态机允许），再过审 → has_approved_copy 跟着变
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "reject", "reason": "换个人再看"}, headers=ho)
        asset = (await _rows(AssetItem))[0]
        assert asset.has_approved_copy is False
        assert asset.status == "awaiting_review"
        reject_row = {str(r.id): r for r in await _rows(AssetSummary)}[sid]
        assert reject_row.reject_reason == "换个人再看"

        # 非法迁移：已 rejected 直接再 reject（同态）应幂等通过，但 approved→approved 之后
        # 走 approve 的幂等；这里验 assert_review_transition 的边界：pending 不能直接到 pending 之外
        bad = await client.post("/api/assets/summaries/review",
                                json={"summary_ids": [sid], "action": "未知动作"}, headers=ho)
        assert bad.status_code == 400
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  6. 生产单  ─────────────────────────


def test_produce_blocks_unapproved_and_caps_n():
    """未过审进不了生产；N 超上限 400；过审后才产差异化生产单。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        clean_id = _approvable(items)["id"]

        unapproved = await client.post(
            "/api/assets/produce", json={"summary_ids": [clean_id], "n": 3}, headers=ho)
        assert unapproved.status_code == 200
        assert unapproved.json()["results"][0]["created"] == 0
        assert "未过审" in unapproved.json()["results"][0]["error"]
        assert await _count(AssetProduction) == 0

        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [clean_id], "action": "approve"}, headers=ho)

        over = await client.post(
            "/api/assets/produce",
            json={"summary_ids": [clean_id], "n": int(settings.ASSET_PRODUCE_MAX_N) + 1}, headers=ho)
        assert over.status_code == 400 and "最多派生" in over.json()["detail"]

        zero = await client.post(
            "/api/assets/produce", json={"summary_ids": [clean_id], "n": 0}, headers=ho)
        assert zero.status_code == 400

        bad_channel = await client.post(
            "/api/assets/produce",
            json={"summary_ids": [clean_id], "n": 2, "channel": "jimeng"}, headers=ho)
        assert bad_channel.status_code == 400 and "channel" in bad_channel.json()["detail"]

        # 生产跨人：素材是专员导入的，operator 审完必须能直接投产（曾因 data_scope 404 死链）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call:
            resp = await client.post(
                "/api/assets/produce",
                json={
                    "summary_ids": [clean_id], "n": 3, "duration": 10,
                    "hook_codes": ["7C0B1", "7C0B2", "7C0B3"], "recommended_title_count": 4,
                    "character_card_key": "asset-cards/card-1.jpg",
                },
                headers=ho)
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 3
        assert not {"capacity_hint", "board_capacity", "capacity"} & resp.json().keys(), \
            "免费投产不再返回任何产能/号池提示"
        # P1 #19：字数软校验字段必须在成功响应里出现。替身给的是「标题1…K」短标题，
        # 预算内 → 空清单；有超支的也只是多几条 warning，**不拦投产**（见 title_budget 单测）
        assert resp.json()["title_warnings"] == []
        # B-1：投放量 = 任务数 × 板上 total（默认每任务 1 版）
        board = resp.json()["board"]
        assert board["channel"] == "wework_aivideo" and board["tasks"] == 3
        assert board["board_total"] == 1 and board["planned_rows"] == 3
        # B-2：board_date 后端生成、完整到秒（只写日期＝成片永久取不回）。
        # 落库/回口是 ISO；投板时由 worker 以 `YYYY-MM-DD HH:MM:SS`（空格分隔）提交。
        assert len(board["date"]) == 19 and board["date"][10] in ("T", " ")

        rows = await _rows(AssetProduction)
        assert len(rows) == 3
        assert len({r.variant_basis for r in rows}) == 3, "N 的语义＝差异化，不是重复投喂"
        assert all(r.prompt_snapshot == rows[0].prompt_snapshot for r in rows)
        assert all(r.drift is False for r in rows)
        assert all(r.status == "order_ready" and r.channel == "wework_aivideo" for r in rows)
        assert {r.seq for r in rows} == {1, 2, 3}
        assert all(r.idempotency_key.endswith(f":{r.seq}") for r in rows)
        assert call.await_count == 3
        assert [c.args[1]["seq"] for c in call.await_args_list] == [1, 2, 3]
        # B-3/B-5/B-7 落列 + 一钩一号按序发号
        assert all(r.board_total == 1 and r.board_tag == settings.ASSET_BOARD_TAG for r in rows)
        assert all(r.board_date is not None and r.board_date.microsecond == 0 for r in rows)
        assert {r.hook_code for r in rows} == {"7C0B1", "7C0B2", "7C0B3"}
        assert all(r.board_name in {"标题1"} for r in rows), "板上 name＝推荐视频标题第 1 条"
        assert all(r.character_card_key == "asset-cards/card-1.jpg" for r in rows)
        # B-9：执行要求行不进正文，只落 dispatch_note
        assert all("执行要求" not in (r.prompt_text or "") for r in rows)
        assert all("重命名一字不差" in (r.dispatch_note or "") for r in rows)
        # K 生效：条数按发布号数出，不是偷偷按 5
        assert len(rows[0].video_titles) == 4
        assert all(r.project_title is None for r in rows), "11-02 版取消项目标题行"

        asset = (await _rows(AssetItem))[0]
        assert asset.has_approved_copy is True
        assert asset.status == AS_READY_TO_PRODUCE
        await client.aclose()

    _run(_scenario())


def test_produce_flags_drift_when_model_rewrites_the_copy():
    """展开结果与过审原句不是同一条 → drift=true + 成因，四种形态一种都不许漏（A3-3）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        copy = _approvable(items)["text"]
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt="一个被改写过、不含原句的提示词")):
            resp = await client.post(
                "/api/assets/produce", json={"summary_ids": [sid], "n": 2}, headers=ho)
        assert resp.status_code == 200 and resp.json()["created"] == 2
        rows = await _rows(AssetProduction)
        assert all(r.drift is True for r in rows)
        assert rows[0].video_titles and len(rows[0].video_titles) == 5
        # 一个 bool 不够一线判断要不要重投：成因逐条落库并回显
        assert "没出现在提示词里" in rows[0].drift_reason
        body = resp.json()
        assert len(body["drifted"]) == 2 and body["drifted"][0]["reason"] == rows[0].drift_reason
        assert any("不是同一条" in w for w in body["warnings"])

        # 旧判据（去空格子串包含）漏掉的三种，现在必须逐个抓到
        for shape, why in (
            (f"镜头缓慢推进，{copy}", "前面被拼了字"),
            (f"（{copy}）", "被括号包住"),
            (f"{copy}。{copy}", "2 遍"),
        ):
            before = await _count(AssetProduction)
            with patch("app.api.assets._call_autoclip", _fake_autoclip(expand_prompt=shape)):
                again = await client.post(
                    "/api/assets/produce", json={"summary_ids": [sid], "n": 1}, headers=ho)
            assert again.json()["created"] == 1
            newest = (await _rows(AssetProduction))[-1]
            assert newest.seq == before + 1, "序号接着排"
            assert newest.drift is True, f"{shape[:20]} 判成没漂移 = 这道闸还是虚设"
            assert why in newest.drift_reason, newest.drift_reason

        # 合法引出（冒号引出、原句后接描述）不许误报——drift 提示一多一线就不看了
        # （引号引用那一型写在单测里，这里同一条文案出现两遍会命中"复制两遍"判据）
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt=f"【编号 7C0B3】\n旁白：{copy}，神情疲惫\n镜头2：远景")):
            clean = await client.post(
                "/api/assets/produce", json={"summary_ids": [sid], "n": 1}, headers=ho)
        assert (await _rows(AssetProduction))[-1].drift is False
        assert clean.json()["drifted"] == []

        export = await client.get(f"/api/assets/productions/export?asset_id={asset_id}&accounts=4", headers=ho)
        assert export.status_code == 200, export.text
        ex = export.json()
        assert ex["count"] == 6 == ex["ready"], "2 条改写 + 3 种漂移形态 + 1 条合法引出"
        drift_items = [i for i in ex["items"] if i["drift"]]
        assert len(drift_items) == 5 and all(i["drift_reason"] for i in drift_items)
        assert [i for i in ex["items"] if not i["drift"]][0]["drift_reason"] is None
        assert not {"capacity_hint", "board_capacity", "capacity"} & ex.keys(), \
            "免费导出只报真实生产单，不再返回产能/号池提示"

        # 重头再来：序号接着排，历史不覆盖（交付对账要能追到每一版）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            again = await client.post(
                "/api/assets/produce", json={"summary_ids": [sid], "n": 1, "expand": False}, headers=ho)
        assert again.json()["created"] == 1
        assert {r.seq for r in await _rows(AssetProduction)} == set(range(1, 8)), "序号接着排、历史不覆盖"

        # 展开服务挂掉：生产单仍建行但 prompt_text 为空 + error，不半途中止整单
        boom = await _make_ready_asset(client, hm, url="https://www.douyin.com/video/7499888777666555444")
        boom_items, _ = await _gen_and_list(boom[0], hm, client)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [_approvable(boom_items)["id"]], "action": "approve"}, headers=ho)
        with patch("app.api.assets._call_autoclip", _fake_autoclip(expand_error="AutoClip 502")):
            failed = await client.post(
                "/api/assets/produce", json={"summary_ids": [_approvable(boom_items)["id"]], "n": 3}, headers=ho)
        assert failed.status_code == 200, failed.text
        assert failed.json()["created"] == 0
        assert "502" in failed.json()["results"][0]["error"]
        assert await _count(AssetProduction) == 7, "展开失败不落半成品行（前面 happy path 的 7 条还在）"
        await client.aclose()

    _run(_scenario())


def test_produce_board_channel_validation_without_capacity_hint():
    """后台板口径的校验照旧；免费投产不返回容量提示，也不因投板量拒绝建单。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        # B-4：板上没有时长开关，写 15 只会给出错误的操作预期 → 400 并把实测回显
        wrong = await client.post(
            "/api/assets/produce", json={"summary_ids": [sid], "n": 1, "duration": 15}, headers=ho)
        assert wrong.status_code == 400
        assert "10.08" in wrong.json()["detail"] and "上集" in wrong.json()["detail"]

        # B-1：board_total 超接口上限（min1/max20），且提示两个量相乘
        over_total = await client.post(
            "/api/assets/produce", json={"summary_ids": [sid], "n": 1, "board_total": 21}, headers=ho)
        assert over_total.status_code == 400 and "board_total" in over_total.json()["detail"]

        # 编号只能来自取号工具：格式不对/重复一律 400，后端不代编
        bad_code = await client.post(
            "/api/assets/produce",
            json={"summary_ids": [sid], "n": 1, "hook_codes": ["7c0b"]}, headers=ho)
        assert bad_code.status_code == 400 and "五位" in bad_code.json()["detail"]
        dup_code = await client.post(
            "/api/assets/produce",
            json={"summary_ids": [sid], "n": 2, "hook_codes": ["7C0B1", "7C0B1"]}, headers=ho)
        assert dup_code.status_code == 400 and "重复" in dup_code.json()["detail"]

        # 不传编号也照常建单，但必须明示缺编号（导出三处都要带号）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            bare = await client.post(
                "/api/assets/produce", json={"summary_ids": [sid], "n": 1}, headers=ho)
        assert bare.status_code == 200, bare.text
        assert bare.json()["created"] == 1
        assert any("缺五位钩子编号" in w for w in bare.json()["warnings"])
        assert all(p["hook_code"] is None for p in (await client.get(
            f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"])

        # expand=false 的裸单不许投：没有推荐标题 → 板上 name 无从生成，必须给出警告
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            naked = await client.post(
                "/api/assets/produce", json={"summary_ids": [sid], "n": 1, "expand": False}, headers=ho)
        assert any("expand=false 的裸单不许投" in w for w in naked.json()["warnings"])

        # 免费投产不设软线：12 条板上量照常建单，响应不带任何容量提示。
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            heavy = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [sid], "n": 3, "board_total": 4}, headers=ho)
        assert heavy.status_code == 200, heavy.text
        heavy_body = heavy.json()
        assert heavy_body["created"] == 3
        assert heavy_body["board"]["tasks"] == 3
        assert heavy_body["board"]["board_total"] == 4
        assert heavy_body["board"]["planned_rows"] == 12
        assert not {"capacity_hint", "board_capacity", "capacity"} & heavy_body.keys(), heavy_body
        assert await _count(AssetProduction) == 5, "两条裸单 + 三条多版单都照常落库"
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  7. 产物  ─────────────────────────


def test_output_download_refuses_failed_qc():
    """产物下载：验收不合格 409（不静默交付）；合格才给 presigned 直链。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [_approvable(items)["id"]], "action": "approve"}, headers=h["admin"])
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/produce",
                              json={"summary_ids": [_approvable(items)["id"]], "n": 1}, headers=h["admin"])
        prod = (await _rows(AssetProduction))[0]

        async def _add(qc):
            oid = uuid.uuid4()
            async with dbmod.async_session_factory() as s:
                s.add(AssetOutput(
                    id=oid, production_id=prod.id, asset_id=uuid.UUID(asset_id),
                    kind="doubao_raw", file_key=f"asset-out/{oid}.mp4",
                    bucket=settings.MINIO_BUCKET_SLICED, file_name="成片.mp4",
                    qc_status=qc, qc_note="字幕压脸" if qc == "failed" else None,
                ))
                await s.commit()
            return oid

        bad = await _add("failed")
        denied = await client.get(f"/api/assets/outputs/{bad}/download", headers=hm)
        assert denied.status_code == 409, denied.text
        assert "验收不合格" in denied.json()["detail"]

        good = await _add("passed")
        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://minio:9000/presigned?X-Amz-Signature=deadbeef")) as presign:
            got = await client.get(f"/api/assets/outputs/{good}/download", headers=hm)
        assert got.status_code == 200, got.text
        assert got.json()["url"].startswith("http://minio")
        assert got.json()["file_name"] == "成片.mp4"
        assert presign.await_args.kwargs["as_attachment"] is True

        listed = await client.get("/api/assets/outputs", headers=hm)
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 2
        missing = await client.get(f"/api/assets/outputs/{uuid.uuid4()}/download", headers=hm)
        assert missing.status_code == 404
        await client.aclose()

    _run(_scenario())


def test_inline_preview_never_forces_download():
    """批 E：预览口 presign **不带 attachment**（否则 `<video>` 拿到就是存盘＝黑屏），
    且预览不是交付——不进审计、不点亮 `downloaded_at`；验收不合格的**照样能看**
    （下载口 409 是防把废片投出去，看一眼为什么废必须放行）。"""
    _run(_bootstrap())

    async def _scenario():
        from app.services import minio_service as msvc

        client, h = await _client_and_headers()
        hm = h["material"]

        # ──  机制层先把开关钉住：content-disposition 才是"浏览器存盘"的那一行 ──
        seen = {}

        def _fake_gen(_client, bucket, key, expires, method="GET", response_headers=None):
            seen["response_headers"] = response_headers
            return f"http://minio:9000/{bucket}/{key}?sig=1"

        with patch("app.services.minio_service._generate_presigned_url", _fake_gen), \
             patch("app.services.minio_service.get_external_minio_client", lambda: object()):
            await msvc.get_presigned_url("raw", "a.mp4", expires_seconds=60)
            assert seen["response_headers"] is None, "默认（预览）不该挂任何响应头覆盖"
            await msvc.get_presigned_url("raw", "a.mp4", expires_seconds=60, as_attachment=True)
            assert "attachment" in seen["response_headers"]["response-content-disposition"]

        # ──  文件素材原片预览：inline 外链、带时长/平台，供抽屉上栏显示 ──
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 45.5):
            up = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("原片.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
        assert up.status_code == 201, up.text
        aid = up.json()["items"][0]["id"]

        audit_before = await _count(AuditLog)
        presign = AsyncMock(return_value="http://minio:9000/raw/a.mp4?sig=2")
        with patch("app.api.assets.get_presigned_url", presign):
            got = await client.get(f"/api/assets/{aid}/source-preview", headers=hm)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["mode"] == "stored" and body["url"].endswith("sig=2")
        assert body["duration"] == 45.5 and body["file_name"] == "原片.mp4"
        assert presign.await_args.kwargs.get("as_attachment", False) is False, (
            "预览口只要带上 as_attachment 就退化成下载，播放器拿不到流——这条是批 E 的全部意义")
        assert body["note"] is None
        assert await _count(AuditLog) == audit_before, "预览只是看一眼，不该淹了交付审计"

        # 没落库的文件素材（file_key 空）→ 404，不给半截链接
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(aid))
            key = a.file_key
            a.file_key = None
            await s.commit()
        empty = await client.get(f"/api/assets/{aid}/source-preview", headers=hm)
        assert empty.status_code == 404 and "没有可预览的原文件" in empty.json()["detail"]
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(aid))
            a.file_key = key
            await s.commit()

        # ── ③ 链接素材：桶里没文件，如实回 external 并给出显式出口（不是死路） ──
        lid, _ = await _make_ready_asset(client, hm, url=DOUYIN_1)
        with patch("app.api.assets.get_presigned_url", AsyncMock(return_value="不该被调用")) as ps:
            ext = await client.get(f"/api/assets/{lid}/source-preview", headers=hm)
        assert ext.status_code == 200, ext.text
        assert ext.json()["mode"] == "external" and ext.json()["url"] is None
        assert ext.json()["source_url"] == DOUYIN_1 and ps.await_count == 0
        # 11-06 播放直链修复：external 的出口话术从「查时长/回源解析」统一成「取直链并播放」
        assert "取直链并播放" in ext.json()["note"]

        # ──  产物预览：废片也能看，且不点亮 downloaded_at ──
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [_approvable(items)["id"]], "action": "approve"},
                          headers=h["admin"])
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/produce",
                              json={"summary_ids": [_approvable(items)["id"]], "n": 1}, headers=h["admin"])
        prod = (await _rows(AssetProduction))[-1]

        async def _add(qc, with_file=True):
            oid = uuid.uuid4()
            async with dbmod.async_session_factory() as s:
                s.add(AssetOutput(
                    id=oid, production_id=prod.id, asset_id=uuid.UUID(asset_id),
                    kind="doubao_raw",
                    file_key=f"asset-out/{oid}.mp4" if with_file else None,
                    bucket=settings.MINIO_BUCKET_SLICED, file_name="成片.mp4",
                    duration=10.08, resolution="720x1280",
                    qc_status=qc, qc_note="字幕压脸" if qc == "failed" else None,
                ))
                await s.commit()
            return oid

        bad = await _add("failed")
        assert (await client.get(f"/api/assets/outputs/{bad}/download", headers=hm)).status_code == 409
        audit_before_out = await _count(AuditLog)
        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://minio:9000/sliced/x.mp4?sig=3")) as p2:
            pv = await client.get(f"/api/assets/outputs/{bad}/preview", headers=hm)
        assert pv.status_code == 200, pv.text
        assert pv.json()["qc_status"] == "failed" and pv.json()["qc_note"] == "字幕压脸", (
            "预览要把验收结论一起回，前端才能在播放器上方标红")
        assert pv.json()["resolution"] == "720x1280" and pv.json()["duration"] == 10.08
        assert p2.await_args.kwargs.get("as_attachment", False) is False
        out_row = await _row_of(AssetOutput, bad)
        assert out_row.downloaded_at is None, "看一眼不算交付，downloaded_at 不能被预览点亮"

        nofile = await _add(None, with_file=False)
        miss = await client.get(f"/api/assets/outputs/{nofile}/preview", headers=hm)
        assert miss.status_code == 404 and "没有可预览的文件" in miss.json()["detail"]
        assert (await client.get(f"/api/assets/outputs/{uuid.uuid4()}/preview", headers=hm)).status_code == 404
        assert await _count(AuditLog) == audit_before_out, "两个预览口都不写审计"
        await client.aclose()

    _run(_scenario())


def test_import_is_forbidden_for_publisher_role():
    """发布专员不参与素材采集链路（require_roles 挡在门口）。"""
    _run(_bootstrap())

    async def _scenario():
        async with dbmod.async_session_factory() as s:
            s.add(User(id=uuid.uuid4(), username="asset_pub", password_hash=get_password_hash(PASSWORD),
                       display_name="发布专员", role="publisher", data_scope="all", is_active=True))
            await s.commit()
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30)
        r = await client.post("/api/auth/login", json={"username": "asset_pub", "password": PASSWORD})
        assert r.status_code == 200, r.text
        hp = {"Authorization": f"Bearer {r.json()['access_token']}"}
        resp = await _import(client, hp, [DOUYIN_1])
        assert resp.status_code == 403, resp.text
        review = await client.post("/api/assets/summaries/review",
                                   json={"summary_ids": [], "action": "approve"}, headers=hp)
        assert review.status_code == 403
        anon = await client.get("/api/assets")
        assert anon.status_code == 401, "未登录一律 401"
        await client.aclose()

    _run(_scenario())


def test_batches_list_and_stage_progression():
    """批次列表 + 全链路阶段推进：draft → waiting_prompt → analyzing → awaiting_review → ready_to_produce。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        resp = await _import(client, hm, [DOUYIN_1, DOUYIN_2], name="11 月第一批")
        body = resp.json()
        batch_id = body["batch"]["id"]
        assert body["batch"]["name"] == "11 月第一批"
        assert body["batch"]["item_count"] == 2
        assert body["batch"]["budget_cap"] == settings.ASSET_BATCH_BUDGET_CAP

        batches = await client.get("/api/assets/batches", headers=hm)
        assert batches.status_code == 200, batches.text
        assert batches.json()["items"][0]["code"] == body["batch"]["code"]

        listed = await client.get(f"/api/assets?batch_id={batch_id}&page_size=10", headers=hm)
        assert listed.json()["total"] == 2
        assert all(i["summary_count"] == 0 and i["pending_review_count"] == 0 for i in listed.json()["items"])

        ids = [i["id"] for i in body["items"]]
        # 反推（mock 成功提交 → running）
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task",
                   AsyncMock(side_effect=lambda db, **kw: _fake_prompt_task())) as cpt:
            # A1-3：≥2 条是批量扣费，确认单没点（confirmed 缺省）就不许扣
            unconfirmed = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": ids, "max_duration": 60}, headers=hm)
            assert unconfirmed.status_code == 409, unconfirmed.text
            assert unconfirmed.json()["detail"]["code"] == "ASSET_COST_CONFIRM_REQUIRED"
            cpt.assert_not_awaited()

            an = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": ids, "max_duration": 60, "confirmed": True}, headers=hm)
        assert an.status_code == 200, an.text
        assert an.json()["estimate"]["total_cost"] == round(0.00054 * 60 * 2, 4)
        assert len(an.json()["results"]) == 2
        after = await client.get(f"/api/assets?batch_id={batch_id}", headers=hm)
        assert all(i["status"] == "analyzing" for i in after.json()["items"])
        assert all(i["prompt_max_duration"] == 60 for i in after.json()["items"])

        # 批次成本回填（按档位推算的额度，供与账单对账）
        batches_after = await client.get("/api/assets/batches", headers=hm)
        row = batches_after.json()["items"][0]
        assert row["cost_estimate"] == pytest.approx(0.0648, abs=1e-4)
        assert row["budget_gate"] == "ok"
        assert row["prompt_max_duration"] == 60

        # 伪造反推成功 → 出文案 → 审核 → 生产，看派生态一路走到 ready_to_produce
        from wechat_download.models import PT_SUCCESS, WechatDlPromptTask
        async with dbmod.async_session_factory() as s:
            for aid in ids:
                t = WechatDlPromptTask(id=uuid.uuid4(), source_type="url", source_url="x",
                                       provider_task_id="p", status=PT_SUCCESS, content=SCRIPT)
                s.add(t)
                a = await s.get(AssetItem, uuid.UUID(aid))
                a.prompt_task_id, a.stage_prompt = t.id, "success"
            await s.commit()
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            g = await client.post("/api/assets/summaries/generate", json={"asset_ids": ids}, headers=hm)
        assert [r["created"] for r in g.json()["results"]] == [3, 3]
        queue = await client.get("/api/assets/summaries?audit_status=pending", headers=h["admin"])
        rec = [i for i in queue.json()["items"] if i["is_recommended"]]
        assert len(rec) == 2 and {i["asset_id"] for i in rec} == set(ids)
        target = rec[0]["asset_id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [rec[0]["id"]], "action": "approve"}, headers=h["admin"])
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            p = await client.post("/api/assets/produce",
                                  json={"summary_ids": [rec[0]["id"]], "n": 2}, headers=h["admin"])
        assert p.json()["created"] == 2
        one = await client.get(f"/api/assets/{target}", headers=hm)
        st = one.json()["asset"]
        assert st["status"] in ("ready_to_produce", "composing")
        assert st["stage_produce"] == "pending"
        assert st["has_approved_copy"] is True
        assert st["summary_count"] == 3 and st["approved_count"] == 1
        assert st["pending_review_count"] == 2 and st["production_count"] == 2
        assert len(one.json()["productions"]) == 2
        assert len(one.json()["summaries"]) == 3

        # 同批另一条没被审 → 派生态停在待审，两条素材各走各的阶段（批量 ≠ 一刀切）
        other = await client.get(f"/api/assets/{(set(ids) - {target}).pop()}", headers=hm)
        assert other.json()["asset"]["status"] == "awaiting_review"
        assert other.json()["asset"]["approved_count"] == 0
        assert other.json()["asset"]["production_count"] == 0
        await client.aclose()

    _run(_scenario())


# ─────────────────────────  8. 审核闭环（批2：A2-1～A2-4）  ─────────────────────────


async def _write_lexicon(value):
    """把风险词表覆盖写进 system_config 并**清缓存**（TTL 300s，不清测不到热更）。"""
    from app.api import assets as assets_api

    async with dbmod.async_session_factory() as s:
        row = await s.get(SystemConfig, "asset_risk_lexicon")
        if row is None:
            s.add(SystemConfig(key="asset_risk_lexicon", value=value, description="test override"))
        else:
            row.value = value
        await s.commit()
    assets_api._RISK_CACHE["at"], assets_api._RISK_CACHE["payload"] = 0.0, None


def test_approve_is_actually_gated_and_admin_waiver_is_audited():
    """A2-1 + R-6：block 风险词 approve **真的拦**，一致性对不上**只是预警**；
    豁免只有 admin 能用、可用 `waive_codes` 只放某几类，豁免逐条进审计。

    改前的行为是"只记录不拦"——risk_hit 非空照样过审、照样投产，审核台等于橡皮章。
    R-6 又把一致性从硬闸降成预警：专名靠白名单抽、天然误报，拿它卡人的结果是一线
    逢人名钩子必找 admin 豁免，而豁免不分类型 → 同条里的真违禁词被一起放过。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        risky = _risky(items)
        bad_consist = next(i for i in items if i["consistency_ok"] is False)

        refused = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve"}, headers=ho)
        row = refused.json()["results"][0]
        assert row["ok"] is False and row["error_code"] == "ASSET_RECHECK_FAILED"
        assert "根治" in row["error"]
        rows = {str(r.id): r for r in await _rows(AssetSummary)}
        assert rows[risky["id"]].audit_status == RV_PENDING, "拦下必须留在待审，不许偷偷改态"

        # R-6：一致性对不上**不再拦过审**（专名白名单天然误报，硬拦只会训练一线找 admin
        # 豁免，一豁免就连真违禁词一起放过）。现在它是预警：能过、但当场回显并落两列留痕。
        passed_warn = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [bad_consist["id"]], "action": "approve"}, headers=ho)
        w = passed_warn.json()["results"][0]
        assert w["ok"] is True and w["waived"] is False, "一致性预警不该算管理员豁免"
        assert {p["code"] for p in w["warnings"]} == {"consistency"}
        assert "对不上" in "；".join(p["message"] for p in w["warnings"])
        assert "预警" in passed_warn.json()["message"]
        rows = {str(r.id): r for r in await _rows(AssetSummary)}
        assert rows[bad_consist["id"]].audit_status == RV_APPROVED
        assert rows[bad_consist["id"]].consistency_ok is False, "不拦人，但留痕列必须照实落库"

        # 豁免只对 admin 生效：operator 带理由也照样拦
        op_waive = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve", "waive_reason": "剧情需要"}, headers=ho)
        assert op_waive.json()["results"][0]["ok"] is False

        # R-6 分粒度：`waive_codes` 只点名 shape 时，risk 拦点照旧拦（防"一句理由全放行"）
        partial = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve",
                  "waive_reason": "先只放字数", "waive_codes": ["shape"]}, headers=ha)
        p1 = partial.json()["results"][0]
        assert p1["ok"] is False and {x["code"] for x in p1["problems"]} == {"risk"}, (
            "只豁免 shape 就不该顺手把违禁词一起放过"
        )
        assert "risk" in p1["waivable_codes"]

        ok = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve", "waive_reason": "剧情必需，已确认平台可过"},
            headers=ha)
        assert ok.json()["results"][0]["ok"] is True and ok.json()["results"][0]["waived"] is True
        audits = await _rows(AuditLog, AuditLog.action == "asset.summary_review.approve")
        waived = audits[-1].after["waived"]
        assert waived["reason"] == "剧情必需，已确认平台可过"
        assert any(p["code"] == "risk" for p in waived["problems"]), "豁免了也要留住拦下的东西"

        # 投产前再复核一遍：同一条带 block 词的文案，不带理由投不进
        plain = await client.post(
            "/api/assets/produce", json={"summary_ids": [risky["id"]], "n": 1}, headers=ha)
        assert plain.json()["created"] == 0
        assert plain.json()["results"][0]["error_code"] == "ASSET_RECHECK_FAILED"
        assert plain.json()["recheck_failed"], "响应要当场回显拦了几条，别让前端去翻审计"
        assert await _count(AssetProduction) == 0

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            waived_prod = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [risky["id"]], "n": 1, "waive_reason": "同上，管理员已确认"}, headers=ha)
        assert waived_prod.json()["created"] == 1, waived_prod.json()["results"]
        assert len(waived_prod.json()["recheck_waived"]) == 1
        prod_audit = (await _rows(AuditLog, AuditLog.action == "asset.produce_order"))[-1]
        assert prod_audit.after["recheck_waived"][0]["summary_id"] == risky["id"]
        # 模型展开后提示词里也带着「根治」（原样包进去了）→ 展开侧复扫同样留痕
        assert prod_audit.after["recheck_waived"][0]["waived"].get("prompt_problems"), (
            "豁免是整条文案的豁免，展开侧新加的风险词也必须挂在这条豁免记录上"
        )
        await client.aclose()

    _run(_scenario())


def test_revoking_approval_supersedes_orders_and_bans_export():
    """A2-2：撤销过审 → 关联未投递单置 superseded、导出正文不外泄；重生成前先断言没有连坐删单。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        clean = _approvable(items)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [clean["id"]], "action": "approve"}, headers=ha)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post(
                "/api/assets/produce", json={"summary_ids": [clean["id"]], "n": 2}, headers=ha)
        assert made.json()["created"] == 2

        exp = await client.get(f"/api/assets/productions/export?asset_id={asset_id}", headers=ha)
        assert exp.json()["count"] == 2 and exp.json()["blocked_count"] == 0
        assert all(i["prompt_text"] for i in exp.json()["items"])

        # 撤销过审（approved→rejected）：单不能继续被当成品导出去投
        revoked = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [clean["id"]], "action": "reject", "reason": "复核后发现台词不对"}, headers=ha)
        assert revoked.json()["results"][0]["superseded_productions"] == 2
        prows = await _rows(AssetProduction)
        assert all(r.status == "superseded" for r in prows)
        sup_audit = (await _rows(AuditLog, AuditLog.action == "asset.production.supersede"))
        assert len(sup_audit) == 2 and "台词不对" in sup_audit[0].after["reason"]

        after = await client.get(f"/api/assets/productions/export?asset_id={asset_id}", headers=ha)
        assert after.json()["count"] == 2 and after.json()["blocked_count"] == 2
        assert all(i["prompt_text"] is None and i["exportable"] is False for i in after.json()["items"])
        assert len(after.json()["blocked"]) == 2
        assert all("撤销" in b["reason"] for b in after.json()["blocked"]), "挡下的成因要当场可见"

        # 覆盖重生成：候选挂着生产单（含作废单）→ 必须拒绝，不能 FK CASCADE 静默删单
        boom = await client.post(
            "/api/assets/summaries/generate",
            json={"asset_ids": [asset_id], "overwrite": True}, headers=ha)
        assert boom.status_code == 200
        refused_row = boom.json()["results"][0]
        assert refused_row["created"] == 0 and "连坐删单" in refused_row["error"]
        assert await _count(AssetSummary) == 3, "拒绝必须真的没删"

        # 清理掉作废单以后（这里直接删行模拟人工处理），才允许覆盖重生成，且删除本身留痕
        async with dbmod.async_session_factory() as s:
            for r in await s.execute(select(AssetProduction)):
                await s.delete(r[0])
            await s.commit()
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            again = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "overwrite": True},
                headers=ha)
        assert again.status_code == 200, again.text
        deletes = await _rows(AuditLog, AuditLog.action == "asset.summary.delete")
        assert len(deletes) == 3, "三条旧候选都要有删除留痕"
        await client.aclose()

    _run(_scenario())


def test_risk_lexicon_is_operationally_hot_swappable():
    """A2-3：词表迁到 system_config，加词/配豁免**不发版生效**；produce 对展开后的提示词复扫。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        clean = _approvable(items)
        assert "翻脸" in clean["text"]

        # 默认表里没有「翻脸」→ 能过
        first = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [clean["id"]], "action": "approve"}, headers=ho)
        assert first.json()["results"][0]["ok"] is True

        # 撤销 + 加词：同一个词现在成了 block 级 → 复核真的会拦（改的是配置，不是代码）
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [clean["id"]], "action": "reject", "reason": "先加词"}, headers=ho)
        await _write_lexicon({"block": ["翻脸"]})
        blocked = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [clean["id"]], "action": "approve"}, headers=ho)
        assert blocked.json()["results"][0]["ok"] is False
        assert "翻脸" in blocked.json()["results"][0]["error"]

        # 配豁免正则：「当场翻脸」是剧情动作，不算风险 → 放行
        await _write_lexicon({"block": ["翻脸"], "exempt": {"翻脸": "当场翻脸"}})
        passed = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [clean["id"]], "action": "approve"}, headers=ho)
        assert passed.json()["results"][0]["ok"] is True, passed.text

        # inherit=false 才整体替换：默认表的「根治」不再拦（运营要把口径收窄时用的开关）
        await _write_lexicon({"block": ["翻脸"], "exempt": {"翻脸": "当场翻脸"}, "inherit": False})
        risky = _risky(items)
        loose = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve"}, headers=ho)
        assert loose.json()["results"][0]["ok"] is True, loose.text

        # produce 复扫：过审文案是干净的，但**模型在提示词里自己加了 block 词** → 整条不生成单
        await _write_lexicon({"block": ["血流成河"]})
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt="镜头1：街头血流成河，王总站在康华医院门口")):
            rescan = await client.post(
                "/api/assets/produce", json={"summary_ids": [clean["id"]], "n": 2}, headers=ho)
        assert rescan.json()["created"] == 0
        assert rescan.json()["results"][0]["error_code"] == "ASSET_EXPAND_RECHECK_FAILED"
        assert await _count(AssetProduction) == 0, "展开侧命中要整条不落半成品行"
        await client.aclose()

    _run(_scenario())


def test_export_and_download_leave_delivery_trail_and_are_visible_to_all():
    """A2-4：导出/下载写审计 + 回写 downloaded_at；11-03 起交付读口**不分可见范围**
    （旧口径下 operator 看不见别人导入素材的产物，只能借导入人账号下载，审计就记成别人）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        clean = _approvable(items)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [clean["id"]], "action": "approve"}, headers=h["admin"])
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/produce",
                              json={"summary_ids": [clean["id"]], "n": 1}, headers=h["admin"])
        prod = (await _rows(AssetProduction))[0]

        exported = await client.get(f"/api/assets/productions/export?asset_id={asset_id}", headers=h["admin"])
        exp_audit = (await _rows(AuditLog, AuditLog.action == "asset.production.export"))[-1]
        assert exp_audit.after["exported"] == exported.json()["count"] == 1

        oid = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetOutput(
                id=oid, production_id=prod.id, asset_id=uuid.UUID(asset_id),
                kind="composed", file_key=f"asset-out/{oid}.mp4", bucket=settings.MINIO_BUCKET_SLICED,
                file_name="成片.mp4", qc_status="passed",
            ))
            await s.commit()

        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://minio:9000/presigned?X-Am-Signature=x")):
            got = await client.get(f"/api/assets/outputs/{oid}/download", headers=hm)
        assert got.status_code == 200, got.text
        assert got.json()["downloaded_at"]
        dl_audit = (await _rows(AuditLog, AuditLog.action == "asset.output.download"))[-1]
        assert dl_audit.after["first_download"] is True and dl_audit.after["file_key"]
        async with dbmod.async_session_factory() as s:
            out = await s.get(AssetOutput, oid)
            assert out.downloaded_at is not None, "presigned 发出去了就要回写，否则交付页看不出来谁拿过"

        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://minio:9000/presigned?x=1")):
            await client.get(f"/api/assets/outputs/{oid}/download", headers=hm)
        second = (await _rows(AuditLog, AuditLog.action == "asset.output.download"))[-1]
        assert second.after["first_download"] is False

        # 交付读口对全员开放（取消隔离）：别人导入的素材，产物也看得见、下得着
        listed = await client.get("/api/assets/outputs", headers=ho)
        assert [i["id"] for i in listed.json()["items"]] == [str(oid)], "运营看得见这条产物"
        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://minio:9000/presigned?x=2")):
            cross = await client.get(f"/api/assets/outputs/{oid}/download", headers=ho)
        assert cross.status_code == 200, cross.text
        third = (await _rows(AuditLog, AuditLog.action == "asset.output.download"))[-1]
        assert str(third.operator_id) == str((await _rows(User, User.username == OPERATOR_USER))[0].id), \
            "谁下载就记谁，不再需要借导入人的账号"
        missing = await client.get(f"/api/assets/outputs/{uuid.uuid4()}/download", headers=ho)
        assert missing.status_code == 404, "不存在仍然是 404"
        await client.aclose()

    _run(_scenario())


def test_export_txt_and_board_payload_are_directly_usable():
    """A3-1：format=txt 给「段头+正文+推荐标题+产出清单」整块，format=payload 给七键 create 体。

    这两块是 P0 的交付终点（投板属 P1），所以断言按「拿来就能投」的口径钉：
    键序、reqID 与生产单 id 的绑定、date 的完整时间戳、picDatas 的纯 base64。
    """
    import base64 as b64mod
    import re as _re

    _run(_bootstrap())
    CARD_BYTES = b"\xff\xd8\xff\xe0fake-jpeg"

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        copy = _approvable(items)["text"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 2, "board_total": 2, "board_tag": "ben",
                "hook_codes": ["7C0B3", "7C0B4"], "character_card_key": "cards/7c0b3.jpg",
                "recommended_title_count": 2,
            }, headers=ho)
        assert made.status_code == 200, made.text
        assert made.json()["created"] == 2

        base = f"/api/assets/productions/export?asset_id={asset_id}&accounts=4"
        plain = await client.get(base, headers=ho)
        assert plain.json()["format"] == "json"
        assert "export_text" not in plain.json() and "payloads" not in plain.json(), "默认形态零变化"
        bad = await client.get(f"{base}&format=docx", headers=ho)
        assert bad.status_code == 400 and "json / txt / payload" in bad.json()["detail"]

        txt = await client.get(f"{base}&format=txt", headers=ho)
        body = txt.json()
        assert body["delivery_count"] == 2 and body["excluded"] == 0
        text = body["export_text"]
        assert "=== 7C0B3 ===" in text and "=== 7C0B4 ===" in text, "段头带五位编号"
        assert copy in text, "正文里就是过审原句（drift=False 的单）"
        assert "1. 标题1（7C0B3）" in text and "2. 标题2（7C0B4）" in text, "编号补在推荐标题尾部"
        assert "跳过任何二次确认" in text.split("不要贴进豆包对话")[1], "投放要求只进 txt（B-9）"
        manifest = body["manifest"]
        assert manifest.startswith("产出清单") and "7C0B3｜标题1" in manifest, "第三处编号"

        with patch("app.api.assets.download_file", AsyncMock(return_value=CARD_BYTES)) as dl:
            pay = await client.get(f"{base}&format=payload", headers=ho)
        payloads = pay.json()["payloads"]
        assert pay.json()["delivery_count"] == 2
        assert [tuple(x["payload"].keys()) for x in payloads] == [svc.BOARD_PAYLOAD_KEYS] * 2
        assert dl.await_count == 1, "同剧同卡：一张卡只从 MinIO 取一次"
        first, second = payloads
        assert first["payload"]["reqID"] == first["id"], "reqID 钉在生产单 id 上（重复导出不换号）"
        assert first["payload"]["total"] == 2 and first["payload"]["tag"] == "ben"
        assert _re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", first["payload"]["date"]), (
            "完整时间戳：只写日期会 succ 但永久查不到"
        )
        assert first["payload"]["name"] == "标题1" and copy in first["payload"]["prompt"]
        assert first["payload"]["picDatas"] == [b64mod.b64encode(CARD_BYTES).decode()], "纯 base64，无 data: 前缀"
        assert first["payload"]["picDatas"] == second["payload"]["picDatas"], "每条都自带卡，不做引用"
        assert first["warnings"] == [] and second["warnings"] == []
        assert "未缩放" in pay.json()["card_advisory"]

        # 没挂角色卡 / 读不到卡：payload 照给（七键结构不能缺），但必须点名
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            nocard = await client.post("/api/assets/produce",
                                       json={"summary_ids": [sid], "n": 1}, headers=ho)
        assert nocard.json()["created"] == 1
        with patch("app.api.assets.download_file", AsyncMock(side_effect=RuntimeError("MinIO 503"))):
            p2 = (await client.get(f"{base}&format=payload", headers=ho)).json()["payloads"]
        loose = [x for x in p2 if x["seq"] == 3][0]
        assert loose["payload"]["picDatas"] == []
        assert any("没挂角色卡" in w or "读取失败" in w for w in loose["warnings"]), loose["warnings"]

        # 与 items 同一道闸：撤销过审 → 作废单不进 txt/payload（不给第二条出口）
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "reject", "reason": "换个角度重看"}, headers=ho)
        after = (await client.get(f"{base}&format=txt", headers=ho)).json()
        assert after["delivery_count"] == 0 and after["export_text"] == "" and after["manifest"] is None
        assert after["excluded"] == 3, "作废/裸单全部挡在交付块外面，但 items 里状态照实回显"
        assert [i["exportable"] for i in after["items"]] == [False, False, False]

        fmt_audit = (await _rows(AuditLog, AuditLog.action == "asset.production.export"))[-1]
        assert fmt_audit.after["format"] == "txt", "拿走的是哪种交付形态也要能回溯"
        await client.aclose()

    _run(_scenario())


def test_export_rescans_current_risk_lexicon_and_admin_can_force():
    """R-4（D-2 拍板）：导出是存量单**唯一**还会碰到当前词表的时刻，所以必须重扫。

    钉五件事：
    1. 过审之后运营新加的禁词，会把**已经建好的**生产单在导出口拦下来（不重扫＝新词管不到存量单）；
    2. 拦下来是「置灰 + 正文不给」，txt/payload 里同样不出现（不给第二条出口）；
    3. 放行只有 admin，而且必须带理由（素材专员/运营都踩不动这道闸）；
    4. 放行后命中信息照实回显（哪几张被点过名、哪几张是放行的），不是当没发生过；
    5. 谁放行的、放了哪几张、凭什么，进审计。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        good = _approvable(items)
        sid, copy = good["id"], good["text"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce",
                                     json={"summary_ids": [sid], "n": 1}, headers=ho)
        assert made.status_code == 200 and made.json()["created"] == 1, made.text
        pid = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"][0]["id"]

        base = f"/api/assets/productions/export?asset_id={asset_id}"
        # 默认词表下这张单是干净的（投产当场也复扫过），导出正常给正文
        before = await client.get(f"{base}&format=txt", headers=ho)
        assert before.json()["delivery_count"] == 1 and copy in before.json()["export_text"]
        assert before.json()["risk_recheck"]["hit_count"] == 0

        # 过审之后加词：这条文案里有的词（「翻脸」）现在算 block 级
        added = await client.put("/api/assets/risk-lexicon",
                                 json={"block": ["翻脸"], "inherit": True}, headers=ha)
        assert added.status_code == 200, added.text

        # ①②存量单在导出口被新词拦下：正文置空、txt 里也不出现
        after = await client.get(f"{base}&format=txt", headers=ho)
        body = after.json()
        assert body["delivery_count"] == 0 and body["export_text"] == "", "命中行不进交付块"
        assert body["risk_recheck"]["hit_count"] == 1
        assert body["risk_recheck"]["blocked"] == [pid] and body["risk_recheck"]["forced"] == []
        row = [i for i in body["items"] if i["id"] == pid][0]
        assert row["exportable"] is False and row["prompt_text"] is None
        assert [x["word"] for x in row["risk_hits"]] == ["翻脸"], row["risk_hits"]
        assert row["risk_hits"][0]["level"] == "block"
        assert "词表被改过" in body["blocked"][0]["reason"] and "翻脸" in body["blocked"][0]["reason"]

        # warn 级不拦：词表里降级成 warn 后放行，级别口径不能靠导出侧偷偷收紧
        await client.put("/api/assets/risk-lexicon",
                         json={"block": [], "warn": ["翻脸"], "inherit": True}, headers=ha)
        demoted = await client.get(base, headers=ho)
        assert demoted.json()["risk_recheck"]["hit_count"] == 0 and demoted.json()["blocked_count"] == 0

        await client.put("/api/assets/risk-lexicon",
                         json={"block": ["翻脸"], "inherit": True}, headers=ha)

        # ③放行闸门：角色 + 理由，两个都不能少
        by_operator = await client.get(f"{base}&force_risk=true&force_reason=语境需要", headers=ho)
        assert by_operator.status_code == 403, by_operator.text
        no_reason = await client.get(f"{base}&force_risk=true", headers=ha)
        assert no_reason.status_code == 400 and "force_reason" in no_reason.json()["detail"]

        # ④admin 带理由放行：正文回来、命中信息照实回显，delivery 块也带上
        forced = await client.get(
            f"{base}&format=txt&force_risk=true&force_reason=该片语境里不构成承诺，与运营已确认", headers=ha)
        assert forced.status_code == 200, forced.text
        fb = forced.json()
        assert fb["delivery_count"] == 1 and copy in fb["export_text"], "放行的单子要真的能用"
        frow = [i for i in fb["items"] if i["id"] == pid][0]
        assert frow["exportable"] is True and frow["prompt_text"] and copy in frow["prompt_text"]
        assert frow["risk_forced"] is True and [x["word"] for x in frow["risk_hits"]] == ["翻脸"], (
            "放行不等于没命中：页面上还得看得见这张被点过名"
        )
        assert fb["risk_recheck"]["forced"] == [pid] and fb["risk_recheck"]["blocked"] == []
        assert "已确认" in fb["risk_recheck"]["forced_reason"]

        # ⑤审计：放行记录单独成块，事后能回答「谁放的、放的哪几张、凭什么」
        audit = (await _rows(AuditLog, AuditLog.action == "asset.production.export"))[-1]
        rec = audit.after["risk_recheck"]
        assert rec["hits"] == {pid: ["翻脸"]} and rec["forced_ids"] == [pid]
        assert rec["blocked_ids"] is None and "不构成承诺" in rec["forced_reason"]

        # 还原默认表，别让这条加词影响同文件后面的用例
        await client.put("/api/assets/risk-lexicon", json={"block": [], "inherit": True}, headers=ha)
        await client.aclose()

    _run(_scenario())


# ────────────────────────  11. 投递状态回写与成功/失败计数（11-03 拍板第 4 条）  ────────────────────────


def test_production_status_writeback_and_dispatch_counts():
    """`POST /assets/productions/status` 钉六件事：
    只有 operator/admin 改得动台账、系统态与非法迁移拒写、id 缺失整批不落库、
    board_tid 不许批量传、素材 produce 阶段按本素材**全部单**收敛（不照抄最后一次回写）、
    `dispatch` 计数不跟着 `status=` 筛选跑（筛失败时更要看得见成功了几条）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        # 4 张单：0 投上板、1 成功改成失败、2 成功、3 留在未投（结尾拿它验撤审作废）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [sid], "n": 4, "recommended_title_count": 4,
                      "hook_codes": ["7C0B1", "7C0B2", "7C0B3", "7C0B4"]},
                headers=ho)
        assert made.status_code == 200, made.text
        body = made.json()
        by_seq = {i["seq"]: i["id"] for i in (await client.get(
            f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"]}
        ids = [by_seq[1], by_seq[2], by_seq[3], by_seq[4]]

        # 建单当场就有数：四条全是 order_ready，号池今天一条没吃
        disp = body["dispatch"]
        assert disp["by_status"] == {"order_ready": 4} and disp["dispatched"] == 0
        assert disp["success_rate"] is None, "没有终态时回 None，不是 0——0 会被读成一条都没成"
        assert disp["today"]["dispatched"] == 0 and disp["today"]["board_rows"] == 0

        # 权限：素材专员改不动生产台账（与「生产者不得自审」同一条纪律）
        forbidden = await client.post("/api/assets/productions/status",
                                      json={"ids": [ids[0]], "status": "queued"}, headers=hm)
        assert forbidden.status_code == 403, forbidden.text

        # 目标态只认四个；系统态从外部写进来＝人手改台账
        bad_state = await client.post("/api/assets/productions/status",
                                      json={"ids": [ids[0]], "status": "superseded"}, headers=ho)
        assert bad_state.status_code == 400 and "系统态" in bad_state.json()["detail"]

        # 判失败必须写成因（板上失败行没有原因字段，空着事后无从对账）
        no_reason = await client.post("/api/assets/productions/status",
                                      json={"ids": [ids[0]], "status": "failed"}, headers=ho)
        assert no_reason.status_code == 400 and "error" in no_reason.json()["detail"]

        # 有假 id → 整批不落库：台账说改了 4 条就必须 4 条都改了
        ghost = str(uuid.uuid4())
        mixed = await client.post("/api/assets/productions/status",
                                  json={"ids": ids + [ghost], "status": "queued"}, headers=ho)
        assert mixed.status_code == 400 and "整批未回写" in mixed.json()["detail"]
        for pid in ids:
            assert (await _row_of(AssetProduction, pid)).status == "order_ready"
        asset = await _row_of(AssetItem, asset_id)
        assert asset.stage_produce == "pending" and asset.status == "ready_to_produce"

        # board_tid 是逐条回读主键，多条传会把 20 条钉成同一个 tid
        tid_many = await client.post(
            "/api/assets/productions/status",
            json={"ids": ids[:2], "status": "queued", "board_tid": "T-1"}, headers=ho)
        assert tid_many.status_code == 400 and "逐条" in tid_many.json()["detail"]

        # 正常：第 1 条投上板。回写口也必须锁住旧状态，不能与删单/回收竞态覆盖。
        from sqlalchemy import event
        from sqlalchemy.sql import Select
        status_locks = []

        def capture_status_select(state):
            statement = state.statement
            if isinstance(statement, Select) and AssetProduction.__tablename__ in str(statement):
                status_locks.append(getattr(statement, "_for_update_arg", None))

        session_class = dbmod.async_session_factory.class_.sync_session_class
        event.listen(session_class, "do_orm_execute", capture_status_select)
        try:
            q = await client.post("/api/assets/productions/status",
                                  json={"ids": [ids[0]], "status": "queued", "board_tid": "T-9001"}, headers=ho)
        finally:
            event.remove(session_class, "do_orm_execute", capture_status_select)
        assert any(arg is not None for arg in status_locks), "状态回写读取旧状态必须加行锁"
        assert q.status_code == 200, q.text
        assert q.json()["updated"] == 1 and q.json()["results"][0]["attempts"] == 1
        first_row = await _row_of(AssetProduction, ids[0])
        assert first_row.status == "queued" and first_row.attempts == 1
        assert first_row.started_at is not None and first_row.board_tid == "T-9001"
        asset = await _row_of(AssetItem, asset_id)
        assert asset.stage_produce == "running" and asset.status == "producing"
        disp = q.json()["dispatch"]
        assert disp["dispatched"] == 1 and disp["order_ready"] == 3
        assert disp["today"]["dispatched"] == 1 and disp["today"]["board_rows"] == 1, "未投的单不吃号池"

        # 补报：一线常常投完直接来报结果（order_ready → success 也收），
        # 但素材阶段**不跟着变成成功**——还有在投的、还有没投的
        late = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[1], ids[2]], "status": "success"}, headers=ho)
        assert late.status_code == 200, late.text
        assert late.json()["updated"] == 2
        asset = await _row_of(AssetItem, asset_id)
        assert asset.stage_produce == "running", "阶段按本素材全部单重算：还有未收的就别写完成"
        assert asset.status == "producing"
        assert (await _row_of(AssetProduction, ids[2])).completed_at is not None

        # 同态重报＝幂等：不改字段、不重算阶段，attempts 也不会被连点两次加上去
        again = await client.post("/api/assets/productions/status",
                                  json={"ids": [ids[0]], "status": "queued"}, headers=ho)
        assert again.status_code == 200 and again.json()["updated"] == 0
        assert again.json()["unchanged"] == [ids[0]]
        assert (await _row_of(AssetProduction, ids[0])).attempts == 1

        # 非法迁移：running 不能退回 queued（要重投先报 failed 再 queued）
        assert (await client.post("/api/assets/productions/status",
                                  json={"ids": [ids[0]], "status": "running"}, headers=ho)).status_code == 200
        illegal = await client.post("/api/assets/productions/status",
                                    json={"ids": [ids[0]], "status": "queued"}, headers=ho)
        assert illegal.status_code == 200 and illegal.json()["updated"] == 0
        assert "不允许从 running 直接到 queued" in illegal.json()["blocked"][0]["reason"]

        # 成片回收后发现不可用：success → failed 是唯一允许的改判，且必须带成因
        flip = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[1]], "status": "failed", "error": "首帧整片黑屏，判定不可用"}, headers=ho)
        assert flip.status_code == 200 and flip.json()["updated"] == 1
        flipped = await _row_of(AssetProduction, ids[1])
        assert flipped.status == "failed" and flipped.error.startswith("首帧整片黑屏")

        # 计数不跟筛选跑：筛 failed 时成功数还在页面上
        listed = await client.get(
            f"/api/assets/productions?asset_id={asset_id}&status=failed", headers=ho)
        assert len(listed.json()["items"]) == 1 and listed.json()["total"] == 1
        d = listed.json()["dispatch"]
        assert d["by_status"] == {"running": 1, "success": 1, "failed": 1, "order_ready": 1}
        assert d["succeeded"] == 1 and d["failed"] == 1 and d["success_rate"] == 0.5
        assert d["today"]["tasks"] == 3, "在投/成功/失败都算今日真实投放，未投的不算"
        # 序列化把台账三列吐出来，前端不用为了一次「投了几次」再打一条接口
        listed_all = await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=ho)
        row0 = [x for x in listed_all.json()["items"] if x["id"] == ids[0]][0]
        assert row0["attempts"] == 1 and row0["started_at"] and row0["status"] in PRODUCTION_STATES

        # 撤审作废**未投递**与**投失败**那两张（A2-2 + R-5：失败单留着只会被「重投」复活成可导出）；
        # 已投上板还没回结果的（running）是既成事实，不抹号池当日量
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "reject", "reason": "角度不对"}, headers=ho)
        assert (await _row_of(AssetProduction, ids[3])).status == "superseded"
        assert (await _row_of(AssetProduction, ids[1])).status == "superseded", (
            "R-5：failed 单撤审时一并作废，否则一线报一次「失败重投」就把它送回可导出集"
        )
        assert (await _row_of(AssetProduction, ids[0])).status == "running"
        after_revoke = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[3]], "status": "success"}, headers=ho)
        assert after_revoke.status_code == 200 and after_revoke.json()["updated"] == 0
        assert "作废" in after_revoke.json()["blocked"][0]["reason"]
        d2 = after_revoke.json()["dispatch"]
        assert d2["by_status"] == {"running": 1, "success": 1, "superseded": 2}
        assert d2["dispatched"] == 3 and d2["today"]["dispatched"] == 3, "作废不该把已投的量抹成没投"

        logs = await _rows(AuditLog, AuditLog.action == "asset.production_status")
        assert logs, "改台账必须留痕"
        assert logs[0].before["from"][ids[0]] == "order_ready"
        assert logs[0].after["to"] == "queued" and logs[0].after["board_tid"] == "T-9001"
        assert logs[-1].after["blocked"][0]["id"] == ids[3]

        # ── R-5 第二条路：撤审那一刻单还在板上（running，按口径不动）→ 随后改判 failed →
        #    再想「失败重投」。这一跳不看文案审核态就能把撤审的稿子送回可导出集，必须挡住。
        revive = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[0]], "status": "failed", "error": "回收判不可用"}, headers=ho)
        assert revive.status_code == 200 and revive.json()["updated"] == 1, revive.text
        retry = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[0]], "status": "queued"}, headers=ho)
        assert retry.status_code == 200 and retry.json()["updated"] == 0
        assert "已不是过审状态" in retry.json()["blocked"][0]["reason"], retry.json()["blocked"]
        assert (await _row_of(AssetProduction, ids[0])).status == "failed", "被挡下就一个字都不改"

        # 文案重新过审后，同一张失败单恢复可重投（挡的是状态，不是把单子焊死）
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        ok_retry = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[0]], "status": "queued"}, headers=ho)
        assert ok_retry.json()["updated"] == 1, ok_retry.json()

        await client.aclose()

    _run(_scenario())


def test_dispatch_today_counts_uses_board_rows_not_row_count():
    """`dispatch.today` 的单位钉在「号池吃掉的条数」（Σ board_total），不是生产单行数。

    一张板 `total=3` 就是 3 条。统计只保留真实任务数、板上条数和状态分布，
    不再返回软线、超线或提示文案。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [sid], "n": 1, "board_total": 3,
                      "hook_codes": ["7C0B1"]}, headers=ho)
        assert made.status_code == 200, made.text
        assert made.json()["created"] == 1
        row = (await client.get(
            f"/api/assets/productions?asset_id={asset_id}", headers=ho
        )).json()["items"][0]
        pid = row["id"]
        assert row["board_total"] == 3, "板上 total＝同一条出 3 版 → 号池吃 3 条"

        # 没投上板：当日任务数/板上条数都是 0，且不带软线字段。
        t0 = made.json()["dispatch"]["today"]
        assert t0["tasks"] == 0 and t0["board_rows"] == 0
        assert not {"soft_cap", "over_cap", "note"} & t0.keys(), t0

        st = await client.post("/api/assets/productions/status",
                               json={"ids": [pid], "status": "queued"}, headers=ho)
        assert st.status_code == 200, st.text
        t1 = st.json()["dispatch"]["today"]
        assert t1["tasks"] == 1, "行数＝1 张板"
        assert t1["board_rows"] == 3, "号池吃掉的是 Σ total＝3 条"
        assert t1["by_status"] == {"queued": 1}, "状态统计仍保留"
        assert not {"soft_cap", "over_cap", "note"} & t1.keys(), t1

        # 列表口同一套数（不跟 status= 筛选走），也不再带软线字段。
        lst = await client.get("/api/assets/productions?status=queued", headers=ho)
        today = lst.json()["dispatch"]["today"]
        assert today["tasks"] == 1 and today["board_rows"] == 3
        assert not {"soft_cap", "over_cap", "note"} & today.keys(), today
        await client.aclose()

    _run(_scenario())


def test_autoclip_timeout_chain_and_single_inner_retry():
    """超时口径钉成契约：外层等得比内层久，且内层只试一次（11-04 flash 实测）。

    背景：现网/预览都是「浏览器点一下 → 后端同步等 autoclip → autoclip 同步等网关」。
    11-04 在同一条 1333 字反推详规上实测：mimo-v2.6-flash 93.6s、pro 96.2s 正常回 3 条
    候选；**同一批里 flash 还连续两次卡到 autoclip 自己的 API_TIMEOUT(240s) 才超时、
    第三次才成功**。旧口径后端只等 180s，于是「后端先 502 → 模型那边其实还在跑并最终
    成功 → 钱照扣、候选没落库、一线看到失败」。

    口径只能是**从请求路径的外到内递减**（浏览器 → nginx → 后端 → autoclip），且**相邻两层
    必须严格大于、不能同值**——同值等于掷硬币，谁先到期看调度：
      仓库根 `nginx.conf`（现网 clip-nginx）3600s
      > `frontend/nginx.conf`（镜像内代理，预览栈走这份）1200s
      > 浏览器 axios（`frontend/src/api/assets.ts` 的 `MODEL_WAIT_TIMEOUT`）960s
      > 后端 `_call_autoclip` 默认 900s
      > autoclip 单次 `API_TIMEOUT`（现网 600s），内部重试只 1 次。

    ⚠️ nginx 那一层 11-04 第二轮审核时订正过两处：① **现网 /api/ 走的是仓库根
    `nginx.conf`（`clip-nginx` 把它挂成 `conf.d/default.conf`，`proxy_pass backend:8080`
    直连后端，不经过 clip-frontend），`proxy_read_timeout` 实测 3600s**；
    `frontend/nginx.conf` 里那份只在「直接访问 frontend 容器」时生效（旁路预览栈就是这么跑的）。
    两份都读、都断，别再拿其中一份当现网口径。② 那份原来写 900s 并与后端"同口径"，
    同值就是上面说的竞态，已抬到 1200s。
    这几条分属四个文件，改一个就得改另几个，所以在这里一次钉死。
    """
    import inspect
    from pathlib import Path

    from app.api import assets as assets_api

    # 1) 后端 → autoclip 的默认超时不能比 autoclip 单次上限（建议 600）短
    default_timeout = float(
        inspect.signature(assets_api._call_autoclip).parameters["timeout"].default
    )
    assert default_timeout >= 600, f"后端只等 {default_timeout}s，模型卡流时会先崩"

    root = Path(__file__).resolve().parents[3]

    def _api_read_timeout(conf_name: str) -> int:
        """只读 `/api/` 块里**真正生效**的那行，注释里提到别处的数不算。"""
        nginx = (root / conf_name).read_text()
        block = nginx.split("location /api/ {", 1)[1].split("}", 1)[0]
        live = "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("#"))
        return int(re.search(r"proxy_read_timeout\s+(\d+)s", live).group(1))

    # 2a) 镜像内的 frontend 代理（旁路预览栈走这份）必须**严格长于**后端，同值有竞态
    read_t = _api_read_timeout("frontend/nginx.conf")
    assert read_t > default_timeout, (
        f"frontend/nginx.conf {read_t}s 不比后端 {default_timeout}s 长：两层同值时谁先掐看调度"
    )
    # 2b) 现网 clip-nginx 挂的是仓库根那份，是最外层，同样必须长于内层代理
    live_t = _api_read_timeout("nginx.conf")
    assert live_t > read_t, f"根 nginx.conf {live_t}s 不长于 frontend/nginx.conf {read_t}s，会 504"

    # 3) 浏览器侧：client.ts 的默认 60s 对同步等模型的口是**必掐**的（出文案单条实测 93.6s），
    #    所以每个同步口都必须显式带 MODEL_WAIT_TIMEOUT，且要长于后端、短于镜像内 nginx。
    client_ts = (root / "frontend" / "src" / "api" / "client.ts").read_text()
    default_ms = int(re.search(r"timeout:\s*(\d+)", client_ts).group(1))
    api_ts = (root / "frontend" / "src" / "api" / "assets.ts").read_text()
    wait_ms = int(re.search(r"const MODEL_WAIT_TIMEOUT = (\d+)", api_ts).group(1))
    assert wait_ms > default_timeout * 1000, (
        f"前端 {wait_ms}ms 不比后端 {default_timeout}s 长，卡流时后端和浏览器同时到期（R-1）"
    )
    assert wait_ms < read_t * 1000, (
        f"前端 {wait_ms}ms 不长于 nginx {read_t}s 的倒数：nginx 先 504、后端其实还在等模型"
    )
    assert default_ms < wait_ms, "默认超时若已不小于同步超时，说明口径写反了"
    sync_paths = (
        "/assets/analyze/batch",
        "/assets/analyze/refresh-batch",
        "/assets/resolve",
        "/assets/summaries/generate",
        "/assets/produce",
        "/assets/concat",
    )
    for path in sync_paths:
        line = next(
            (ln for ln in api_ts.splitlines() if f"client.post('{path}'" in ln), None
        )
        assert line, f"前端没有 {path} 的调用，同步口清单要同步更新"
        assert "MODEL_WAIT_TIMEOUT" in line, (
            f"{path} 还在吃 client.ts 的 {default_ms / 1000:.0f}s 默认超时：一线会看到"
            "「失败」，而后端跑完、钱照扣、结果照落库"
        )

    # 4) 发给 autoclip 的两个 payload 必须把内部重试压到 1 次
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        seen = []
        fake = _fake_autoclip()

        async def _recorder(path, payload, timeout=180.0):
            seen.append({"path": path, "payload": payload, "timeout": timeout})
            return await fake(path, payload, timeout=timeout)

        with patch("app.api.assets._call_autoclip", _recorder):
            g = await client.post("/api/assets/summaries/generate",
                                  json={"asset_ids": [asset_id]}, headers=hm)
            assert g.status_code == 200, g.text
            sid = (await _rows(AssetSummary))[0].id
            await client.post("/api/assets/summaries/review",
                              json={"summary_ids": [str(sid)], "action": "approve"}, headers=ho)
            p = await client.post("/api/assets/produce",
                                  json={"summary_ids": [str(sid)], "n": 2, "expand": True},
                                  headers=ho)
            assert p.status_code == 200, p.text

        gen = [x for x in seen if x["path"].endswith("hook-copy/generate")]
        exp = [x for x in seen if x["path"].endswith("hook-copy/expand")]
        assert gen and exp, f"没打到两个端点：{[x['path'] for x in seen]}"
        for call in gen + exp:
            assert call["payload"].get("max_retries") == 1, (
                "autoclip 内部重试必须＝1：240s×3 的重试风暴只会让外层先崩，"
                "重试这件事交给一线点按钮（旧候选/旧单都有保留逻辑）"
            )
        await client.aclose()

    _run(_scenario())


def test_concat_two_videos_lands_a_composed_output_row():
    """**简单拼接**（11-04 简化口径）：两段直拼、顺序可选、不挂生产单也能落产物行。

    ffmpeg / MinIO 全部 mock（不真跑转码、不碰桶），验的是接线：
    - 产物落 `asset_outputs(kind="composed")`，**production_id 可以为空**（拼接不强制有生产单）；
    - `stage_compose` 是五阶段里唯一原先没写入方的，拼成功要置 success 并把派生态推到 ready；
    - 目标画幅＝**排在最前那一段**，换顺序就换画幅（这是"选顺序"唯一的真实含义）；
    - 成本 0 元：不调模型不调智令，所以不许污染 cost_*，但要留一条 asset.concat 审计。
    """
    _run(_bootstrap())

    VERT = {"duration": 10.08, "width": 720, "height": 1280, "fps": "25/1", "has_audio": True}
    HORIZ = {"duration": 6.0, "width": 1280, "height": 720, "fps": "30/1", "has_audio": False}
    OUT = {"duration": 16.08, "width": 720, "height": 1280, "fps": "25/1", "has_audio": True}

    async def _file_asset(client, hm, name):
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 10.08):
            resp = await client.post(
                "/api/assets/upload/batch",
                files=[("files", (name, VIDEO_BYTES, "video/mp4"))],
                headers=hm,
            )
        assert resp.status_code == 201, resp.text
        return resp.json()["items"][0]

    async def _seed_slice():
        """造一条现网切片产物（sliced 桶），走的是主系统的表，不是素材库的。"""
        async with dbmod.async_session_factory() as s:
            project = Project(name="拼接来源项目", created_by=None)   # 无主＝公共项目，四角色都可见
            s.add(project)
            await s.flush()
            episode = Episode(project_id=project.id, title="第1集")
            s.add(episode)
            await s.flush()
            task = SliceTask(episode_id=episode.id, status="completed")
            s.add(task)
            await s.flush()
            out = SliceOutput(task_id=task.id, file_key="slices/e/t/clip1.mp4",
                              file_name="clip1.mp4", duration=6.0, resolution="1280x720")
            s.add(out)
            await s.commit()
            return str(out.id)

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        a = await _file_asset(client, hm, "正文片段.mp4")
        b = await _file_asset(client, hm, "另一条片段.mp4")
        slice_id = await _seed_slice()

        calls = []

        async def _fake_concat(paths, target, out_path):
            calls.append({"paths": list(paths), "target": dict(target)})
            with open(out_path, "wb") as fh:
                fh.write(b"fake composed mp4 bytes")
            return None

        def _patched(first_info, second_info, out_info):
            return (
                patch("app.api.assets.download_to_file", AsyncMock(return_value=True)),
                patch("app.services.asset_compose_service.probe_media",
                      AsyncMock(side_effect=[first_info, second_info, out_info])),
                patch("app.services.asset_compose_service.concat_segments", _fake_concat),
                patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)),
            )

        # 1) A 在前（默认）
        ps = _patched(VERT, HORIZ, OUT)
        with ps[0], ps[1], ps[2], ps[3]:
            resp = await client.post("/api/assets/concat", json={
                "asset_id": a["id"], "second_source": "asset", "second_id": b["id"],
            }, headers=hm)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["kind"] == "composed" and body["resolution"] == "720x1280", body
        assert body["duration"] == 16.08 and body["production_id"] is None
        assert body["asset_status"] == "ready", f"拼完该推到 ready：{body['asset_status']}"
        assert calls and calls[0]["target"]["width"] == 720, "画幅必须跟排在最前那一段"
        row = (await _rows(AssetOutput))[0]
        assert row.kind == "composed" and row.production_id is None
        assert row.file_key.startswith(f"asset/composed/{a['code']}/")
        assert row.bucket == settings.MINIO_BUCKET_RAW
        assert row.sha256 and len(row.sha256) == 64
        asset_row = await _row_of(AssetItem, a["id"])
        assert asset_row.stage_compose == "success" and asset_row.status == "ready"
        # 拼接不花钱：不许写任何 cost_*，但要留审计（谁拼的、用哪两段、什么顺序）
        assert float(asset_row.cost_prompt or 0) == 0.0
        audits = await _rows(AuditLog, AuditLog.action == "asset.concat")
        assert len(audits) == 1 and audits[0].after["order"] == "asset_first"
        assert "正文片段" in audits[0].after["first"]

        # 2) 换成 B 在前 → 画幅跟着变（这就是"拼在前/拼在后"的实际作用）
        calls.clear()
        ps = _patched(HORIZ, VERT, {**OUT, "width": 1280, "height": 720})
        with ps[0], ps[1], ps[2], ps[3]:
            resp2 = await client.post("/api/assets/concat", json={
                "asset_id": a["id"], "second_source": "slice", "second_id": slice_id,
                "order": "second_first",
            }, headers=hm)
        assert resp2.status_code == 201, resp2.text
        assert resp2.json()["resolution"] == "1280x720", resp2.json()
        assert calls[0]["target"]["width"] == 1280
        # 每条一行不覆盖：两次拼 = 两行产物
        assert await _count(AssetOutput) == 2

        # 3) 两段是同一个文件 → 400（自己拼自己是废片）
        bad = await client.post("/api/assets/concat", json={
            "asset_id": a["id"], "second_source": "asset", "second_id": a["id"],
        }, headers=hm)
        assert bad.status_code == 400 and "同一个文件" in bad.json()["detail"]

        # 4) 非法 order / 非法来源都要 400，别把垃圾参数带到 ffmpeg
        for payload in (
            {"asset_id": a["id"], "second_source": "asset", "second_id": b["id"], "order": "middle"},
            {"asset_id": a["id"], "second_source": "nas", "second_id": b["id"]},
        ):
            r = await client.post("/api/assets/concat", json=payload, headers=hm)
            assert r.status_code == 400, (payload, r.text)

        # 5) 不存在的切片 / 不存在的素材
        r404 = await client.post("/api/assets/concat", json={
            "asset_id": a["id"], "second_source": "slice", "second_id": str(uuid.uuid4()),
        }, headers=hm)
        assert r404.status_code == 404
        r404b = await client.post("/api/assets/concat", json={
            "asset_id": str(uuid.uuid4()), "second_source": "asset", "second_id": b["id"],
        }, headers=hm)
        assert r404b.status_code == 404

        # 6) 链接素材（还没有文件）→ 400 并指出去哪取回原片
        link_asset, _ = await _make_ready_asset(client, hm)
        rlink = await client.post("/api/assets/concat", json={
            "asset_id": link_asset, "second_source": "asset", "second_id": b["id"],
        }, headers=hm)
        assert rlink.status_code == 400 and "/assets/resolve" in rlink.json()["detail"]

        # 7) 发布专员不能拼（拼接是生产侧动作，_PROD_ROLES 不含 publisher）
        assert "publisher" not in h

        # 8) 下载口复用既有产物下载（composed 可 presigned，qc_status 为空＝未验收但可下）
        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://minio/signed?x=1")) as presign:
            dl = await client.get(f"/api/assets/outputs/{body['id']}/download", headers=hm)
        assert dl.status_code == 200 and dl.json()["kind"] == "composed"
        assert presign.await_args.args[0] == settings.MINIO_BUCKET_RAW
        await client.aclose()

    _run(_scenario())


def test_concat_reports_which_segment_broke():
    """探不出视频流 / ffmpeg 失败时，错误要指到**第几段**，别回一句"拼接失败"让人猜。"""
    _run(_bootstrap())
    VERT = {"duration": 10.0, "width": 720, "height": 1280, "fps": "25", "has_audio": True}

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        a = await _file_asset_simple(client, hm, "能拼的.mp4")
        b = await _file_asset_simple(client, hm, "也能拼.mp4")

        with patch("app.api.assets.download_to_file", AsyncMock(return_value=True)), \
             patch("app.services.asset_compose_service.probe_media",
                   AsyncMock(side_effect=[VERT, None, VERT])):
            r = await client.post("/api/assets/concat", json={
                "asset_id": a["id"], "second_source": "asset", "second_id": b["id"],
            }, headers=hm)
        assert r.status_code == 400 and "第2段" in r.json()["detail"], r.text

        async def _fail_concat(paths, target, out_path):
            return "ffmpeg 拼接失败（退出码 234）：Invalid argument"

        with patch("app.api.assets.download_to_file", AsyncMock(return_value=True)), \
             patch("app.services.asset_compose_service.probe_media",
                   AsyncMock(side_effect=[VERT, VERT, VERT])), \
             patch("app.services.asset_compose_service.concat_segments", _fail_concat):
            r2 = await client.post("/api/assets/concat", json={
                "asset_id": a["id"], "second_source": "asset", "second_id": b["id"],
            }, headers=hm)
        assert r2.status_code == 502 and "退出码 234" in r2.json()["detail"]
        # 失败了就不许留产物行，也别把 stage_compose 写成 success
        assert await _count(AssetOutput) == 0
        asset_row = await _row_of(AssetItem, a["id"])
        assert asset_row.stage_compose != "success"
        await client.aclose()

    async def _file_asset_simple(client, hm, name):
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 10.0):
            resp = await client.post("/api/assets/upload/batch",
                                     files=[("files", (name, VIDEO_BYTES, "video/mp4"))], headers=hm)
        assert resp.status_code == 201, resp.text
        return resp.json()["items"][0]

    _run(_scenario())


def test_risk_lexicon_api_read_update_and_immediate_effect():
    """风险词库接口（GET/PUT /assets/risk-lexicon）。

    要验的：
    1. material 也能**读**（他被 block 词拦下来时得知道拦的是哪个词），但只有 admin 能改；
    2. 豁免正则写坏 → 400（不许把闸门搞挂）；
    3. admin 加一个 block 词 → **立刻**生效（不等 TTL 缓存）：闸门那份词表里已经能看到新词；
    4. 端到端：含新词的候选会被扫出风险词、并且过审真的被拦（不是只记录不拦）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]

        # ① 读：能看到「生效词表 / 内置默认表 / 豁免正则 / 能不能改」
        r = await client.get("/api/assets/risk-lexicon", headers=hm)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "砍死" in data["effective"]["block"], "生效词表里要有内置 block 词"
        assert "第一" in data["effective"]["warn"], "生效词表里要有内置 warn 词"
        assert data["defaults"]["block"], "必须能看见内置默认表（否则不知道哪些词是出厂的）"
        assert data["defaults"]["exempt"], "必须能看见内置豁免正则"
        assert data["can_edit"] is False, "material 不是管理员，不能改"
        r = await client.get("/api/assets/risk-lexicon", headers=ha)
        assert r.json()["can_edit"] is True

        # ② material 改 → 403（词表等于投放闸门）
        r = await client.put("/api/assets/risk-lexicon",
                             json={"block": ["越权词"], "warn": [], "exempt": {}, "inherit": True},
                             headers=hm)
        assert r.status_code == 403, r.text

        # ③ 豁免正则写坏 → 400
        r = await client.put("/api/assets/risk-lexicon",
                             json={"block": [], "warn": [], "exempt": {"坏": "([a-z"}, "inherit": True},
                             headers=ha)
        assert r.status_code == 400, r.text

        # ④ admin 加词 → 立刻生效（缓存必须被清掉）
        r = await client.put("/api/assets/risk-lexicon",
                             json={"block": ["新拦词"], "warn": [], "exempt": {}, "inherit": True},
                             headers=ha)
        assert r.status_code == 200, r.text
        assert "新拦词" in r.json()["effective"]["block"]
        from app.api import assets as assets_api
        async with dbmod.async_session_factory() as s:
            lexicon, _exempt = await assets_api._risk_lexicon(s)
        assert "新拦词" in lexicon["block"], "改完词表必须立刻生效，不能等 TTL 过期"

        # ④b R-3：改词必须留痕——这份表**保存即生效**且直接决定能否过审/投产，
        #     匿名改闸门等于事后问「谁把这个词挪到 block」答不上。
        #     ②③ 两次失败（403/400）不该留下任何痕迹，所以这里必须**恰好 1 条**。
        audits = await _rows(AuditLog, AuditLog.action == "asset.risk_lexicon.update")
        assert len(audits) == 1, f"改词留痕条数不对（失败请求不该写审计）：{len(audits)}"
        assert audits[0].target_type == "asset_risk_lexicon"
        assert audits[0].operator_id is not None, "必须能回答是谁改的"
        assert not audits[0].before, "第一次改之前没有覆盖配置，before 该是空"
        assert audits[0].after["block"] == ["新拦词"]
        assert audits[0].after["inherit"] is True

        # ④c 再改一次：before 必须是上一份的整份覆盖（改前改后连得起来才叫历史）
        r = await client.put("/api/assets/risk-lexicon",
                             json={"block": ["新拦词", "又一直播"], "warn": ["全网最低"],
                                   "exempt": {"第一": "第一次|第一时间"}, "inherit": False},
                             headers=ha)
        assert r.status_code == 200, r.text
        audits = await _rows(AuditLog, AuditLog.action == "asset.risk_lexicon.update")
        assert len(audits) == 2
        assert audits[-1].before["block"] == ["新拦词"], "before 要能还原改前那份词表"
        assert audits[-1].after["inherit"] is False and audits[-1].after["warn"] == ["全网最低"]

        # ⑤ 端到端：含新词的候选 → 扫出风险词 + 过审真被拦
        cands = [{"text": "她一把掀翻了餐桌，新拦词就在这里", "style_tag": "statement",
                  "formula_tag": "悬念前置", "is_recommended": True}]
        asset_id, _ = await _make_ready_asset(client, hm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip(candidates=cands)):
            resp = await client.post("/api/assets/summaries/generate",
                                     json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        q = await client.get(f"/api/assets/summaries?asset_id={asset_id}", headers=hm)
        items = q.json()["items"]
        assert items, "候选没落库"
        assert items[0]["risk_hit"] and "新拦词" in items[0]["risk_hit"], \
            "新加的 block 词必须被扫出来"
        r = await client.post("/api/assets/summaries/review",
                              json={"summary_ids": [items[0]["id"]], "action": "approve"},
                              headers=ha)
        row = r.json()["results"][0]
        assert row["ok"] is False and row["error_code"] == "ASSET_RECHECK_FAILED", row
        assert "新拦词" in row["error"], row

        await client.aclose()

    _run(_scenario())


def test_rejected_copy_goes_back_to_queue_when_its_owner_fixes_it():
    """11-04 用户问出来的闭环：驳回之后，**出文案的人**能改了重新提审。

    规矩（别在改代码时 loosen）：
    1. 只有 rejected / need_rewrite 能重提（待审的本来就在队列里）；
    2. 只有这条素材的负责人（导入人）或 admin 能重提——审核人不能自己擦屁股；
    3. 形态与 block 级风险词当场拦（改完再提也得干净），一致性只留痕；
    4. 改前改后进 AuditLog，原文留在 text_before_edit。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        old_text = next(i["text"] for i in items if i["id"] == sid)

        # 审核人驳回（理由必填）
        rej = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "reject", "reason": "钩子不成立，改成疑问句"},
            headers=ho,
        )
        assert rej.status_code == 200, rej.text
        assert rej.json()["results"][0]["ok"] is True
        row = await _row_of(AssetSummary, sid)
        assert row.audit_status == RV_REJECTED
        assert row.reject_reason == "钩子不成立，改成疑问句"

        # 列表里这条要标出「可以重提」，且只对负责人亮
        q_owner = await client.get(f"/api/assets/summaries?asset_id={asset_id}", headers=hm)
        mine = [i for i in q_owner.json()["items"] if i["id"] == sid][0]
        assert mine["can_resubmit"] is True
        q_other = await client.get(f"/api/assets/summaries?asset_id={asset_id}", headers=ho)
        theirs = [i for i in q_other.json()["items"] if i["id"] == sid][0]
        assert theirs["can_resubmit"] is False

        # 「等我改的」入口筛选：负责人看得到自己的待改条目，别人看不到
        only_mine = await client.get("/api/assets/summaries?only_resubmittable=true", headers=hm)
        assert [i["id"] for i in only_mine.json()["items"]] == [sid]
        only_other = await client.get("/api/assets/summaries?only_resubmittable=true", headers=ho)
        assert only_other.json()["items"] == []

        # 审核人自己不能重提（生产者不得自审是同一条线）
        by_reviewer = await client.post(
            "/api/assets/summaries/resubmit",
            json={"summary_ids": [sid], "new_text": "王总在康华医院门口站了三小时，谁也没想到他会当场翻脸？"},
            headers=ho,
        )
        assert by_reviewer.status_code == 200, by_reviewer.text
        assert by_reviewer.json()["results"][0]["ok"] is False
        assert "负责人" in by_reviewer.json()["results"][0]["error"]

        # 负责人改了交回待审队列
        # 先把 summary 阶段人为打成 failed（真实来路：后来重出文案失败了，但旧的被驳候选
        # 还在库里）。重提成功后整条状态**必须**跟着收敛，否则一线会看到
        # 「文案环节＝失败，候选却就在待审队列」这种自相矛盾的行，按阶段筛也筛不到它。
        from app.services import asset_service as svc
        async with dbmod.async_session_factory() as s:
            poisoned = await s.get(AssetItem, uuid.UUID(asset_id))
            poisoned.stage_summary = "failed"
            poisoned.status = svc.derive_status(svc.stage_of(poisoned))
            await s.commit()

        new_text = "王总在康华医院门口站了三小时，他还不敢信这事？"
        sub = await client.post(
            "/api/assets/summaries/resubmit",
            json={"summary_ids": [sid], "new_text": new_text, "note": "按建议改成疑问句"},
            headers=hm,
        )
        assert sub.status_code == 200, sub.text
        assert sub.json()["results"][0]["ok"] is True
        row = await _row_of(AssetSummary, sid)
        assert row.audit_status == RV_PENDING
        assert row.text == new_text
        assert row.text_before_edit == old_text
        assert row.reject_reason is None
        assert row.reviewed_by is None
        audits = await _rows(AuditLog, AuditLog.action == "asset.summary_resubmit")
        assert len(audits) == 1
        assert audits[0].before["audit_status"] == RV_REJECTED
        assert audits[0].before["text"] == old_text
        assert audits[0].after["text"] == new_text
        # 阶段收敛（11-04 第二轮审核）：交回队列的这一刻，素材整条状态要从「failed」回到
        # 「待审」这一档——原来只改了 has_approved_copy，`stage_summary` 和 status 都没跟着走。
        back = await _row_of(AssetItem, asset_id)
        assert back.stage_summary == "success", "重提成功必须把 summary 阶段收敛回来"
        assert back.status != "failed", f"素材整条状态还停在失败：{back.status}"

        # 待审的不能再重提（本来就在队列里）
        again = await client.post(
            "/api/assets/summaries/resubmit",
            json={"summary_ids": [sid], "new_text": new_text}, headers=hm)
        assert again.json()["results"][0]["ok"] is False
        assert "重新提审" in again.json()["results"][0]["error"]

        # 硬闸门照旧：带 block 级风险词的文案提不上去
        rej2 = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "reject", "reason": "再退一次"},
            headers=ho,
        )
        assert rej2.json()["results"][0]["ok"] is True
        bad = await client.post(
            "/api/assets/summaries/resubmit",
            json={"summary_ids": [sid], "new_text": "这药百分百根治，谁都不敢说"}, headers=hm)
        assert bad.json()["results"][0]["ok"] is False
        assert bad.json()["results"][0]["error_code"] == "ASSET_RECHECK_FAILED"
        # block 级的是「根治」（「百分百」只是 warn，只留痕不拦）
        assert any("根治" in p["message"] for p in bad.json()["results"][0]["problems"])
        # 11-04 现网实测踩到的坑：闸门没过时**不能把作者原来的文案改掉**——
        # 一次失败的提交不该吃掉别人的稿子（这行此时文案还是 admin 上次提的那版）
        row_after_fail = await _row_of(AssetSummary, sid)
        assert row_after_fail.text == new_text
        assert row_after_fail.text_before_edit == old_text
        assert row_after_fail.audit_status == RV_REJECTED

        # admin 可以代提（逃生门）
        ok = await client.post(
            "/api/assets/summaries/resubmit",
            json={"summary_ids": [sid], "new_text": "王总在康华医院门口站了三小时，他还不敢信这事？"},
            headers=ha,
        )
        assert ok.json()["results"][0]["ok"] is True
        row = await _row_of(AssetSummary, sid)
        assert row.audit_status == RV_PENDING

        await client.aclose()

    _run(_scenario())


# ─────────────────  11. 后台任务台账（D-1：提交即回 + 轮询）  ─────────────────


async def _wait_job(client, headers, job_id, *, timeout=10.0):
    """轮询到终态。拿到 running 就一直等，超时要明确报错，别默默返回半份状态。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        resp = await client.get(f"/api/assets/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if not body["running"]:
            return body
        if loop.time() > deadline:
            raise AssertionError(f"任务 {job_id} 在 {timeout}s 内没跑完：{body}")
        await asyncio.sleep(0.05)


def test_generate_hook_copy_async_mode_returns_immediately_and_polling_gets_result():
    """D-1：`async_mode=true` 提交当场回任务号，模型在后台跑，轮询拿**整份**结果。

    这条测的是"人不用干等"这件事本身：出文案单条 ~95s，一批十几条就是十几分钟，
    同步等会一路撞上浏览器/nginx 超时（第二轮审核 D-1 的原始事故形态）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)

        call = _fake_autoclip()
        with patch("app.api.assets._call_autoclip", call):
            sub = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "async_mode": True},
                headers=hm,
            )
            # ① 当场就回，而且**不是**同步那套 {results:[...]} 形状
            assert sub.status_code == 200, sub.text
            ack = sub.json()
            assert ack["queued"] is True and ack["job_id"]
            assert ack["planned_units"] == 1
            assert ack["poll_url"] == f"/api/assets/jobs/{ack['job_id']}"
            assert "results" not in ack, "异步回执不能长得像同步结果（前端会误读成空批次）"

            # ② 轮询到终态：结果整份在台账里
            done = await _wait_job(client, h["admin"], ack["job_id"])
        assert done["status"] == "succeeded", done
        assert done["status_label"] == "已完成"
        assert done["result"]["results"][0]["created"] == 3, done["result"]
        assert done["progress"]["done"] == 1 and done["progress"]["total"] == 1

        # ④ 数据真的落库了（台账不是唯一真相，业务表才是）
        assert await _count(AssetSummary) == 3
        # ⑤ 台账只有一行——后台重放时 async_mode 被摘掉，没有自我套娃
        jobs = await _rows(AssetJob)
        assert len(jobs) == 1, [j.status for j in jobs]
        assert jobs[0].params["async_mode"] is True, "params 存的是原请求体（追溯用）"
        # ⑥ 提交动作本身进了审计日志
        audits = await _rows(AuditLog, AuditLog.action == "asset.job.summary_generate.submit")
        assert len(audits) == 1 and audits[0].target_id == str(jobs[0].id)

        # ⑦ 列表口：跑完后 only_open 为空，按 kind 能查到
        open_now = await client.get("/api/assets/jobs?only_open=true", headers=hm)
        assert open_now.json()["items"] == []
        by_kind = await client.get("/api/assets/jobs?kind=summary_generate", headers=hm)
        assert [i["id"] for i in by_kind.json()["items"]] == [str(jobs[0].id)]
        bad_kind = await client.get("/api/assets/jobs?kind=nonsense", headers=hm)
        assert bad_kind.status_code == 400 and "kind 只支持" in bad_kind.json()["detail"]
        await client.aclose()

    _run(_scenario())


def test_produce_async_mode_records_what_failed_and_why():
    """后台任务的两种"没成"必须分开落账：逐条失败（结果还在）与整批炸了（只有原话）。

    一线最怕"点了没反应"：台账里得写清是模型/展开把这条拒了（还能看出是哪条），
    还是编排自己炸了（整批作废，得重投）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        ok = await client.post(
            "/api/assets/summaries/review", json={"summary_ids": [sid], "action": "approve"}, headers=ha)
        assert ok.json()["results"][0]["ok"] is True, ok.text

        # ① 展开服务挂了 = **逐条**失败：接口本身回 200，台账是 succeeded，
        #    明细里带原话，且绝不落半成品行（与同步口的既有口径一致）
        with patch("app.api.assets._call_autoclip", _fake_autoclip(expand_error="展开服务没回话")):
            sub = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [sid], "n": 2, "async_mode": True},
                headers=ha,
            )
            assert sub.status_code == 200, sub.text
            ack = sub.json()
            assert ack["planned_units"] == 1 and "生成生产单" in ack["message"]
            done = await _wait_job(client, ha, ack["job_id"])
        assert done["status"] == "succeeded", done
        assert done["result"]["results"][0]["created"] == 0, done["result"]
        assert "展开服务没回话" in done["result"]["results"][0]["error"], done["result"]
        assert await _count(AssetProduction) == 0, "展开失败不落半成品行"

        # ② 请求体不合法 = **当场拒绝**，根本不排后台、不留台账
        boom = await client.post(
            "/api/assets/produce", json={"summary_ids": [], "async_mode": True}, headers=ha)
        assert boom.status_code == 400, boom.text
        assert await _count(AssetJob) == 1, "校验没过就不该落台账（否则全是必然失败的行）"

        # ③ 编排炸了（故障注入：读词表这步抛 RuntimeError）= 整批 failed + 异常原话。
        #    注入的是"接口以外"的意外，真实形态是连不上库/代码抛错，
        #    判据是同一条：绝不能把异常抛回事件循环，也绝不能标成 succeeded。
        with patch("app.api.assets._call_autoclip", _fake_autoclip()), \
             patch("app.api.assets._risk_lexicon", AsyncMock(side_effect=RuntimeError("连不上配置库"))):
            sub2 = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [sid], "n": 1, "async_mode": True},
                headers=ha,
            )
            assert sub2.status_code == 200, sub2.text
            done2 = await _wait_job(client, ha, sub2.json()["job_id"])
        assert done2["status"] == "failed", done2
        assert done2["result"] is None, "整批没跑成的不该有结果可看"
        assert "RuntimeError" in done2["error"] and "连不上配置库" in done2["error"], done2["error"]
        assert done2["status_label"] == "失败"
        await client.aclose()

    _run(_scenario())


def test_async_submit_blocked_by_running_twin_same_batch():
    """防重复烧钱：同批/同条已经在后台跑着，第二次提交当场 409，不起第二份活。

    这条守卫是**台账自己判**（不靠前端禁用按钮）：两个人同时点、或一个人连点两下，
    模型费用和钩子编号只会被烧一次。测试里直接造一条 queued 台账，
    不靠"抢在后台跑完之前发第二次"那种撞时间窗的写法（那是随机测试）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        batch_id = str((await _row_of(AssetItem, asset_id)).batch_id)

        async with dbmod.async_session_factory() as s:
            s.add(AssetJob(
                kind=JOB_SUMMARY_GENERATE, status=JB_QUEUED,
                batch_id=uuid.UUID(batch_id), params={"asset_ids": [asset_id]},
            ))
            await s.commit()

        # 点名同一条素材 → 409
        dup = await client.post(
            "/api/assets/summaries/generate",
            json={"asset_ids": [asset_id], "async_mode": True}, headers=hm)
        assert dup.status_code == 409, dup.text
        assert "正在后台跑" in dup.json()["detail"] and "重复扣模型费用" in dup.json()["detail"]

        # 整批排队（只有 batch_id）→ 同样 409，话说得更直白
        dup_batch = await client.post(
            "/api/assets/summaries/generate",
            json={"batch_id": batch_id, "async_mode": True}, headers=hm)
        assert dup_batch.status_code == 409, dup_batch.text
        assert "已经在后台跑着" in dup_batch.json()["detail"]

        # 同步口径不受影响：没在跑的那批照样能提交（这里换个批次 id 是空队列 → 400 而非 409）
        other = await client.post(
            "/api/assets/summaries/generate",
            json={"batch_id": str(uuid.uuid4())}, headers=hm)
        assert other.status_code == 400 and "没有待出文案的素材" in other.json()["detail"]

        # 台账里没有第二条：守卫拦在落库之前
        assert await _count(AssetJob) == 1
        await client.aclose()

    _run(_scenario())


def test_startup_sweep_marks_open_jobs_interrupted():
    """重启清扫：进程没了，挂在 queued/running 的任务一律判「已中断」，绝不假装还在跑。

    现网 backend 是 `--workers 1`，协程活在进程内存里，重启即全没；
    不清扫的话台账永远显示"正在跑"，一线等一个永远不会来的结果。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        async with dbmod.async_session_factory() as s:
            s.add_all([
                AssetJob(kind=JOB_SUMMARY_GENERATE, status=JB_QUEUED, params={"asset_ids": [asset_id]},
                         created_by=None),
                AssetJob(kind=JOB_PRODUCE, status=JB_RUNNING, params={"summary_ids": []}, created_by=None),
                AssetJob(kind=JOB_SUMMARY_GENERATE, status=JB_SUCCEEDED, params={}, created_by=None),
            ])
            await s.commit()

        swept = await assets_api.sweep_interrupted_asset_jobs()
        assert swept == 2, swept
        rows = await _rows(AssetJob, AssetJob.status == JB_INTERRUPTED)
        assert len(rows) == 2 and all("重启" in r.error for r in rows)
        # 已经跑完的不动（结果仍然可信）
        still = await _rows(AssetJob, AssetJob.status == JB_SUCCEEDED)
        assert len(still) == 1

        # 前端拿到的状态是说人话的
        listing = await client.get("/api/assets/jobs?only_open=true", headers=hm)
        assert listing.json()["items"] == [], "中断是终态，不能再算「还在跑」"
        detail = await client.get(f"/api/assets/jobs/{rows[0].id}", headers=hm)
        assert detail.json()["status_label"].startswith("已中断"), detail.json()
        assert detail.json()["running"] is False
        await client.aclose()

    _run(_scenario())


def test_job_done_note_says_where_the_work_actually_got_to():
    """11-10 用户口径③「刚才投出去的那条生产单显示完成，成片墙还是看不到」——话术表守卫（不连库）。

    「已完成」这三个字在台账里本来只说明**这一个动作**跑完了：投板跑完＝单挂上豆包的板，
    片子还在出（几十分钟）；开单跑完＝单建好、还没投板。一线把它读成"片儿到手了"完全合理，
    错的是我们只报动作不报去向。所以每一种任务都必须带一句去向，而且**这句话本身不能谎报**：
    这里钉的是措辞底线（投板那条必须出现"几十分钟""才算到手""成片墙"），改话术的人会先撞到这里。
    """
    from app.models.asset import ASSET_JOB_KINDS, JOB_ANALYZE, JOB_DISPATCH, JOB_DOWNLOAD, JOB_PROMPT_PREVIEW

    notes = assets_api.ASSET_JOB_DONE_NOTES
    # ① 每种任务都得有话：新增 kind 却忘了写去向 = 又回到"只显示完成"那个投诉
    missing = sorted(set(ASSET_JOB_KINDS) - set(notes))
    assert not missing, f"这些后台任务类型没有完成话术（一线只会看到「已完成」）：{missing}"
    assert all(n and n.strip() for n in notes.values()), "话术不能是空串"
    # ② 花钱/花号池那两条必须说清"还没到手"
    assert "还没投板" in notes[JOB_PRODUCE], notes[JOB_PRODUCE]
    d = notes[JOB_DISPATCH]
    assert "几十分钟" in d and "才算到手" in d and "成片墙" in d, d
    # ③ 出稿类不能让人以为片子已经在库里
    assert "没投板" in notes[JOB_SUMMARY_GENERATE], notes[JOB_SUMMARY_GENERATE]
    for kind in (JOB_ANALYZE, JOB_SUMMARY_GENERATE, JOB_PRODUCE, JOB_PROMPT_PREVIEW, JOB_DOWNLOAD):
        assert "已出片" not in notes[kind] and "出片完成" not in notes[kind], (kind, notes[kind])


def test_job_api_returns_done_note_only_for_succeeded():
    """去向那句话只在**成功终态**给；失败／中断给的是成因（`error`），两套话不许混。

    混了会怎样：一条失败的投板也挂着"投板只是把单挂上板…几十分钟"，一线就会守着页面
    等一个永远不会来的片子——这正是本轮投诉的反面形态。
    """
    from app.models.asset import JB_FAILED, JOB_DISPATCH

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        async with dbmod.async_session_factory() as s:
            s.add_all([
                AssetJob(kind=JOB_DISPATCH, status=JB_SUCCEEDED, params={}, created_by=None),
                AssetJob(kind=JOB_PRODUCE, status=JB_SUCCEEDED, params={}, created_by=None),
                AssetJob(kind=JOB_DISPATCH, status=JB_FAILED, params={}, created_by=None,
                         error="豆包任务板没回话"),
                AssetJob(kind=JOB_SUMMARY_GENERATE, status=JB_INTERRUPTED, params={}, created_by=None,
                         error="服务重启，这条没跑完"),
            ])
            await s.commit()
        rows = {
            (r.kind, r.status): str(r.id)
            for r in await _rows(AssetJob, AssetJob.status.in_(list(assets_api.JOB_TERMINAL_STATES)))
        }
        got = {}
        for key, jid in rows.items():
            body = (await client.get(f"/api/assets/jobs/{jid}", headers=hm)).json()
            got[key] = body["done_note"]
        assert got[(JOB_DISPATCH, JB_SUCCEEDED)] == assets_api.ASSET_JOB_DONE_NOTES[JOB_DISPATCH], got
        assert got[(JOB_PRODUCE, JB_SUCCEEDED)] == assets_api.ASSET_JOB_DONE_NOTES[JOB_PRODUCE], got
        assert got[(JOB_DISPATCH, JB_FAILED)] is None, got
        assert got[(JOB_SUMMARY_GENERATE, JB_INTERRUPTED)] is None, got
        await client.aclose()

    _run(_scenario())


def test_startup_sweep_requeues_frames_jobs_and_interrupts_the_rest():
    """P2-1（11-06）：进程重启打死的 frames 任务**原行重排**，不留下假终态。

    frames 免费＋幂等（已有帧默认跳过），重启被打断纯属运气不好，判 interrupted
    等于让人手工补一单；其它 kind（出文案/投产要花钱、有闸门口径）必须保持判死——
    启动清扫绝不能把带豁免理由、带成本确认的提交偷偷重放一遍。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        admin_uid = (await _rows(User, User.username == ADMIN_USER))[0].id
        async with dbmod.async_session_factory() as s:
            s.add_all([
                AssetJob(kind=JOB_FRAMES, status=JB_RUNNING,
                         params={"asset_ids": ["aa"], "output_ids": [], "async_mode": True},
                         created_by=admin_uid),
                AssetJob(kind=JOB_FRAMES, status=JB_QUEUED,
                         params={"asset_ids": [], "output_ids": ["bb"], "async_mode": True},
                         created_by=admin_uid),
                AssetJob(kind=JOB_FRAMES, status=JB_QUEUED, params={"asset_ids": []}, created_by=None),
                AssetJob(kind=JOB_SUMMARY_GENERATE, status=JB_RUNNING,
                         params={"asset_ids": [str(admin_uid)]}, created_by=admin_uid),
            ])
            await s.commit()

        scheduled: list = []
        with patch.object(assets_api, "_schedule_asset_job", lambda *a: scheduled.append(a)):
            swept = await assets_api.sweep_interrupted_asset_jobs()
        # 只有「非 frames」的 2 条判死（出文案 ＋ 没提交人的 frames）；frames 两条重排不计入
        assert swept == 2, swept
        interrupted = await _rows(AssetJob, AssetJob.status == JB_INTERRUPTED)
        assert {j.kind for j in interrupted} == {JOB_SUMMARY_GENERATE, JOB_FRAMES}
        assert all("重启" in j.error for j in interrupted)

        requeued = await _rows(AssetJob, AssetJob.status == JB_QUEUED)
        assert len(requeued) == 2 and all(j.kind == JOB_FRAMES for j in requeued)
        assert all(j.error is None and j.finished_at is None for j in requeued), "重排要清掉终态痕迹"
        assert all(j.params.get("async_mode") is True for j in requeued), "params 原样保留（重放口径不变）"

        # 重排走的是**原行**调度，不是新开一行：台账里没有多出任何新任务
        assert len(scheduled) == 2
        assert {a[0] for a in scheduled} == {str(j.id) for j in requeued}
        assert all(a[1] == JOB_FRAMES for a in scheduled)
        total = await _count(AssetJob)
        assert total == 4, f"重排不该新建台账行，现在 {total} 行"

        await client.aclose()

    _run(_scenario())


# ─────────────────────────────────────────────────────────────
# 11-04 拍板①：钩子原型字典（asset_categories ＋ 素材/文案 category_id）
# ─────────────────────────────────────────────────────────────


async def _cat_id(client, h, key):
    """从字典里按"原型 X"这个前缀取一个 id（用例里不写死 uuid）。"""
    r = await client.get("/api/assets/categories", headers=h)
    assert r.status_code == 200, r.text
    hit = [i for i in r.json()["items"] if i["name"].startswith(f"原型 {key}：")]
    assert len(hit) == 1, hit
    return hit[0]["id"]


def test_category_dictionary_is_seeded_verbatim_from_the_hook_doc():
    """字典种入：7 行原型 A–G **原名**、按 sort 排、谁读谁的角色决定能不能改。

    钉住"原名"这条：11-04 拍板写的是"照《钩子模版换皮参数设定.docx》原名录入，
    我不改词、不加项"。名字一旦被后人顺手"优化"成更好看的说法，一线按文档沟通的
    那套词就和系统对不上了，所以这里按字面断言，不比长度不比数量。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        r = await client.get("/api/assets/categories", headers=h["material"])
        assert r.status_code == 200, r.text
        data = r.json()
        names = [i["name"] for i in data["items"]]
        assert names == [
            "原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）",
            "原型 B：偷听泄密（获取关键情报）",
            "原型 C：隐藏财富 / 秘境发现（反转爆发）",
            "原型 D：虐待 / 冲突 / 不公反转（情绪引爆）",
            "原型 E：超能力 / 异常 / 猎奇（设定反差）",
            "原型 F：神力 / 温情 / 绝境反转（其他）",
            "原型 G：前置故事叙事（口播）",
        ], names
        assert len(DEFAULT_ASSET_CATEGORIES) == 7
        # 顺序按 sort 而不是按插入序（字典抽屉要能重排）
        sorts = [i["sort"] for i in data["items"]]
        assert sorts == sorted(sorts), sorts
        # 原型 D 的合规提醒是文档自带口径，作为行内说明显示
        d = next(i for i in data["items"] if i["name"].startswith("原型 D"))
        assert "本故事纯属虚构" in (d["note"] or "") and "侧拍" in (d["note"] or ""), d
        # 读侧：material 读得到、但改不了；admin 能改
        assert data["can_edit"] is False
        assert (await client.get("/api/assets/categories", headers=h["admin"])).json()["can_edit"] is True
        # 未分类计数（列表页那句"未分类 N 条"的数据源）
        assert data["unclassified"] == {"asset_count": 0, "copy_count": 0}, data["unclassified"]
        # 发布专员（publisher）不在读口径里：它不参与素材生产
        await client.aclose()

    _run(_scenario())


def test_empty_dictionary_refills_itself_on_read():
    """字典被清空后，读口自己补回 7 行（老库刚建完表、服务还没重启过的窗口不能是空的）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        async with dbmod.async_session_factory() as s:
            await s.execute(AssetCategory.__table__.delete())
            await s.commit()
        assert await _count(AssetCategory) == 0

        r = await client.get("/api/assets/categories", headers=h["material"])
        assert len(r.json()["items"]) == 7, "读到空表要兜底种入"
        # 再读一次不会长出第二份（按 name 幂等）
        await client.get("/api/assets/categories", headers=h["material"])
        assert await _count(AssetCategory) == 7
        # 服务每次重启都会再走一遍 init_db 的种入：这里直接点同一个函数，
        # 断它第二次返回 0 行 —— 否则现网每重启一次就多 7 行原型，下拉会变成两倍长
        async with dbmod.async_session_factory() as s:
            again = await dbmod.ensure_default_asset_categories(s)
            await s.commit()
        assert again == 0 and await _count(AssetCategory) == 7, again
        await client.aclose()

    _run(_scenario())


def test_category_dictionary_writes_are_admin_only_and_leave_a_trail():
    """改字典：material/operator 一律 403，admin 改完进审计（形态照风险词库）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        cid = await _cat_id(client, h["admin"], "A")

        for role in ("material", "operator"):
            r = await client.put(
                "/api/assets/categories",
                json={"items": [{"id": cid, "name": "被我改掉的原型 A"}]},
                headers=h[role],
            )
            assert r.status_code == 403, (role, r.status_code, r.text)
        assert (await _row_of(AssetCategory, cid)).name.startswith("原型 A"), "非 admin 不许改到库"

        r = await client.put(
            "/api/assets/categories",
            json={"items": [{"id": cid, "name": "原型 A：非人物件开口说话", "sort": 10, "note": "改了说明"}]},
            headers=h["admin"],
        )
        assert r.status_code == 200, r.text
        assert (await _row_of(AssetCategory, cid)).name == "原型 A：非人物件开口说话"
        audits = await _rows(AuditLog, AuditLog.action == "asset.categories.update")
        assert len(audits) == 1 and audits[0].operator_name == ADMIN_USER, audits
        before = (audits[0].before or {}).get("items") or []
        assert any(i["id"] == cid and i["name"].startswith("原型 A：非人物件 /") for i in before), before
        await client.aclose()

    _run(_scenario())


def test_categories_put_retires_unlisted_rows_instead_of_deleting_them():
    """整单语义：没列出来的行＝下线，**不删**——素材上还挂着引用，删了会静默清空一线点好的分类。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        a_id = await _cat_id(client, ha, "A")
        b_id = await _cat_id(client, ha, "B")
        # 先挂一条素材到 B 上，制造"引用还在"的现场
        imp = await _import(client, hm, [DOUYIN_1], category_id=b_id)
        assert imp.status_code == 201, imp.text
        assert imp.json()["items"][0]["category_id"] == b_id

        rest = [
            {"id": i["id"], "name": i["name"], "sort": i["sort"], "active": i["active"], "note": i["note"]}
            for i in (await client.get("/api/assets/categories", headers=ha)).json()["items"]
            if i["id"] != b_id
        ]
        r = await client.put("/api/assets/categories", json={"items": rest}, headers=ha)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["retired"] == 1, body
        assert any("已下线" in n for n in body["notes"]), body["notes"]

        rows = await _rows(AssetCategory)
        assert len(rows) == 7, "下线不是删除：行数一根毛都不少"
        gone = await _row_of(AssetCategory, b_id)
        assert gone.active is False and gone.name.startswith("原型 B")

        # 历史素材的分类**没被清空**，且名字仍然读得到（列表要显示它挂过哪个原型）
        got = await client.get(f"/api/assets/{imp.json()['items'][0]['id']}", headers=hm)
        assert got.json()["asset"]["category_id"] == b_id, got.json()["asset"]
        assert got.json()["asset"]["category_name"] == gone.name, "下线行的名字仍要读得到"
        # 但不能再把新条目挂上去
        bad = await client.post(
            "/api/assets/categories/assign",
            json={
                "asset_ids": [imp.json()["items"][0]["id"]],
                "summary_ids": [],
                "category_id": b_id,
            },
            headers=hm,
        )
        assert bad.status_code == 400 and "已下线" in bad.json()["detail"], bad.text
        await client.aclose()

    _run(_scenario())


def test_categories_put_rejects_duplicate_names():
    """字典里两个同名原型 → 400 说清是哪条（name 上有唯一约束，静默撞上去就是一批 500）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        r = await client.put(
            "/api/assets/categories",
            json={"items": [{"name": "重名原型"}, {"name": "重名原型"}]},
            headers=h["admin"],
        )
        assert r.status_code == 400 and "重名" in r.json()["detail"], r.text
        assert await _count(AssetCategory) == 7, "400 的这次不许留下半个新行"
        # 空名同样进不来
        r2 = await client.put(
            "/api/assets/categories", json={"items": [{"name": "   "}]}, headers=h["admin"]
        )
        assert r2.status_code == 400, r2.text
        await client.aclose()

    _run(_scenario())


def test_copy_inherits_the_asset_prototype_and_review_can_override():
    """文案继承素材的原型（出稿那一刻定下），之后逐条可改、改前值留痕。

    为什么继承发生在建行的那一刻而不是每次读时算：一线把素材重新归过类，
    不该把已经定性的文案一起带走——那是两组不同的判定对象（审核台筛的就是文案自己那列）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        a_id = await _cat_id(client, hm, "C")
        asset_id, _ = await _make_ready_asset(client, hm, category_id=a_id)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            r = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm
            )
        assert r.status_code == 200, r.text
        copies = await _rows(AssetSummary)
        assert len(copies) == 3 and all(c.category_id is not None for c in copies)
        assert {str(c.category_id) for c in copies} == {a_id}, "三条候选都要继承到原型"

        # 审核台逐条改：改成 B
        b_id = await _cat_id(client, hm, "B")
        ids = [str(c.id) for c in copies]
        asg = await client.post(
            "/api/assets/categories/assign",
            json={"asset_ids": [], "summary_ids": ids[:1], "category_id": b_id},
            headers=hm,
        )
        assert asg.status_code == 200 and asg.json()["summary_changed"] == 1, asg.text
        assert (await _row_of(AssetSummary, ids[0])).category_id == uuid.UUID(b_id)
        trail = await _rows(AuditLog, AuditLog.action == "asset.category.assign")
        assert len(trail) == 1, trail
        # 改前的值在 before 里查得回来（手法同 text_before_edit：不能只记"改过"）
        assert trail[0].before["summaries"] == [
            {"id": ids[0], "before": a_id}
        ], trail[0].before

        # 素材重新归类**不回写**已出稿的文案
        e_id = await _cat_id(client, hm, "E")
        await client.post(
            "/api/assets/categories/assign",
            json={"asset_ids": [asset_id], "summary_ids": [], "category_id": e_id},
            headers=hm,
        )
        assert (await _row_of(AssetSummary, ids[1])).category_id == uuid.UUID(a_id), "已定性的文案不跟着素材漂"
        await client.aclose()

    _run(_scenario())


def test_assign_category_reports_what_it_could_not_find():
    """点分类：点名里查不到的 id 要如实回传，不许"看起来改成功了"。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        cid = await _cat_id(client, hm, "F")
        imp = await _import(client, hm, [DOUYIN_1])
        assert imp.status_code == 201, imp.text
        real = imp.json()["items"][0]["id"]
        assert imp.json()["items"][0]["category_id"] is None, "不选就是未分类，不许默认塞一个"
        ghost = str(uuid.uuid4())

        r = await client.post(
            "/api/assets/categories/assign",
            json={"asset_ids": [real, ghost], "summary_ids": [], "category_id": cid},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["not_found"] == [ghost], body
        assert body["asset_changed"] == 1
        assert (await _row_of(AssetItem, real)).category_id == uuid.UUID(cid)

        # 留空＝清成未分类（不是"不改"）
        r2 = await client.post(
            "/api/assets/categories/assign",
            json={"asset_ids": [real], "summary_ids": [], "category_id": None},
            headers=hm,
        )
        assert r2.status_code == 200 and r2.json()["asset_changed"] == 1, r2.text
        assert (await _row_of(AssetItem, real)).category_id is None

        # 空点名 → 400；脏 id → 400（不是 500）
        assert (await client.post("/api/assets/categories/assign",
                                  json={"asset_ids": [], "summary_ids": [], "category_id": cid},
                                  headers=hm)).status_code == 400
        assert (await client.post("/api/assets/categories/assign",
                                  json={"asset_ids": ["not-a-uuid"], "summary_ids": [], "category_id": cid},
                                  headers=hm)).status_code == 400

        # 单次条数借的是「单批导入上限」（100），**不是**反推/出文案那个 20 条上限：
        # 点分类不花钱、不等模型，卡 20 会让人一次只能挑一屏（25 条必须照常收下）
        many = [str(uuid.uuid4()) for _ in range(25)]
        r25 = await client.post("/api/assets/categories/assign",
                                json={"asset_ids": many, "summary_ids": [], "category_id": cid}, headers=hm)
        assert r25.status_code == 200 and len(r25.json()["not_found"]) == 25, r25.text
        over = [str(uuid.uuid4()) for _ in range(int(settings.ASSET_IMPORT_BATCH_MAX) + 1)]
        big = await client.post("/api/assets/categories/assign",
                                json={"asset_ids": over, "summary_ids": [], "category_id": cid}, headers=hm)
        assert big.status_code == 400 and "单次最多点" in big.json()["detail"], big.text
        await client.aclose()

    _run(_scenario())


def test_import_accepts_prototype_and_rejects_a_bad_one():
    """导入时的"整批默认原型"：合法就整批带上，指向不存在的原型当场 400（不静默变未分类）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        cid = await _cat_id(client, hm, "A")
        r = await _import(client, hm, [DOUYIN_1, DOUYIN_2], category_id=cid)
        assert r.status_code == 201, r.text
        items = r.json()["items"]
        assert len(items) == 2 and all(i["category_id"] == cid for i in items), items

        bad = await _import(client, hm, [DOUYIN_1], category_id=str(uuid.uuid4()))
        assert bad.status_code == 400 and "不存在" in bad.json()["detail"], bad.text
        dirty = await _import(client, hm, [DOUYIN_1], category_id="not-a-uuid")
        assert dirty.status_code == 400, dirty.text
        await client.aclose()

    _run(_scenario())


def test_list_endpoints_filter_by_prototype_and_unclassified():
    """两个列表口都能按原型筛，且 `none` 筛未分类（列表页那句"未分类 N 条"的数据源）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        a_id = await _cat_id(client, hm, "A")
        g_id = await _cat_id(client, hm, "G")
        await _import(client, hm, [DOUYIN_1], category_id=a_id)
        await _import(client, hm, [DOUYIN_2], category_id=g_id)
        # 未分类那条**必须另起一部片子**（DOUYIN_3），并用 _make_ready_asset 拿到行 id：
        # 库里素材行是按归一化链接判重的，重链接会被 skip、建不出行。
        real3, _task3 = await _make_ready_asset(client, hm, url=DOUYIN_3)

        la = await client.get(f"/api/assets?category_id={a_id}", headers=hm)
        assert [i["code"] for i in la.json()["items"]] and la.json()["total"] == 1, la.json()
        assert la.json()["items"][0]["category_name"].startswith("原型 A"), la.json()["items"][0]
        lg = await client.get(f"/api/assets?category_id=none", headers=hm)
        assert lg.json()["total"] == 1 and lg.json()["items"][0]["id"] == real3, lg.json()
        assert lg.json()["items"][0]["category_name"] is None
        bad = await client.get("/api/assets?category_id=not-a-uuid", headers=hm)
        assert bad.status_code == 400, bad.text

        # 文案侧：给那条未分类素材补出文案，然后按原型筛队列
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/summaries/generate",
                              json={"asset_ids": [real3]}, headers=hm)
        ls_all = await client.get("/api/assets/summaries", headers=hm)
        assert ls_all.json()["total"] == 3, ls_all.json()
        ls_none = await client.get("/api/assets/summaries?category_id=none", headers=hm)
        assert ls_none.json()["total"] == 3, ls_none.json()
        ls_a = await client.get(f"/api/assets/summaries?category_id={a_id}", headers=hm)
        assert ls_a.json()["items"] == []
        # 点一条文案挂到 G 上，队列筛选立刻按**文案自己**那列走
        sid = ls_none.json()["items"][0]["id"]
        await client.post("/api/assets/categories/assign",
                          json={"asset_ids": [], "summary_ids": [sid], "category_id": g_id}, headers=hm)
        ls_g = await client.get(f"/api/assets/summaries?category_id={g_id}", headers=hm)
        assert [i["id"] for i in ls_g.json()["items"]] == [sid], ls_g.json()
        assert ls_g.json()["items"][0]["category_name"].startswith("原型 G")
        await client.aclose()

    _run(_scenario())


# ────────────────  12. 抽帧（批 F：审核台卡片图 + 封面图）  ────────────────

_HAS_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_FRAMES_CLIP = _TMPDIR / "frames_clip.mp4"

# 抽帧是**纯呈现层**：这条清单就是"业务面"的口径，前后必须一模一样。
# 只列序列化后与 ORM 取值同型的字段（cost_* 是 Decimal/float、id 是 UUID/str，比不得）。
_BUSINESS_FIELDS = (
    "source_kind", "source_url", "file_name", "file_key", "bucket",
    "title", "duration", "resolution", "prompt_max_duration",
    "stage_import", "stage_prompt", "stage_summary", "stage_produce", "stage_compose",
    "status", "has_approved_copy", "note",
)


def _make_frames_clip() -> str:
    """真造一条 6 秒 720x1280 的片子：抽帧这段只有真 ffmpeg 才算验过。"""
    if not _FRAMES_CLIP.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=25:duration=6",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(_FRAMES_CLIP)],
            check=True, capture_output=True,
        )
    return str(_FRAMES_CLIP)


def _clip_download_writer():
    """mock 桶读取：把真片子"取回"到调用方要的路径，后面 ffmpeg 真在这条文件上跑。"""
    src = _make_frames_clip()

    async def _dl(bucket, object_key, local_path):
        shutil.copyfile(src, local_path)
        return True

    return AsyncMock(side_effect=_dl)


def _frame_put_recorder(store: dict):
    """mock 桶写入：按 key 收字节，顺带抓住 content_type（帧必须是 image/jpeg）。"""

    async def _put(bucket, object_key, file_path, content_type="application/octet-stream"):
        with open(file_path, "rb") as fh:
            store[object_key] = (fh.read(), content_type)
        return True

    return AsyncMock(side_effect=_put)


async def _add_output(asset_id: str, name: str) -> str:
    """直接插一条产物（拼接口的替身）：批 F 只关心"产物也能挂帧"这件事。"""
    async with dbmod.async_session_factory() as s:
        o = AssetOutput(
            asset_id=uuid.UUID(asset_id), kind="composed",
            file_key=f"asset/composed/{name}.mp4", bucket=settings.MINIO_BUCKET_RAW,
            file_name=name, duration=6.0, resolution="720x1280",
        )
        s.add(o)
        await s.commit()
        return str(o.id)


def _frames_env(store):
    """抽帧用例的公共 mock：桶读写 + 时长。整段套住，别让自动排的任务跑到 patch 外面。"""
    return (
        patch("app.api.assets.upload_file_from_path", _frame_put_recorder(store)),
        patch("app.api.assets.download_to_file", _clip_download_writer()),
        patch("app.api.assets._ffprobe_duration", lambda p: 6.0),
    )


def test_upload_batch_auto_enqueues_frames_job_and_fills_cover():
    """文件入库 → 系统自动排抽帧 → 真 ffmpeg 抽出 3 单帧 + 1 九宫格 → 封面列第一次有值。

    这条是批 F 的主干：`cover_image_key` 这列从 0055 建出来就一直**没有写入方**
    （列表那格永远空转），批 F 起它写的是第 1 张单帧。
    """
    if not _HAS_FF:
        pytest.skip("本机/CI 没装 ffmpeg+ffprobe，抽帧主干跑不了")
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        store: dict = {}
        p1, p2, p3 = _frames_env(store)
        with p1, p2, p3:
            resp = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("卡片原片.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
            assert resp.status_code == 201, resp.text
            body = resp.json()
            aid = body["items"][0]["id"]
            # 抽帧前的业务面快照：跑完还要一模一样（纯呈现层的判据得有个"前"）
            before = {f: body["items"][0][f] for f in _BUSINESS_FIELDS}
            assert body["items"][0]["cover_image_key"] is None, "入库那一刻封面还是空的"

            # ① 响应说清了"抽帧已排后台"，而且台账里真有一行 kind=frames
            assert body["frames"]["queued"] is True, body["frames"]
            assert "抽帧" in body["message"], body["message"]
            jobs = await _rows(AssetJob, AssetJob.kind == JOB_FRAMES)
            assert len(jobs) == 1 and jobs[0].planned_units == 1, [j.kind for j in jobs]

            # ② 轮到终态（同一套 D-1 台账，不另开队列）
            done = await _wait_job(client, h["admin"], body["frames"]["job_id"])
        assert done["status"] == "succeeded", done
        assert done["result"]["extracted"] == 1, done["result"]
        assert done["kind_label"] == "抽帧"

        rows = await _rows(AssetFrame, AssetFrame.asset_id == uuid.UUID(aid))
        kinds = sorted(f"{r.kind}:{r.seq}" for r in rows)
        assert kinds == ["grid:0", "thumb:0", "thumb:1", "thumb:2"], kinds

        # ③ 帧真的进了桶：JPEG 头 + 有字节（0 字节对象照样 200 那个坑在这再挡一次）
        frame_keys = [k for k in store if k.startswith("asset/frames/")]
        assert len(frame_keys) == 4, sorted(store)
        for key in frame_keys:
            payload, ctype = store[key]
            assert ctype == "image/jpeg" and payload[:3] == b"\xff\xd8\xff", key
            assert len(payload) > 1000, (key, len(payload))

        by_key = {f"{r.kind}:{r.seq}": r for r in rows}
        # ④ 尺寸按原片 720x1280 等比：单帧 360x640、九宫格整图 1080x1920
        assert by_key["thumb:0"].width == int(settings.ASSET_FRAME_THUMB_WIDTH)
        assert by_key["thumb:0"].height == 640, by_key["thumb:0"].height
        assert by_key["grid:0"].width == int(settings.ASSET_FRAME_GRID_WIDTH)
        assert by_key["grid:0"].height == 1920, by_key["grid:0"].height
        # ⑤ 不取 t=0：三张分别落在 10%/45%/80%
        assert [by_key[f"thumb:{i}"].t_offset for i in range(3)] == [0.6, 2.7, 4.8]
        # ⑥ 每行都记了"抽自哪个对象"，日后查"帧和视频对不上"不用猜
        assert {r.source_file_key for r in rows} == {body["items"][0]["file_key"]}

        # ⑦ 封面写入方（本批的全部意义之一）
        item = await _row_of(AssetItem, aid)
        assert item.cover_image_key == by_key["thumb:0"].file_key

        # ⑧ 纯呈现层：抽帧前后业务字段**一个都没变**（拿抽帧前的快照比，不是自己比自己）
        after = {f: getattr(item, f) for f in _BUSINESS_FIELDS}
        assert after == before, f"抽帧动了业务字段：{[(k, before[k], after[k]) for k in before if before[k] != after[k]]}"
        assert item.stage_prompt == "pending" and item.stage_summary == "pending"

        # ⑨ 取图口：inline presign（不许挂 attachment，否则卡片是黑块）、不写审计
        audit_before = await _count(AuditLog)
        presign = AsyncMock(return_value="http://minio:9000/f.jpg?sig=1")
        with patch("app.api.assets.get_presigned_url", presign):
            got = await client.get(f"/api/assets/frames?asset_ids={aid}", headers=hm)
        assert got.status_code == 200, got.text
        body2 = got.json()
        assert len(body2["frames"]) == 4
        slot = body2["by_asset"][aid]
        assert [t["seq"] for t in slot["thumbs"]] == [0, 1, 2], "卡片左侧横排要按 seq 给"
        assert slot["grid"]["kind"] == "grid" and slot["grid"]["url"].endswith("sig=1")
        assert body2["cover_url"][aid].endswith("sig=1")
        assert body2["missing"] == []
        assert presign.await_count == 5, presign.await_count  # 4 帧 + 1 封面
        for call in presign.await_args_list:
            assert call.kwargs.get("as_attachment", False) is False, "挂上 attachment 播放器/图片都吃不到"
        assert await _count(AuditLog) == audit_before, "看图不是交付动作，别淹了审计页"

        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_frames_are_overwritten_not_duplicated_and_two_outputs_do_not_collide():
    """重抽＝覆盖（4 行还是 4 行）；同一素材的两个产物各占一行，不撞 `(asset_id,kind,seq)`。

    第二条是本批唯一"只有真库才会露出来"的设计点：如果照原计划用
    `UniqueConstraint(asset_id, kind, seq)`，两个产物的 `output_thumb` 都是 seq=0，
    第二个直接 IntegrityError——所以幂等键拆成两条**部分**唯一索引。
    """
    if not _HAS_FF:
        pytest.skip("本机/CI 没装 ffmpeg+ffprobe")
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        store: dict = {}
        p1, p2, p3 = _frames_env(store)
        with p1, p2, p3:
            resp = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("重抽.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
            aid = resp.json()["items"][0]["id"]
            await _wait_job(client, h["admin"], resp.json()["frames"]["job_id"])
            assert await _count(AssetFrame) == 4

            # ① 不带 force 再点一次：一句"已经有 4 张帧"就完事，不重跑 ffmpeg
            again = await client.post(
                "/api/assets/frames/extract", json={"asset_ids": [aid]}, headers=hm)
            assert again.status_code == 200, again.text
            b = again.json()
            assert b["extracted"] == 0 and b["skipped"] == 1, b
            assert "已经有" in b["results"][0]["reason"], b["results"][0]

            # ② 带 force：覆盖同键，行数不涨（幂等键真的在挡事）
            forced = await client.post(
                "/api/assets/frames/extract",
                json={"asset_ids": [aid], "force": True}, headers=hm)
            assert forced.json()["extracted"] == 1, forced.json()
        assert await _count(AssetFrame) == 4, [
            (r.kind, r.seq) for r in await _rows(AssetFrame)]

        # ③ 两个产物都抽首帧：两行、同 seq=0、键是 (output_id,kind,seq)
        out_a = await _add_output(aid, "A 版.mp4")
        out_b = await _add_output(aid, "B 版.mp4")
        store2: dict = {}
        with patch("app.api.assets.upload_file_from_path", _frame_put_recorder(store2)), \
             patch("app.api.assets.download_to_file", _clip_download_writer()):
            r = await client.post(
                "/api/assets/frames/extract",
                json={"output_ids": [out_a, out_b]}, headers=hm)
        assert r.status_code == 200, r.text
        assert r.json()["extracted"] == 2, r.json()
        rows = await _rows(AssetFrame, AssetFrame.kind == FRAME_OUTPUT_THUMB)
        assert len(rows) == 2, [(x.output_id, x.seq) for x in rows]
        assert {x.seq for x in rows} == {0}
        assert {str(x.output_id) for x in rows} == {out_a, out_b}
        assert all(x.asset_id is not None for x in rows), "产物帧也挂素材：卡片一条查询拿全"
        # 产物帧不动素材封面
        item = await _row_of(AssetItem, aid)
        assert item.cover_image_key and "output_thumb" not in item.cover_image_key

        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_frames_skip_what_they_cannot_draw_and_never_touches_the_bucket():
    """链接素材／时长未知／超上限：一律 skipped 带人话原因，而且**一次下载都不发起**。

    「不许把整集片拖回来只为抽三张图」是靠这条钉住的：跳过判定在 I/O 之前，
    所以 download_to_file 的调用次数必须是 0。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        # 链接素材（桶里没文件）
        link_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        dl = AsyncMock(return_value=False)
        with patch("app.api.assets.download_to_file", dl), \
             patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            r = await client.post(
                "/api/assets/frames/extract", json={"asset_ids": [link_id]}, headers=hm)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["skipped"] == 1 and body["extracted"] == 0, body
        assert "链接素材" in body["results"][0]["reason"], body["results"][0]
        assert dl.await_count == 0, "跳过判定必须在下载之前"

        # 超上限的整集片（1200s > ASSET_FRAME_MAX_SOURCE_SECONDS=900）
        store: dict = {}
        with patch("app.api.assets.upload_file_from_path", _frame_put_recorder(store)), \
             patch("app.api.assets.download_to_file", _clip_download_writer()), \
             patch("app.api.assets._ffprobe_duration", lambda p: 1200.0):
            up = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("整集.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
            long_id = up.json()["items"][0]["id"]
            r2 = await client.post(
                "/api/assets/frames/extract", json={"asset_ids": [long_id]}, headers=hm)
        assert "超过抽帧上限" in r2.json()["results"][0]["reason"], r2.json()["results"][0]
        assert await _count(AssetFrame) == 0, "跳过的东西不该留下半张图"

        # 时长未知（老数据没回填）：也算不出时间点
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(long_id))
            a.duration = None
            await s.commit()
        with patch("app.api.assets.download_to_file", _clip_download_writer()):
            r3 = await client.post(
                "/api/assets/frames/extract", json={"asset_ids": [long_id]}, headers=hm)
        assert "时长未知" in r3.json()["results"][0]["reason"], r3.json()["results"][0]

        # 参数面：没点名 / 非法 id / 超单批上限
        assert (await client.post(
            "/api/assets/frames/extract", json={}, headers=hm)).status_code == 400
        assert (await client.post(
            "/api/assets/frames/extract", json={"asset_ids": ["不是id"]}, headers=hm)).status_code == 400
        too_many = {"asset_ids": [str(uuid.uuid4()) for _ in range(21)]}
        r4 = await client.post("/api/assets/frames/extract", json=too_many, headers=hm)
        assert r4.status_code == 400 and "async_mode" in r4.json()["detail"], r4.json()

        # 取图口的入参面：非法 id / 没点名 / 不认识的 kind / 超 50
        assert (await client.get("/api/assets/frames", headers=hm)).status_code == 400
        assert (await client.get("/api/assets/frames?asset_ids=zzz", headers=hm)).status_code == 400
        assert (await client.get(
            f"/api/assets/frames?asset_ids={long_id}&kind=nope", headers=hm)).status_code == 400
        over = ",".join(str(uuid.uuid4()) for _ in range(51))
        assert (await client.get(f"/api/assets/frames?asset_ids={over}", headers=hm)).status_code == 400
        # 不存在的素材：200 + missing（不是 404，卡片要的是"这条没图"）
        ghost = await client.get(f"/api/assets/frames?asset_ids={str(uuid.uuid4())}", headers=hm)
        assert ghost.status_code == 200 and len(ghost.json()["missing"]) == 1

        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_downloaded_link_asset_gets_frames():
    """11-05 易操作性评估 P0-1 收口：链接素材**下载完成后**（file_key 非空）抽帧必须真抽得出来。

    修前两头一起堵死：排程侧下载完成后没人排、执行侧 `source_kind != SOURCE_FILE`
    见链接素材就跳过（file_key 非空也一样）——现网 asset_frames 0 行、审核台永远
    「没有预览图」就是这么来的。修后判据只看 file_key；没下载的链接素材照旧跳过，
    话术指向「下载完成后系统自动补排」。
    """
    if not _HAS_FF:
        pytest.skip("本机/CI 没装 ffmpeg+ffprobe")
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        link_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        # 模拟「下载原片完成」：原片落自有桶、时长已探、下载状态 success
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(link_id))
            a.file_key = f"asset/source/{a.code}/abc123.mp4"
            a.bucket = settings.MINIO_BUCKET_RAW
            a.duration = 6.0
            a.download_status = "success"
            await s.commit()

        store: dict = {}
        p1, p2, p3 = _frames_env(store)
        with p1, p2, p3:
            r = await client.post(
                "/api/assets/frames/extract", json={"asset_ids": [link_id]}, headers=hm)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["extracted"] == 1 and body["frames"] == 4, body
        rows = await _rows(AssetFrame, AssetFrame.asset_id == uuid.UUID(link_id))
        assert sorted(f"{x.kind}:{x.seq}" for x in rows) == ["grid:0", "thumb:0", "thumb:1", "thumb:2"]
        # 封面跟着补上（审核台卡片有图的第一来源）
        thumb0 = [x for x in rows if x.kind == "thumb" and x.seq == 0][0]
        assert (await _row_of(AssetItem, link_id)).cover_image_key == thumb0.file_key
        # 帧确实进桶且是真 JPEG
        frame_keys = [k for k in store if k.startswith("asset/frames/")]
        assert len(frame_keys) == 4 and all(store[k][0][:3] == b"\xff\xd8\xff" for k in frame_keys)

        # 反面钉住：链接素材**没** file_key 仍然跳过，话术指向自动补排而不是死路
        # （换一条没用过的链接，重复链接会被导入去重吃掉）
        link2, _ = await _make_ready_asset(client, hm, url=DOUYIN_2)
        with patch("app.api.assets.download_to_file", AsyncMock(return_value=False)):
            r2 = await client.post(
                "/api/assets/frames/extract", json={"asset_ids": [link2]}, headers=hm)
        assert r2.json()["skipped"] == 1, r2.json()
        reason = r2.json()["results"][0]["reason"]
        assert "链接素材" in reason and "自动补排" in reason, reason

        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_frames_job_is_queued_by_async_mode_and_hidden_from_the_default_ledger():
    """手动 `async_mode=true` 走同一套台账；`GET /assets/jobs` 默认**不列**抽帧。

    后端重放本口时 `async_mode` 被摘掉，所以台账里只有 1 行（不自我套娃）；
    横幅默认只看人点的活，否则人人都有的抽帧会把「我刚点的那批还在不在跑」挤出去。
    """
    if not _HAS_FF:
        pytest.skip("本机/CI 没装 ffmpeg+ffprobe")
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        store: dict = {}
        p1, p2, p3 = _frames_env(store)
        with p1, p2, p3:
            resp = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("横幅.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
            aid = resp.json()["items"][0]["id"]
            await _wait_job(client, h["admin"], resp.json()["frames"]["job_id"])

            r = await client.post(
                "/api/assets/frames/extract",
                json={"asset_ids": [aid], "force": True, "async_mode": True}, headers=hm)
            assert r.status_code == 200, r.text
            ack = r.json()
            assert ack["queued"] is True and "results" not in ack, ack
            done = await _wait_job(client, h["admin"], ack["job_id"])
        assert done["status"] == "succeeded", done
        assert done["kind"] == JOB_FRAMES and done["kind_label"] == "抽帧"
        assert done["progress"]["note"].startswith("抽帧进度"), done["progress"]

        frames_jobs = await _rows(AssetJob, AssetJob.kind == JOB_FRAMES)
        assert len(frames_jobs) == 2, [j.status for j in frames_jobs]
        assert await _count(AssetFrame) == 4, "重放是覆盖，不是第二份"

        default = await client.get("/api/assets/jobs", headers=hm)
        assert default.json()["items"] == [], default.json()
        opened = await client.get("/api/assets/jobs?only_open=true", headers=hm)
        assert opened.json()["items"] == []
        with_frames = await client.get("/api/assets/jobs?include_frames=true", headers=hm)
        assert len(with_frames.json()["items"]) == 2, with_frames.json()
        by_kind = await client.get(f"/api/assets/jobs?kind={JOB_FRAMES}", headers=hm)
        assert len(by_kind.json()["items"]) == 2

        # 自动排的那次也留了痕：提交动作进审计（人点的手动口另算一条 asset.frames.extract）
        audits = await _rows(AuditLog, AuditLog.action == "asset.job.frames.submit")
        assert len(audits) == 2, [a.action for a in audits]

        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_frames_extraction_never_breaks_the_upload_that_triggered_it():
    """抽帧排程失败**不许**把已经落库的导入带崩（纯呈现层的代价只能由呈现层自己吃）。

    这里把 `_start_asset_job` 打成异常——真机上对应"排程时库抖了一下"。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._ffprobe_duration", lambda p: 8.0), \
             patch("app.api.assets._start_asset_job", AsyncMock(side_effect=RuntimeError("库抖了"))):
            resp = await client.post(
                "/api/assets/upload/batch",
                files=[("files", ("排程失败.mp4", VIDEO_BYTES, "video/mp4"))], headers=hm)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["items"]) == 1, body
        assert body["frames"]["queued"] is False and "没排上" in body["frames"]["note"], body["frames"]
        assert await _count(AssetItem) == 1, "素材行不能因为抽帧没排上而回滚"
        assert await _count(AssetJob) == 0

        # 链接导入本来就没文件：明确告知"这次没排抽帧"，别让前端以为在排
        imp = await _import(client, hm, [DOUYIN_3])
        assert imp.status_code == 201, imp.text
        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_review_list_carries_output_count_for_the_card_badge():
    """卡片右侧「已产 N 条」：按 `summary → production → output` 一条 join 数给前端。

    三个口径必须钉住，否则徽标就是假信息：
    1. **只数视频**——交付包 zip（package）/文案 txt（copy）是附属文件，
       一条成片配个 zip 不能显示成"产了 2 条"；
    2. **没挂生产单的拼接产物不计**——那是"两段拼的"，不归到某条文案头上；
    3. 0 和"没查"是两回事：列表口整页聚合后**每条都有这个键**（没产就是 0），
       素材详情口不查 → 键**不存在**，前端拿 undefined 就不画徽标。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        clean = _approvable(items)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [clean["id"]], "action": "approve"}, headers=ha)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/produce",
                              json={"summary_ids": [clean["id"]], "n": 1}, headers=ha)
        prod = (await _rows(AssetProduction))[0]

        async with dbmod.async_session_factory() as s:
            s.add_all([
                # ① 真成片：算
                AssetOutput(id=uuid.uuid4(), production_id=prod.id, asset_id=uuid.UUID(asset_id),
                            kind="composed", file_key="o/1.mp4", bucket=settings.MINIO_BUCKET_RAW,
                            file_name="成片.mp4"),
                # ② 交付包 zip：不算
                AssetOutput(id=uuid.uuid4(), production_id=prod.id, asset_id=uuid.UUID(asset_id),
                            kind="package", file_key="o/2.zip", bucket=settings.MINIO_BUCKET_RAW,
                            file_name="交付包.zip"),
                # ③ 没挂生产单的拼接：不算（归不到这条文案头上）
                AssetOutput(id=uuid.uuid4(), production_id=None, asset_id=uuid.UUID(asset_id),
                            kind="composed", file_key="o/3.mp4", bucket=settings.MINIO_BUCKET_RAW,
                            file_name="随手拼的.mp4"),
            ])
            await s.commit()

        listed = await client.get("/api/assets/summaries", headers=hm)
        assert listed.status_code == 200, listed.text
        by_id = {i["id"]: i for i in listed.json()["items"]}
        assert by_id[clean["id"]]["output_count"] == 1, by_id[clean["id"]]
        others = [i for iid, i in by_id.items() if iid != clean["id"]]
        assert others and all("output_count" in i and i["output_count"] == 0 for i in others), \
            "整页都要带这个键（没产＝0），别留 nil 让前端自己猜"

        # 素材详情口不查这件事 → 键不存在（回 0 会是假信息）
        detail = await client.get(f"/api/assets/{asset_id}", headers=hm)
        s0 = detail.json()["summaries"][0]
        assert "output_count" not in s0, sorted(s0)

        await client.aclose()

    _run(_scenario())



# ────────────────  13. 图片入库（11-05 批 G：media_kind ＋ 四环拒图）  ────────────────


def _png_bytes(width: int, height: int) -> bytes:
    """纯 stdlib 造一张真能ffprobe出宽高的 PNG（不依赖 PIL，测试侧零新增依赖）。

    为什么非要"真图"：`_ingest_one_image_file` 用 ffprobe 量尺寸，喂它一坨
    `b"\\x89PNG"` 假头会探不到 → 断言 `resolution` 就变成在测"探不到"这件事。
    """
    import struct
    import zlib

    def _chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 1))
        + _chunk(b"IEND", b"")
    )


PNG_PORTRAIT = _png_bytes(720, 1280)   # 9:16 竖版（成片同画幅）
PNG_LANDSCAPE = _png_bytes(1280, 720)  # 16:9 横版（投出去会出横屏，必须提醒）


async def _upload_mixed(client, hm, files):
    """一次视频入库（桶 mock、视频时长 mock 6s），返回响应体。

    11-25 批 W 起 /upload/batch 只收视频：图片传进来不入库，逐张落在 `failed`
    里指路「角色卡」库。要传卡走 `_upload_cards`。
    """
    with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
         patch("app.api.assets._ffprobe_duration", lambda p: 6.0):
        resp = await client.post("/api/assets/upload/batch", files=files, headers=hm)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _upload_cards(client, hm, files):
    """传角色卡（POST /api/assets/cards，桶 mock），断言 201 后回响应体。

    卡口不做任何视频 I/O：量尺寸走 `_probe_image_size`（真 ffprobe，测什么是什么）。
    """
    with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
        resp = await client.post("/api/assets/cards", files=files, headers=hm)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_upload_accepts_images_but_only_bills_videos():
    """11-25 批 W：/upload/batch 混传视频+图片 → **只有视频入库**，图片逐张指路「角色卡」库。

    这条是批 W 的主干，钉住四件只有走接口才看得见的事：
    1. 图片不再当素材行：`items` 只有视频，两张图各在 `failed` 里有一条以
       「图片不入素材库（11-25 起）」开头的指路条目；
    2. 旧响应里的 `image_notes` 键已删除（画幅提醒跟着卡走 cards 口）；
    3. 预算/审计仍只数视频：混进图片数就是把 3 个对象报成 3 条待反推；
    4. 图片文件不做任何 I/O：一个字节都不落盘、不传桶。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        sent = []

        async def _recording_put(bucket, key, path, content_type="application/octet-stream"):
            with open(path, "rb") as fh:
                sent.append((key, content_type, fh.read()))
            return True

        with patch("app.api.assets.upload_file_from_path", _recording_put), \
             patch("app.api.assets._ffprobe_duration", lambda p: 6.0):
            resp = await client.post(
                "/api/assets/upload/batch",
                files=[
                    ("files", ("原片.mp4", VIDEO_BYTES, "video/mp4")),
                    # 扩展名只喂"是不是图"这一件事：批 W 起图片逐条进 failed，扩展名不参与入库
                    ("files", ("三视图.jpg", PNG_LANDSCAPE, "image/jpeg")),
                    ("files", ("角色卡.png", PNG_PORTRAIT, "image/png")),
                ],
                headers=hm,
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # ① 图片不入素材库：items 只有视频，两张图逐条进 failed 且话术指路
        assert len(body["items"]) == 1, body
        vid = body["items"][0]
        assert vid["media_kind"] == "video" and vid["duration"] == 6.0
        assert vid["status"] == "waiting_prompt", "视频口径一个字没动"
        assert vid["file_name"] == "原片.mp4"

        assert len(body["failed"]) == 2, body["failed"]
        by_name = {f["file_name"]: f["error"] for f in body["failed"]}
        assert set(by_name) == {"三视图.jpg", "角色卡.png"}, by_name
        for name, err in by_name.items():
            assert err.startswith("图片不入素材库（11-25 起）"), (name, err)
            assert "角色卡" in err, (name, err)

        # ② 旧键已删：批 W 起 upload/batch 响应里没有 image_notes
        assert "image_notes" not in body, sorted(body)

        # ③ 图片零 I/O：落桶的只有视频那一个对象（图片偷偷做了 I/O 就不止一条）
        assert len(sent) == 1 and sent[0][1] == "video/mp4", sent

        # ④ 预算只数视频：3 个对象 → 按 1 条估
        unit = 0.00054 * 180 + 0.001
        assert body["budget"]["cost_estimate"] == pytest.approx(unit, abs=1e-4), body["budget"]
        assert body["budget"]["gate"] == "ok"

        # ⑤ 审计仍只记视频入库这一件事，图片没触发第二类审计
        audits = await _rows(AuditLog, AuditLog.action == "asset.upload_files")
        assert len(audits) == 1, [(a.action, a.after) for a in audits]
        assert audits[0].after["created"] == 1 and audits[0].after["failed"] == 2, audits[0].after

        # ⑥ 库里只有视频这一行；批次件数只记视频
        rows = await _rows(AssetItem)
        assert [r.file_name for r in rows] == ["原片.mp4"], [r.file_name for r in rows]
        batch = (await _rows(AssetBatch))[0]
        assert batch.item_count == 1, "件数记入库的视频，图片从没进来过"

        await client.aclose()

    _run(_scenario())


def test_cards_endpoint_upload_measures_and_warns():
    """cards 口是 11-25 批 W 起**唯一**的图片入库口：量尺寸、横版提醒、审计、素材表不见。

    旧「图片当素材行」的用例搬到这里：同一张真 PNG（ffprobe 量得出宽高），
    走 POST /api/assets/cards 后——items 两条都进 `asset_cards`、resolution 是
    真量出来的值、横版那张当场给提醒、审计 action=asset.card.upload、
    而**素材表（GET /api/assets）里查不到这些图**。
    """
    if not _HAS_FF:
        pytest.skip("本机/CI 没装 ffprobe，量不出尺寸就没法断言 resolution")
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        body = await _upload_cards(client, hm, [
            ("files", ("竖版卡.png", PNG_PORTRAIT, "image/png")),
            ("files", ("横版卡.png", PNG_LANDSCAPE, "image/png")),
        ])

        # ① 两张都入库，resolution 是 ffprobe 真量出来的
        assert len(body["items"]) == 2 and body["failed"] == [], body
        by_name = {i["file_name"]: i for i in body["items"]}
        assert by_name["竖版卡.png"]["resolution"] == "720x1280", by_name
        assert by_name["横版卡.png"]["resolution"] == "1280x720", by_name

        # ② 横版那张当场提醒；竖版那张干净
        notes = {n["file_name"]: n for n in body["image_notes"]}
        assert "横版卡.png" in notes, body["image_notes"]
        assert notes["横版卡.png"]["resolution"] == "1280x720"
        assert notes["横版卡.png"]["ratio"] == "16:9", notes
        assert any("横版" in n and "横屏" in n for n in notes["横版卡.png"]["notes"]), notes
        assert "竖版卡.png" not in notes, notes
        assert "画幅" in body["message"], body["message"]

        # ③ 审计落了 asset.card.upload 一条
        audits = await _rows(AuditLog, AuditLog.action == "asset.card.upload")
        assert len(audits) == 1, [(a.action, a.after) for a in audits]
        assert audits[0].after["created"] == 2 and audits[0].after["failed"] == 0, audits[0].after

        # ④ 素材表里没有这些图：GET /api/assets 查不到，库行数也是 0
        listed = await client.get("/api/assets?page_size=100", headers=hm)
        assert listed.status_code == 200, listed.text
        names = [i["file_name"] for i in listed.json()["items"]]
        assert "竖版卡.png" not in names and "横版卡.png" not in names, names
        assert await _count(AssetItem) == 0, "图片不许再进素材表（11-25 批 W）"
        assert await _count(AssetBatch) == 0, "卡不占批次"

        await client.aclose()

    _run(_scenario())


def test_image_only_batch_is_free_and_asks_for_no_frames_job():
    """纯图片上传（11-25 批 W）：**批次都不建**，逐条指路「角色卡」库，零 I/O 零台账。

    旧口径是"图片行入库但免费、不排抽帧"；批 W 之后图片压根不进素材库——
    image-only 上传连批次行都回滚掉（不留 0 条素材的空批次），抽帧/反推自然无活可干。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        body = await _upload_mixed(client, hm, [("files", ("角色卡.png", PNG_PORTRAIT, "image/png"))])
        # 批次回滚：items 空、batch/batch_id 双 None，图片条目在 failed 里带指路
        assert body["items"] == [], body
        assert body["batch"] is None and body["batch_id"] is None, body
        assert len(body["failed"]) == 1, body["failed"]
        assert body["failed"][0]["file_name"] == "角色卡.png"
        assert body["failed"][0]["error"].startswith("图片不入素材库（11-25 起）"), body["failed"]
        assert "没有成功入库的文件" in body["message"], body["message"]
        # 回滚是认真的：库里不留批次行，更不许留抽帧/反推台账
        assert await _count(AssetBatch) == 0, "图片-only 上传不许留空批次"
        assert await _count(AssetItem) == 0
        assert await _count(AssetJob) == 0, "纯图上传不该留下一行抽帧台账"
        assert await _count(AssetFrame) == 0
        await client.aclose()

    _run(_scenario(), with_frames=True)


def test_images_never_enter_the_paid_queues():
    """整批排队（反推／出文案）必须跳过图片 —— 图片现在**连库都不进**，这条钉的是双保险。

    11-25 批 W 起图片不再当素材行（上传口逐张指路「角色卡」库），所以批次里
    天然只有视频；这里用真实队列断言"取了几条、剩几条"，再钉住图片没进素材表。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        body = await _upload_mixed(client, hm, [
            ("files", ("原片.mp4", VIDEO_BYTES, "video/mp4")),
            ("files", ("角色卡A.png", PNG_PORTRAIT, "image/png")),
            ("files", ("角色卡B.png", PNG_PORTRAIT, "image/png")),
        ])
        bid = body["batch_id"]
        # 图片逐条进了 failed、没进 items
        assert [i["file_name"] for i in body["items"]] == ["原片.mp4"], body["items"]
        assert {f["file_name"] for f in body["failed"]} == {"角色卡A.png", "角色卡B.png"}, body["failed"]

        # 批次累计口径（熔断用的那把尺）：3 个对象里只有 1 条是"将来要花钱的"
        batch_uuid = uuid.UUID(bid)
        async with dbmod.async_session_factory() as s:
            pending_units = await assets_api._batch_pending_prompt_units(
                s, batch_ids={batch_uuid}, exclude_ids=[]
            )
        assert pending_units == 1, f"图片被算进待反推条数了：{pending_units}"

        created = []

        async def _create(db, **kw):
            created.append(kw)
            return _fake_prompt_task()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.download_to_file", _fake_download_writer()), \
             patch("app.api.assets.create_upload_prompt_task", AsyncMock(side_effect=_create)):
            r = await client.post(
                "/api/assets/analyze/batch",
                json={"batch_id": bid, "limit": 10, "confirmed": True}, headers=hm)
        assert r.status_code == 200, r.text
        q = r.json()["queue"]
        assert q["picked"] == 1, q
        assert q["remaining"] == 0, f"两张图被算进队列剩余了：{q}"
        assert len(created) == 1 and len(r.json()["results"]) == 1

        # 出文案侧同一个口径：图片不反推 → 永远没有详规，压根进不了 summary 队列
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_upload_prompt_task", AsyncMock(side_effect=_create)):
            again = await client.post(
                "/api/assets/analyze/batch",
                json={"batch_id": bid, "limit": 10, "confirmed": True}, headers=hm)
        assert again.status_code == 400, again.text
        assert "没有可提交反推" in again.json()["detail"], again.json()

        gen = await client.post(
            "/api/assets/summaries/generate",
            json={"batch_id": bid, "limit": 10}, headers=hm)
        assert gen.status_code == 400, gen.text
        assert "没有待出文案" in gen.json()["detail"], gen.json()
        assert await _count(AssetSummary) == 0

        # 素材表里只有视频这一行：图片压根没进来（更没有 image_ready 行可被队列捞走）
        rows = await _rows(AssetItem)
        assert [r_.file_name for r_ in rows] == ["原片.mp4"], [r_.file_name for r_ in rows]
        assert await _count(AssetItem) == 1
        await client.aclose()

    _run(_scenario())


def test_image_pointed_at_every_paid_gate_is_refused_in_plain_words():
    """点名形态也要挡图（四个花钱/花钱风险的口各验一次），而且**不 500、不扣费、不留孤儿行**。

    11-25 批 W 起图片从上传口进不了素材库了，但库里的**遗留图片行**（批 W 之前
    入的那批）仍然合法存在——五个付费口对它的防御分支一个都不能拆。这里直插一行
    遗留图片素材，逐个口点名试：判据是**理由说得清**，如果只回一句"不支持"，
    他的下一动作是换个口再试一遍（每个口都提交一次＝扣四次）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        body = await _upload_mixed(client, hm, [
            ("files", ("原片.mp4", VIDEO_BYTES, "video/mp4")),
        ])
        vid_id = body["items"][0]["id"]

        # 遗留图片素材行（批 W 前入库的形状）：直插，不走上传口（上传口已收不了图）
        img_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetItem(
                id=img_id, media_kind="image", source_kind="file",
                file_name="角色卡.png", file_key="asset/2026/11/24/角色卡.png",
                bucket=settings.MINIO_BUCKET_RAW, created_by=None,
                status="image_ready", stage_import="success",
            ))
            await s.commit()
        img_id = str(img_id)

        # ① 反推：200 + skipped（不是 400 —— 全被跳过是"没活干"，不是"你写错了"）
        created = []

        async def _create(db, **kw):
            created.append(kw)
            return _fake_prompt_task()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_upload_prompt_task", AsyncMock(side_effect=_create)), \
             patch("app.api.assets.download_to_file", _fake_download_writer()):
            r = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": [img_id]}, headers=hm)
        assert r.status_code == 400, r.text
        assert "没有能新提交反推的" in r.json()["detail"], r.json()   # 一条都没得跑 → 空队列话术（11-06 改成逐档说清）
        assert created == [], "点名图片绝不能发起外呼"

        # 混着点名：图进 skipped、视频正常进 todo（证明挡的是图，不是把整单打死）
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_upload_prompt_task", AsyncMock(side_effect=_create)), \
             patch("app.api.assets.download_to_file", _fake_download_writer()):
            mixed = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": [img_id, vid_id], "confirmed": True}, headers=hm)
        assert mixed.status_code == 200, mixed.text
        assert len(created) == 1, created
        why = mixed.json()["skipped"][0]["reason"]
        assert "图片" in why and "角色卡" in why and "扣一次钱" in why, why

        # ② 出文案：逐条 error 里点名是图片，且不落任何候选行
        gen = await client.post(
            "/api/assets/summaries/generate", json={"asset_ids": [img_id]}, headers=hm)
        assert gen.status_code == 200, gen.text
        res = gen.json()["results"][0]
        assert res["created"] == 0 and "图片" in res["error"], res
        assert "只吃视频" in res["error"], res
        assert await _count(AssetSummary) == 0

        # ③ 回源解析：跳过且明确"没发起外呼、没产生费用"
        resolve = await client.post(
            "/api/assets/resolve", json={"asset_ids": [img_id]}, headers=hm)
        assert resolve.status_code == 200, resolve.text
        rbody = resolve.json()
        assert rbody["charged"] == 0 and rbody["resolved"] == 0, rbody
        assert "图片" in rbody["skipped"][0]["reason"], rbody

        # ④ 抽帧：skipped 带人话，且不落帧行（原图就是封面，不用解一遍）
        fr = await client.post(
            "/api/assets/frames/extract", json={"asset_ids": [img_id]}, headers=hm)
        assert fr.status_code == 200, fr.text
        assert fr.json()["results"][0]["result"] == "skipped", fr.json()
        assert "本来就是图片" in fr.json()["results"][0]["reason"], fr.json()
        assert await _count(AssetFrame) == 0

        # ⑤ 拼接：A 段、B 段都要挡（少挡一段，ffmpeg 就在解码那步炸成 502）
        ca = await client.post(
            "/api/assets/concat",
            json={"asset_id": img_id, "second_source": "asset", "second_id": vid_id},
            headers=hm)
        assert ca.status_code == 400, ca.text
        assert "A 段" in ca.json()["detail"] and "图片" in ca.json()["detail"], ca.json()
        cb = await client.post(
            "/api/assets/concat",
            json={"asset_id": vid_id, "second_source": "asset", "second_id": img_id},
            headers=hm)
        assert cb.status_code == 400, cb.text
        assert "B 段" in cb.json()["detail"], cb.json()
        assert await _count(AssetOutput) == 0

        # 图那条一个成本字段都没被写过、状态也还是 image_ready（拒了不等于动过它）
        after = await _row_of(AssetItem, img_id)
        assert (after.cost_prompt, after.cost_parse, after.status) == (0, 0, "image_ready"), after
        await client.aclose()

    _run(_scenario())


def test_media_kind_filter_and_link_assets_stay_video():
    """列表按 `media_kind` 筛（批 W 起库里只有视频，image 筛出空集也算口径正确）；拼错值当场 400。

    图片（角色卡）改走卡库后，素材表里不会再有 image 行——但筛选口本身不能坏：
    image 筛出**空列表**（不是 400、不是把整页原样吐回），链接导入的行仍是 video。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        body = await _upload_mixed(client, hm, [
            ("files", ("原片.mp4", VIDEO_BYTES, "video/mp4")),
            ("files", ("角色卡A.png", PNG_PORTRAIT, "image/png")),
            ("files", ("角色卡B.png", PNG_PORTRAIT, "image/png")),
        ])
        assert all("media_kind" in i for i in body["items"]), body["items"][0]
        # 上传口只收了视频：两张图在 failed 里，items 全是 video
        assert [i["file_name"] for i in body["items"]] == ["原片.mp4"], body["items"]

        only_img = await client.get("/api/assets?media_kind=image", headers=hm)
        assert only_img.status_code == 200, only_img.text
        assert only_img.json()["items"] == [], "图片不进素材表了，image 筛选该是空集"

        only_vid = await client.get("/api/assets?media_kind=video", headers=hm)
        assert [i["file_name"] for i in only_vid.json()["items"]] == ["原片.mp4"]

        # 拼错值不能筛成空集（"库里没有图"比报错难查得多），也不能当"没这个筛选"放过
        bad = await client.get("/api/assets?media_kind=iamge", headers=hm)
        assert bad.status_code == 400, bad.text
        assert "video" in bad.json()["detail"] and "iamge" in bad.json()["detail"], bad.json()

        # 链接导入没有图片这回事：一行都是 video（默认值不是靠 DB DEFAULT 蒙的）
        imp = await _import(client, hm, [DOUYIN_3])
        assert imp.status_code == 201, imp.text
        assert imp.json()["items"][0]["media_kind"] == "video", imp.json()["items"][0]

        # 详情口同样带这一列（抽屉要按它决定放播放器还是放图）；注意详情把素材包在 `asset` 下
        vid_id = only_vid.json()["items"][0]["id"]
        detail = await client.get(f"/api/assets/{vid_id}", headers=hm)
        assert detail.json()["asset"]["media_kind"] == "video", sorted(detail.json())
        assert detail.json()["asset"]["summary_count"] == 0
        await client.aclose()

    _run(_scenario())


def test_image_ingest_guard_fails_before_the_bucket():
    """图片 ingest 的两道自己的闸：超限与落盘不完整都得**在传桶之前**判失败。

    超限走的是 `max_bytes` 早停（不把 200MB 读进磁盘），落盘不完整是真链路那个
    "0 字节对象照样 201"的同一条判据在图片侧的复制 —— 图片侧新写的一段，所以
    必须自己钉一次，不能因为"视频侧有用例"就当它自动成立。
    """
    from io import BytesIO

    from fastapi import UploadFile

    from app.api.assets import _ingest_one_image_file

    async def _scenario():
        # ① 超上限：早停、不入库、不传桶
        put = AsyncMock(return_value=True)
        with patch("app.api.assets.upload_file_from_path", put):
            res = await _ingest_one_image_file(
                UploadFile(filename="超大卡.png", file=BytesIO(PNG_PORTRAIT * 40)),
                tmp_dir=str(_TMPDIR), batch_code="AB-TEST",
                max_bytes=64 * 1024, sem=asyncio.Semaphore(1),
            )
        assert res["ok"] is False and "图片过大" in res["error"], res
        assert res["media_kind"] == "image"
        put.assert_not_awaited()

        # ② 落盘不完整：当场失败，不把空壳传进桶
        with patch("app.api.assets.upload_file_from_path", put), \
             patch("app.api.assets.os.path.getsize", return_value=0):
            res2 = await _ingest_one_image_file(
                UploadFile(filename="半张卡.png", file=BytesIO(PNG_PORTRAIT)),
                tmp_dir=str(_TMPDIR), batch_code="AB-TEST",
                max_bytes=10 * 1024 * 1024, sem=asyncio.Semaphore(1),
            )
        assert res2["ok"] is False and "落盘不完整" in res2["error"], res2
        put.assert_not_awaited()

        # ③ 正向对照：同一入参在真 getsize 下必须成功并量出 720×1280
        #    （证明 ② 是"少字节"造成的，不是这条路径本身不通）
        got = []

        async def _rec(bucket, key, path, content_type="application/octet-stream"):
            with open(path, "rb") as fh:
                got.append((fh.read(), content_type))
            return True

        with patch("app.api.assets.upload_file_from_path", _rec):
            ok = await _ingest_one_image_file(
                UploadFile(filename="角色卡.png", file=BytesIO(PNG_PORTRAIT)),
                tmp_dir=str(_TMPDIR), batch_code="AB-TEST",
                max_bytes=10 * 1024 * 1024, sem=asyncio.Semaphore(1),
            )
        assert ok["ok"] is True, ok
        assert (ok["width"], ok["height"]) == (720, 1280), ok
        assert ok["aspect"]["ratio"] == "9:16" and ok["aspect"]["ok"] is True, ok
        assert ok["notes"] == [], ok["notes"]
        assert got[0][0] == PNG_PORTRAIT and got[0][1] == "image/png", got

        # ④ 非图片扩展名在这里就出局，压根不落盘（分流在调用方，但这条也得自己挡一遍）
        with patch("app.api.assets.upload_file_from_path", put):
            res4 = await _ingest_one_image_file(
                UploadFile(filename="原片.mp4", file=BytesIO(VIDEO_BYTES)),
                tmp_dir=str(_TMPDIR), batch_code="AB-TEST",
                max_bytes=10 * 1024 * 1024, sem=asyncio.Semaphore(1),
            )
        assert res4["ok"] is False and "图片类型不支持" in res4["error"], res4
        put.assert_not_awaited()

    asyncio.run(_scenario())


# ─────────────  14. 多卡保序与逐张取图（11-05 批 G-2：card_asset_ids）  ─────────────


async def _approved_copy(client, h):
    """造一条**已过审**的文案（投产入组条件），回 (素材 id, 文案 id, 过审正文)。"""
    hm, ho = h["material"], h["operator"]
    asset_id, _ = await _make_ready_asset(client, hm)
    items, _ = await _gen_and_list(asset_id, hm, client)
    good = _approvable(items)
    await client.post(
        "/api/assets/summaries/review",
        json={"summary_ids": [good["id"]], "action": "approve"}, headers=ho)
    return asset_id, good["id"], good["text"]


def test_cards_keep_the_picked_order_and_every_one_is_read():
    """多张卡：`card_asset_ids` 的顺序就是板上 picDatas 的顺序，逐张真取字节。

    批 G-2 的主干。旧写法"按 key 去重只装 1 项"在多卡时会把第 2、3 张**静默丢掉**
    ——picDatas 少一张照样投得出去，只是画中人不对，事后从台账上看不出来。
    所以这里故意**倒序**挑两张（B 在前），断言三层都是这个序：
    响应 cards、库里的数组、payload 的 picDatas。
    顺带钉两件兼容事：单值列继续有值（＝主卡 key），同 key 跨单只取一次（不重复读桶）。
    """
    import base64 as b64mod

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        body = await _upload_cards(client, hm, [
            ("files", ("男主卡.png", PNG_PORTRAIT, "image/png")),
            ("files", ("女主卡.png", PNG_PORTRAIT, "image/png")),
        ])
        male = next(i for i in body["items"] if i["file_name"] == "男主卡.png")
        female = next(i for i in body["items"] if i["file_name"] == "女主卡.png")
        asset_id, sid, _copy = await _approved_copy(client, h)

        # 倒序挑：女主在前。谁排第一谁是 picDatas 的第一项＝模型眼里的"主形象"
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 2, "board_tag": "ben",
                "card_asset_ids": [female["id"], male["id"]],
            }, headers=ho)
        assert made.status_code == 200, made.text
        resp = made.json()
        assert resp["created"] == 2
        assert [c["asset_id"] for c in resp["cards"]] == [female["id"], male["id"]], resp["cards"]

        rows = await _rows(AssetProduction)
        assert len(rows) == 2
        for p in rows:
            assert p.card_asset_ids == [female["id"], male["id"]], p.card_asset_ids
            # 兼容写：旧读侧（只看 character_card_key 的一切）拿到的是主卡＝数组第一张
            assert p.character_card_key == female["file_key"], p.character_card_key
        audit = (await _rows(AuditLog, AuditLog.action == "asset.produce_order"))[-1]
        assert audit.after["card_asset_ids"] == [female["id"], male["id"]], audit.after
        assert audit.after["card_shapes"] and audit.after["card_shapes"][0]["orientation"] == "portrait"

        CARDS = {male["file_key"]: b"MALE-BYTES", female["file_key"]: b"FEMALE-BYTES"}
        seen = []

        async def _dl(bucket, key):
            seen.append((bucket, key))
            return CARDS.get(key)

        base = f"/api/assets/productions/export?asset_id={asset_id}&format=payload&accounts=1"
        with patch("app.api.assets.download_file", _dl):
            pay = (await client.get(base, headers=ho)).json()

        assert len(pay["payloads"]) == 2
        want = [
            b64mod.b64encode(CARDS[female["file_key"]]).decode(),
            b64mod.b64encode(CARDS[male["file_key"]]).decode(),
        ]
        for pl in pay["payloads"]:
            assert pl["payload"]["picDatas"] == want, "两张都在，且顺序＝挑卡顺序"
            assert [c["label"].split("（")[0] for c in pl["cards"]] == ["女主卡.png", "男主卡.png"] or \
                   [c["asset_id"] for c in pl["cards"]] == [female["id"], male["id"]], pl["cards"]
            assert all(c["loaded"] for c in pl["cards"]), pl["cards"]
            assert pl["warnings"] == [], pl["warnings"]
        # 同一批两张单共用同两张卡 → 每张只读一次桶（2 张 × 2 单如果逐单重读就是 4 次）
        assert len(seen) == 2, seen
        assert sorted(k for _b, k in seen) == sorted([male["file_key"], female["file_key"]])
        assert pay["card_check"]["rows_with_card_issues"] == 0, pay["card_check"]
        await client.aclose()

    _run(_scenario())


def test_broken_card_is_named_and_the_others_still_deliver():
    """一张取不到 → 点名是哪一张、picDatas 少一张、并明确"挂了 2 张只取到 1 张"。

    旧口径只在单卡时报"读取失败"，多卡后**最坏的情况是静默少一张**（数组非空、
    看起来一切正常）。所以这里除了点名，还要断那条总数对不上的话。
    """
    import base64 as b64mod

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        body = await _upload_cards(client, hm, [
            ("files", ("好的卡.png", PNG_PORTRAIT, "image/png")),
            ("files", ("坏掉的卡.png", PNG_PORTRAIT, "image/png")),
        ])
        good = next(i for i in body["items"] if i["file_name"] == "好的卡.png")
        bad = next(i for i in body["items"] if i["file_name"] == "坏掉的卡.png")
        asset_id, sid, _copy = await _approved_copy(client, h)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1,
                "card_asset_ids": [bad["id"], good["id"]],
            }, headers=ho)

        async def _dl(bucket, key):
            # 坏的那张：桶里没有对象（download_file 把 S3Error 吞成 None，正是真链路会遇到的形状）
            return b"GOOD" if key == good["file_key"] else None

        base = f"/api/assets/productions/export?asset_id={asset_id}&format=payload&accounts=1"
        with patch("app.api.assets.download_file", _dl):
            pay = (await client.get(base, headers=ho)).json()
        pl = pay["payloads"][0]
        assert pl["payload"]["picDatas"] == [b64mod.b64encode(b"GOOD").decode()], pl["payload"]["picDatas"]
        text = "；".join(pl["warnings"])
        # 卡上带的是 name（去扩展名的卡名），导出点名用 label＝「code（卡名）」
        assert "坏掉的卡" in text, pl["warnings"]
        assert "挂了 2 张卡、只取到 1 张" in text, pl["warnings"]
        assert [c["loaded"] for c in pl["cards"]] == [False, True], pl["cards"]
        assert pay["card_check"]["rows_with_card_issues"] == 1

        # 桶彻底读不到（两张全失败）：七键结构不能缺，picDatas 给空数组
        with patch("app.api.assets.download_file", AsyncMock(side_effect=RuntimeError("MinIO 503"))):
            pay2 = (await client.get(base, headers=ho)).json()
        assert pay2["payloads"][0]["payload"]["picDatas"] == []
        assert tuple(pay2["payloads"][0]["payload"].keys()) == svc.BOARD_PAYLOAD_KEYS
        assert "读取失败" in "；".join(pay2["payloads"][0]["warnings"])
        await client.aclose()

    _run(_scenario())


def test_non_image_or_gone_card_is_refused_before_the_order_is_made():
    """挑卡脏输入当场 400（三种各一次），而且**一条单都不许落库**。

    "静默少一张卡"和"投出去才发现卡不对"都太贵：投产要调模型（实测一次 90~150s），
    号池额度也在这一刻开始被占。所以判据是**先拒后做**，拒的理由还得让人知道下一步。
    11-25 批 W 后卡表里只有图片，所以"视频当卡"这个旧分支没有了——视频 id 在
    `_resolve_card_assets` 眼里就是"卡库里找不到"，同一个 400 闸照挡。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        body = await _upload_mixed(client, hm, [
            ("files", ("原片.mp4", VIDEO_BYTES, "video/mp4")),
        ])
        vid = body["items"][0]
        cards = await _upload_cards(client, hm, [
            ("files", ("角色卡.png", PNG_PORTRAIT, "image/png")),
        ])
        img = cards["items"][0]
        _asset_id, sid, _copy = await _approved_copy(client, h)

        # ① 视频当卡：卡表里只有图片，视频 id 直接落"卡库里找不到"这个 400
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as clip:
            r1 = await client.post("/api/assets/produce",
                                   json={"summary_ids": [sid], "n": 1,
                                         "card_asset_ids": [vid["id"]]}, headers=ho)
        assert r1.status_code == 400, r1.text
        assert "卡库里找不到" in r1.json()["detail"], r1.json()
        clip.assert_not_awaited()  # 参数没过就不该调模型（一调就是几十秒和一笔额度）

        # ② 卡不存在（多半已被删除）
        r2 = await client.post("/api/assets/produce", json={
            "summary_ids": [sid], "n": 1, "card_asset_ids": [str(uuid.uuid4())]}, headers=ho)
        assert r2.status_code == 400, r2.text
        assert "卡库里找不到" in r2.json()["detail"] and "刷新" in r2.json()["detail"], r2.json()

        # ③ 卡在卡库、桶里没文件（上传失败行）
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetCard, uuid.UUID(img["id"]))
            row.file_key = None
            await s.commit()
        r3 = await client.post("/api/assets/produce", json={
            "summary_ids": [sid], "n": 1, "card_asset_ids": [img["id"]]}, headers=ho)
        assert r3.status_code == 400, r3.text
        assert "桶里没有文件" in r3.json()["detail"], r3.json()

        assert await _count(AssetProduction) == 0, "三种脏输入都没资格留下生产单"
        await client.aclose()

    _run(_scenario())


def test_card_aspect_is_said_at_produce_time_not_discovered_after():
    """画幅提示：横版卡、方向不一致都在**建单当场**说（拍板③：卡宽高比决定成片画幅）。

    这条只在真链路上吃过亏：横版三视图卡喂进去，提示词写 9:16 也压不住，
    出片是横屏 —— 而"发现"的时刻往往是投放之后。所以这里断三处都说话：
    响应逐张 hint、warnings 点名横版、导出侧再卡一道。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        body = await _upload_cards(client, hm, [
            ("files", ("竖版卡.png", PNG_PORTRAIT, "image/png")),
            ("files", ("横版卡.png", PNG_LANDSCAPE, "image/png")),
        ])
        port = next(i for i in body["items"] if i["file_name"] == "竖版卡.png")
        wide = next(i for i in body["items"] if i["file_name"] == "横版卡.png")
        assert port["resolution"] == "720x1280" and wide["resolution"] == "1280x720"
        # 挑卡列表侧就带画幅判据（前端不许自己再拼一张比例表，口径只能有一套）
        listed = await client.get("/api/assets/cards?page_size=20", headers=hm)
        asp = {i["file_name"]: i["aspect"] for i in listed.json()["items"]}
        assert (asp["竖版卡.png"]["ratio"], asp["竖版卡.png"]["orientation"]) == ("9:16", "portrait")
        assert asp["横版卡.png"]["orientation"] == "landscape", asp
        assert asp["竖版卡.png"]["width"] == 720 and asp["竖版卡.png"]["height"] == 1280
        asset_id, sid, _copy = await _approved_copy(client, h)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1,
                "card_asset_ids": [port["id"], wide["id"]],
            }, headers=ho)
        assert made.status_code == 200, made.text
        resp = made.json()
        by_id = {c["asset_id"]: c for c in resp["cards"]}
        assert by_id[port["id"]]["hint"] == "这张 9:16（720×1280）出竖屏", by_id[port["id"]]
        assert "横屏" in by_id[wide["id"]]["hint"] and by_id[wide["id"]]["orientation"] == "landscape"
        text = "；".join(resp["warnings"])
        assert "横版" in text and "别指望提示词里写 9:16" in text, resp["warnings"]
        assert "方向不一致" in text, resp["warnings"]

        # 导出侧再卡一道：同一张单在 payload 的 warnings 里也要看见画幅（导出是最后一道闸）
        with patch("app.api.assets.download_file", AsyncMock(return_value=b"X")):
            pay = (await client.get(
                f"/api/assets/productions/export?asset_id={asset_id}&format=payload",
                headers=ho)).json()
        warns = "；".join(pay["payloads"][0]["warnings"])
        assert "1 张卡是横版" in warns, pay["payloads"][0]["warnings"]
        assert "卡的方向不一致" in warns, pay["payloads"][0]["warnings"]
        assert pay["card_check"]["rows_with_card_issues"] == 1, pay["card_check"]
        await client.aclose()

    _run(_scenario())


def test_legacy_key_still_delivers_but_never_backfills_a_broken_array():
    """旧单（只有 `character_card_key`）继续出片；新单数组坏掉时**不许**偷偷回退旧 key。

    两条方向相反的判据，缺一条都会出事：
    - 只加新列、不回退 → 昨天建的单今天导出没卡，而那批号池额度已经烧了；
    - 回退写得太宽（"数组取不到就用 key"）→ 新前端挂了一张挑坏的卡，
      后端替他把旧 key 塞回去，出片和他在界面上选的**不是同一张图**，还查不出来。
    所以判据是"数组为空才回退"，不是"数组里没一项能用才回退"。
    """
    import base64 as b64mod

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, sid, _copy = await _approved_copy(client, h)
        legacy_key = "asset/2026/11/05/旧角色卡.jpg"
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1, "character_card_key": legacy_key,
            }, headers=ho)
        p = (await _rows(AssetProduction))[0]
        assert p.card_asset_ids in (None, []), p.card_asset_ids
        assert p.character_card_key == legacy_key

        base = f"/api/assets/productions/export?asset_id={asset_id}&format=payload&accounts=1"
        with patch("app.api.assets.download_file", AsyncMock(return_value=b"OLD-CARD")) as dl:
            pay = (await client.get(base, headers=ho)).json()
        assert pay["payloads"][0]["payload"]["picDatas"] == \
            [b64mod.b64encode(b"OLD-CARD").decode()], "存量单不许因为加了新列就没卡"
        assert pay["payloads"][0]["cards"][0]["legacy"] is True, pay["payloads"][0]["cards"]
        assert dl.await_args.args == (settings.MINIO_BUCKET_RAW, legacy_key), dl.await_args

        # 现在把这张单的卡数组写成"一条已删除的素材"，旧 key 还留在列上 → 不许回退
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p.id)
            row.card_asset_ids = [str(uuid.uuid4())]
            await s.commit()
        with patch("app.api.assets.download_file", AsyncMock(return_value=b"OLD-CARD")) as dl2:
            pay2 = (await client.get(base, headers=ho)).json()
        pl = pay2["payloads"][0]
        assert pl["payload"]["picDatas"] == [], "数组非空就不回退：偷塞旧 key＝替人改了输入"
        dl2.assert_not_awaited()
        assert "已从卡库删除" in "；".join(pl["warnings"]), pl["warnings"]
        assert pl["cards"][0]["asset_id"] and pl["cards"][0]["key"] is None, pl["cards"]

        # 反向对照：数组清空（真·旧单形状）时同一条 key 又该被读到
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p.id)
            row.card_asset_ids = None
            await s.commit()
        with patch("app.api.assets.download_file", AsyncMock(return_value=b"OLD-CARD")):
            pay3 = (await client.get(base, headers=ho)).json()
        assert pay3["payloads"][0]["payload"]["picDatas"] == [b64mod.b64encode(b"OLD-CARD").decode()]
        await client.aclose()

    _run(_scenario())


def test_resolution_string_is_parsed_defensively():
    """`resolution` 那列是给人看的字符串，量画幅前必须先证明解析不吃亏。

    历史值有 `720x1280`、`1080×1920`（全角乘号）、空串、`unknown` 四种形状。
    猜错方向的代价是**报反**：把横版报成"出竖屏"，一线就照着这句去投了。
    """
    from app.api.assets import _card_ratio_fields, _resolution_wh

    assert _resolution_wh("720x1280") == (720, 1280)
    assert _resolution_wh("1080×1920") == (1080, 1920), "全角乘号（人手填过的那批）"
    assert _resolution_wh(" 1280 X 720 ") == (1280, 720)
    for junk in (None, "", "unknown", "720", "720x", "0x0"):
        assert _resolution_wh(junk) in ((None, None), (0, 0)), junk
    f = _card_ratio_fields("720x1280")
    assert (f["ratio"], f["orientation"]) == ("9:16", "portrait")
    assert _card_ratio_fields("1280x720")["orientation"] == "landscape"
    # 探不到尺寸 → 三个字段全空，且**不许给一个猜测方向**
    empty = _card_ratio_fields("unknown")
    assert empty["ratio"] is None and empty["orientation"] is None, empty


# ─────────  14b. 卡库 CRUD（11-25 批 W：asset_cards 独立成库）  ─────────


def test_card_library_list_filter_and_item_fields():
    """GET /api/assets/cards：全员可读、q 模糊过滤、item 字段齐全（含画幅判据）。

    批 W 起挑卡器的数据源就是这个口（不再扫素材表）。这里钉住前端赖以工作的
    全部字段：`code/name/file_name/file_size/resolution/aspect/note/owner_id/
    preview_url/created_at`——少了任何一个，挑卡弹窗当场画不出来。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        await _upload_cards(client, hm, [
            ("files", ("男主卡.png", PNG_PORTRAIT, "image/png")),
            ("files", ("女主卡.png", PNG_LANDSCAPE, "image/png")),
        ])

        listed = await client.get("/api/assets/cards", headers=hm)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] == 2 and len(body["items"]) == 2, body
        assert body["page"] == 1 and body["page_size"] == 100, body

        item = next(i for i in body["items"] if i["file_name"] == "男主卡.png")
        for key in ("id", "code", "name", "file_name", "file_size", "resolution",
                    "aspect", "note", "owner_id", "preview_url", "created_at"):
            assert key in item, f"列表 item 缺字段 {key}：{sorted(item)}"
        assert item["name"] == "男主卡", item
        assert item["aspect"]["orientation"] == "portrait", item["aspect"]
        assert item["aspect"]["ratio"] == "9:16", item["aspect"]
        assert item["aspect"]["width"] == 720 and item["aspect"]["height"] == 1280, item["aspect"]
        # preview_url 只钉结构不钉值（测试库 MinIO 未起：签名失败被吞成 None 也是合法形状）
        assert item["preview_url"] is None or item["preview_url"].startswith("http"), item
        wide = next(i for i in body["items"] if i["file_name"] == "女主卡.png")
        assert wide["aspect"]["orientation"] == "landscape", wide["aspect"]

        # q 模糊匹配 name / file_name / code 三条路各走一遍
        by_name = await client.get("/api/assets/cards?q=男主", headers=hm)
        assert [i["file_name"] for i in by_name.json()["items"]] == ["男主卡.png"], by_name.json()
        by_code = await client.get(f"/api/assets/cards?q={item['code']}", headers=hm)
        assert by_code.json()["total"] == 1 and \
            by_code.json()["items"][0]["id"] == item["id"], by_code.json()
        none = await client.get("/api/assets/cards?q=不存在的卡", headers=hm)
        assert none.json()["total"] == 0 and none.json()["items"] == [], none.json()

        # 分页参数真的生效（不是回显完就把整页吐回来）
        paged = await client.get("/api/assets/cards?page=2&page_size=1", headers=hm)
        assert paged.json()["total"] == 2 and len(paged.json()["items"]) == 1, paged.json()
        assert paged.json()["page"] == 2 and paged.json()["page_size"] == 1, paged.json()

        # 读全员：operator/admin 都能看（挑卡在投产弹窗里，投的人是 operator）
        for key in ("operator", "admin"):
            r = await client.get("/api/assets/cards", headers=h[key])
            assert r.status_code == 200 and r.json()["total"] == 2, (key, r.text)
        await client.aclose()

    _run(_scenario())


def test_card_rename_owner_other_and_admin():
    """PATCH /api/assets/cards/{id}：卡主改得动；他人 403；admin 兜底 200；空卡名 400。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        body = await _upload_cards(client, hm, [("files", ("男主卡.png", PNG_PORTRAIT, "image/png"))])
        cid = body["items"][0]["id"]

        # ① 他人先拒：话术要让人知道是权限不是卡丢了
        r_other = await client.patch(f"/api/assets/cards/{cid}",
                                     json={"name": "被偷换的卡"}, headers=ho)
        assert r_other.status_code == 403, r_other.text
        assert "这张卡不是你传的" in r_other.json()["detail"], r_other.json()

        # ② 卡主改名/备注，库里的行真的跟着变
        r_own = await client.patch(f"/api/assets/cards/{cid}",
                                   json={"name": "男主·正面", "note": "横版别投"}, headers=hm)
        assert r_own.status_code == 200, r_own.text
        assert r_own.json()["name"] == "男主·正面" and r_own.json()["note"] == "横版别投", r_own.json()
        row = await _row_of(AssetCard, uuid.UUID(cid))
        assert row.name == "男主·正面" and row.note == "横版别投", (row.name, row.note)
        # 改名留审计
        assert await _rows(AuditLog, AuditLog.action == "asset.card.update"), "改名必须留审计"

        # ③ 空卡名当场 400（全空白卡名在挑卡列表里没法认）
        r_blank = await client.patch(f"/api/assets/cards/{cid}", json={"name": "   "}, headers=hm)
        assert r_blank.status_code == 400, r_blank.text
        assert "卡名" in r_blank.json()["detail"], r_blank.json()

        # ④ admin 兜底：不是卡主也能改（与素材写口同一条「admin 全能」口径）
        r_admin = await client.patch(f"/api/assets/cards/{cid}",
                                     json={"note": "管理员标注"}, headers=ha)
        assert r_admin.status_code == 200, r_admin.text
        assert r_admin.json()["note"] == "管理员标注", r_admin.json()

        # ⑤ 不存在的卡 404，别误报成 403/400
        r_gone = await client.patch(f"/api/assets/cards/{uuid.uuid4()}",
                                    json={"name": "x"}, headers=ha)
        assert r_gone.status_code == 404, r_gone.text
        await client.aclose()

    _run(_scenario())


def test_card_delete_refs_and_permissions():
    """DELETE /api/assets/cards/{id}：没单挂着删得动；挂着生产单 400；他人 403；无主卡谁都能删。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]

        # ① 他人拒删（话术同改名那条）
        body = await _upload_cards(client, hm, [("files", ("男主卡.png", PNG_PORTRAIT, "image/png"))])
        cid = body["items"][0]["id"]
        r_other = await client.delete(f"/api/assets/cards/{cid}", headers=ho)
        assert r_other.status_code == 403, r_other.text
        assert "这张卡不是你传的" in r_other.json()["detail"], r_other.json()

        # ② 卡主删得动：行没了、审计留了 asset.card.delete
        r_del = await client.delete(f"/api/assets/cards/{cid}", headers=hm)
        assert r_del.status_code == 200, r_del.text
        assert r_del.json()["ok"] is True and r_del.json()["code"] == body["items"][0]["code"], r_del.json()
        assert await _row_of(AssetCard, uuid.UUID(cid)) is None
        assert await _rows(AuditLog, AuditLog.action == "asset.card.delete"), "删卡必须留审计"

        # ③ 挂着生产单的卡拒删：删了它那些单投出去就是没卡的片
        body2 = await _upload_cards(client, hm, [("files", ("女主卡.png", PNG_PORTRAIT, "image/png"))])
        cid2 = body2["items"][0]["id"]
        _asset_id, _sid, listed = await _order_ready_production(
            client, h, n=1, hook_codes=["14B01"])
        async with dbmod.async_session_factory() as s:
            prod = await s.get(AssetProduction, uuid.UUID(listed[0]["id"]))
            prod.card_asset_ids = [cid2]
            await s.commit()
        r_held = await client.delete(f"/api/assets/cards/{cid2}", headers=hm)
        assert r_held.status_code == 400, r_held.text
        assert "还挂着 1 张生产单" in r_held.json()["detail"], r_held.json()
        assert await _row_of(AssetCard, uuid.UUID(cid2)) is not None, "拒删就该还在"
        # 单上的引用摘掉之后同一个口就删得动了
        async with dbmod.async_session_factory() as s:
            prod = await s.get(AssetProduction, uuid.UUID(listed[0]["id"]))
            prod.card_asset_ids = []
            await s.commit()
        r_free = await client.delete(f"/api/assets/cards/{cid2}", headers=hm)
        assert r_free.status_code == 200, r_free.text

        # ④ admin 兜底可删他人的卡
        body3 = await _upload_cards(client, hm, [("files", ("配角卡.png", PNG_PORTRAIT, "image/png"))])
        r_admin = await client.delete(f"/api/assets/cards/{body3['items'][0]['id']}", headers=ha)
        assert r_admin.status_code == 200, r_admin.text

        # ⑤ 无主卡（迁移带来的公共历史）谁都能管：operator 删得动
        orphan_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetCard(id=orphan_id, name="历史卡", file_name="历史卡.png",
                            file_key="asset/legacy/old.png", bucket=settings.MINIO_BUCKET_RAW,
                            owner_id=None))
            await s.commit()
        r_orphan = await client.delete(f"/api/assets/cards/{orphan_id}", headers=ho)
        assert r_orphan.status_code == 200, r_orphan.text
        await client.aclose()

    _run(_scenario())



# ══════════════════════════════════════════════════════════════
#  1105 批 H · 自动投板（可自动投板，但逐批人工确认）
#
#  这一节**绝不打真板**：`app.services.aivideo_board` 的三个出网函数
#  （create_task / readback / download_output）全部由 `_FakeBoard` 替身接管，
#  桶与 ffprobe 同样 mock。板子的形状照权威脚本实测写死：
#  ① 行里**没有 reqID**（认领只能靠 tid 差集）；② 一次 create 出 `total` 行；
#  ③ 状态词只有 succ/fail 算终态，waiting 是"还在跑"。
# ══════════════════════════════════════════════════════════════

import contextlib  # noqa: E402
from typing import Any, Dict, List, Optional, Tuple  # noqa: E402

from app.services import aivideo_board as board_mod  # noqa: E402
from app.models.asset import (  # noqa: E402
    CH_DOUBAO_RPA,
    CH_WEWORK_AIVIDEO,
    JOB_DISPATCH,
    PR_CANCELLED,
    PR_FAILED,
    PR_ORDER_READY,
    PR_QUEUED,
    PR_RUNNING,
    PR_SKIPPED,
    PR_SUCCESS,
    PR_SUPERSEDED,
)


def _board_today(offset_days: int = 0) -> str:
    """板面日期串，口径与 `aivideo_board.days_to_query` 完全一致（UTC＋时区偏移）。

    测试里造"昨天的行"必须走这个函数：直接用 `utcnow().strftime` 在傍晚跑用例时
    会和板面今天差一天，于是一条本来该被并集查到的行永远查不到（假失败）。
    """
    return board_mod.board_day(
        datetime.utcnow() + timedelta(hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0))
        + timedelta(days=offset_days)
    )


class _FakeBoard:
    """任务板替身：建任务→按 tid 差集回读→下载，全在内存里，一个包都不出。

    形状照权威脚本实测（`aivideo_ops/watch_8K2A1.py` 那一套）：
    - `info` 回读的行**没有 reqID**——所以"这条 tid 是哪张单"只能靠**投前/投后差集**，
      本替身因此会先塞一条"别人的旧任务"，代码要是靠"行里有 reqID"认领就会认到别人头上；
    - 一次 create 出 `total` 行（板上 TOTAL=N＝同一条 prompt 出 N 版）；
    - 行里就 tid/name/status/outUrl/rgid/doubaoName 这几个键，状态词 waiting 不是终态。
    """

    def __init__(self, *, status_fn=None, pre_existing=(), create_error=None,
                 readback_error_after=None, hide_new=False, download_error=None,
                 video_bytes=None, readback_ok_days=None, fail_tids=None):
        self.creates: List[dict] = []
        self.rows: Dict[str, dict] = {}
        self.reads: List[Tuple[tuple, str]] = []
        self.downloads: List[str] = []
        self._seq = 0
        self.status_fn = status_fn or (lambda created_index, read_round: "succ")
        # 11-24 批：按 **tid** 点名判失败，用来造「一张单 3 版里 1 版 fail」这种
        # 版级混合终态——`status_fn` 只按 created_index 分，做不到同一批内分化。
        # tid 是确定性号（T000001…），用例点第几版就写第几版。
        self.fail_tids = set(fail_tids or ())
        self.create_error = create_error
        self.readback_error_after = readback_error_after
        self.hide_new = hide_new
        self.download_error = download_error
        self.video_bytes = video_bytes if video_bytes is not None else (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
        # 落桶与 ffprobe 的替身（投板协程回收成功条时一定会经过这两步）
        self.upload = AsyncMock(return_value=True)
        self.probe = AsyncMock(return_value={"duration": 10.08, "width": 720, "height": 1280})
        # 某些日期查不到（查询抖动）：给了这个集合就只返回集合内日期的行
        self.readback_ok_days = readback_ok_days
        for row_seed in pre_existing:
            # (tid, name) 或 (tid, name, day)：day 用来造"昨天的行"这种隔夜形状
            tid, name = row_seed[0], row_seed[1]
            day = row_seed[2] if len(row_seed) > 2 else None
            self._add_row(tid=tid, name=name, tag="suanku", created_index=0, day=day)

    def _add_row(self, *, tid, name, tag, created_index, day=None):
        self.rows[tid] = {
            "tid": tid, "name": name, "tag": tag, "_created": created_index, "_reads": 0,
            # 行"属于哪一天"按板接口口径记着：`info?date=` 只按日期返回那天的行，
            # 跨午夜那批必须靠**双日并集**才查得到（见 test_dispatch_overnight_reclaim_needs_both_days）
            "day": day or _board_today(),
            "outUrl": f"/out/{tid}.mp4", "rgid": f"RG{tid[-4:]}", "doubaoName": "豆包A",
        }

    def _next_tid(self) -> str:
        """板面 tid 分配：**保证不与已有行撞号**。

        真实板子的 tid 是全局唯一的，替身要是图省事直接 `T{seq}`，一旦和
        `pre_existing` 里那条同名就会把旧行**覆盖**掉——于是投前/投后差集为空，
        代码按口径判成"建上了但认不回来"（uncertain），用例红得莫名其妙。
        11-05 那次"混合点名"用例就是这么撞上的，所以这条写进替身而不是每个用例自己躲。
        """
        while True:
            self._seq += 1
            tid = f"T{self._seq:06d}"
            if tid not in self.rows:
                return tid

    async def create_task(self, payload):
        self.creates.append(dict(payload))
        if self.create_error is not None:
            raise self.create_error
        idx = len(self.creates)
        for _ in range(int(payload.get("total") or 1)):
            self._add_row(tid=self._next_tid(), name=str(payload.get("name") or ""),
                          tag=str(payload.get("tag") or ""), created_index=idx)
        return '{"code":0,"msg":"succ"}'

    async def readback(self, days, tag):
        days = tuple(sorted(days))
        self.reads.append((days, tag))
        if self.readback_error_after is not None and len(self.reads) > self.readback_error_after:
            raise board_mod.BoardError("回读这一天失败了（测试注入）")
        wanted = set(days)
        out: Dict[str, dict] = {}
        for tid, row in self.rows.items():
            if row["tag"] != tag:
                continue
            # 板接口 `info?date=` 是**按天**返回的：不在本次并集里的日期，行就不出来
            if row["day"] not in wanted:
                continue
            # 给了 readback_ok_days 就只有这几天查得到（另几种日期静默为空）
            if self.readback_ok_days is not None and row["day"] not in set(self.readback_ok_days):
                continue
            if self.hide_new and row["_created"] > 0:
                continue
            row["_reads"] += 1
            st = self.status_fn(row["_created"], row["_reads"])
            if tid in self.fail_tids:
                st = "fail"
            out[tid] = {
                "tid": tid, "name": row["name"], "status": st,
                "outUrl": row["outUrl"],
                "rgid": row["rgid"], "doubaoName": row["doubaoName"],
            }
        return out

    async def download_output(self, out_url):
        self.downloads.append(str(out_url))
        if self.download_error is not None:
            raise self.download_error
        return self.video_bytes


def _patch_board(fb: _FakeBoard):
    """把"会出网/碰盘/排后台真跑 ffmpeg"的调用换成替身（板子三个 + 落桶 + ffprobe + 抽帧排程）。

    ⚠️ 落桶与 ffprobe 必须在同一个替身组里：投板协程回收成功条时会真去
    `upload_file_from_path`（本机 MinIO:9000 没起 → 整批用例挂在 ConnectionRefused），
    分开打桩就会有用例漏一个、把"闸门没过"测成"连不上 MinIO"。
    ⚠️ `_enqueue_frames` 也在这里钉：批 K 起回收落库会自动排产物首帧任务——不钉的话
    `asyncio.create_task` 会把真抽帧协程甩进测试事件循环里跑 ffmpeg。要看排程参数的
    用例（如回收 e2e）在 with 内层再补一层自己的 patch，内层的赢。
    """
    return (
        patch("app.services.aivideo_board.create_task", fb.create_task),
        patch("app.services.aivideo_board.readback", fb.readback),
        patch("app.services.aivideo_board.download_output", fb.download_output),
        patch("app.api.assets.upload_file_from_path", fb.upload),
        patch("app.services.asset_compose_service.probe_media", fb.probe),
        patch(
            "app.api.assets._enqueue_frames",
            AsyncMock(return_value={"queued": True, "job_id": "jf", "note": None}),
        ),
    )


@contextlib.contextmanager
def _board_off(fb: _FakeBoard, *, retry_max=None):
    """`with _board_off(fb):` ＝投板这段线全程不出网（含轮询协程），并且**跑得完**。

    除了三个出网函数，这里还顺手钉四件事，每一件都是"不钉就会挂/会假绿"：
    - `AIVIDEO_AUTH` / `ASSET_BOARD_BASE_URL`：默认空＝自动投板没启用，投递口会**当场 400**
      （见 test_dispatch_refuses_when_board_not_configured）。不在这儿填上假凭据，
      整节用例测到的都是"凭据没配"而不是投板；填的是替身用的假值，一个包都不会发出去。
    - 轮询间隔／最长等待：现网口径 45s×45min，用例里等 45 分钟就是挂。压到下限
      （0.05s / 0.02 分钟）后，"waiting 若干轮→succ""到期不判失败"两条码路都能真跑过。
    - `retry_max`：把「失败自动重启上限」钉成用例要的那个数（不填就沿用类默认值 2）。
      不钉这一层，"重启几次"就跟着 config.py 走，改默认值会把一片用例判读改成别的形状。
    - 退出时**原样还原**，不污染同进程后面的用例（含那些依赖"凭据为空"的用例）。
    """
    saved = {
        "AIVIDEO_AUTH": settings.AIVIDEO_AUTH,
        "ASSET_BOARD_BASE_URL": settings.ASSET_BOARD_BASE_URL,
        "ASSET_BOARD_POLL_INTERVAL": settings.ASSET_BOARD_POLL_INTERVAL,
        "ASSET_BOARD_POLL_MAX_MINUTES": settings.ASSET_BOARD_POLL_MAX_MINUTES,
        "ASSET_BOARD_RETRY_MAX": settings.ASSET_BOARD_RETRY_MAX,
    }
    settings.AIVIDEO_AUTH = "tester:board-pass-for-tests"
    settings.ASSET_BOARD_BASE_URL = "http://board.invalid"
    settings.ASSET_BOARD_POLL_INTERVAL = 0.05
    settings.ASSET_BOARD_POLL_MAX_MINUTES = 0.02
    if retry_max is not None:
        settings.ASSET_BOARD_RETRY_MAX = retry_max
    try:
        with contextlib.ExitStack() as st:
            for p in _patch_board(fb):
                st.enter_context(p)
            yield fb
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


async def _order_ready_production(client, h, *, url=None, n=1, board_total=1,
                                  hook_codes=None, summary_over=None, produce_extra=None):
    """跑到「有 N 张 order_ready 生产单」，返回 (asset_id, summary_id, [production 行])。

    全程只 mock autoclip 展开（真链路里唯一花钱的一步），板子一个字都不碰。
    """
    hm, ho = h["material"], h["operator"]
    asset_id, _ = await _make_ready_asset(client, hm, **( {"url": url} if url else {}))
    items, _ = await _gen_and_list(asset_id, hm, client)
    sid = _approvable(items)["id"]
    if summary_over:
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetSummary, uuid.UUID(sid))
            for k, v in summary_over.items():
                setattr(row, k, v)
            await s.commit()
    ok = await client.post("/api/assets/summaries/review",
                           json={"summary_ids": [sid], "action": "approve"}, headers=ho)
    assert ok.json()["results"][0]["ok"] is True, ok.text
    payload = {"summary_ids": [sid], "n": n, "board_total": board_total,
               "recommended_title_count": 1, **(produce_extra or {})}
    if hook_codes:
        payload["hook_codes"] = hook_codes
    with patch("app.api.assets._call_autoclip", _fake_autoclip()):
        made = await client.post("/api/assets/produce", json=payload, headers=ho)
    assert made.status_code == 200, made.text
    listed = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"]
    return asset_id, sid, listed


def _dispatch(client, headers, ids, **extra):
    """投板口的统一调用形状（默认同步档，用例里按需改 async_mode）。

    免费投板不再有跨人确认；`confirm=true` 仍保留，表示这一批确实由人发起。
    """
    return client.post(
        "/api/assets/productions/dispatch",
        json={"ids": [str(i) for i in ids], "confirm": True, "async_mode": False, **extra},
        headers=headers,
    )


def test_dispatch_creates_tasks_and_collects_outputs_end_to_end():
    """批 H 主链路：点名 2 张单 → 各建 1 条板任务 → 回读钉 tid → 下载落桶 → 单与素材双双收敛。

    钉的都是"烧钱那条线"不能错的几件事：
    - payload 与导出**同一个函数**产出（七键、reqID＝生产单 id、date 是完整时间戳）；
    - 认领靠 **tid 差集**：板面上别人那条旧任务不许被认成我们的；
    - `board_date` 按**投递时刻**重排（建单是前天的，量必须记在今天那天的号池上）；
    - 产物落 `asset_outputs`（kind=doubao_raw + sha256 + 实测分辨率），投递台账与素材阶段一起收敛。
    """
    import re as _re
    from app.services import aivideo_board as board_mod

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=2, hook_codes=["7C0D1", "7C0D2"])
        ids = [p["id"] for p in listed]
        assert [p["status"] for p in listed] == [PR_ORDER_READY, PR_ORDER_READY]

        # 把两张单的排日刻意改成**前天**：投板必须按投递时刻重生成，否则量记错一天
        aged = datetime.utcnow() - timedelta(days=2)
        async with dbmod.async_session_factory() as s:
            for pid in ids:
                row = await s.get(AssetProduction, uuid.UUID(pid))
                row.board_date = aged
                await s.commit()

        fb = _FakeBoard(pre_existing=[("OLD999999", "别人昨天的任务")])
        with _board_off(fb), \
             patch("app.api.assets._enqueue_frames", AsyncMock(
                 return_value={"queued": True, "job_id": "jf1", "note": "抽帧已排后台"})) as enq_frames:
            resp = await _dispatch(client, ho, ids)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # ① 建任务：一张单一次 POST，七键 payload
        assert body["dispatched"] == 2 and body["succeeded"] == 2 and body["failed"] == 0
        assert len(fb.creates) == 2, "N 份＝N 张单、每张 total=1，不许合并成一条"
        for payload in fb.creates:
            assert tuple(payload.keys()) == svc.BOARD_PAYLOAD_KEYS, payload.keys()
            assert _re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", payload["date"]), payload["date"]
            assert payload["total"] == 1 and payload["tag"] == settings.ASSET_BOARD_TAG
            assert payload["name"] and payload["prompt"]

        # ② 排日重生成：不是前天，是板面今天
        board_today = board_mod.board_day(
            datetime.utcnow() + timedelta(hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0)))
        assert [p["date"][:10] for p in fb.creates] == [board_today, board_today]

        # ③ 认领＝差集：别人的旧 tid 一个都不许钉到我们单上
        rows = await _rows(AssetProduction)
        pinned = {str(r.board_tid) for r in rows}
        assert "OLD999999" not in pinned, "投前快照里就存在的行不是我们的任务"
        assert pinned == {"T000001", "T000002"}, pinned
        assert all(p["reqID"] in {str(r.id) for r in rows} for p in fb.creates), "reqID 钉在生产单 id 上"

        # ④ 状态与台账
        for r in rows:
            assert r.status == PR_SUCCESS, r.status
            assert r.attempts == 1 and r.board_rgid and r.started_at and r.completed_at
            assert r.error is None
        # produce 环成了 → 四环状态机把素材推进到下一环（与人工回写口同一套判据）
        assert body["asset_status"][str(asset_id)] == "composing", body["asset_status"]

        # ⑤ 产物：两支都落库，规格是实测口径（10.08s / 720×1280）
        outs = await _rows(AssetOutput)
        assert len(outs) == 2 and [o.kind for o in outs] == ["doubao_raw"] * 2
        assert {o.production_id for o in outs} == {r.id for r in rows}
        for o in outs:
            assert o.bucket == settings.MINIO_BUCKET_RAW
            assert o.file_key.startswith("asset/board/"), o.file_key
            assert o.sha256 and len(o.sha256) == 64, "摘要必须在删临时文件之前算出来"
            assert (o.duration, o.resolution) == (10.08, "720x1280")
            assert o.board_out_url in {f"/out/T00000{i}.mp4" for i in (1, 2)}
        assert fb.upload.await_count == 2 and fb.downloads == ["/out/T000001.mp4", "/out/T000002.mp4"]

        # ⑥ 审计 + 当日计数（对账看板上条数，不是行数）
        audit = (await _rows(AuditLog, AuditLog.action == "asset.production.dispatch"))[-1]
        assert audit.after["payload_keys"] == list(svc.BOARD_PAYLOAD_KEYS)
        assert len(audit.after["created"]) == 2
        assert body["dispatch"]["dispatched"] == 2
        assert body["dispatch"]["today"]["board_rows"] == 2, body["dispatch"]["today"]
        assert not {"capacity_hint", "board_capacity", "capacity"} & body.keys(), body
        assert not {"soft_cap", "over_cap", "note"} & body["dispatch"]["today"].keys(), \
            body["dispatch"]["today"]

        # ⑦ 批 K：这次真落库的两条产物**自动排了首帧任务**（素材墙的缩略图从这来）。
        # 排程必须 fail-soft（帧没排上不连累回收），所以这里只断"排了、点名排的是产物"。
        enq_frames.assert_awaited_once()
        kwf = enq_frames.await_args.kwargs
        assert kwf["asset_ids"] == [] and len(kwf["output_ids"]) == 2, kwf
        assert kwf["why"].startswith("豆包成片回收落库"), kwf["why"]
        assert {o[:8] for o in kwf["output_ids"]} <= {str(o.id)[:8] for o in outs}

        # ⑧ 批 L：板子侧状态写回。认领 tid 那一刻钉「已投板」，轮询每轮回读后
        # 覆盖成板面真实行状态（假板默认直接 succ）＋检查时间；列表口必须带出，
        # 不然前端「板子：出片中·上轮检查 …」这条进度线没有数据源。
        listed2 = await client.get("/api/assets/productions", params={
            "asset_id": asset_id}, headers=ho)
        rows2 = listed2.json()["items"]
        assert len(rows2) == 2
        for r2 in rows2:
            assert r2["board_last_status"] == "succ", r2["board_last_status"]
            assert r2["board_last_check_at"], "检查时间必须随写回落库"
        await client.aclose()

    _run(_scenario())


def test_outputs_wall_fields_batch_filter_and_total():
    """批 K 素材墙数据口：批次过滤走素材侧、total 计数、卡片带素材码/首帧直链。

    钉三件不能错的：
    - `batch_id` 收敛走 `asset_items` 侧——拼接产物不挂生产单（production_id 可空），
      按生产单查会漏，按素材查永远查得到；
    - 没帧的产物 `thumb_url` 必须是**显式 null 不是缺键**（前端靠 null 画「没有预览图」）；
    - `limit/offset` 分页配 `total`，墙要翻页要计数。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)

        code = None
        async with dbmod.async_session_factory() as s:
            asset = await s.get(AssetItem, uuid.UUID(asset_id))
            batch_id = str(asset.batch_id)
            code = asset.code
            out1 = AssetOutput(
                asset_id=asset.id, kind="doubao_raw",
                file_key="asset/board/x/v1.mp4", bucket=settings.MINIO_BUCKET_RAW,
                file_name="v1.mp4", duration=10.08, file_size=2048, resolution="720x1280",
            )
            s.add(out1)
            await s.flush()
            s.add(AssetFrame(
                asset_id=asset.id, output_id=out1.id,
                kind=FRAME_OUTPUT_THUMB, seq=0,
                file_key="asset/board/x/v1.jpg", bucket=settings.MINIO_BUCKET_RAW,
            ))
            out2 = AssetOutput(
                asset_id=asset.id, kind="composed",
                file_key="asset/composed/v2.mp4", bucket=settings.MINIO_BUCKET_RAW,
                file_name="v2.mp4", duration=6.0,
            )
            s.add(out2)
            await s.commit()
            oid1, oid2 = str(out1.id), str(out2.id)

        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://signed/thumb.jpg")):
            r = await client.get("/api/assets/outputs", params={"batch_id": batch_id}, headers=hm)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["total"] == 2, b
        rows = {x["id"]: x for x in b["items"]}
        assert rows[oid1]["asset_code"] == code, rows[oid1]
        assert rows[oid1]["thumb_url"] == "http://signed/thumb.jpg"
        assert rows[oid1]["downloaded_at"] is None and rows[oid1]["hook_code"] is None
        assert rows[oid2]["thumb_url"] is None, "没帧的产物必须显式回 null，前端好画「没有预览图」"
        assert rows[oid2]["kind"] == "composed"

        # kind 过滤 + 分页各走一遍
        with patch("app.api.assets.get_presigned_url",
                   AsyncMock(return_value="http://signed/t.jpg")):
            r2 = await client.get(
                "/api/assets/outputs", params={"batch_id": batch_id, "kind": "doubao_raw"}, headers=hm)
            assert r2.json()["total"] == 1
            r3 = await client.get(
                "/api/assets/outputs", params={"batch_id": batch_id, "limit": 1, "offset": 1}, headers=hm)
            b3 = r3.json()
            assert b3["total"] == 2 and len(b3["items"]) == 1, b3

        # 别的批次一条都查不到
        r4 = await client.get(
            "/api/assets/outputs", params={"batch_id": str(uuid.uuid4())}, headers=hm)
        assert r4.json()["total"] == 0
        await client.aclose()

    _run(_scenario())


def test_dispatch_needs_confirm_and_only_review_roles():
    """「逐批人工确认」是接口层的闸门，不是前端的按钮：不带 confirm=true 一律 400。

    顺带钉三条同族的纪律：素材专员（material）没资格投、点名点不到就整批不投、
    一次点太多直接 400 让人分批（限制的是单次后台任务规模，不是每日号池额度）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0D3"])
        pid = listed[0]["id"]

        fb = _FakeBoard()
        with _board_off(fb):
            # ① 没有 confirm：闸门判定照跑，但一张都不许投出去
            no_confirm = await client.post(
                "/api/assets/productions/dispatch",
                json={"ids": [pid], "async_mode": False}, headers=ho)
            assert no_confirm.status_code == 400, no_confirm.text
            assert "confirm=true" in no_confirm.json()["detail"]
            assert fb.creates == [], "没确认就不许出网"
            assert (await _row_of(AssetProduction, pid)).status == PR_ORDER_READY

            # ② 权限：投递口跟审核口同一套角色（_REVIEW_ROLES），素材专员不行
            forbidden = await _dispatch(client, hm, [pid])
            assert forbidden.status_code == 403, forbidden.text
            assert fb.creates == []

            # ③ 点名的单子不存在 → 整批 400（绝不"投了能找到的那些"）
            ghost = await _dispatch(client, ho, [pid, uuid.uuid4()])
            assert ghost.status_code == 400 and "不存在" in ghost.json()["detail"]
            assert fb.creates == [], "缺一张就整批不动，否则台账说投了 2 张其实只投了 1 张"

            # ④ 超单批上限 → 400 且提示分批
            old_cap = settings.ASSET_DISPATCH_MAX_PER_CALL
            settings.ASSET_DISPATCH_MAX_PER_CALL = 1
            try:
                over = await _dispatch(client, ho, [pid, str(uuid.uuid4())])
                assert over.status_code == 400 and "单次最多投 1 张" in over.json()["detail"]
            finally:
                settings.ASSET_DISPATCH_MAX_PER_CALL = old_cap

            # ⑤ ids 为空
            empty = await _dispatch(client, ho, [])
            assert empty.status_code == 400 and "ids 为空" in empty.json()["detail"]
            assert await _count(AssetJob) == 0, "被拒的提交不进台账"
        await client.aclose()

    _run(_scenario())


def test_dispatch_gate_blocks_drift_failed_voided_bare_and_wrong_channel():
    """闸门五条负面：漂移/失败/作废/裸单/错通道，一张都不许替人把钱烧掉。

    与导出侧同一套判据（R-4/R-5），所以这里同时钉"口径没分叉"：
    失败单**不在投递口自动重投**（板上失败行没有原因字段，重投与否要人判读）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=5, hook_codes=["7C0D4", "7C0D5", "7C0D6", "7C0D7", "7C0D8"])
        by_code = {p["hook_code"]: p for p in listed}
        assert len(by_code) == 5

        async with dbmod.async_session_factory() as s:
            # 漂移单：展开把词改了
            r = await s.get(AssetProduction, uuid.UUID(by_code["7C0D4"]["id"]))
            r.drift, r.drift_reason = True, "原句被改写"
            # 失败单：不自动重投
            r = await s.get(AssetProduction, uuid.UUID(by_code["7C0D5"]["id"]))
            r.status, r.error, r.started_at = PR_FAILED, "板面 fail（人工判读）", datetime.utcnow()
            # 作废单：撤审后作废，导不出也不许投
            r = await s.get(AssetProduction, uuid.UUID(by_code["7C0D6"]["id"]))
            r.status = PR_SUPERSEDED
            # 裸单：没有展开正文
            r = await s.get(AssetProduction, uuid.UUID(by_code["7C0D7"]["id"]))
            r.prompt_text = None
            # 错通道
            r = await s.get(AssetProduction, uuid.UUID(by_code["7C0D8"]["id"]))
            r.channel = CH_DOUBAO_RPA
            await s.commit()

        fb = _FakeBoard()
        with _board_off(fb):
            resp = await _dispatch(client, ho, [p["id"] for p in listed])
            assert resp.status_code == 400, resp.text
            detail = resp.json()["detail"]
            assert "一张都投不了" in detail and "漂移" in detail, detail
            assert fb.creates == []

        # 逐张点名（拿一张可投的进来当对照，blocked 就会带全五条成因）
        ok_asset, _ok_sid, ok_listed = await _order_ready_production(client, h, url=DOUYIN_3, n=1,
                                                                    hook_codes=["7C0D9"])
        with _board_off(_FakeBoard()):
            resp2 = await _dispatch(client, ho, [p["id"] for p in listed] + [ok_listed[0]["id"]])
        assert resp2.status_code == 200, resp2.text
        body = resp2.json()
        assert body["dispatched"] == 1 and len(body["blocked"]) == 5, body["blocked"]
        reasons = {b["hook_code"]: b["reason"] for b in body["blocked"]}
        assert "漂移" in reasons["7C0D4"] and "不给豁免" in reasons["7C0D4"]
        assert "不在这里自动重投" in reasons["7C0D5"], reasons["7C0D5"]
        assert "7C0D6" in reasons and reasons["7C0D6"]
        assert "expand=false" in reasons["7C0D7"] or "没有展开后的提示词正文" in reasons["7C0D7"]
        assert "wework_aivideo" in reasons["7C0D8"]
        # 被挡的单子状态一个字都没动
        for code in ("7C0D4", "7C0D5", "7C0D6", "7C0D7", "7C0D8"):
            assert (await _row_of(AssetProduction, by_code[code]["id"])).hook_code == code
        assert (await _row_of(AssetProduction, by_code["7C0D4"]["id"])).board_tid is None
        assert (await _row_of(AssetProduction, ok_listed[0]["id"])).status == PR_SUCCESS
        await client.aclose()

    _run(_scenario())


def test_dispatch_never_rebuilds_a_row_that_already_has_a_tid():
    """拍板②「已拿到 board_tid 的单只回读不重建」——这条是"重投烧两遍号池"的唯一天花板。

    场景就是现网最怕的那一次：投上板了、协程被进程重启带走、一线又点了一遍投递。
    正确动作是**把片子取回来**（一分钱不花），绝不再 POST 一次（一分钱都不该再花）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=2, hook_codes=["7C0E1", "7C0E2"])
        sent, fresh = listed[0], listed[1]

        # 第一张：已经投上板（有 tid、queued、attempts=1）——形状照 `_adopt_tids` 落库
        async with dbmod.async_session_factory() as s:
            r = await s.get(AssetProduction, uuid.UUID(sent["id"]))
            r.status, r.board_tid, r.attempts = PR_QUEUED, "T000001", 1
            r.started_at = datetime.utcnow()
            await s.commit()

        fb = _FakeBoard(pre_existing=[("T000001", sent["board_name"] or "标题1")])
        with _board_off(fb):
            # ① 只回读回收：已投的那张取片子，没投的那张点名挡下
            rec = await _dispatch(client, ho, [sent["id"], fresh["id"]], recover_only=True)
        assert rec.status_code == 200, rec.text
        assert fb.creates == [], "回收档一次 POST 都不许出网"
        body = rec.json()
        assert body["recovered"] == 1 and body["succeeded"] == 1 and body["dispatched"] == 0
        assert len(body["blocked"]) == 1 and "只回读回收" in body["blocked"][0]["reason"]
        assert (await _row_of(AssetProduction, sent["id"])).status == PR_SUCCESS
        assert (await _row_of(AssetProduction, sent["id"])).attempts == 1, "回收不加 attempts（没再投一次）"
        assert await _count(AssetOutput) == 1

        # ② 混合点名：有 tid 的进回收、没 tid 的才建任务（各走各的，不串）。
        # 先把①到手的那张放回"已投上板但片子还没回收"的形状——现网进程重启前就是这一瞬，
        # 留着 success 状态测不到"回收＋新建混在一批"这条真实形状。
        async with dbmod.async_session_factory() as s:
            r = await s.get(AssetProduction, uuid.UUID(sent["id"]))
            r.status, r.completed_at = PR_QUEUED, None
            await s.commit()
        fb2 = _FakeBoard(pre_existing=[("T000001", sent["board_name"] or "标题1")])
        with _board_off(fb2):
            mixed = await _dispatch(client, ho, [sent["id"], fresh["id"]])
        assert mixed.status_code == 200, mixed.text
        assert len(fb2.creates) == 1, "两张单只有一条是新建"
        assert fb2.creates[0]["reqID"] == str(fresh["id"])
        mbody = mixed.json()
        assert mbody["dispatched"] == 1 and mbody["recovered"] == 1
        # 同一条 outUrl 不会被第二次落进产物：回收幂等靠的就是板上那个 outUrl
        assert await _count(AssetOutput) == 2, await _count(AssetOutput)

        # ③ 一张都没投过却要求只回收 → 400（不许空跑一次「看起来在回收」）
        # ② 已经把 fresh 投出去了，所以再建一条真·没投过的来验。
        # 这里同样要在 `_board_off` 里跑：出了作用域凭据就还原成空，会先撞上
        # "自动投板还没启用"那道 400（11-05 用例实测：两条 400 措辞完全不同，别混）。
        _a2, _s2, only_new = await _order_ready_production(client, h, url=DOUYIN_3, n=1,
                                                          hook_codes=["7C0E3"])
        fb3 = _FakeBoard()
        with _board_off(fb3):
            none = await _dispatch(client, ho, [only_new[0]["id"]], recover_only=True)
        assert none.status_code == 400 and "board_tid" in none.json()["detail"], none.text
        assert none.json()["detail"].count("无从回读") == 1
        assert fb3.creates == [], "空跑一次也不该出网"
        await client.aclose()

    _run(_scenario())


def test_dispatch_reclaims_a_row_whose_create_timed_out():
    """POST 报了错 ≠ 板上没有这条：先差集认领，认到就照实记账（这一条最值钱）。

    真实事故形状：90s 超时把连接掐了，板子其实建上了。如果按"报错＝没投"处理，
    一线重投一次就是同一条文案烧两遍号池。这里钉三件事：
    ① 只 POST 了一次；② tid 认回来了、片子照样到手；③ `created` 里这条**只有一行**
    （曾经这里 append 了两次，台账会虚报"投了 2 张"）。
    """
    _run(_bootstrap())

    class _TimeoutBoard(_FakeBoard):
        """建任务超时，但行**已经落在板上**（板子的真实行为）。"""

        async def create_task(self, payload):
            self.creates.append(dict(payload))
            self._add_row(tid=self._next_tid(), name=str(payload.get("name") or ""),
                          tag=str(payload.get("tag") or ""), created_index=len(self.creates))
            raise board_mod.BoardError("连不上后台任务板（ReadTimeout），本条没投出去，稍后重试或改人工投板")

        async def download_output(self, out_url):
            self.downloads.append(str(out_url))
            return self.video_bytes

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0E4"])
        pid = listed[0]["id"]

        fb = _TimeoutBoard()
        with _board_off(fb):
            resp = await _dispatch(client, ho, [pid])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(fb.creates) == 1, "认回来了就绝不重投"
        assert body["dispatched"] == 1 and len(body["created"]) == 1, body["created"]
        assert body["created"][0]["recovered_after_error"], body["created"]
        assert "ReadTimeout" in body["created"][0]["recovered_after_error"]
        assert body["uncertain"] == [] and body["errors"] == []
        row = await _row_of(AssetProduction, pid)
        assert row.status == PR_SUCCESS and row.board_tid == "T000001", (row.status, row.board_tid)
        assert row.attempts == 1
        assert await _count(AssetOutput) == 1
        await client.aclose()

    _run(_scenario())


def test_dispatch_board_refusal_stays_order_ready_and_vanished_row_is_uncertain():
    """两种"没对上账"必须分开：板子明确拒了＝留 order_ready；建上了却查不到＝状态未知。

    前者可以放心再点一次；后者**绝不能**自动重投——先让人去板面看一眼
    （1021 那次 date 写错、120 条永久找不回，就是"投出去了但认不回"的形状）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=2, hook_codes=["7C0E5", "7C0E6"])
        refused, vanished = listed[0], listed[1]

        # ① 板子拒了（且回读确认没有新行）
        fb1 = _FakeBoard(create_error=board_mod.BoardError("后台板拒绝建任务（HTTP 200）：号池当天已用完"))
        with _board_off(fb1):
            r1 = await _dispatch(client, ho, [refused["id"]])
        assert r1.status_code == 200, r1.text
        b1 = r1.json()
        assert b1["dispatched"] == 0 and len(b1["errors"]) == 1 and b1["errors"][0]["stage"] == "建任务"
        assert b1["uncertain"] == []
        assert "号池当天已用完" in b1["errors"][0]["error"]
        row = await _row_of(AssetProduction, refused["id"])
        assert row.status == PR_ORDER_READY and row.board_tid is None and row.attempts == 0, (
            '连板都没上，没有"失败"可言：不许落 failed 污染当天到手率')
        assert "一张都没投出去" in b1["message"]

        # ② 回了 succ 但按批次日＋今天都查不到新行 → 状态未知，点名人工看板
        fb2 = _FakeBoard(hide_new=True)
        with _board_off(fb2):
            r2 = await _dispatch(client, ho, [vanished["id"]])
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2["dispatched"] == 0 and len(b2["uncertain"]) == 1, b2
        assert "请立刻到板面核对" in b2["uncertain"][0]["error"] and "重复建任务" in b2["uncertain"][0]["error"]
        assert b2["errors"] == [], '未知不是"板子拒了"，两句话不能混'
        row2 = await _row_of(AssetProduction, vanished["id"])
        assert row2.status == PR_ORDER_READY and row2.board_tid is None, "认不回来的单不钉 tid"
        assert await _count(AssetOutput) == 0
        await client.aclose()

    _run(_scenario())


def test_dispatch_waiting_and_read_jitter_are_never_failures():
    """板面判读的两条"别当失败"：waiting 是还在跑；查不到/查得抖一下也是还在跑。

    判死的后果不是状态难看，而是**诱导重投**——11-04 真把 waiting 当失败重投过，
    同一条烧了两遍号池。到期同样不判失败，只写"稍后带 recover_only 再回收一次"。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=2, hook_codes=["7C0E7", "7C0E8"])
        waits, jitters = listed[0], listed[1]

        # ① waiting 两轮 → succ：全程没被改成 failed，最后正常到手
        fb = _FakeBoard(status_fn=lambda created_index, read_round: "waiting" if read_round < 3 else "succ")
        with _board_off(fb):
            resp = await _dispatch(client, ho, [waits["id"]])
        assert resp.status_code == 200, resp.text
        assert resp.json()["succeeded"] == 1 and resp.json()["failed"] == 0
        assert len(fb.creates) == 1, "waiting 期间不许再 POST 一次"
        assert len(fb.reads) >= 3, "至少轮过 waiting 的那两轮"
        assert (await _row_of(AssetProduction, waits["id"])).status == PR_SUCCESS

        # ② 回读一直失败（第 3 次起抛错）：不判死，留在 queued 并记下最后一次的原话
        fb2 = _FakeBoard(readback_error_after=2)
        with _board_off(fb2):
            resp2 = await _dispatch(client, ho, [jitters["id"]])
        assert resp2.status_code == 200, resp2.text
        body2 = resp2.json()
        assert body2["failed"] == 0 and body2["still_running"] == 1, body2["results"]
        s = list(body2["results"].values())[0]
        assert s["status"] == PR_QUEUED and s["last_read_error"], s
        assert "到期" in s["note"], s
        row = await _row_of(AssetProduction, jitters["id"])
        assert row.status == PR_QUEUED and row.board_tid == "T000001", (row.status, row.board_tid)
        assert row.error is None, "没出片不等于失败，error 不能写脏"
        assert await _count(AssetOutput) == 1, "只有 waiting 那条到手，抖动这条取不到片"
        await client.aclose()

    _run(_scenario())


def test_dispatch_restarts_a_failed_task_within_the_retry_budget():
    """板面全版 fail → 按同一条 payload **有界**自动重启；额度花完落 failed 交人工。

    11-24 需求④（用户：「失败后有一个重试机制」，圈定口径「有界自动重试＋缺口提示」）：
    旋钮 `ASSET_BOARD_RETRY_MAX` 说了算，用例把旋钮钉死再断言，**不跟 config 默认值走**
    ——否则日后改默认值会把这条钉子悄悄改成另一个形状。四格共用一条判据 `len(fb.creates)`：

    - `retry_max=1`（老口径）＝首投＋1 次＝2 次上板；
    - 首投就成功＝一次都不多烧；
    - `retry_max=2`（现默认）且一直 fail＝3 次上板后收手，成因写明重启了几次、上限多少；
    - `retry_max=0`＝完全关掉自动重试，失败直接交人工（1 次上板）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=4, hook_codes=["7C0E9", "7C0F1", "7C0F2", "7C0F3"])
        ok_first, revived, dead, off = listed[0], listed[1], listed[2], listed[3]

        # ⓪ 首投就成功：重试这条路根本没走，板上只建一条（额度不因新旋钮而多烧）
        fb0 = _FakeBoard()
        with _board_off(fb0, retry_max=2):
            resp0 = await _dispatch(client, ho, [ok_first["id"]])
        assert len(fb0.creates) == 1, f"成功条不该触发重启：{fb0.creates}"
        assert list(resp0.json()["results"].values())[0]["retries"] == 0
        assert resp0.json()["gap"]["retries"] == 0

        # ① 老口径 retry_max=1：首投 fail → 重启一次 → succ
        fb = _FakeBoard(status_fn=lambda created_index, read_round: (
            "fail" if created_index == 1 else "succ"))
        with _board_off(fb, retry_max=1):
            resp = await _dispatch(client, ho, [revived["id"]])
        assert resp.status_code == 200, resp.text
        assert len(fb.creates) == 2, "上限 1 次＝最多两次上板"
        b = resp.json()
        r = list(b["results"].values())[0]
        # `restarted` 这个旧键保留（前端/历史用例按它判「救回来了」），新键是次数
        assert r["restarted"] is True and r["retries"] == 1 and r["retry_max"] == 1, r
        assert b["succeeded"] == 1 and b["gap"]["retries"] == 1
        row = await _row_of(AssetProduction, revived["id"])
        assert row.status == PR_SUCCESS and row.board_tid == "T000002", (row.status, row.board_tid)
        assert row.attempts == 2, "重启是真投了一次，attempts 要如实+1"
        assert "失败自动重启 1 次" in b["message"], b["message"]

        # ② 默认口径 retry_max=2：一直 fail → 三次上板后收手，成因写明次数与上限
        fb2 = _FakeBoard(status_fn=lambda created_index, read_round: "fail")
        with _board_off(fb2, retry_max=2):
            resp2 = await _dispatch(client, ho, [dead["id"]])
        assert len(fb2.creates) == 3, f"第四次就是无界重投烧号池了：{len(fb2.creates)}"
        b2 = resp2.json()
        assert b2["failed"] == 1 and b2["succeeded"] == 0
        row2 = await _row_of(AssetProduction, dead["id"])
        assert row2.status == PR_FAILED
        assert "自动重启 2 次（上限 2 次）仍失败" in row2.error, row2.error
        assert "没有原因字段" in row2.error, row2.error
        assert row2.attempts == 3, "三次上板都记进台账"

        # ③ 关掉自动重试 retry_max=0：失败直接交人工，一次都不重投
        fb3 = _FakeBoard(status_fn=lambda created_index, read_round: "fail")
        with _board_off(fb3, retry_max=0):
            resp3 = await _dispatch(client, ho, [off["id"]])
        assert len(fb3.creates) == 1, "上限 0 就是完全关，别偷偷重投"
        row3 = await _row_of(AssetProduction, off["id"])
        assert row3.status == PR_FAILED and "ASSET_BOARD_RETRY_MAX=0" in row3.error, row3.error
        assert "交人工判读" in row3.error, row3.error
        await client.aclose()

    _run(_scenario())


def test_dispatch_keeps_polling_after_an_auto_restart_from_running():
    """跑过几轮 running 才 fail 的单：重启后**必须继续跟踪**，不许把自己写回的 queued 当人工接管。

    11-27 现网事故形状（1116钩子-2）：首投先跑了几轮 waiting（库里被写成 running），
    之后板面 fail → 自动重启落 queued。下一轮「开工重读」拿 summary 里的旧快照（running）
    跟库里（queued）比，判成"人工改过状态"→ 整行让位、不再跟踪。结果板子 09:22 就出了
    succ，单子却在 queued 挂了一夜，任务台账还写着"轮询已结束"。

    判据：重启后照常等到 succ 并落库；note 里不许出现"人工已把状态改成"；attempts=2。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0FA"])

        # 建任务那一步自己会先回读一次（投前/投后差集），所以首投这一行的 `_reads`
        # 进轮询时已经是 1：`<=2` 才算第一轮的 waiting，第 3 次才是 fail。
        fb = _FakeBoard(status_fn=lambda created_index, read_round: (
            "waiting" if created_index == 1 and read_round <= 2
            else "fail" if created_index == 1 else "succ"))
        with _board_off(fb, retry_max=2):
            resp = await _dispatch(client, ho, [listed[0]["id"]])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(fb.creates) == 2, f"首投 fail 后只该重启一次：{len(fb.creates)}"

        r = list(body["results"].values())[0]
        assert body["succeeded"] == 1 and r["status"] == PR_SUCCESS, r
        assert r["restarted"] is True and r["retries"] == 1, r
        assert "人工已把状态改成" not in str(r.get("note") or ""), (
            "重启是自己的写回，不是人工接管——判成接管就会把这条单丢下不管")

        row = await _row_of(AssetProduction, listed[0]["id"])
        assert row.status == PR_SUCCESS and row.board_tid == "T000002", (row.status, row.board_tid)
        assert row.attempts == 2
        assert await _count(AssetOutput) == 1
        await client.aclose()

    _run(_scenario())


def test_dispatch_partial_version_failure_converges_with_a_named_gap():
    """一张单多版里只有部分版 fail：**不整批重启**，收掉成功版并点名缺几版。

    需求④的另一半（用户：「我需要多少素材，最终就能给我回收多少素材，能不能做到？」）。
    答复是「有界自动重试做不到百分百，但缺口必须说清楚」，这条用例钉的就是那句提示：

    1. 部分成功**没有**重启资格——重启是整条 payload 重投，会把已到手的版次再烧一遍额度；
    2. 板面全出终态后这张单**当场收敛**，不再空等到 45 分钟期限（改前会一路挂到到期）；
    3. 缺口口径读侧派生：`results[].short_by` ＝ 应收 board_total − 实收产物数，
       与生产单列表口 `short_by` 同源，界面上的「缺 N 版」和后台说的必须是同一个数；
    4. 提示里指到人能走的那一步：「按同文案重开单」，并写明隔夜不自动补投。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=1, board_total=3, hook_codes=["7C0F4"])
        prod = listed[0]

        # tid 是确定号：这张单一次 create 出 3 版＝T000001..T000003，点掉中间那版
        fb = _FakeBoard(fail_tids={"T000002"})
        with _board_off(fb, retry_max=2):
            resp = await _dispatch(client, ho, [prod["id"]])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(fb.creates) == 1, "部分失败不许整批重启（会把已到手的 2 版再烧一遍）"

        r = list(body["results"].values())[0]
        assert (r["expected"], r["collected"], r["short_by"]) == (3, 2, 1), r
        assert r["status"] == PR_FAILED and r["retries"] == 0, r
        assert body["gap"] == {"expected": 3, "collected": 2, "short_by": 1,
                               "retry_max": 2, "retries": 0}, body["gap"]
        assert "缺口 1 版（要 3 版、账上已收 2 版）" in body["message"], body["message"]
        assert "按同文案重开单" in body["message"] and "隔夜不自动补投" in body["message"]

        row = await _row_of(AssetProduction, prod["id"])
        assert row.status == PR_FAILED, row.status
        assert "板面 3 版里 1 版 fail（succ 的 2 版已正常回收）" in row.error, row.error
        assert "按同文案重开单" in row.error, row.error
        assert await _count(AssetOutput) == 2, "已成功的 2 版要照常落库，不能整批作废"

        # 列表口的缺口必须和回收协程说同一个数（读侧派生，不是另一套算法）
        got = await client.get("/api/assets/productions", headers=ho)
        assert got.status_code == 200, got.text
        mine = [x for x in got.json()["items"] if x["id"] == str(prod["id"])]
        assert len(mine) == 1
        assert mine[0]["board_total"] == 3 and mine[0]["output_count"] == 2
        assert mine[0]["short_by"] == 1, mine[0]

        # 没投过板的行（order_ready）不算缺口：否则界面满屏假「缺 N 版」。
        # ⚠️ url 必须换一条（DOUYIN_3）：同一条链接二次导入会被去重挡下，items 是空的。
        fresh = await _order_ready_production(
            client, h, n=1, board_total=2, hook_codes=["7C0F5"], url=DOUYIN_3)
        row_f = [x for x in (await client.get("/api/assets/productions", headers=ho)
                             ).json()["items"] if x["id"] == fresh[2][0]["id"]]
        assert row_f[0]["status"] == PR_ORDER_READY and row_f[0]["short_by"] == 0, row_f[0]
        await client.aclose()

    _run(_scenario())


def test_dispatch_has_no_quota_limit_or_capacity_hint():
    """免费投板不设额度/软线：13 张单 × total 20 可执行，预检报 260 条且不带容量提示。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        _asset_id, _sid, listed = await _order_ready_production(
            client, h, n=13, board_total=20)
        assert len(listed) == 13
        ids = [p["id"] for p in listed]

        # 一直 waiting：只验证建任务可执行，不下载 260 条成片；到期仍留在 queued，不判失败。
        fb = _FakeBoard(status_fn=lambda created_index, read_round: "waiting")
        with _board_off(fb):
            resp = await _dispatch(client, ho, ids, async_mode=True)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            precheck = body["precheck"]
            assert precheck["will_create"] == 13 and precheck["will_recover"] == 0
            assert precheck["planned_board_rows"] == 260, precheck
            assert not {"capacity_hint", "board_capacity", "capacity"} & body.keys(), body
            assert not {"capacity_hint", "board_capacity", "capacity"} & precheck.keys(), precheck
            job = await _wait_job(client, ho, body["job_id"])
        assert job["status"] == "succeeded", job
        assert len(fb.creates) == 13 and all(p["total"] == 20 for p in fb.creates)

        listed_after = await client.get("/api/assets/productions", headers=ho)
        assert listed_after.status_code == 200, listed_after.text
        today = listed_after.json()["dispatch"]["today"]
        assert today["tasks"] == 13 and today["board_rows"] == 260, today
        assert today["by_status"] == {"running": 13}, today
        assert not {"soft_cap", "over_cap", "note"} & today.keys(), today
        await client.aclose()

    _run(_scenario())


def test_dispatch_refuses_when_board_not_configured():
    """凭据没配＝**当场白话拒绝**：不查库、不建任务、不进台账，也不留半个出网的包。

    这条钉子同时守两件事：
    ① `AIVIDEO_AUTH` / `ASSET_BOARD_BASE_URL` 不是"改了没读者"的假旋钮（11-04 D-3
       清掉的正是这类旋钮）——投递口第一件事就是问 `board.is_configured()`；
    ② 拒绝的话必须把"那我这一批怎么办"说全：导出 payload 人工投板 → 投完走投递状态回写
       记账。这条老路一直没断，别让人对着一个空 400 猜。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        _aid, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0F2"])
        pid = listed[0]["id"]

        fb = _FakeBoard()
        saved_auth = settings.AIVIDEO_AUTH
        saved_url = settings.ASSET_BOARD_BASE_URL
        try:
            for label, patch_what in (
                ("凭据为空", {"AIVIDEO_AUTH": ""}),
                ("板地址为空", {"ASSET_BOARD_BASE_URL": ""}),
            ):
                settings.AIVIDEO_AUTH = saved_auth or "tester:pass"
                settings.ASSET_BOARD_BASE_URL = saved_url or "http://board.invalid"
                for k, v in patch_what.items():
                    setattr(settings, k, v)
                assert board_mod.is_configured() is False, f"{label} 时判据就该算出没配齐"
                # 出网函数全程打桩：万一判据失效，这里宁可打桩也不会真连板
                with contextlib.ExitStack() as st:
                    for p in _patch_board(fb):
                        st.enter_context(p)
                    resp = await client.post(
                        "/api/assets/productions/dispatch",
                        json={"ids": [pid], "confirm": True, "async_mode": False}, headers=ho,
                    )
                assert resp.status_code == 400, (label, resp.text)
                detail = resp.json()["detail"]
                assert "自动投板还没启用" in detail, (label, detail)
                assert "AIVIDEO_AUTH" in detail and "人工投板" in detail, (label, detail)
                assert "回写" in detail, (label, detail)
            assert fb.creates == [] and fb.reads == [] and fb.downloads == [], "拒绝发生在出网之前"
            assert await _count(AssetJob) == 0, "没启用 ≠ 一次失败的任务，别往台账里塞"
            assert (await _row_of(AssetProduction, pid)).status == PR_ORDER_READY
        finally:
            settings.AIVIDEO_AUTH = saved_auth
            settings.ASSET_BOARD_BASE_URL = saved_url
        await client.aclose()

    _run(_scenario())


def test_dispatch_overnight_reclaim_needs_both_days():
    """隔夜单靠**双日并集**才认得回来：昨天投的，今天回读必须同时查昨天和板面今天。

    形状照 10-25 那批真实排队跨午夜的情况：`board_date` 是昨天、tid 也落在昨天那一天。
    只查今天 → 一行都查不到 → 于是"看起来全失败" → 人去重投 → 同一条烧两遍号池。
    所以这里钉三层：
    ① 回读带的日期集合**同时含**昨天与板面今天；
    ② 昨天那一天的行确实被认回来、片子到手；
    ③ 反过来，把"昨天那天查不到"演出来时**不判失败**——单子留在 queued 并写明稍后再
       回收一次。认不到不等于没投上（11-04 反推轮询同一条教训）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        _aid, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0F3"])
        old = listed[0]
        yest, today = _board_today(-1), _board_today()
        aged = datetime.utcnow() + timedelta(
            hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0)) - timedelta(days=1)
        async with dbmod.async_session_factory() as s:
            r = await s.get(AssetProduction, uuid.UUID(old["id"]))
            r.status, r.board_tid, r.attempts = PR_QUEUED, "T000001", 1
            r.board_date = aged
            r.started_at = datetime.utcnow()
            await s.commit()

        # ①② 昨天的行＋tid 已钉上：只回读回收，一次 POST 都不该出
        fb = _FakeBoard(pre_existing=[("T000001", old["board_name"] or "隔夜单", yest)])
        with _board_off(fb):
            resp = await _dispatch(client, ho, [old["id"]], recover_only=True)
        assert resp.status_code == 200, resp.text
        assert fb.creates == [], "回收档不新建"
        assert fb.reads and set(fb.reads[0][0]) >= {yest, today}, fb.reads[:1]
        body = resp.json()
        assert body["recovered"] == 1 and body["succeeded"] == 1, body["results"]
        assert (await _row_of(AssetProduction, old["id"])).status == PR_SUCCESS
        assert await _count(AssetOutput) == 1, "隔夜片子必须落进产物"

        # ③ 同一条单，把"昨天那天查不到"演出来：认不到 ≠ 失败
        async with dbmod.async_session_factory() as s:
            r = await s.get(AssetProduction, uuid.UUID(old["id"]))
            r.status, r.completed_at, r.error = PR_QUEUED, None, None
            await s.commit()
        fb2 = _FakeBoard(
            pre_existing=[("T000001", old["board_name"] or "隔夜单", yest)],
            readback_ok_days=[today],
        )
        with _board_off(fb2):
            resp2 = await _dispatch(client, ho, [old["id"]], recover_only=True)
        assert resp2.status_code == 200, resp2.text
        b2 = resp2.json()
        assert b2["failed"] == 0 and b2["still_running"] == 1, b2["results"]
        s2 = list(b2["results"].values())[0]
        assert s2["status"] == PR_QUEUED and "到期" in s2.get("note", ""), s2
        assert (await _row_of(AssetProduction, old["id"])).status == PR_QUEUED
        assert (await _row_of(AssetProduction, old["id"])).error is None
        await client.aclose()

    _run(_scenario())


def test_dispatch_duplicate_job_returns_409_without_quota_wording():
    """同一批投板任务已在后台跑 → 第二次提交当场 409，且不提额度。

    防重复判据仍由台账完成：409 必须发生在出网/建任务之前，也不留下第二份活。
    免费投板没有号池额度话术，重复提示只说明这批任务已经在运行。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        _aid, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0F2"])
        pid = listed[0]["id"]

        async with dbmod.async_session_factory() as s:
            n0 = len((await s.execute(select(AssetJob))).scalars().all())
            s.add(AssetJob(kind=JOB_DISPATCH, status=JB_QUEUED, params={"ids": [pid]}))
            await s.commit()

        fb = _FakeBoard()
        with _board_off(fb):
            dup = await client.post(
                "/api/assets/productions/dispatch",
                json={"ids": [pid], "confirm": True, "async_mode": True}, headers=ho,
            )
        assert dup.status_code == 409, dup.text
        detail = dup.json()["detail"]
        assert "同一批投板任务已在运行" in detail, detail
        assert "额度" not in detail, "免费投板不再提号池额度"
        assert fb.creates == [] and fb.reads == [], "409 发生在出网之前，一张都没投、一次都没读"
        async with dbmod.async_session_factory() as s:
            n1 = len((await s.execute(select(AssetJob))).scalars().all())
        assert n1 == n0 + 1, "被 409 拦下的提交不许在台账里留下第二份活"
        assert (await _row_of(AssetProduction, pid)).status == PR_ORDER_READY
        await client.aclose()

    _run(_scenario())


# ──────────────────────────────────────────────
# 批 J（11-05）：反推顺带下载原片 + 过审顺手备豆包提示词
# ──────────────────────────────────────────────


class _FakePullDownloader:
    """拉流下载替身：往 local_path 写真字节（后面 upload/ffprobe 都按真文件走）。"""

    def __init__(self, *, total=None, fail=False, empty=False, payload=VIDEO_BYTES):
        self.total = total if total is not None else len(payload)
        self.fail = fail
        self.empty = empty
        self.payload = payload
        self.calls: list = []

    async def download_to_file(self, play_url, local_path):
        self.calls.append(play_url)
        if self.fail:
            raise RuntimeError("direct download http 403")
        if self.empty:
            return 0
        with open(local_path, "wb") as f:
            f.write(self.payload)
        return self.total


def test_analyze_queues_download_for_link_assets_by_default():
    """用户口径「反推默认顺带下载」：反推提交完，链接素材自动排下载任务；download=false 才不排。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id, a.stage_prompt, a.status = None, "pending", "waiting_prompt"
            await s.commit()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())), \
             patch("app.api.assets._enqueue_download", AsyncMock(
                 return_value={"queued": True, "job_id": "j1", "queued_count": 1, "note": None})) as enq:
            resp = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["download"]["queued"] is True and body["download"]["queued_count"] == 1
        # 排的正是这条链接素材，且是**还没在桶里**的（file_key 为空）
        assert enq.await_count == 1
        assert enq.await_args.kwargs["asset_ids"] == [asset_id]
        assert "原片正在后台下载" in body["message"]

        # download=false：一句话都不排（显式关掉要被尊重）
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id, a.stage_prompt, a.status = None, "pending", "waiting_prompt"
            await s.commit()
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())), \
             patch("app.api.assets._enqueue_download", AsyncMock()) as enq2:
            resp2 = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": [asset_id], "download": False}, headers=hm)
        assert resp2.status_code == 200
        assert resp2.json()["download"] is None
        enq2.assert_not_awaited()
        await client.aclose()

    _run(_scenario())


def test_download_endpoint_four_piece_set_charges_paid_channel_and_is_idempotent():
    """下载口四件套：解析→拉流→落桶→探时长；付费渠道记 0.01 进 cost_parse；重下跳过不重复占桶。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)

        parsed = SimpleNamespace(success=True, channel="paid-http", play_url="http://cdn.example/v.mp4",
                                 duration=None, title="某剧某集", meta={})
        dl = _FakePullDownloader()
        upload = AsyncMock(return_value=True)
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)), \
             patch("app.api.assets.get_downloader", lambda: dl), \
             patch("app.api.assets.upload_file_from_path", upload), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=8.42)):
            resp = await client.post(
                "/api/assets/download", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["downloaded"] == 1 and body["charged"] == pytest.approx(0.01, abs=1e-4)
        assert body["results"][0]["ok"] is True and body["results"][0]["channel"] == "paid-http"

        row = await _row_of(AssetItem, asset_id)
        assert row.download_status == "success"
        assert row.file_key and row.file_key.startswith(f"asset/source/{row.code}/")
        assert row.bucket == settings.MINIO_BUCKET_RAW
        assert row.file_size == len(VIDEO_BYTES)
        assert row.duration == 8.42, "没探过时长的链接素材顺带补上真实时长"
        assert row.cost_parse == pytest.approx(0.01, abs=1e-4)
        # 落桶的是拉流到的真字节，不是 201 假成功（真链路踩过 0 字节对象的坑）
        assert upload.await_args.args[2] == dl.calls[0] or upload.await_count == 1
        audits = await _rows(AuditLog, AuditLog.action == "asset.download")
        assert len(audits) == 1 and audits[0].after["downloaded"] == 1

        # 幂等：file_key 已非空 → 原样跳过，不再解析（不重复付费）不再拉流
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)) as dp, \
             patch("app.api.assets.get_downloader", lambda: _FakePullDownloader()):
            again = await client.post(
                "/api/assets/download", json={"asset_ids": [asset_id]}, headers=hm)
        assert again.status_code == 200
        assert again.json()["downloaded"] == 0
        assert "已经在自有桶里" in again.json()["skipped"][0]["reason"]
        dp.assert_not_awaited(), "重复下载绝不再发起解析（付费渠道重复＝重复扣 0.01）"
        assert (await _row_of(AssetItem, asset_id)).cost_parse == pytest.approx(0.01, abs=1e-4)
        await client.aclose()

    _run(_scenario())


def test_download_success_enqueues_frames_for_review_cards():
    """11-05 易操作性评估 P0-1：链接素材原片下载落桶后**必须**补排抽帧。

    修前现状：上传（导入）和拼接两条路都排抽帧，唯独下载这条漏了——现网
    asset_frames 0 行实锤，链接素材的审核台卡片永远「没有预览图」，
    审核员全程只能凭文字审。修后：下载成功即排，失败条不排、不连累下载结果。
    """
    _run(_bootstrap())

    async def _scenario():
        from wechat_download.provider_registry import ProviderParseError
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)

        parsed = SimpleNamespace(success=True, channel="paid-http", play_url="http://cdn.example/v.mp4",
                                 duration=None, title="某剧某集", meta={})
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)), \
             patch("app.api.assets.get_downloader", lambda: _FakePullDownloader()), \
             patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=8.42)), \
             patch("app.api.assets._enqueue_frames", AsyncMock(
                 return_value={"queued": True, "job_id": "jf1", "note": None})) as enq:
            resp = await client.post(
                "/api/assets/download", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["downloaded"] == 1
        assert body["frames"] == {"queued": True, "job_id": "jf1", "note": None}
        assert "抽帧已排后台" in body["message"], "回话里要告诉一线卡片几分钟后有图"
        enq.assert_awaited_once()
        kw = enq.await_args.kwargs
        assert kw["asset_ids"] == [asset_id] and kw["output_ids"] == []
        assert kw["why"] == "原片下载完成"

        # 失败条不排：解析炸了（没落桶）就没什么好抽的，抽帧排程也不该被发起
        r2 = await _import(client, hm, ["https://www.douyin.com/video/7612222333334667555"])
        id2 = r2.json()["items"][0]["id"]
        with patch("app.api.assets.dispatch_parse", AsyncMock(
                side_effect=ProviderParseError("yuanbao 限流"))), \
             patch("app.api.assets._enqueue_frames", AsyncMock()) as enq2:
            resp2 = await client.post(
                "/api/assets/download", json={"asset_ids": [id2]}, headers=hm)
        assert resp2.status_code == 200
        assert resp2.json()["downloaded"] == 0
        assert resp2.json()["frames"] is None
        enq2.assert_not_awaited()
        await client.aclose()

    _run(_scenario())


def test_download_failures_are_per_item_and_fail_soft():
    """解析失败/拉流失败都逐条标 failed 带原因，不连坐整批、解析失败不记账。"""
    _run(_bootstrap())

    async def _scenario():
        from wechat_download.provider_registry import ProviderParseError
        client, h = await _client_and_headers()
        hm = h["material"]
        r1 = await _import(client, hm, ["https://www.douyin.com/video/7611111222222333444"])
        r2 = await _import(client, hm, ["https://www.douyin.com/video/7619999888882333444"])
        id1, id2 = r1.json()["items"][0]["id"], r2.json()["items"][0]["id"]

        async def _parse_ok(url):
            return SimpleNamespace(success=True, channel="yuanbao", play_url="http://cdn.example/a.mp4",
                                   duration=None, title=None, meta={})

        async def _parse_fail(url):
            raise ProviderParseError("yuanbao 限流 | preview 不支持该链接")

        dl_fail = _FakePullDownloader(fail=True)
        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse_fail)), \
             patch("app.api.assets.get_downloader", lambda: _FakePullDownloader()):
            resp = await client.post(
                "/api/assets/download", json={"asset_ids": [id1, id2]}, headers=hm)
        assert resp.status_code == 200
        body = resp.json()
        assert body["downloaded"] == 0 and body["charged"] == 0.0, "解析失败一条都没记账"
        assert "解析分享链接失败" in body["results"][0]["error"]
        rows = {str(r.id): r for r in await _rows(AssetItem)}
        assert rows[id1].download_status == "failed"
        assert rows[id1].cost_parse == 0.0

        # 拉流失败：解析（免费渠道）成功、不记账，但下载状态标 failed 带原因
        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse_ok)), \
             patch("app.api.assets.get_downloader", lambda: dl_fail):
            resp2 = await client.post(
                "/api/assets/download", json={"asset_ids": [id1]}, headers=hm)
        assert resp2.status_code == 200
        assert "拉流下载失败" in resp2.json()["results"][0]["error"]
        row = await _row_of(AssetItem, id1)
        assert row.download_status == "failed" and row.file_key is None
        assert row.cost_parse == 0.0, "yuanbao 是免费渠道，失败也不记账"
        await client.aclose()

    _run(_scenario())


def test_download_content_gate_rejects_html_and_keeps_the_books():
    """11-09 现网事故（AS-BB8563FD）补的第五步：拉回来的是网页就判失败，绝不入桶标成功。

    旧代码只挡 0 字节／异常／落桶失败——智令对一条视频号链接回了一个 10.8KB 的 HTML
    中转页（标题「左下角剧名一口气免费看完大结局」），多大都算过：网页带着 video/mp4
    进了自有桶、download_status=success、stage_import=success、照记 0.01 元解析费、
    还排了抽帧（必然 0 帧）。修后：闸门按容器魔数认，认不出再用 ffprobe 兜底，
    两样都不过关就标 failed ＋ 白话原因（说清拿到的是**什么**），不入桶、不抽帧，
    但解析费如实记——钱是真花了。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)

        html = (
            '<!DOCTYPE html><html><head><title>左下角剧名一口气免费看完大结局</title></head>'
            '<body>const videoUrl = "https://finder.video.qq.com/251/stodownload";</body></html>'
        ).encode("utf-8")
        parsed = SimpleNamespace(success=True, channel="zhiling", play_url="https://vnd.example/page",
                                 duration=None, title=None, meta={})
        upload = AsyncMock(return_value=True)
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)), \
             patch("app.api.assets.get_downloader",
                   lambda: _FakePullDownloader(payload=html, total=len(html))), \
             patch("app.api.assets.upload_file_from_path", upload), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=None)), \
             patch("app.api.assets._enqueue_frames", AsyncMock()) as enq:
            resp = await client.post(
                "/api/assets/download", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["downloaded"] == 0
        err = body["results"][0]["error"]
        assert "不是视频" in err and "网页" in err, err
        assert "免费看完大结局" in err, "原因要说出拉回来的到底是什么，一线照着才知道换路子"
        assert body["charged"] == pytest.approx(0.01, abs=1e-4), "解析真花了钱，失败也如实记账"
        assert body["frames"] is None and enq.await_count == 0, "挡下的条不排抽帧（旧行为＝抽 0 帧）"
        upload.assert_not_awaited(), "网页绝不入桶"
        row = await _row_of(AssetItem, asset_id)
        assert row.download_status == "failed" and row.file_key is None, "不能留个 success 的空壳"
        assert row.cost_parse == pytest.approx(0.01, abs=1e-4)

        # 反面对照：真 mp4 容器（ffmpeg 都省了）照样成功，闸门不是把这条线整体收紧
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)), \
             patch("app.api.assets.get_downloader", lambda: _FakePullDownloader()), \
             patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=8.42)), \
             patch("app.api.assets._enqueue_frames", AsyncMock(
                 return_value={"queued": True, "job_id": "j2", "note": None})):
            resp2 = await client.post(
                "/api/assets/download", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp2.status_code == 200 and resp2.json()["downloaded"] == 1, resp2.text
        row2 = await _row_of(AssetItem, asset_id)
        assert row2.download_status == "success" and row2.file_key
        await client.aclose()

    _run(_scenario())


def test_video_container_sniff_and_plain_reason():
    """闸门第一层单独问一遍：真容器要认出，网页/文本/乱码要各给一句人话。

    为什么要有这条：`_video_content_gate` 在集成用例里只走"mp4 放行 / 网页挡下"两端，
    中间那层判据（TS 只凭一个 0x47 就放行 = 会误放；m3u8 是文本 = 要挡）只有直接打
    函数才量得准。判据一旦改错，线上表现是"好链接被挡"或"网页又混进去"，都很难归因。
    """
    from app.api.assets import _describe_not_video, _sniff_video_container

    assert _sniff_video_container(bytes.fromhex("00000018") + b"ftypmp42" + b"\x00" * 64) == "mp4/mov"
    assert _sniff_video_container(b"\x1a\x45\xdf\xa3" + b"\x00" * 300) == "mkv/webm"
    assert _sniff_video_container(b"\x00\x00\x01\xba" + b"\x00" * 64) == "mpeg"
    assert _sniff_video_container(b"\x47" + b"\x11" * 187 + b"\x47" + b"\x22" * 187) == "mpeg-ts"
    assert _sniff_video_container(b"G" + b"\x00" * 50) is None, "不足一个 TS 包长就别硬认 TS"
    assert _sniff_video_container(b"") is None

    html = "<!DOCTYPE html><html><head><title>测试页</title></head></html>".encode("utf-8")
    assert "网页" in _describe_not_video(html) and "测试页" in _describe_not_video(html)
    assert "纯文本" in _describe_not_video(b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n")
    assert "认不出" in _describe_not_video(b"\x00\x01\x02\xff" * 32)


def test_source_preview_and_download_read_file_key_first():
    """批 J 订正：链接素材下载进桶后（file_key 非空），预览/下载口都按 stored 回，不再 external。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        lid, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(lid))
            a.file_key = f"asset/source/{a.code}/abc.mp4"
            a.bucket = settings.MINIO_BUCKET_RAW
            a.download_status = "success"
            await s.commit()

        presign = AsyncMock(return_value="https://minio.example/raw?X-Signature=2")
        with patch("app.api.assets.get_presigned_url", presign):
            got = await client.get(f"/api/assets/{lid}/source-download", headers=hm)
            prev = await client.get(f"/api/assets/{lid}/source-preview", headers=hm)
        assert got.status_code == 200 and got.json()["mode"] == "stored"
        assert prev.status_code == 200 and prev.json()["mode"] == "stored"
        assert prev.json()["url"].endswith("X-Signature=2")
        assert presign.await_count == 2
        await client.aclose()

    _run(_scenario())


def test_review_approve_enqueues_preview_and_unapprove_invalidates_it():
    """过审 → 自动排「备豆包提示词」；撤销过审 → 旧预览作废（重新过审会重新备）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]

        # 过审：预览任务自动排上，且话术点明「提示词正在后台备好」
        with patch("app.api.assets._enqueue_preview", AsyncMock(
                return_value={"queued": True, "job_id": "jp1", "note": None})) as enq:
            ok = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        assert ok.status_code == 200 and ok.json()["results"][0]["ok"] is True
        assert enq.await_count == 1
        assert enq.await_args.kwargs["summary_ids"] == [sid]
        assert "豆包提示词正在后台备好" in ok.json()["message"]

        # 人为放一份旧预览（模拟「以前过审时备过的」），撤销过审必须把它作废
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetSummary, uuid.UUID(sid))
            row.prompt_preview = "旧提示词（文案已经要变了）"
            row.prompt_preview_at = datetime.utcnow()
            await s.commit()
        reject = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "reject", "reason": "口播节奏不对，撤回重写"}, headers=ho)
        assert reject.status_code == 200 and reject.json()["results"][0]["ok"] is True
        row = await _row_of(AssetSummary, sid)
        assert row.prompt_preview is None and row.prompt_preview_at is None, \
            "过期预览留着，一线会拿它当投产结果——撤销过审必须一起作废"
        await client.aclose()

    _run(_scenario())


def test_review_response_carries_is_recommended_per_result():
    """11-06 P2：审核响应逐条带回 is_recommended（后端真话）。

    前端藏卡提示的「非推荐」统计吃这个字段——豁免重放/跨页勾选时目标行不在当前页，
    按当前页 items 数会漏报「其实会被藏住」。这条用例钉住：推荐条回 True、
    非推荐条回 False，且与库里实际值一致。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        good = _approvable(items)
        other_id = next(i["id"] for i in items if i["id"] != good["id"])

        # 人为把另一条改成非推荐；文案换成 good 的（生成侧不保证每条都过复核闸，
        # 这里只测「响应逐条回 is_recommended」，所以两条用同一段能过闸的文字）
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetSummary, uuid.UUID(other_id))
            row.is_recommended = False
            row.text = good["text"]
            row.word_count = len(row.text)
            await s.commit()

        ok = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [good["id"], other_id], "action": "approve"}, headers=ho)
        assert ok.status_code == 200, ok.text
        by_sid = {r["summary_id"]: r for r in ok.json()["results"]}
        assert by_sid[good["id"]]["ok"] is True and by_sid[other_id]["ok"] is True
        assert by_sid[good["id"]]["is_recommended"] is True, "推荐条必须如实回 True"
        assert by_sid[other_id]["is_recommended"] is False, "非推荐条必须如实回 False——前端靠它数「会被藏住几条」"
        # 与库里实际值对账，防「响应回一套、库里存一套」
        row_rec = await _row_of(AssetSummary, good["id"])
        row_non = await _row_of(AssetSummary, other_id)
        assert row_rec.is_recommended is True and row_non.is_recommended is False
        await client.aclose()

    _run(_scenario())


def test_preview_prompt_endpoint_gates_idempotent_and_fails_soft():
    """预览口：没过审不备；备过复用不重复等模型；模型挂了逐条说清且不拦投产。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        good = _approvable(items)
        pending_id = next(i["id"] for i in items if i["id"] != good["id"])

        # 没过审的不备
        not_approved = await client.post(
            "/api/assets/summaries/preview-prompt",
            json={"summary_ids": [pending_id]}, headers=ha)
        assert not_approved.status_code == 200
        assert "还没过审" in not_approved.json()["results"][0]["error"]

        # 过审（默认 _run 把自动预览排程按住了）→ 直接调预览口，mock 模型
        ok = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [good["id"]], "action": "approve"}, headers=ho)
        assert ok.status_code == 200

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            first = await client.post(
                "/api/assets/summaries/preview-prompt",
                json={"summary_ids": [good["id"]]}, headers=ha)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["results"][0]["ok"] is True and body["results"][0]["kept_verbatim"] is True
        assert "预览（非投产稿）" in body["results"][0]["note"]
        assert "重新展开" in body["results"][0]["note"]
        row = await _row_of(AssetSummary, good["id"])
        assert row.prompt_preview and "【第 1 段" in row.prompt_preview
        assert row.prompt_preview_at is not None
        audits = await _rows(AuditLog, AuditLog.action == "asset.prompt_preview")
        assert len(audits) == 1 and audits[0].after["kept_verbatim"] is True

        # 幂等：已有预览直接复用（模型一次都不用再等）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call:
            second = await client.post(
                "/api/assets/summaries/preview-prompt",
                json={"summary_ids": [good["id"]]}, headers=ha)
        assert second.json()["results"][0]["reused"] is True
        call.assert_not_awaited()

        # 模型挂了：逐条 fail-soft，话术说清「投产时会重新展开，不拦投产」
        with patch("app.api.assets._call_autoclip",
                   AsyncMock(side_effect=HTTPException(status_code=502, detail="AutoClip 炸了"))):
            boom = await client.post(
                "/api/assets/summaries/preview-prompt",
                json={"summary_ids": [pending_id]}, headers=ha)
        # pending 那条先被「没过审」拦（不发起模型调用），换一条真过审的来验 fail-soft：
        asset2, _ = await _make_ready_asset(client, hm, url=DOUYIN_1)
        items2, _ = await _gen_and_list(asset2, hm, client)
        good2 = _approvable(items2)
        await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [good2["id"]], "action": "approve"}, headers=ho)
        with patch("app.api.assets._call_autoclip",
                   AsyncMock(side_effect=HTTPException(status_code=502, detail="AutoClip 炸了"))):
            boom = await client.post(
                "/api/assets/summaries/preview-prompt",
                json={"summary_ids": [good2["id"]]}, headers=ha)
        assert boom.status_code == 200, "模型失败不等于接口失败：逐条报原因"
        assert boom.json()["results"][0]["ok"] is False
        assert "投产时会重新展开" in boom.json()["results"][0]["error"]
        assert (await _row_of(AssetSummary, good2["id"])).prompt_preview is None
        await client.aclose()

    _run(_scenario())


def test_preview_prompt_ends_transaction_before_model_call():
    """11-05 现网真链路实锤的坑：预览展开要趴 1~5 分钟等模型，若调模型前不把
    SELECT 的读事务 commit 收掉，PG 的 idle_in_transaction_session_timeout=60s
    会把连接掐死——模型明明成功返回了提示词，回写报 connection is closed，
    整个任务白跑（11-03 出文案口同款事故的预览版）。

    回归判据：用 SQLAlchemy 的 before_commit 事件记录提交次序——
    「commit 必须发生在调模型之前」（把 SELECT 的读事务收掉），且回写成功。
    """
    _run(_bootstrap())

    async def _scenario():
        from sqlalchemy import event
        from sqlalchemy.orm import Session as _SyncSession

        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        good = _approvable(items)
        # 过审时按住自动预览排程（默认 _run 罩法，见文件头说明）——
        # 不按住的话后台预览任务会和本测试的直调口并发跑，污染事件序列
        with patch("app.api.assets._enqueue_preview", AsyncMock(
                return_value={"queued": True, "job_id": "jp1", "note": None})):
            ok = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [good["id"]], "action": "approve"}, headers=ho)
        assert ok.status_code == 200

        order = []  # "commit" / "model" 按发生顺序

        def _on_commit(session):
            order.append("commit")

        fake = _fake_autoclip()

        async def autoclip_spy(path, payload, timeout=900.0):
            order.append("model")
            return await fake(path, payload, timeout)

        event.listen(_SyncSession, "before_commit", _on_commit)
        try:
            with patch("app.api.assets._call_autoclip", autoclip_spy):
                resp = await client.post(
                    "/api/assets/summaries/preview-prompt",
                    json={"summary_ids": [good["id"]]}, headers=ha)
        finally:
            event.remove(_SyncSession, "before_commit", _on_commit)
        assert resp.status_code == 200, resp.text
        assert resp.json()["results"][0]["ok"] is True
        assert "model" in order, "模型没被调到，探针失效"
        assert "commit" in order[:order.index("model")], (
            "调模型前没 commit 收事务：等模型的 1~5 分钟里读事务一直趴着，"
            "PG idle_in_transaction 60s 一到连接就被掐（11-05 现网实录："
            "1449 字提示词生成成功却回写失败，任务白跑）"
        )
        await client.aclose()

    _run(_scenario())


def test_download_and_preview_kinds_are_in_job_ledger():
    """两类新任务进 ASSET_JOB_KINDS：kind 校验、白话名称、防重复话术都要认得它们。"""
    assert assets_api.JOB_DOWNLOAD in assets_api.ASSET_JOB_KINDS
    assert assets_api.JOB_PROMPT_PREVIEW in assets_api.ASSET_JOB_KINDS
    assert assets_api._job_endpoint(assets_api.JOB_DOWNLOAD)[2] == "下载原片"
    assert assets_api._job_endpoint(assets_api.JOB_PROMPT_PREVIEW)[2] == "备豆包提示词"
    assert "解析费" in assets_api._twin_cost_phrase(assets_api.JOB_DOWNLOAD)
    assert "自动跳过" in assets_api._twin_cost_phrase(assets_api.JOB_PROMPT_PREVIEW)


def test_strict_audit_rejects_force_and_waive_when_audit_write_fails():
    """11-06 拍板①：force/waive 类动作审计写失败＝操作被拒；普通动作照旧 fail-soft。

    钉四件事：
    1. admin 豁免过审（waive）时审计落不下去 → 500、过审整体回滚、文案留在待审
       ——绝不出现「豁免了却查无此事」；
    2. admin 强制投板（force_risk）时**预审计**落不下去 → 500、板子一个字没碰、
       单还是 order_ready（预审计在动板子之前，这是它存在的意义）；
    3. 普通动作（不带豁免的过审）在同一个审计替身底下照常成功——fail-soft 没被顺手升级；
    4. 普通投板（不带 force）同样照常走完——预审计只在真 force 时才拦。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        # 审计替身：strict 的写一律炸（模拟审计库挂了），普通写照常放行
        real_write = assets_api._write_audit

        async def audit_down(*args, **kw):
            if kw.get("strict"):
                raise RuntimeError("audit db down")
            return await real_write(*args, **kw)

        # 本仓 httpx 的 ASGITransport 不认 raise_server_exceptions——500 会以异常冒出，
        # 用 try/except 折成状态码断言
        async def post_quiet(cl, *args, **kw):
            try:
                r = await cl.post(*args, **kw)
                return r.status_code, r
            except Exception:
                return 500, None

        # 500 也要能继续往下断言，所以严格路径全部走 post_quiet
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        risky = _risky(items)
        good = _approvable(items)

        # 先证明确实被复核闸拦（有拦点才有豁免可言）
        refused = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve"}, headers=ho)
        assert refused.json()["results"][0]["ok"] is False
        assert refused.json()["results"][0]["error_code"] == "ASSET_RECHECK_FAILED"

        # ① waive + 审计挂 → 操作被拒、整体回滚
        with patch.object(assets_api, "_write_audit", audit_down):
            st, waived = await post_quiet(
                client, "/api/assets/summaries/review",
                json={"summary_ids": [risky["id"]], "action": "approve",
                      "waive_reason": "语境需要，已与运营确认"}, headers=ha)
        assert st == 500, st
        row = await _row_of(AssetSummary, risky["id"])
        assert row.audit_status == RV_PENDING, "豁免没记上账就绝不能过审——整请求回滚"

        # ③ 普通过审在同一个替身底下照常成功（fail-soft 只对普通动作让路）
        with patch.object(assets_api, "_write_audit", audit_down):
            normal = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [good["id"]], "action": "approve"}, headers=ho)
        assert normal.status_code == 200, normal.text
        assert normal.json()["results"][0]["ok"] is True

        # ② 强制投板 + 审计挂 → 预审计拦下，板子一个字没碰
        asset_id2, _sid2, listed = await _order_ready_production(
            client, h, url="https://example.com/v/strict-audit-dispatch.mp4",
            hook_codes=["7C0E1"])
        prod = await client.get(f"/api/assets/productions?asset_id={asset_id2}", headers=ho)
        ptext = prod.json()["items"][0]["prompt_text"]
        assert ptext, "展开单才有正文，正文里挑个词钉成 block 才能造出 forced_ids"
        block_word = ptext[:2]
        put = await client.put("/api/assets/risk-lexicon",
                               json={"block": [block_word], "inherit": True}, headers=ha)
        assert put.status_code == 200, put.text

        with patch.object(assets_api, "_write_audit", audit_down):
            fb = _FakeBoard()
            with _board_off(fb):
                st2, forced = await post_quiet(
                    client, "/api/assets/productions/dispatch",
                    json={"ids": [listed[0]["id"]], "confirm": True, "async_mode": False,
                          "force_risk": True, "force_reason": "语境需要，已确认"},
                    headers=ha)
        assert st2 == 500, st2
        assert fb.creates == [], "预审计没落下去就绝不能动板子"
        prow = await _row_of(AssetProduction, listed[0]["id"])
        assert prow.status == PR_ORDER_READY, prow.status
        assert prow.board_tid is None

        # ④ 普通投板（不 force）在同一个替身底下照常走完——先把试验用的 block 词撤掉
        restore = await client.put("/api/assets/risk-lexicon",
                                   json={"block": [], "inherit": True}, headers=ha)
        assert restore.status_code == 200, restore.text
        with patch.object(assets_api, "_write_audit", audit_down):
            fb2 = _FakeBoard()
            with _board_off(fb2):
                plain = await client.post(
                    "/api/assets/productions/dispatch",
                    json={"ids": [listed[0]["id"]], "confirm": True, "async_mode": False},
                    headers=ho)
        assert plain.status_code == 200, plain.text
        assert plain.json()["dispatched"] == 1 and len(fb2.creates) == 1

        await client.aclose()

    _run(_scenario())


def test_cross_person_charge_actions_do_not_ask_confirmation_and_are_annotated():
    """跨人批次直接执行；成本确认/余额闸保留，审计仍记录操作人与批次来源。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        asset_id, _ = await _make_ready_asset(client, hm)
        async with dbmod.async_session_factory() as s:
            a = await s.get(AssetItem, uuid.UUID(asset_id))
            a.prompt_task_id, a.stage_prompt, a.status = None, "pending", "waiting_prompt"
            batch_id = a.batch_id
            await s.commit()

        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())) as cpt:
            analyzed = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": [asset_id], "max_duration": 180}, headers=ho)
        assert analyzed.status_code == 200, analyzed.text
        assert cpt.await_count == 1
        logs = await _rows(AuditLog, AuditLog.action == "asset.analyze_batch")
        cross = logs[-1].after["cross_person"]
        assert len(cross) == 1
        assert cross[0]["batch_owner"] == "素材专员"
        assert cross[0]["operator"] == OPERATOR_USER
        assert cross[0]["batch_id"] == str(batch_id)

        summary_id, _ = await _make_ready_asset(
            client, hm, url="https://example.com/v/cross-summary.mp4")
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            generated = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [summary_id]}, headers=ho)
        assert generated.status_code == 200, generated.text
        assert generated.json()["results"][0]["created"] > 0
        summary_logs = await _rows(AuditLog, AuditLog.action == "asset.summary_generate")
        assert summary_logs[-1].after["cross_person"][0]["batch_owner"] == "素材专员"

        imported = await _import(
            client, hm, ["https://www.douyin.com/video/7499000000000000091/"])
        assert imported.status_code == 201, imported.text
        resolve_id = imported.json()["items"][0]["id"]
        parsed = SimpleNamespace(channel="zhiling", play_url="https://cdn.example/v.mp4",
                                 duration=12.5, title="跨人解析")
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)) as dp, \
             patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)):
            resolved = await client.post(
                "/api/assets/resolve", json={"asset_ids": [resolve_id], "confirmed": True}, headers=ho)
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["results"][0]["ok"] is True
        dp.assert_awaited_once()
        resolve_logs = await _rows(AuditLog, AuditLog.action == "asset.resolve")
        assert resolve_logs[-1].after["cross_person"][0]["operator"] == OPERATOR_USER

        download_id, _ = await _make_ready_asset(
            client, hm, url="https://www.douyin.com/video/7499000000000000092/")
        parsed = SimpleNamespace(channel="paid-http", play_url="https://cdn.example/v.mp4",
                                 duration=None, title="跨人下载", meta={})
        with patch("app.api.assets.dispatch_parse", AsyncMock(return_value=parsed)) as dp, \
             patch("app.api.assets.get_downloader", lambda: _FakePullDownloader()), \
             patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=8.42)):
            downloaded = await client.post(
                "/api/assets/download", json={"asset_ids": [download_id]}, headers=ho)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.json()["downloaded"] == 1
        dp.assert_awaited_once()
        download_logs = await _rows(AuditLog, AuditLog.action == "asset.download")
        assert download_logs[-1].after["cross_person"][0]["batch_owner"] == "素材专员"

        own_id, _ = await _make_ready_asset(
            client, hm, url="https://example.com/v/cross-own.mp4")
        async with dbmod.async_session_factory() as s:
            own_asset = await s.get(AssetItem, uuid.UUID(own_id))
            own_asset.prompt_task_id, own_asset.stage_prompt, own_asset.status = None, "pending", "waiting_prompt"
            await s.commit()
        with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
             patch("app.api.assets.create_prompt_task", AsyncMock(return_value=_fake_prompt_task())):
            own = await client.post(
                "/api/assets/analyze/batch", json={"asset_ids": [own_id], "max_duration": 180}, headers=hm)
        assert own.status_code == 200, own.text
        own_logs = await _rows(AuditLog, AuditLog.action == "asset.analyze_batch")
        assert own_logs[-1].after["cross_person"] is None
        await client.aclose()

    _run(_scenario())


def test_hook_code_uniqueness_blocks_reuse_and_used_endpoint_reports_it():
    """11-06 拍板③：钩子编号一发就烧掉——作废单也不复用，后端不代取号。

    钉四件事：
    1. 带号建单 200，`GET /assets/hook-codes/used` 把钉过的号找回来
       （带素材 code + 第几张单——只回 seq 不回素材，一线没法对）；
    2. 同号再建单 → 400，白话点名「已钉在素材 X 的第 N 张单上」，
       且模型一次都不调（拦在展开之前）；
    3. 新号照常建单成功，used 口随即多一行；
    4. 没被任何单用过的号在 used 口查不到。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]

        _aid, _sid, listed = await _order_ready_production(
            client, h, url="https://example.com/v/hook-dup-a.mp4", n=1, hook_codes=["7C0A1"])
        assert listed[0]["hook_code"] == "7C0A1", listed[0]

        # ④+① 回显口：只报钉过的；没钉的（7C0A2）不出现
        used = await client.get(
            "/api/assets/hook-codes/used", params={"codes": "7C0A1,7C0A2"}, headers=ho)
        assert used.status_code == 200, used.text
        rows = used.json()["used"]
        assert len(rows) == 1, rows
        assert rows[0]["code"] == "7C0A1"
        assert rows[0]["seq"] == 1
        assert rows[0]["asset_code"], "素材 code 必须带，一线要靠它去库里对单"
        assert rows[0]["status"], "单子状态也要带（作废与否一线自己判断）"

        # 准备第二条过审文案，拿同号再投产
        _aid2, _sid2, _ = await _order_ready_production(
            client, h, url="https://example.com/v/hook-dup-b.mp4", n=1)
        with patch("app.api.assets._call_autoclip",
                   AsyncMock(side_effect=AssertionError("拦在展开之前，不该花一分钱"))):
            dup = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [_sid2], "n": 1, "board_total": 1,
                      "recommended_title_count": 1, "hook_codes": ["7C0A1"]},
                headers=ho)
        assert dup.status_code == 400, dup.text
        detail = dup.json()["detail"]
        assert "已经被用掉" in detail
        assert "7C0A1" in detail and "第 1 张单" in detail

        # 新号照常建单；建完 used 口多一行
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            fresh = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [_sid2], "n": 1, "board_total": 1,
                      "recommended_title_count": 1, "hook_codes": ["7C0A2"]},
                headers=ho)
        assert fresh.status_code == 200, fresh.text
        used2 = await client.get(
            "/api/assets/hook-codes/used", params={"codes": "7C0A1,7C0A2"}, headers=ho)
        rows2 = used2.json()["used"]
        assert {r["code"] for r in rows2} == {"7C0A1", "7C0A2"}
        await client.aclose()

    _run(_scenario())


# ─────────────────  3d. 播放直链缓存（11-06 修复：取过的直链要能免费拿回来）  ─────────────────


def test_play_url_cache_replay_expiry_and_retake():
    """11-06 播放直链修复，钉五件事：

    1. resolve 成功后 `play_url`/`play_url_at` **落库**（以前只回响应，关抽屉就没了）；
    2. 再 resolve：缓存期内 → channel=cache、0 元、一次解析接口都不发；
    3. 缓存过期（把取链时间拨回 TTL 之外）→ skipped，理由点名「已过期」和 retake=true；
    4. retake=true → 真重新解析并按渠道记账 0.01（过期直链的唯一自愈出口）；
    5. source-preview：缓存期内回 mode=cached + 直链（开抽屉免费续播）；过期回 external，
       note 提示重取。
    """
    _run(_bootstrap())

    SHARE = "https://www.douyin.com/video/7499000000000000091/"

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        imp = await _import(client, hm, [SHARE])
        assert imp.status_code == 201, imp.text
        asset_id = imp.json()["items"][0]["id"]

        calls: list = []

        async def _parse(url):
            calls.append(url)
            return SimpleNamespace(channel="zhiling", play_url="https://c.d/live.mp4",
                                   duration=36.6, title=None)

        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse)), \
             patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)):
            first = await client.post(
                "/api/assets/resolve", json={"asset_ids": [asset_id]}, headers=hm)
        assert first.status_code == 200, first.text
        r = first.json()["results"][0]
        assert r["ok"] and r["play_url"] == "https://c.d/live.mp4"
        assert r["charged"] == pytest.approx(0.01, abs=1e-9)

        rows = {str(a.id): a for a in await _rows(AssetItem)}
        a = rows[asset_id]
        assert a.play_url == "https://c.d/live.mp4", "直链必须落库（修复的主体）"
        assert a.play_url_at is not None

        # ② 缓存期内再取：免费回放，一次外呼都不发
        calls.clear()
        replay = await client.post(
            "/api/assets/resolve", json={"asset_ids": [asset_id]}, headers=hm)
        assert replay.status_code == 200, replay.text
        body = replay.json()
        assert body["results"][0]["channel"] == "cache"
        assert body["results"][0]["play_url"] == "https://c.d/live.mp4"
        assert body["results"][0]["charged"] == 0.0
        assert body["charged"] == 0.0 and calls == [], "缓存回放 0 元且不调解析接口"
        assert "0 元" in body["message"]

        # ⑤a source-preview：缓存期内回 mode=cached（开抽屉免费续播）
        prev = await client.get(f"/api/assets/{asset_id}/source-preview", headers=hm)
        assert prev.status_code == 200, prev.text
        pj = prev.json()
        assert pj["mode"] == "cached" and pj["url"] == "https://c.d/live.mp4"
        assert pj["cached"] is True and pj["play_url_taken_at"]
        assert "缓存" in pj["note"]

        # ③ 把取链时间拨回 7 小时前（TTL 默认 6 小时）：缓存过期
        async with dbmod.async_session_factory() as s:
            stale = await s.get(AssetItem, uuid.UUID(asset_id))
            stale.play_url_at = datetime.utcnow() - timedelta(hours=7)
            await s.commit()

        calls.clear()
        expired = await client.post(
            "/api/assets/resolve", json={"asset_ids": [asset_id]}, headers=hm)
        assert expired.status_code == 200, expired.text
        eb = expired.json()
        assert eb["results"] == [] and calls == [], "过期被跳过，不许自作主张重新花钱"
        reason = eb["skipped"][0]["reason"]
        assert "已过期" in reason and "retake=true" in reason, "跳过理由要告诉人自愈出口在哪"

        # ⑤b source-preview：过期回 external，note 提示重取
        prev2 = await client.get(f"/api/assets/{asset_id}/source-preview", headers=hm)
        assert prev2.status_code == 200, prev2.text
        pj2 = prev2.json()
        assert pj2["mode"] == "external" and pj2["url"] is None
        assert "已过期" in pj2["note"] and "重取" in pj2["note"]

        # ④ retake=true：真重新解析、按渠道记账（自愈出口必须通）
        with patch("app.api.assets.dispatch_parse", AsyncMock(side_effect=_parse)), \
             patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)):
            retaken = await client.post(
                "/api/assets/resolve", json={"asset_ids": [asset_id], "retake": True}, headers=hm)
        assert retaken.status_code == 200, retaken.text
        rb = retaken.json()
        assert calls == [SHARE], "retake 必须真的重新发起解析"
        assert rb["results"][0]["channel"] == "zhiling"
        assert rb["results"][0]["charged"] == pytest.approx(0.01, abs=1e-9)
        assert rb["results"][0]["duration"] == 36.6
        rows2 = {str(a2.id): a2 for a2 in await _rows(AssetItem)}
        assert rows2[asset_id].cost_parse == pytest.approx(0.02, abs=1e-9), "两次解析各记一笔"
        assert rows2[asset_id].play_url_at is not None
        assert rows2[asset_id].play_url_at > stale.play_url_at, "取链时间要刷新成这一次的"

        # retake 后缓存又活了：免费回放照旧
        calls.clear()
        replay2 = await client.post(
            "/api/assets/resolve", json={"asset_ids": [asset_id]}, headers=hm)
        assert replay2.status_code == 200, replay2.text
        assert replay2.json()["results"][0]["channel"] == "cache" and calls == []
        await client.aclose()

    _run(_scenario())


# ─────────────────  3e. 导入即自动下载原片（11-06 用户拍板：不用考虑费用）  ─────────────────


def test_import_links_auto_downloads_immediately():
    """11-06 用户拍板：链接任务添加后就直接下载原片，不用等反推、不用任何人确认解析费。

    钉三件事：
    1. 导入成功后 `_enqueue_download` 被排上：圈的是**这次新建**的素材 id、批次对得上；
    2. 响应 message 用白话说「已自动开始下载（0.01 元/条照记账）」；审计记 auto_download；
    3. 跑的仍是 `/assets/download` 那一个口（_job_endpoint 钉过），这里只验排队侧——
       下载本体的幂等/记账已有专门用例，不重复。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        enq = AsyncMock(return_value={"queued": True, "job_id": "j-1", "queued_count": 2, "note": None})
        with patch("app.api.assets._enqueue_download", enq):
            res = await _import(client, hm, [DOUYIN_1, DOUYIN_2])
        assert res.status_code == 201, res.text
        body = res.json()
        assert enq.await_count == 1, "一个批次排一份下载任务"
        kwargs = enq.await_args.kwargs
        assert kwargs["batch_id"] == body["batch"]["id"]
        assert sorted(kwargs["asset_ids"]) == sorted(i["id"] for i in body["items"])
        assert kwargs["operator"] is not None

        assert "自动开始下载" in body["message"]
        assert body["download"] and body["download"][0]["queued"] is True

        logs = await _rows(AuditLog, AuditLog.action == "asset.import_links")
        assert logs[-1].after["auto_download"] is True, "自动下载是用户拍板的默认口径，审计要留痕"

        # 关掉开关（测试/脚本用）：完全不排下载
        enq2 = AsyncMock(return_value={"queued": False, "job_id": None, "queued_count": 0, "note": None})
        with patch("app.api.assets._enqueue_download", enq2):
            res2 = await _import(client, hm, [DOUYIN_3], auto_download=False)
        assert res2.status_code == 201, res2.text
        assert enq2.await_count == 0 and res2.json()["download"] is None
        assert "自动开始下载" not in res2.json()["message"]
        await client.aclose()

    _run(_scenario())


def test_delete_asset_guards_owner_and_force():
    """11-06 素材列表删除功能，钉六件事：

    1. 本人在跑任务挡道（asset_jobs open 圈住这条素材）→ 409；
    2. 本人删自己导入的、没挂任何下游 → 200，行没了、批次 item_count 递减、审计留痕；
    3. 删别人导入的（非 admin）→ 403；
    4. 挂着文案 → 409 拒删（交付台账不连坐），话术点名「文案」；
    5. admin 强删不带理由 → 400；带理由 force → 200 且文案连坐删干净；
    6. 删不存在的 → 404。
    """
    _run(_bootstrap())

    A1 = "https://www.douyin.com/video/7499000000000000101/"
    A2 = "https://www.douyin.com/video/7499000000000000102/"
    A3 = "https://www.douyin.com/video/7499000000000000103/"

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha, ho = h["material"], h["admin"], h["operator"]

        r1 = await _import(client, hm, [A1])
        r2 = await _import(client, hm, [A2])
        r3 = await _import(client, hm, [A3])
        a1 = r1.json()["items"][0]["id"]
        a2 = r2.json()["items"][0]["id"]
        a3 = r3.json()["items"][0]["id"]
        batch1 = str((await _row_of(AssetItem, a1)).batch_id)

        # ① 在跑任务圈住 a1 → 拒删
        async with dbmod.async_session_factory() as s:
            s.add(AssetJob(
                kind=JOB_SUMMARY_GENERATE, status=JB_RUNNING,
                params={"asset_ids": [a1]},
            ))
            await s.commit()
        busy = await client.delete(f"/api/assets/{a1}", headers=hm)
        assert busy.status_code == 409, busy.text
        assert "正在跑" in busy.json()["detail"]
        # 任务收尾（标成终态）后不再挡道
        async with dbmod.async_session_factory() as s:
            from sqlalchemy import delete as sa_delete
            await s.execute(sa_delete(AssetJob))
            await s.commit()

        # ② 本人删自己没挂下游的素材 → 200，批次计数递减 + 审计
        ok = await client.delete(f"/api/assets/{a1}", headers=hm)
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["deleted"].startswith("AS-") and body["force"] is False
        assert await _count(AssetItem) == 2
        b = await _row_of(AssetBatch, uuid.UUID(batch1))
        assert b.item_count == 0, "删一条要减一条，批次计数不能虚高"
        logs = await _rows(AuditLog, AuditLog.action == "asset.asset.delete")
        assert len(logs) == 1 and logs[0].before.get("code") == body["deleted"]

        # ③ 删别人导入的（operator 非 admin 非本人）→ 403
        deny = await client.delete(f"/api/assets/{a2}", headers=ho)
        assert deny.status_code == 403, deny.text

        # ④ 挂着文案 → 409，话术点名「文案」
        async with dbmod.async_session_factory() as s:
            s.add(AssetSummary(asset_id=uuid.UUID(a2), seq=1, text="钩一下"))
            await s.commit()
        blocked = await client.delete(f"/api/assets/{a2}", headers=hm)
        assert blocked.status_code == 409, blocked.text
        assert "文案" in blocked.json()["detail"]

        # ⑤ admin 强删：不带理由 400；带理由 200 连坐删
        no_reason = await client.delete(
            f"/api/assets/{a2}?force=true", headers=ha)
        assert no_reason.status_code == 400, no_reason.text
        forced = await client.delete(
            f"/api/assets/{a2}?force=true&reason=测试数据清理", headers=ha)
        assert forced.status_code == 200, forced.text
        assert forced.json()["force"] is True
        assert await _count(AssetSummary) == 0, "force 连坐要带走文案"
        logs = await _rows(AuditLog, AuditLog.action == "asset.asset.delete")
        assert len(logs) == 2 and logs[-1].after.get("reason") == "测试数据清理"

        # ⑥ 不存在 → 404
        gone = await client.delete(f"/api/assets/{uuid.uuid4()}", headers=ha)
        assert gone.status_code == 404, gone.text

        # 收尾：a3 删掉，两表归零
        last = await client.delete(f"/api/assets/{a3}", headers=hm)
        assert last.status_code == 200
        assert await _count(AssetItem) == 0

        await client.aclose()

    _run(_scenario())


def test_dispatch_prompt_override_changes_only_outgoing_copy():
    """11-06 拍板「投放前投递稿可改」，钉五件事：

    1. override 只对**这次要新建**的单生效：不在新建堆里的 id → 400（回收的单投的是原稿）；
    2. 改后的正文照走 block 级风险词重扫：命中 → 400，话术点名「改稿不等于豁免」；
    3. operator 带 force_risk → 403（闸门只有 admin 能踩，改稿不另开豁免口）；
    4. admin force 投出去：板收到的 prompt 是**改后**的，库里的 prompt_text
       一字不动（下次再投仍是原稿），没改的那张也仍是原稿；
    5. 改稿逐条留审计（asset.production.dispatch_override，含改后正文与 risk_forced）；
    6. 空白 override ＝没改：照原稿投。
    """
    from app.services import asset_service as _svc

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ha, ho = h["admin"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=2, hook_codes=["7C0E1", "7C0E2"])
        ids = [p["id"] for p in listed]
        orig_prompt = listed[0]["prompt_text"]
        orig_prompt2 = listed[1]["prompt_text"]
        assert orig_prompt and orig_prompt2, "fixture 出来的单必须有正文"

        # ① 不在新建堆里的 id → 400（is_configured 的守卫在闸门之前，探针都要在"凭据已配"的环境里发）
        with _board_off(_FakeBoard()):
            r = await _dispatch(client, ho, ids,
                                prompt_overrides={str(uuid.uuid4()): "随便改改"})
        assert r.status_code == 400 and "不在新建堆里" in r.json()["detail"], r.text

        # ② 改稿命中 block 级风险词 → 400
        await client.put("/api/assets/risk-lexicon",
                         json={"block": ["测试雷"], "inherit": True}, headers=ha)
        with _board_off(_FakeBoard()):
            r2 = await _dispatch(client, ho, ids, prompt_overrides={ids[0]: "开头就放测试雷"})
        assert r2.status_code == 400 and "高风险词" in r2.json()["detail"], r2.text
        assert "改稿不等于豁免" in r2.json()["detail"]

        # ③ operator 踩 force 闸 → 403（闸只认 admin）
        with _board_off(_FakeBoard()):
            r3 = await _dispatch(client, ho, ids, prompt_overrides={ids[0]: "开头就放测试雷"},
                                 force_risk=True, force_reason="语境需要")
        assert r3.status_code == 403, r3.text

        # ④ admin force：改稿照投，板收到的是改后的，库里一字不动
        override_text = "开头就放测试雷\n" + orig_prompt
        fb = _FakeBoard()
        with _board_off(fb):
            ok = await _dispatch(client, ha, ids,
                                 prompt_overrides={ids[0]: override_text},
                                 force_risk=True, force_reason="改稿语境需要")
        assert ok.status_code == 200, ok.text
        by_req = {c["reqID"]: c["prompt"] for c in fb.creates}
        assert by_req[_svc.board_req_id(ids[0])] == override_text, "改过的那张投出去必须是改后正文"
        assert by_req[_svc.board_req_id(ids[1])] == orig_prompt2, "没改的那张仍投原稿"
        rows = await _rows(AssetProduction)
        row0 = next(r for r in rows if str(r.id) == ids[0])
        assert row0.prompt_text == orig_prompt, "库里的提示词一字不动"

        # ⑤ 改稿留痕
        logs = await _rows(AuditLog, AuditLog.action == "asset.production.dispatch_override")
        assert len(logs) == 1, len(logs)
        assert logs[0].after["override"] == override_text[:800]
        assert logs[0].after["risk_forced"] is True
        assert logs[0].before["prompt_text"] == orig_prompt[:800]

        # ⑥ 空白 override ＝没改（第一轮投完两张单已 success，单开一张新单来验）
        _a3, _s3, listed3 = await _order_ready_production(
            client, h, url="https://www.douyin.com/video/7499000000000000104/",
            n=1, hook_codes=["7C0E3"])
        id3 = listed3[0]["id"]
        fb2 = _FakeBoard()
        with _board_off(fb2):
            ok2 = await _dispatch(client, ha, [id3], prompt_overrides={id3: "   "})
        assert ok2.status_code == 200, ok2.text
        assert all(c["prompt"] == listed3[0]["prompt_text"] for c in fb2.creates), "空白改稿照原稿投"
        logs2 = await _rows(AuditLog, AuditLog.action == "asset.production.dispatch_override")
        assert len(logs2) == 1, "空白改稿不留痕"

        await client.aclose()

    _run(_scenario())


def test_analyze_async_job_converges_and_auto_retries_fast_fail():
    """11-06 三连投诉的根治验收：反推进任务条（不再隐形）、后台自己收终态（页面关了也收）、
    「第一次总是出错」＝快速失败自动重试一次。

    三个投诉一句话：以前反推提交完就没人管了——收敛只靠前端轮询，页面一关状态就永远
    卡在「反推中」；任务条里也找不到它；智令 6 秒速死那种失败还得人肉点重试。
    """
    _run(_bootstrap())

    async def _scenario():
        from wechat_download.models import PT_PROCESSING, WechatDlPromptTask
        from wechat_download.prompt_client import PromptStatus

        client, h = await _client_and_headers()
        hm = h["material"]
        third = "https://www.douyin.com/video/7400000000000000002"
        imp = await _import(client, hm, [DOUYIN_1, third])
        assert imp.status_code == 201, imp.text
        ids = [i["id"] for i in imp.json()["items"]]

        old_poll = settings.ASSET_ANALYZE_JOB_POLL_SECONDS
        settings.ASSET_ANALYZE_JOB_POLL_SECONDS = 0.05  # 测试把轮询间隔压到毫秒级
        try:
            # 假 create_prompt_task 要**真落任务行**（processing）：后台收敛靠 get_prompt_task
            # 读库，替身只回 SimpleNamespace 的话每条都会被判「任务行缺失」
            async def _mk_task(db, **kw):
                tid = uuid.uuid4()
                db.add(WechatDlPromptTask(
                    id=tid, source_type="url", source_url=kw.get("source_url"),
                    provider_task_id=f"p-{tid.hex[:6]}", status=PT_PROCESSING,
                    max_duration=kw.get("max_duration") or 60))
                await db.flush()
                return SimpleNamespace(id=tid, status="processing", error=None)

            # 收敛侧替身按序回：第 1 条成功、第 2 条快速失败（触发自动重试）、重试后成功
            fake = SimpleNamespace(
                query=AsyncMock(side_effect=[
                    PromptStatus(status="success", content=SCRIPT, schedule="SUCCESS"),
                    PromptStatus(status="failed", error="任务处理失败", schedule="FAIL"),
                    PromptStatus(status="success", content=SCRIPT, schedule="SUCCESS"),
                ]),
                close=AsyncMock(),
            )
            with patch("app.api.assets._query_zhiling_balance_detail", _fake_balance(100.0)), \
                 patch("app.api.assets.create_prompt_task", AsyncMock(side_effect=_mk_task)) as cpt, \
                 patch("wechat_download.prompt_service.PromptClient", lambda: fake):
                # ① 提交即回任务号，不是同步那套 {results:[...]}
                sub = await client.post(
                    "/api/assets/analyze/batch",
                    json={"asset_ids": ids, "max_duration": 60, "confirmed": True,
                          "download": False, "async_mode": True},
                    headers=hm,
                )
                assert sub.status_code == 200, sub.text
                ack = sub.json()
                assert ack["queued"] is True and ack["job_id"]
                assert ack["planned_units"] == 2
                assert "results" not in ack, "异步回执不能长得像同步结果"
                done = await _wait_job(client, h["admin"], ack["job_id"], timeout=20.0)

            # ② 后台自己收完了：一成、自动重试一次后又一成，没有留在跑的
            assert done["status"] == "succeeded", done
            conv = done["result"]["converge"]
            assert conv["success"] == 2 and conv["failed"] == 0, conv
            assert conv["auto_retry"] == 1, "6 秒速死那种失败要自动重试一次"
            assert conv["left_running"] == 0 and conv["deadline_hit"] is False
            assert done["progress"]["done"] == 2 and done["progress"]["total"] == 2

            # ③ 提交 2 次 + 自动重试 1 次 = create_prompt_task 共 3 次
            assert cpt.await_count == 3, cpt.await_count

            # ④ 业务表才是真相：两条都收敛到成功（不是台账绿了业务表还挂着 running）
            rows = await _rows(AssetItem, AssetItem.id.in_([uuid.UUID(x) for x in ids]))
            assert all(r.stage_prompt == "success" for r in rows), \
                [(r.code, r.stage_prompt) for r in rows]

            # ⑤ 自动重试与收敛都留了审计
            retries = await _rows(AuditLog, AuditLog.action == "asset.analyze.auto_retry")
            assert len(retries) == 1 and retries[0].after["retry_status"] == "processing"
            convs = await _rows(AuditLog, AuditLog.action == "asset.analyze.converge")
            assert len(convs) == 1 and convs[0].after["auto_retry"] == 1

            # ⑥ 任务条默认能列到反推任务（「后台任务中不会显示」的验收点）
            listed = await client.get("/api/assets/jobs", headers=hm)
            kinds = {i["kind"] for i in listed.json()["items"]}
            assert "analyze" in kinds, kinds

            # ⑦ 收敛完再点同样的两条：400 说清每档多少条、怎么重试，不再是没头没尾的「都已处理过」
            again = await client.post(
                "/api/assets/analyze/batch",
                json={"asset_ids": ids, "max_duration": 60, "confirmed": True, "download": False},
                headers=hm,
            )
            assert again.status_code == 400, again.text
            detail = again.json()["detail"]
            assert "没有能新提交反推的" in detail and "已成功 2 条" in detail and "重试失败项" in detail, detail

            # ⑧ 台账里 params 存的是原请求体（含 wait_converge，追溯口径不变）
            jobs = await _rows(AssetJob)
            mine = [j for j in jobs if j.kind == "analyze"]
            assert len(mine) == 1 and mine[0].params["wait_converge"] is True
            assert mine[0].params["async_mode"] is True, "params 存的是原请求体（追溯用）"
        finally:
            settings.ASSET_ANALYZE_JOB_POLL_SECONDS = old_poll

        await client.aclose()

    _run(_scenario())


def test_summary_generate_also_fills_doubao_web_prompts():
    """11-06 双产出：出文案时第二跳把每条候选的豆包网页版提示词按 seq 填进 doubao_prompt。

    三段：①正常路径（第二跳成功，逐条对号）；②第二跳失败不拖累文案（doubao_prompt 留
    NULL、可单独补）；③补口（只补缺的、force 重出、超上限 400）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]

        # ① 正常：候选落库 + doubao_prompt 全填（count 显式 3，测三候选并行展开的机制）
        asset_id, _ = await _make_ready_asset(client, hm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call:
            gen = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "count": 3}, headers=hm)
        assert gen.status_code == 200, gen.text
        body = gen.json()
        first = body["results"][0]
        assert first["created"] == 3
        assert first["doubao_prompt_filled"] == 3 and first["doubao_prompt_total"] == 3, first
        assert "网页版提示词已同步生成" in body["message"]
        # 两次调用：一次出文案、一次网页版提示词；第二跳按 seq 带全候选与剧名参数
        paths = [c.args[0] for c in call.await_args_list]
        assert sum(1 for p in paths if p.endswith("hook-copy/prompt-web")) == 1
        web_payload = [c.args[1] for c in call.await_args_list if c.args[0].endswith("hook-copy/prompt-web")][0]
        assert [c["seq"] for c in web_payload["candidates"]] == [1, 2, 3]
        assert web_payload["candidates"][0]["text"] == CANDIDATES[0]["text"]
        assert "drama_title" in web_payload["params"]
        rows = await _rows(AssetSummary, AssetSummary.asset_id == uuid.UUID(asset_id))
        assert all((r.doubao_prompt or "").strip() for r in rows)
        assert all("9:16，10s" in r.doubao_prompt for r in rows)
        # 序列化口带 doubao_prompt
        detail = await client.get(f"/api/assets/{asset_id}", headers=hm)
        assert detail.status_code == 200
        assert all(s["doubao_prompt"] for s in detail.json()["summaries"])

        # ② 第二跳失败：文案照常落库（created=3），doubao_prompt 全空，results 记可补
        # （同测试里第二次导入必须换 URL，同链接默认被导入去重拦下）
        asset2, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        with patch("app.api.assets._call_autoclip", _fake_autoclip(web_error="网关卡流")):
            gen2 = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset2], "count": 3}, headers=hm)
        assert gen2.status_code == 200, gen2.text
        body2 = gen2.json()
        assert body2["results"][0]["created"] == 3
        assert body2["results"][0]["doubao_prompt_filled"] == 0
        assert "可单独补" in body2["results"][0]["web_note"]
        assert "没生成全" in body2["message"]
        rows2 = await _rows(AssetSummary, AssetSummary.asset_id == uuid.UUID(asset2))
        assert all(r.doubao_prompt is None for r in rows2)
        assert all(r.text for r in rows2), "文案不受第二跳失败影响"

        # ③ 补口：先缺后补
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            backfill = await client.post(
                "/api/assets/summaries/prompt-web",
                json={"summary_ids": [str(r.id) for r in rows2]},
                headers=hm,
            )
        assert backfill.status_code == 200, backfill.text
        assert backfill.json()["filled"] == 3, backfill.text
        rows2 = await _rows(AssetSummary, AssetSummary.asset_id == uuid.UUID(asset2))
        assert all((r.doubao_prompt or "").strip() for r in rows2)
        # 已有的不重出（不带 force）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call3:
            again = await client.post(
                "/api/assets/summaries/prompt-web",
                json={"summary_ids": [str(rows2[0].id)]}, headers=hm)
        assert again.status_code == 200 and again.json()["filled"] == 0
        assert "force" in again.json()["results"][0]["note"]
        call3.assert_not_awaited()
        # force 才重出
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call4:
            forced = await client.post(
                "/api/assets/summaries/prompt-web",
                json={"summary_ids": [str(rows2[0].id)], "force": True}, headers=hm)
        assert forced.status_code == 200 and forced.json()["filled"] == 1
        assert call4.await_count == 1
        # 超上限 400
        too_many = await client.post(
            "/api/assets/summaries/prompt-web",
            json={"summary_ids": [str(uuid.uuid4())] * 11}, headers=hm)
        assert too_many.status_code == 400 and "一次最多补" in too_many.json()["detail"]
        await client.aclose()

    _run(_scenario())




# ────────────────────────  批 M（评审一·P1-1）：人工回写 vs 轮询写回并发  ────────────────────────


class _WritebackHookBoard(_FakeBoard):
    """在指定第 N 次回读的**当口**，以「人工」身份调一次投递状态回写口。

    轮询与人工的交叠点只能在替身钩子里造：回读是轮询协程让出事件循环的地方，
    此刻轮询的事务是收掉的（出网在事务外），人工请求拿独立 session 进来写库
    不会互相卡。hook 在 super().readback() 之前落笔，保证「写完之后轮询才看到板面」，
    时序是确定的，不靠 sleep 撞运气。
    """

    def __init__(self, *, hook_read_index, writeback, **kw):
        super().__init__(**kw)
        self._hook_read_index = hook_read_index
        self._writeback = writeback          # 无参 async callable，只钩一次
        self.writeback_status: list = []

    async def readback(self, days, tag):
        if self._writeback is not None and len(self.reads) + 1 == self._hook_read_index:
            wb, self._writeback = self._writeback, None
            resp = await wb()
            self.writeback_status.append(resp.status_code)
        return await super().readback(days, tag)


def test_dispatch_poll_reown_skips_restart_when_human_rewrote_status():
    """批 M（评审一·P1-1）重启前重读：人工改走的状态，轮询绝不按旧快照再重启一次。

    真实形状：轮询持有 dispatch 时加载的 ORM 对象、整轮不重读库，第 1 轮板面
    waiting 会把单子从 queued 推进到 running；人工在第 2 轮回读的当口经「投递状态
    回写口」判 failed（板上失败行没有原因字段，我们记的是自己的判读），同一轮
    板面正好报 fail——修法前轮询会按旧快照自动重启（payload 还在手），同一条
    **烧两遍号池**。修法后重启前用独立短会话重读一眼，状态被改走的行整行让位：
    不重启、不写回、summary 点名。

    时序账（替身 readback 计数）：#1 投前快照、#2 建任务认领（行面 waiting）、
    #3 轮询第 1 轮（waiting→轮询自己推进 running）、#4 轮询第 2 轮＝钩子先落笔
    人工判 failed，再返回板面 fail。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, hook_codes=["7C0M1"])
        pid = listed[0]["id"]

        async def _human_writeback():
            # running → failed 是迁移表放行的路（人工判读失败必须带成因）
            return await client.post(
                "/api/assets/productions/status",
                json={"ids": [pid], "status": "failed",
                      "error": "人工判读：这条在板上没出来，别自动重投，等我确认"},
                headers=ho)

        # 板面：行面第 1、2 次被读到是 waiting，第 3 次（＝轮询第 2 轮，正好人工
        # 落笔的那轮）起 fail——若让位机制没生效，本轮就会触发自动重启
        # （creates 变 2），在这里红。
        fb = _WritebackHookBoard(
            hook_read_index=4, writeback=_human_writeback,
            status_fn=lambda created_index, read_round: "waiting" if read_round <= 2 else "fail",
        )
        with _board_off(fb):
            resp = await _dispatch(client, ho, [pid])
        assert fb.writeback_status == [200], fb.writeback_status
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # ① 重启没发生：板上只建过投第一次那一条（号池只烧一遍）
        assert len(fb.creates) == 1, fb.creates
        # ② 人工的 failed 原样保留，轮询没有按旧快照把 running/queued 写回去
        row = await _row_of(AssetProduction, pid)
        assert row.status == "failed", row.status
        assert row.attempts == 1, "让位的行不许再走 _adopt_tids（attempts 会 +1）"
        assert row.board_tid, "tid 还在（第一次投板认领的），让位不抹历史"
        assert "人工判读" in (row.error or ""), "成因是人工写的，不是轮询的模板话术"
        # ③ summary 点名交还人工
        res = body["results"][pid]
        assert res["status"] == "failed" and "交还人工" in (res.get("note") or ""), res
        await client.aclose()

    _run(_scenario())


def test_dispatch_poll_reown_preserves_manual_status_at_writeback():
    """批 M（评审一·P1-1）写回前重读：轮询写回前发现状态被人工改走就整行让位。

    人工在轮询第 2 轮回读的当口把单子判 failed（板面这轮还是 waiting，轮询照常
    走完心跳）；修法前写回阶段会按旧快照 commit（lost update：人工的 failed 被
    覆盖回轮询的 running 口径）。专验「写回前重读」这一道，不掺重启分支。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, hook_codes=["7C0M2"])
        pid = listed[0]["id"]

        async def _human_writeback():
            return await client.post(
                "/api/assets/productions/status",
                json={"ids": [pid], "status": "failed",
                      "error": "人工判读：这条别再等了"},
                headers=ho)

        # 板面一直 waiting：轮询到期限为止只写心跳与 running 推进，不会进重启分支。
        fb = _WritebackHookBoard(
            hook_read_index=4, writeback=_human_writeback,
            status_fn=lambda created_index, read_round: "waiting",
        )
        with _board_off(fb):
            resp = await _dispatch(client, ho, [pid])
        assert fb.writeback_status == [200], fb.writeback_status
        assert resp.status_code == 200, resp.text
        body = resp.json()

        row = await _row_of(AssetProduction, pid)
        assert row.status == "failed", "人工的 failed 必须原样保留（写回前重读让位）"
        assert row.attempts == 1
        # 第 1 轮的心跳已照常落库（心跳是轮询自己的口径，人工不写这两个字段），
        # 第 2 轮整行让位后心跳停在第 1 轮的值——有值即说明第 1 轮写回没被误伤。
        assert row.board_last_status == "waiting" and row.board_last_check_at is not None
        res = body["results"][pid]
        assert res["status"] == "failed" and "交还人工" in (res.get("note") or ""), res
        await client.aclose()

    _run(_scenario())


def test_dispatch_card_override_pins_rows_and_rejects_dirty_ids():
    """投板前统一挂卡：给 card_asset_ids 时覆盖本批**要新建**的单，脏 id 当场 400。

    用户拍板的形状：卡（人物三视图）不只在「生成生产单」那一步挂——投板确认弹窗里
    也能统一挑/传。后端口径：给出的数组对 to_create 逐张覆盖写（card_asset_ids 数组
    ＋兼容单值列写第一张，与 produce 同一套写法），随建任务前的 commit 落库，
    _build_delivery 读到的就是新卡；回收档（已有 tid）不适用。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=2, hook_codes=["7C0N1", "7C0N2"])
        ids = [p["id"] for p in listed]

        # 直接种一张合法的角色卡（11-25 批 W 起卡在 `asset_cards`，不在素材表）
        card_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetCard(
                id=card_id, name="女主三视图", file_name="女主三视图.png",
                file_key="asset/cards/santi.png", bucket=settings.MINIO_BUCKET_RAW,
                owner_id=None,
            ))
            await s.commit()

        # 脏 id（不存在的卡）当场 400，一张都不投（排在真投之前：投过就成终态，进不了闸门了）
        fb_dirty = _FakeBoard()
        with _board_off(fb_dirty):
            bad = await _dispatch(client, ho, [ids[0]], card_asset_ids=[str(uuid.uuid4())])
        assert bad.status_code == 400 and "卡" in bad.json()["detail"], bad.text
        assert len(fb_dirty.creates) == 0, "脏卡必须在建任务之前拦下，一张任务都不许投"

        fb = _FakeBoard()
        with _board_off(fb):
            resp = await _dispatch(client, ho, ids, card_asset_ids=[str(card_id)])
        assert resp.status_code == 200, resp.text

        # 两张单都被钉上这张卡（顺序数组＋兼容单值列＝第一张）
        rows = await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(asset_id))
        assert {str(r.card_asset_ids[0]) for r in rows if r.card_asset_ids} == {str(card_id)}
        assert all(r.character_card_key == "asset/cards/santi.png" for r in rows)
        await client.aclose()

    _run(_scenario())


def test_summary_generate_passes_original_duration_for_first_candidate():
    """2026-11-07 用户口径：第 1 条钩子文案要贴合原片长度（10s/15s 取最接近档）。

    后端只负责把原片时长带给文案服务（params.duration_seconds）；定档规则在
    autoclip 的 hook_copy.txt / hook_prompt_web.txt。这里钉两件事：
    ① duration 有值 → payload 带上（四舍五入取整）；② duration 为空 → 不带该键
    （autoclip 侧退回原「按文案丰满程度」判断）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        # 先给素材写上时长（模拟文件导入 ffprobe / 链接解析回填的产物）
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetItem, uuid.UUID(asset_id))
            row.duration = 15.4
            await s.commit()

        captured: list = []

        async def _capture(path, payload, timeout=180.0):
            captured.append((path, payload))
            return await _fake_autoclip()(path, payload, timeout)

        with patch("app.api.assets._call_autoclip", _capture):
            resp = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        gen = [p for path, p in captured if path.endswith("hook-copy/generate")]
        assert gen and gen[0]["params"]["duration_seconds"] == 15, "15.4s 四舍五入取整透传"
        web = [p for path, p in captured if path.endswith("hook-copy/prompt-web")]
        assert web and web[0]["params"]["duration_seconds"] == 15, "网页版提示词同口径透传"

        # 没时长的素材：不带该键（模板退回原判断），且不能被 0/None 污染
        asset2, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            resp2 = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset2]}, headers=hm)
        assert resp2.status_code == 200, resp2.text
        await client.aclose()

    _run(_scenario())


def test_output_groups_aggregate_by_asset_and_batch():
    """成片墙两级视图第一级（2026-11-07 用户口径）：按素材（钩子）/按批次聚合成清单。

    钉五件事：①按素材分组带成片数＋钩子号（挂在生产单上的，汇总去重）；②按批次
    分组带批次码；③batch_id 筛选两级一致（素材侧收敛）；④qc 筛选真正生效
    （qc_status=None 的不算进 passed 组，也不出现在 passed 清单）；⑤每组带
    最新一条时间；没有首帧的组 thumb_url 显式 null（前端画占位不报错）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, hadm = h["material"], h["admin"]

        async def _asset_with_outputs(url, hook_code, qc):
            """一条素材：出文案→过审→投产（带钩子号）→直接插 N 条产物。"""
            asset_id, _ = await _make_ready_asset(client, hm, url=url)
            items, _ = await _gen_and_list(asset_id, hm, client)
            sid = _approvable(items)["id"]
            await client.post("/api/assets/summaries/review",
                              json={"summary_ids": [sid], "action": "approve"}, headers=hadm)
            with patch("app.api.assets._call_autoclip", _fake_autoclip()):
                await client.post("/api/assets/produce",
                                  json={"summary_ids": [sid], "n": 1, "hook_codes": [hook_code]}, headers=hadm)
            prod = (await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(asset_id)))[0]
            oid = uuid.uuid4()
            async with dbmod.async_session_factory() as s:
                s.add(AssetOutput(
                    id=oid, production_id=prod.id, asset_id=uuid.UUID(asset_id),
                    kind="doubao_raw", file_key=f"asset-out/{oid}.mp4",
                    bucket=settings.MINIO_BUCKET_SLICED, file_name="成片.mp4",
                    qc_status=qc,
                ))
                await s.commit()
            return asset_id

        a1 = await _asset_with_outputs(DOUYIN_2, "7C0G1", "passed")
        a2 = await _asset_with_outputs(DOUYIN_3, "7C0G2", None)

        # ① 按素材：两行、各自成片数与钩子号
        g = await client.get("/api/assets/outputs/groups?group_by=asset", headers=hm)
        assert g.status_code == 200, g.text
        rows = {r["key"]: r for r in g.json()["groups"]}
        assert set(rows) == {a1, a2}
        assert rows[a1]["count"] == 1 and rows[a2]["count"] == 1
        assert "7C0G1" in (rows[a1]["sub"] or "")
        assert rows[a1]["latest_at"] and rows[a1]["thumb_url"] is None
        assert g.json()["group_by"] == "asset"

        # ② 按批次：两行，标签带批次码
        gb = await client.get("/api/assets/outputs/groups?group_by=batch", headers=hm)
        assert gb.status_code == 200, gb.text
        b_rows = gb.json()["groups"]
        assert len(b_rows) == 2
        assert all("·" in r["label"] or r["label"] == "未挂批次" for r in b_rows)

        # ③ batch_id 筛选（素材侧收敛）：只剩该批次下的素材组（asset 模式的 key 是素材 id）
        a1_item = (await _rows(AssetItem, AssetItem.id == uuid.UUID(a1)))[0]
        assert a1_item.batch_id is not None
        gf = await client.get(
            f"/api/assets/outputs/groups?group_by=asset&batch_id={a1_item.batch_id}", headers=hm)
        assert gf.status_code == 200, gf.text
        f_rows = gf.json()["groups"]
        assert len(f_rows) == 1 and f_rows[0]["key"] == a1 and "7C0G1" in (f_rows[0]["sub"] or "")

        # ④ qc=passed：qc=None 的素材2整组消失（组内计数与组级清单同一套过滤）
        gq = await client.get("/api/assets/outputs/groups?group_by=asset&qc_status=passed", headers=hm)
        assert gq.status_code == 200, gq.text
        assert [r["key"] for r in gq.json()["groups"]] == [a1]

        # 非法 group_by 400
        bad = await client.get("/api/assets/outputs/groups?group_by=hook", headers=hm)
        assert bad.status_code == 400

        # ⑤ `awaiting`：墙空着的时候界面得说得出「为什么空」（11-10 用户口径
        #    「刚才投出去的那条生产单显示完成，成片墙还是看不到」）。三件事分开数：
        #    只建单没投板 / 已投板还在出片 / 最近一次回收时间。终态（成／败）不算在途——
        #    成没成片墙自己会说话，再算进来就会永远"还在出片"。
        aw = g.json()["awaiting"]
        assert aw["order_ready_not_dispatched"] == 2, aw
        assert aw["waiting_on_board"] == 0, aw
        assert aw["last_output_at"], "已经有成片了，最近回收时间不能是空"

        prods = await _rows(AssetProduction)
        p_a1 = [x for x in prods if str(x.asset_id) == a1][0]
        p_a2 = [x for x in prods if str(x.asset_id) == a2][0]
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p_a1.id)
            row.status, row.board_tid = PR_RUNNING, "T-G1"
            done = await s.get(AssetProduction, p_a2.id)
            done.status, done.board_tid = PR_SUCCESS, "T-G2"
            await s.commit()
        aw = (await client.get("/api/assets/outputs/groups?group_by=asset", headers=hm)).json()["awaiting"]
        assert aw["waiting_on_board"] == 1, f"投出去那张要算成在途：{aw}"
        assert aw["order_ready_not_dispatched"] == 0, f"回收成功的那张不能再算待投：{aw}"

        # 批次口径：切到某一批时只数这一批的单，别把别人在跑的任务算成"你这批还在出片"
        a2_item = (await _rows(AssetItem, AssetItem.id == uuid.UUID(a2)))[0]
        assert a2_item.batch_id is not None and str(a2_item.batch_id) != str(a1_item.batch_id)
        aw = (await client.get(
            f"/api/assets/outputs/groups?group_by=asset&batch_id={a2_item.batch_id}", headers=hm
        )).json()["awaiting"]
        assert aw["waiting_on_board"] == 0 and aw["order_ready_not_dispatched"] == 0, \
            f"这一批那张单已经回收成功了，两个在途数都该是 0：{aw}"
        aw = (await client.get(
            f"/api/assets/outputs/groups?group_by=asset&batch_id={a1_item.batch_id}", headers=hm
        )).json()["awaiting"]
        assert aw["waiting_on_board"] == 1 and aw["order_ready_not_dispatched"] == 0, aw

        # ⑥ 批 V 需求②（11-25 用户口径「投了豆包之后、豆包返回之前，看成片的地方要把这个
        #    任务先显示出来并标个状态」＋「灰卡＋把失败/超时也标出来」）：占位条数据口。
        #    在途判据必须与上面 `awaiting.waiting_on_board` **同一套**——空态说「1 张在途」、
        #    占位卡摆 3 张，比不摆更让人困惑。
        inf = await client.get("/api/assets/outputs/inflight", headers=hm)
        assert inf.status_code == 200, inf.text
        body = inf.json()
        assert body["total"] == 1 == body["inflight_total"], f"只剩 running 那张在途：{body}"
        assert len([i for i in body["items"] if i["bucket"] == "generating"]) == 1
        row0 = [i for i in body["items"] if i["bucket"] == "generating"][0]
        assert row0["production_id"] == str(p_a1.id) and row0["board_tid"] == "T-G1"
        assert row0["status"] == PR_RUNNING and row0["hook_code"] == "7C0G1"
        assert row0["asset_code"], "占位卡要认得出是哪条素材"
        assert row0["board_total"] == 1 and row0["attempts"] == 0
        assert row0["owner_id"] and row0["owner_name"], "占位卡要带出实际投产人，供素材专员判断能否删单"
        assert row0["owner_name"] == "管理员"
        productions = (await client.get(
            f"/api/assets/productions?asset_id={a1}", headers=hadm
        )).json()["items"]
        assert all(item["board_date"] and item["board_date"].endswith("+08:00") for item in productions), \
            f"任务板时间是北京墙钟，不能标成 UTC：{productions}"
        assert (row0["minutes_since_dispatch"] or 0) >= 0
        assert isinstance(body["slow_after_minutes"], int) and body["slow_after_minutes"] > 0, \
            "慢的判断基准要跟轮询窗口同源，别前端硬编一个数"
        # 终态成功那张（success＋有 tid）**不能**出现在占位里：片有没有，墙自己会说话
        assert str(p_a2.id) not in {i["production_id"] for i in body["items"]}
        # owner=me：单是 admin 投的，素材号看自己的＝0，admin 看＝1
        assert (await client.get("/api/assets/outputs/inflight?owner=me", headers=hm)).json()["inflight_total"] == 0
        assert (await client.get("/api/assets/outputs/inflight?owner=me", headers=hadm)).json()["inflight_total"] == 1
        # 批次口径与空态同一套：切到 a2 那批＝0，切到 a1 那批＝1
        n_a2 = (await client.get(
            f"/api/assets/outputs/inflight?batch_id={a2_item.batch_id}", headers=hm)).json()["inflight_total"]
        n_a1 = (await client.get(
            f"/api/assets/outputs/inflight?batch_id={a1_item.batch_id}", headers=hm)).json()["inflight_total"]
        assert (n_a2, n_a1) == (0, 1), f"在途占位不能串批：a2={n_a2} a1={n_a1}"
        bad = await client.get("/api/assets/outputs/inflight?owner=mine", headers=hm)
        assert bad.status_code == 400, "非法 owner 值要当场 400，别静默当 all"
        # 试产单不进交付墙（`/assets/outputs` 默认也滤掉它的成片），占位照同一口径
        async with dbmod.async_session_factory() as s:
            t = await s.get(AssetProduction, p_a1.id)
            t.is_trial = True
            await s.commit()
        assert (await client.get("/api/assets/outputs/inflight", headers=hm)).json()["inflight_total"] == 0, \
            "试产片的占位不该混进交付墙"
        async with dbmod.async_session_factory() as s:
            t = await s.get(AssetProduction, p_a1.id)
            t.is_trial = False
            await s.commit()

        # 投板协程尚未认领 tid 的 order_ready 默认不摆卡；成片墙显式要即时面板时才纳入。
        async with dbmod.async_session_factory() as s:
            making = await s.get(AssetProduction, p_a1.id)
            making.status, making.board_tid = PR_ORDER_READY, None
            await s.commit()
        default_body = (await client.get("/api/assets/outputs/inflight", headers=hadm)).json()
        assert default_body["inflight_total"] == 0, default_body
        creating_body = (await client.get(
            "/api/assets/outputs/inflight", params={"include_creating": "true"}, headers=hadm
        )).json()
        creating = [i for i in creating_body["items"] if i["production_id"] == str(p_a1.id)]
        assert len(creating) == 1 and creating[0]["status"] == PR_ORDER_READY, creating_body
        assert creating[0]["owner_id"] and creating[0]["owner_name"] == "管理员"
        material_user = (await _rows(User, User.username == MATERIAL_USER))[0]
        async with dbmod.async_session_factory() as s:
            making = await s.get(AssetProduction, p_a1.id)
            making.created_by = material_user.id
            await s.commit()
        own_creating_cancel = await client.post(
            f"/api/assets/productions/{p_a1.id}/cancel", headers=hm
        )
        assert own_creating_cancel.status_code == 200, own_creating_cancel.text
        assert own_creating_cancel.json()["status"] == PR_CANCELLED
        async with dbmod.async_session_factory() as s:
            making = await s.get(AssetProduction, p_a1.id)
            making.status, making.board_tid = PR_RUNNING, "T-G1"
            making.created_by = p_a1.created_by
            await s.commit()

        # ⑥b 失败也要摆（用户选的正是「灰卡＋把失败/超时也标出来」）：p_a2 改判失败，
        #     卡上必须带得成因（`error` 原文）与「多久前失败」；超出回看窗口的老失败
        #     **只报数不摆卡**——失败行永久累积，墙顶放一条越滚越长的红列两周后没人看。
        async with dbmod.async_session_factory() as s:
            f = await s.get(AssetProduction, p_a2.id)
            f.status, f.completed_at, f.error = PR_FAILED, datetime.utcnow(), "板面判失败：角色卡宽高比不对"
            await s.commit()
        body = (await client.get("/api/assets/outputs/inflight", headers=hm)).json()
        assert body["failed_total"] == 1 and body["failed_older"] == 0, body
        fk = [i for i in body["items"] if i["bucket"] == "failed"]
        assert [i["production_id"] for i in fk] == [str(p_a2.id)]
        assert fk[0]["error"] and "角色卡" in fk[0]["error"] and fk[0]["hook_code"] == "7C0G2"
        assert (fk[0]["minutes_since_failed"] or 0) >= 0
        assert fk[0]["bucket"] == "failed" and fk[0]["error"] is not None
        # 生成中的那类永远不带 error（免得前端把两套话术混用）
        assert [i for i in body["items"] if i["bucket"] == "generating"][0]["error"] is None
        # 挪到窗口外（3 天前失败）→ 卡消失，但总数照样报得出，界面才敢说「另有 N 张更早的」
        async with dbmod.async_session_factory() as s:
            f = await s.get(AssetProduction, p_a2.id)
            f.completed_at = datetime.utcnow() - timedelta(days=3)
            await s.commit()
        body = (await client.get("/api/assets/outputs/inflight", headers=hm)).json()
        assert body["failed_total"] == 1 and body["failed_older"] == 1, body
        assert not [i for i in body["items"] if i["bucket"] == "failed"], "窗口外不摆卡"
        expanded = (await client.get(
            "/api/assets/outputs/inflight", params={"include_older_failed": "true"}, headers=hadm
        )).json()
        old_failed = [i for i in expanded["items"] if i["bucket"] == "failed"]
        assert expanded["failed_total"] == 1 and expanded["failed_older"] == 0, expanded
        assert [i["production_id"] for i in old_failed] == [str(p_a2.id)], \
            "展开后老失败单必须真正给卡，让一线能删，而不是只把计数藏起来"

        # ⑦ 批 V 顺手修的一处**静默错键**：片层灰字「投：某人」以前恒为 null——
        #    代码拿 `o.production_id` 去查「用户 id → 显示名」的映射（两个不同实体的 id），
        #    永不相等。用例此前只断言 `/productions` 口的 owner_name，没盖住这个口，
        #    所以现网成片卡上从来没出现过投产人。这里钉住"有生产单就必须带出人名"。
        outs = (await client.get("/api/assets/outputs?owner=all", headers=hm)).json()["items"]
        with_prod = [o for o in outs if o["production_id"]]
        assert with_prod, "本例的产物都挂在生产单上"
        assert all(o["owner_name"] for o in with_prod), \
            f"成片卡要标得出投产人：{[(o['file_key'], o['owner_name']) for o in with_prod]}"
        await client.aclose()

    _run(_scenario())


def test_wall_delete_inflight_and_outputs():
    """批 Y（11-25 用户口径「成片墙没有删除功能，比如超时生成的豆包素材无法删掉」）。

    钉七件事：①在途（queued/running）可人工删单→cancelled，成因带操作人与投出时长；
    ②删掉的单必须从在途占位里消失——**老查询第二臂 `board_tid is not None` 会把作废单
    继续摆回墙上**，这是本批唯一真正的回归点；③失败单也可删→cancelled，原失败成因保留，
    红卡消失且当天号池消耗不变；④success 终态不可删（409）；
    ⑤权限闸：material 可删本人单、删他人 403，operator/admin 可删他人；动作进审计；⑥成片删除逐形回报（invalid/
    not_found/files_failed），MinIO 尽力语义＝删不掉文件照删行并如实报；⑦墙列表跟掉。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, hadm = h["material"], h["operator"], h["admin"]

        asset_id, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=hadm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            pr = await client.post("/api/assets/produce",
                                   json={"summary_ids": [sid], "n": 1, "hook_codes": ["7CY01"]}, headers=hadm)
            assert pr.status_code == 200, f"投产回包异常 {pr.status_code}: {pr.text[:300]}"
        p = (await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(asset_id)))[0]

        # 置成「投出去 80 分钟没回片」的在途单
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p.id)
            row.status, row.board_tid, row.started_at = PR_QUEUED, "T-Y1", datetime.utcnow() - timedelta(minutes=80)
            row.board_date = svc.board_timestamp(
                tz_offset_hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0)
            )
            await s.commit()
        assert (await client.get("/api/assets/outputs/inflight", headers=hadm)).json()["inflight_total"] == 1

        # 权限：material 能删本人，不能删他人；非法 id 400、不存在 404
        assert (await client.post(f"/api/assets/productions/{p.id}/cancel", headers=hm)).status_code == 403
        assert (await client.post("/api/assets/productions/not-a-uuid/cancel", headers=hadm)).status_code == 400
        assert (await client.post(f"/api/assets/productions/{uuid.uuid4()}/cancel", headers=hadm)).status_code == 404

        # ① 删单：queued→cancelled，error 说清谁删的、投出多久
        c = await client.post(f"/api/assets/productions/{p.id}/cancel", headers=hadm)
        assert c.status_code == 200, c.text
        cb = c.json()
        assert cb["status"] == PR_CANCELLED and "人工删单" in cb["error"] and ADMIN_USER in cb["error"]
        assert "80" in cb["error"], f"删因要带投出时长，跟卡上「投出 80 分」对得上：{cb['error']}"
        # ② 占位条跟掉（board_tid 还在——没排作废态的老查询会把它继续摆回墙上）
        inf = (await client.get("/api/assets/outputs/inflight", headers=hadm)).json()
        assert inf["inflight_total"] == 0 and str(p.id) not in {i["production_id"] for i in inf["items"]}, inf
        # ③ 重复删/终态删：409 且话术指路
        again = await client.post(f"/api/assets/productions/{p.id}/cancel", headers=hadm)
        assert again.status_code == 409 and "成片走产物删除口" in again.text
        # ④ 审计留痕
        audits = await _rows(AuditLog, AuditLog.action == "asset.production.cancel")
        assert [a.target_id for a in audits] == [str(p.id)]

        # ③b 失败单也必须能从红卡删掉：failed→cancelled，原失败成因留在 error，
        # 失败卡消失，但 started_at 已吃掉的号池不能因为「删单」被抹掉。
        # 原错误刻意塞满 500 字：删单原因必须自己留位，不能被末尾截断吞掉。
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p.id)
            row.status, row.error = PR_FAILED, ("内容审核未通过：角色卡不符；" + "长" * 600)[:500]
            row.completed_at = datetime.utcnow() - timedelta(minutes=20)
            row.board_total = 20
            await s.commit()
        failed_inf = (await client.get("/api/assets/outputs/inflight", headers=hadm)).json()
        assert failed_inf["failed_total"] == 1
        before_disp = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=hadm)).json()["dispatch"]
        assert before_disp["today"]["dispatched"] == 1, before_disp
        assert before_disp["today"]["board_rows"] == 20, before_disp
        # SQLite 会静默忽略 FOR UPDATE，所以不能只靠「删单成功」证明并发闸门存在。
        # 从 ORM 执行事件检查真实 Select 的锁参数；以后有人去掉行锁，这条用例必须红。
        from sqlalchemy import event
        from sqlalchemy.sql import Select
        locked_selects = []
        statements_seen = []

        def capture_production_select(state):
            statement = state.statement
            statements_seen.append(type(statement).__name__)
            if isinstance(statement, Select) and AssetProduction.__tablename__ in str(statement):
                locked_selects.append(getattr(statement, "_for_update_arg", None))

        session_class = dbmod.async_session_factory.class_.sync_session_class
        event.listen(session_class, "do_orm_execute", capture_production_select)
        try:
            fc = await client.post(f"/api/assets/productions/{p.id}/cancel", headers=hadm)
        finally:
            event.remove(session_class, "do_orm_execute", capture_production_select)
        assert fc.status_code == 200, fc.text
        assert any(arg is not None for arg in locked_selects), \
            f"删单读取生产单必须加行锁，不能与回收改判 success 竞态覆盖：{statements_seen}"
        fcb = fc.json()
        assert fcb["status"] == PR_CANCELLED and fcb["error"].startswith("内容审核未通过：角色卡不符")
        assert "人工删单" in fcb["error"] and ADMIN_USER in fcb["error"], fcb
        assert len(fcb["error"]) <= 500, "超长原错误不能把删单操作人截掉"
        failed_after = (await client.get("/api/assets/outputs/inflight", headers=hadm)).json()
        assert failed_after["failed_total"] == 0 and str(p.id) not in {i["production_id"] for i in failed_after["items"]}

        # operator 删的是 admin 投出的他人单；素材专员也应能删自己投出的失败单。
        material_user = (await _rows(User, User.username == MATERIAL_USER))[0]
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p.id)
            row.status, row.created_by = PR_FAILED, material_user.id
            await s.commit()
        own_cancel = await client.post(f"/api/assets/productions/{p.id}/cancel", headers=hm)
        assert own_cancel.status_code == 200, own_cancel.text
        assert own_cancel.json()["status"] == PR_CANCELLED
        assert MATERIAL_USER in own_cancel.json()["error"]
        assert (await _row_of(AssetProduction, p.id)).status == PR_CANCELLED

        after_disp = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=hadm)).json()["dispatch"]
        assert after_disp["today"]["dispatched"] == before_disp["today"]["dispatched"], \
            f"人工删失败单不能把已消耗号池抹掉：{before_disp} -> {after_disp}"
        assert after_disp["today"]["tasks"] == before_disp["today"]["tasks"], after_disp
        assert after_disp["today"]["board_rows"] == before_disp["today"]["board_rows"], \
            "删单不能把已吃的 20 条板面额度改成 0"
        assert after_disp["voided_after_dispatch"] == 1, after_disp
        audits = await _rows(AuditLog, AuditLog.action == "asset.production.cancel")
        assert len(audits) == 3 and any(
            ((a.before or {}).get("error") or "").startswith("内容审核未通过：角色卡不符")
            and len((a.before or {}).get("error") or "") == 500
            for a in audits
        ), "审计 before 要保留 500 字原错误全文"

        exported = await client.get(
            "/api/assets/productions/export", params={"ids": str(p.id), "format": "txt"}, headers=hadm)
        assert exported.status_code == 200, exported.text
        export_body = exported.json()
        assert export_body["items"][0]["status"] == PR_CANCELLED
        assert export_body["items"][0]["exportable"] is False
        assert export_body["items"][0]["prompt_text"] is None
        assert not export_body.get("export_text"), "作废单不得从 txt 口继续交付"
        fb = _FakeBoard()
        with _board_off(fb):
            blocked_dispatch = await _dispatch(client, hadm, [p.id], recover_only=True)
        assert blocked_dispatch.status_code == 400, blocked_dispatch.text
        assert "没有可回收的单" in blocked_dispatch.json()["detail"]
        assert fb.creates == [] and fb.reads == [], "作废单既不新建板任务，也不进回收轮询"

        # 作废后人工回写也不能把卡片复活；正常顺序下应被 cancelled 闸门挡住。
        revive = await client.post(
            "/api/assets/productions/status",
            json={"ids": [str(p.id)], "status": "success"}, headers=hadm,
        )
        assert revive.status_code == 200 and revive.json()["updated"] == 0
        assert "取消" in revive.json()["blocked"][0]["reason"]
        assert (await _row_of(AssetProduction, p.id)).status == PR_CANCELLED

        # ④ 已出成片的终态仍不可从这里删，必须走产物删除口。
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, p.id)
            row.status = PR_SUCCESS
            await s.commit()
        success_block = await client.post(f"/api/assets/productions/{p.id}/cancel", headers=hadm)
        assert success_block.status_code == 409 and "成片走产物删除口" in success_block.text

        # ⑤ 成片删除：三行，第 2 行模拟 MinIO 抖动（删不掉文件也照删行，如实回报）
        oids = []
        for i in range(3):
            oid = uuid.uuid4()
            oids.append(oid)
            async with dbmod.async_session_factory() as s:
                s.add(AssetOutput(
                    id=oid, production_id=p.id, asset_id=uuid.UUID(asset_id),
                    kind="doubao_raw", file_key=f"asset-out/y-del-{i}.mp4",
                    bucket=settings.MINIO_BUCKET_SLICED, file_name=f"成片{i}.mp4",
                ))
                await s.commit()
        calls = []

        async def _fake_delete(bucket, key):
            calls.append((bucket, key))
            return "y-del-1" not in key

        gone_id = str(oids[2])
        ghost_id = str(uuid.uuid4())
        with patch("app.api.assets.misc.delete_file", _fake_delete):
            d = await client.post("/api/assets/outputs/delete", headers=hadm,
                                  json={"ids": [str(oids[0]), str(oids[1]), "bad-id", ghost_id],
                                        "reason": "超时重复片"})
        assert d.status_code == 200, d.text
        dr = d.json()
        assert dr["deleted"] == 2 and sorted(dr["ids"]) == sorted([str(oids[0]), str(oids[1])])
        assert dr["invalid"] == ["bad-id"] and dr["not_found"] == [ghost_id]
        assert dr["files_failed"] == [str(oids[1])], f"文件删失败不拦删行，但要报出来：{dr}"
        assert len(calls) == 2 and all(b == settings.MINIO_BUCKET_SLICED for b, _ in calls)
        left = {str(x.id) for x in await _rows(AssetOutput)}
        assert str(oids[0]) not in left and str(oids[1]) not in left and gone_id in left
        # ⑥ 墙列表跟掉 + 预览口别给死链报错以外的惊喜
        outs = (await client.get("/api/assets/outputs?owner=all", headers=hadm)).json()["items"]
        assert {str(oids[0]), str(oids[1])}.isdisjoint({o["id"] for o in outs})
        # 空名单 400、超上限 400、material 403、operator（同圈）能删
        assert (await client.post("/api/assets/outputs/delete", headers=hadm, json={"ids": []})).status_code == 400
        too_many = await client.post("/api/assets/outputs/delete", headers=hadm,
                                     json={"ids": [str(uuid.uuid4()) for _ in range(201)]})
        assert too_many.status_code == 400
        assert (await client.post("/api/assets/outputs/delete", headers=hm, json={"ids": [gone_id]})).status_code == 403
        with patch("app.api.assets.misc.delete_file", _fake_delete):
            d2 = await client.post("/api/assets/outputs/delete", headers=ho, json={"ids": [gone_id]})
        assert d2.status_code == 200 and d2.json()["deleted"] == 1
        d_audits = await _rows(AuditLog, AuditLog.action == "asset.outputs.delete")
        assert len(d_audits) == 2
        assert any((a.after or {}).get("reason") == "超时重复片" for a in d_audits), "删因必须进审计"
        await client.aclose()

    _run(_scenario())


def test_summary_generate_sets_condensed_title_as_asset_name():
    """2026-11-07 用户口径：出文案同步产浓缩标题，直接当素材名称（不用 AS 编号）。

    服务给了 title（2~30 字）→ asset.title 被覆盖（反推扫描的长标题也让位）；
    没给 title → 标题维持原状，绝不硬写。规则本体在 autoclip hook_copy.txt
    （6~14 字、人设＋事件、不编号不带平台词），这里钉的是后端的接法。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        old_title = (await _row_of(AssetItem, asset_id)).title

        with patch("app.api.assets._call_autoclip", _fake_autoclip(gen_title="顶替姐姐的新娘")):
            resp = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
        assert resp.status_code == 200, resp.text
        assert (await _row_of(AssetItem, asset_id)).title == "顶替姐姐的新娘"

        # 服务没给 title：已有标题不被覆盖（空标题仍走既有的反推兜底，那是另一条路）
        asset2, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        async with dbmod.async_session_factory() as s:
            row2 = await s.get(AssetItem, uuid.UUID(asset2))
            row2.title = "陈天强素材原标题"
            await s.commit()
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            resp2 = await client.post(
                "/api/assets/summaries/generate", json={"asset_ids": [asset2]}, headers=hm)
        assert resp2.status_code == 200, resp2.text
        assert (await _row_of(AssetItem, asset2)).title == "陈天强素材原标题" 
        await client.aclose()

    _run(_scenario())


# ─────────────────────  A′ 按运营隔离（2026-11-07，评审团定稿方案）  ─────────────────────


def test_isolation_owner_views_public_produce_and_owner_scoped_outputs():
    """A′ 按运营隔离：读口仍按过审人/投产人过滤，免费投产不再有跨人确认。

    钉六件事：
    ① 已过审区按过审人隔离（owner=me 不含别人的、也不含 reviewed_by NULL 的无主公共历史），
       pending 队列全量共享（挑文案是大家的事）；
    ② 投别人过审的候选无需确认即可投产，production.created_by 记实际投产人，
       审计保留操作人、候选审核人；reviewed_by NULL 的存量过审行仍按公共候选处理；
    ③ 同态重报已过审候选不改归属（B 重按 A 过审过的「过」，reviewed_by 保持 A＋note）；
    ④ 成片 owner：owner=me 含自己的＋拼接公共产物（production_id NULL），不含别人的；
       groups 组层与片层同一套口径（IN 半连接不丢行）；
    ⑤ _dispatch_counts owner 只进 scope 聚合：A 的「我的」succeeded=1，today 号池口径
       全站（A+B 两人的都算），dispatch_all 给全站 scope；
    ⑥ 写口零放松回归：写请求带 owner 参数行为不变（owner 是 GET 查询偏好，不进写路径）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        # 造第二个 operator（隔离矩阵需要 A/B 两个运营）
        async with dbmod.async_session_factory() as s:
            op_b = (await s.execute(select(User).where(User.username == "asset_op_b"))).scalar_one_or_none()
            if op_b is None:
                op_b = User(id=uuid.uuid4(), username="asset_op_b",
                            password_hash=get_password_hash(PASSWORD),
                            display_name="运营B", role="operator", data_scope="own", is_active=True)
                s.add(op_b)
                await s.commit()
                op_b = await s.get(User, op_b.id)
        hb = {"Authorization": "Bearer " + (
            await client.post("/api/auth/login", json={"username": "asset_op_b", "password": PASSWORD})
        ).json()["access_token"]}
        ho = h["operator"]  # 运营 A

        async def _approved_summary(url, approver_headers):
            """导入→出文案→指定运营过审，返回 (asset_id, summary_id)。"""
            aid, _ = await _make_ready_asset(client, hm, url=url)
            items, _ = await _gen_and_list(aid, hm, client)
            sid = _approvable(items)["id"]
            r = await client.post("/api/assets/summaries/review",
                                  json={"summary_ids": [sid], "action": "approve"},
                                  headers=approver_headers)
            assert r.status_code == 200 and r.json()["results"][0]["ok"] is True, r.text
            return aid, sid

        async def _produce(headers, sid, **extra):
            with patch("app.api.assets._call_autoclip", _fake_autoclip()):
                return await client.post(
                    "/api/assets/produce",
                    json={"summary_ids": [sid], "n": 1, "async_mode": False, **extra},
                    headers=headers)

        a1, s1 = await _approved_summary(DOUYIN_2, ho)        # A 过审
        a2, s2 = await _approved_summary(DOUYIN_3, ho)        # A 过审
        a3, s3 = await _approved_summary("https://www.douyin.com/video/7599000000000000001", ho)  # A 过审
        a4, s4 = await _approved_summary("https://www.douyin.com/video/7599000000000000002", ho)  # A 过审

        # ① 已过审区隔离：B 的 owner=me 看不到 A 过审的；owner=all 全量；pending 全量共享
        me_q = await client.get("/api/assets/summaries?owner=me&audit_status=approved", headers=hb)
        assert me_q.status_code == 200 and me_q.json()["total"] == 0, me_q.text
        all_q = await client.get("/api/assets/summaries?owner=all&audit_status=approved", headers=hb)
        assert all_q.json()["total"] == 4
        pd = await client.get("/api/assets/summaries?owner=me&audit_status=pending", headers=hb)
        assert pd.status_code == 200 and pd.json()["total"] >= 4, "pending 候选池全量共享（owner=me 也要看得见）"
        # pending 共享：再造一条 pending（只出文案不过审）
        a5, _ = await _make_ready_asset(client, hm, url="https://www.douyin.com/video/7599000000000000003")
        await _gen_and_list(a5, hm, client)
        pd2 = await client.get("/api/assets/summaries?owner=me&audit_status=pending", headers=hb)
        assert pd2.json()["total"] >= 4 + 1, "新素材的 pending 同样全量共享"
        # A 的 owner=me：已过审区四条全是自己的，带显示名
        me_a = await client.get("/api/assets/summaries?owner=me&audit_status=approved", headers=ho)
        assert me_a.json()["total"] == 4
        assert me_a.json()["items"][0]["reviewed_by_name"], "过审人灰字名随行返回"

        # ② 投别人过审的候选：无需跨人确认即可投产，归实际投产人并保留审核人留痕。
        ok = await _produce(hb, s1)
        assert ok.status_code == 200, ok.text
        assert not {"capacity_hint", "board_capacity", "capacity"} & ok.json().keys(), ok.json()
        prodB = (await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(a1)))[0]
        assert prodB.created_by == op_b.id, "谁投账算谁：created_by 记实际投产人"
        summary1 = await _row_of(AssetSummary, s1)
        assert summary1.reviewed_by is not None, "候选审核人不能被投产动作抹掉"
        # 审计同时保留实际操作人与候选审核人。
        audits = await _rows(AuditLog, AuditLog.action == "asset.produce_order")
        audit = next(a for a in audits if a.after and any(
            x.get("summary_id") == s1 for x in (a.after.get("owner_cross") or {}).get("summaries", [])
        ))
        assert audit.operator_id == op_b.id, "审计人记实际投产人"
        crossed = audit.after["owner_cross"]["summaries"][0]
        assert crossed["reviewed_by"] == str(summary1.reviewed_by)
        assert crossed["reviewed_by_name"] == "运营专员", crossed
        # reviewed_by NULL 的存量过审行＝无主公共，不拦
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetSummary, uuid.UUID(s4))
            row.reviewed_by = None
            await s.commit()
        legacy = await _produce(hb, s4)
        assert legacy.status_code == 200, f"无主公共候选不拦：{legacy.text[:200]}"

        # ③ 同态重报不改归属：B 重按 A 过审过的 s2，reviewed_by 保持 A＋note
        again = await client.post("/api/assets/summaries/review",
                                  json={"summary_ids": [s2], "action": "approve"}, headers=hb)
        assert again.status_code == 200, again.text
        res0 = again.json()["results"][0]
        assert res0["ok"] is True and "保持原归属" in (res0.get("note") or ""), res0
        s2row = await _row_of(AssetSummary, s2)
        op_a_row = (await _rows(User, User.username == OPERATOR_USER))[0]
        assert s2row.reviewed_by == op_a_row.id, "同态重报绝不偷换 reviewed_by"

        # ②b async_mode=true（前端唯一真实路径）同样无需确认，受理即回任务号。
        # 全程给模型替身，等后台任务收口后再清掉本用例的成片，避免污染下面的 owner 矩阵。
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            r = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [s3], "n": 1, "async_mode": True}, headers=hb)
            assert r.status_code == 200, r.text
            assert r.json()["queued"] is True and r.json()["job_id"], r.json()
            assert not {"capacity_hint", "board_capacity", "capacity"} & r.json().keys(), r.json()
            async_job = await _wait_job(client, hb, r.json()["job_id"])
        assert async_job["status"] == "succeeded", async_job
        from sqlalchemy import delete as sa_delete
        async_prod = (await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(a3)))[0]
        async with dbmod.async_session_factory() as s:
            await s.execute(sa_delete(AssetOutput).where(AssetOutput.production_id == async_prod.id))
            await s.execute(sa_delete(AssetProduction).where(AssetProduction.id == async_prod.id))
            await s.commit()

        # ④ 成片 owner：A 投自己的（无闸）＋直接插产物（A 的单、B 的单、拼接公共）
        own = await _produce(ho, s2)
        assert own.status_code == 200, own.text[:300]
        prodA = (await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(a2)))[0]
        async with dbmod.async_session_factory() as s:
            s.add(AssetOutput(id=uuid.uuid4(), production_id=prodA.id, asset_id=uuid.UUID(a2),
                              kind="doubao_raw", file_key="o/a.mp4", bucket=settings.MINIO_BUCKET_SLICED))
            s.add(AssetOutput(id=uuid.uuid4(), production_id=prodB.id, asset_id=uuid.UUID(a1),
                              kind="doubao_raw", file_key="o/b.mp4", bucket=settings.MINIO_BUCKET_SLICED))
            s.add(AssetOutput(id=uuid.uuid4(), production_id=None, asset_id=uuid.UUID(a2),
                              kind="composed", file_key="o/pub.mp4", bucket=settings.MINIO_BUCKET_SLICED))
            await s.commit()
        oa = await client.get("/api/assets/outputs?owner=me", headers=ho)
        keys = {i["file_key"] for i in oa.json()["items"]}
        assert "o/a.mp4" in keys and "o/pub.mp4" in keys and "o/b.mp4" not in keys, keys
        ob = await client.get("/api/assets/outputs?owner=me", headers=hb)
        keys_b = {i["file_key"] for i in ob.json()["items"]}
        assert "o/b.mp4" in keys_b and "o/pub.mp4" in keys_b and "o/a.mp4" not in keys_b, keys_b
        ga = await client.get("/api/assets/outputs/groups?group_by=asset&owner=me", headers=ho)
        gkeys = {g["key"] for g in ga.json()["groups"]}
        assert a2 in gkeys and a1 not in gkeys, f"组层与片层同一套 owner 口径：{gkeys}"
        # owner=all 全量
        al = await client.get("/api/assets/outputs?owner=all", headers=ho)
        assert len(al.json()["items"]) == 3

        # ⑤ dispatch counts：owner 只进 scope，today 号池全站
        today = datetime.utcnow() + timedelta(hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0))
        async with dbmod.async_session_factory() as s:
            for pr in (prodA, prodB):
                p = await s.get(AssetProduction, pr.id)
                p.status = "success"
                p.started_at = datetime.utcnow()
                p.board_date = svc.board_timestamp(tz_offset_hours=int(settings.ASSET_BOARD_TZ_OFFSET_HOURS or 0))
                p.board_total = 1
            await s.commit()
        ca = await client.get("/api/assets/productions?owner=me", headers=ho)
        body = ca.json()
        _dbg = await _rows(AssetProduction)
        _codes = {str(a.id): a.code for a in await _rows(AssetItem)}
        _unames = {str(u.id): u.username for u in await _rows(User)}
        print("DBG prods:", [( _codes.get(str(r.asset_id), "?"), r.status, _unames.get(str(r.created_by), "?")) for r in _dbg])
        print("DBG assets:", [(a.code, str(a.id)[:8]) for a in await _rows(AssetItem)])
        print("DBG dispatch:", body["dispatch"]["by_status"], "| all:", body["dispatch_all"]["by_status"])
        assert body["dispatch"]["succeeded"] == 1, "我的 scope 只算我的"
        assert body["dispatch_all"]["succeeded"] == 2, "dispatch_all 给全站 scope"
        assert body["dispatch"]["today"]["dispatched"] == 2, "today 号池口径全站（A+B 都算）"
        assert body["items"][0]["owner_name"], "投产人灰字随行返回"

        # ⑥ 写口零放松：写请求带 owner 参数行为不变（owner 是 GET 查询偏好，不进写路径）
        wb = await client.post("/api/assets/summaries/review?owner=me",
                               json={"summary_ids": [s3], "action": "approve"}, headers=hb)
        assert wb.status_code == 200 and wb.json()["results"][0]["ok"] is True, wb.text
        # 非法 owner 值在读口 400
        bad = await client.get("/api/assets/summaries?owner=someone", headers=ho)
        assert bad.status_code == 400
        await client.aclose()

    _run(_scenario())


def test_import_copy_summaries_direct_to_review_queue():
    """直接贴文案导入（2026-11-08 用户需求）：跳过链接/反推，文案直挂候选进审核队列。

    钉四件事：①建批次＋素材壳＋pending 候选（推荐=第一条）；②形态不合格的条目
    被跳过并点名（只提示不拦在导入口的形态校验）；③无视频无脚本的候选能正常过审
    （recheck 无脚本时一致性优雅退化 ok=True）；④审核→投产全链路照走（expand 展开）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        good1 = "她替姐姐嫁的第二天，新郎出现在她姐的婚礼上，当着两家长辈问这婚到底算谁的"
        good2 = "总裁摘下手表坐在塑料凳上吃泡面，秘书问他为什么放着办公室的沙发不坐"
        bad = "这个太长了，" * 30  # 超 80 字 → 形态不合格被跳过

        r = await client.post(
            "/api/assets/summaries/import-copy",
            json={"batch_name": "e2e-贴文案", "texts": [good1, bad, good2]},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2 and len(body["skipped"]) == 1, body
        assert body["skipped"][0]["index"] == 2, body["skipped"]
        assert body["batch_code"], body

        # 候选：pending、第一条推荐、无脚本
        listed = (await client.get(
            f"/api/assets/summaries?audit_status=pending&batch_id={body['batch_id']}", headers=ho)).json()
        assert listed["total"] == 2, listed
        rec = [i for i in listed["items"] if i["is_recommended"]]
        assert len(rec) == 1, f"恰好一条推荐：{[i['is_recommended'] for i in listed['items']]}"
        assert rec[0]["text"].startswith("她替姐姐嫁"), rec[0]["text"][:30]

        # 无脚本过审：一致性优雅退化（ok=True），风险词/形态照校验
        sids = [i["id"] for i in listed["items"]]
        ok = await client.post("/api/assets/summaries/review",
                               json={"summary_ids": sids, "action": "approve"}, headers=ho)
        assert ok.status_code == 200, ok.text
        assert all(x["ok"] for x in ok.json()["results"]), ok.json()

        # 投产照走（expand 展开提示词）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [sids[0]], "n": 1, "async_mode": False},
                headers=ho)
        assert made.status_code == 200, made.text[:300]
        assert made.json()["created"] >= 1, made.json()
        await client.aclose()

    _run(_scenario())


# ───────────────────  12. 成稿配对导入（11-09）  ───────────────────


def _paired_files(items_bytes):
    """[(文件名, 字节, mime)] → httpx 的 files 参数形状。"""
    return [("files", (name, data, mime)) for name, data, mime in items_bytes]


def test_import_paired_lands_four_slots_and_costs_nothing():
    """成稿配对导入：原片＋人工稿＋一句话文案＋豆包提示词一次进四个槽位，全程 0 元。

    钉五件事（都是这个口存在的理由，任何一条塌了就不如走老路）：
      ① 素材行带上 file_key/duration/**resolution**（横屏标记的唯一数据源）；
      ② 反推任务行是 success 且不带 provider_task_id —— 于是 `refresh_prompt_task`
         永远不会去智令查询（不会把一条人工稿刷成一笔真扣费）；
      ③ 四种形状各停各的位置，且**只有有稿没文案**那条进得了出文案队列（没稿的当场 400，
         说明本口没把"没稿"粉饰成"有稿"）；
      ④ 钱：批次 cost_estimate=0、素材 cost_prompt/cost_parse=0（对账页不能出现没发生的钱）；
      ⑤ 每条一行审计。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]

        # 字典里种一条真类别，验证「清单吃人话名字」这条路
        cat_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetCategory(id=cat_id, name="悬念", sort=900, active=True, note="测试种入"))
            await s.commit()

        manifest = {
            "batch_name": "e2e 成稿",
            "items": [
                # ① 四件齐全：稿＋文案＋提示词（这批 26 条就是这个形状）
                {"video": "悬念/已完成/地里捡到小男孩.mp4", "category": "悬念",
                 "title": "地里捡到小男孩", "script_text": SCRIPT,
                 "hook_copy": CANDIDATES[0]["text"], "doubao_prompt": "【完整豆包提示词】镜头1…"},
                # ② 只有稿：字典里没这个名字 → 未分类＋进 need_copy（用户拍板要补文案的那 60 条）
                {"video": "猎奇/下水道口.mp4", "category": "猎奇脑洞",
                 "title": "下水道口", "script_text": SCRIPT},
                # ③ 只有文案：欠的是**稿**，不是文案 → 必须出现在 need_prompt 里
                {"video": "偷听/会议室.mp4", "category": "悬念",
                 "title": "会议室", "hook_copy": CANDIDATES[0]["text"]},
                # ④ 两样都缺：原片先入库，稿和文案都欠着
                {"video": "预言/老宅半夜.mp4", "title": "老宅半夜"},
            ],
        }
        files = _paired_files([
            ("地里捡到小男孩.mp4", VIDEO_BYTES, "video/mp4"),
            ("下水道口.mp4", VIDEO_BYTES, "video/mp4"),
            ("会议室.mp4", VIDEO_BYTES, "video/mp4"),
            ("老宅半夜.mp4", VIDEO_BYTES, "video/mp4"),
        ])
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=8.85)), \
             patch("app.api.assets._probe_image_size", AsyncMock(return_value=(1280, 720))):
            r = await client.post(
                "/api/assets/import/paired", files=files,
                data={"manifest": json.dumps(manifest, ensure_ascii=False)}, headers=hm,
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["created"] == 4, body
        # 悬念 2 条 + 猎奇脑洞 1 条 + 未分类 1 条 = 三个批次（按类别分组，验收与回滚都按类别走）
        assert len(body["batches"]) == 3, body["batches"]
        assert body["unknown_categories"] == ["猎奇脑洞"], body["unknown_categories"]
        assert body["shape_warnings"] == []
        assert body["errors"] == [] and body["leftover_files"] == [], body
        # 两条欠账轴分开报：②欠文案、③④欠稿（④两头都欠，归到"缺稿"——不补稿就轮不到文案）
        assert len(body["need_copy"]) == 1, body["need_copy"]
        assert len(body["need_prompt"]) == 2, body["need_prompt"]
        assert "0 模型费" in body["message"], body["message"]

        assets = {a.code: a for a in await _rows(AssetItem)}
        assert len(assets) == 4
        by_title = {a.title: a for a in assets.values()}
        assert len(by_title) == 4, sorted(by_title)
        for a in assets.values():
            assert a.media_kind == "video" and a.source_kind == "file"
            assert a.file_key.startswith("asset/") and a.bucket == settings.MINIO_BUCKET_RAW
            # ① 画幅入库时就量出来：链接素材是下载后回写，文件素材以前一直没写
            assert a.resolution == "1280x720", a.resolution
            assert a.duration == 8.85
            # ④ 钱：一条都没花
            assert a.cost_prompt == 0 and a.cost_parse == 0 and a.cost_produce == 0

        # 四种形状各停在哪儿（欠账轴与状态必须一一对上，否则一线看队列就不知道下一步点什么）
        full = by_title["地里捡到小男孩"]
        assert (full.stage_prompt, full.stage_summary) == ("success", "success")
        assert full.status == "awaiting_review" and full.category_id, full
        assert str(full.category_id) == str(cat_id), "清单吃的是原型**名字**，要钉到字典那一行"
        script_only = by_title["下水道口"]
        assert (script_only.stage_prompt, script_only.stage_summary) == ("success", "pending")
        assert script_only.status == "waiting_summary", script_only.status
        assert script_only.category_id is None, "字典里没有的名字→未分类，不替人建字典行"
        assert assets[body["need_copy"][0]].title == "下水道口", body["need_copy"]
        copy_only = by_title["会议室"]
        assert (copy_only.stage_prompt, copy_only.stage_summary) == ("pending", "success")
        assert copy_only.status == "awaiting_review", copy_only.status
        both_missing = by_title["老宅半夜"]
        assert (both_missing.stage_prompt, both_missing.stage_summary) == ("pending", "pending")
        assert both_missing.status == "waiting_prompt", both_missing.status
        assert set(body["need_prompt"]) == {copy_only.code, both_missing.code}, body["need_prompt"]

        # ② 反推任务行：只有带稿的两条有；success、content＝人工稿、source_url 是明确不是 URL 的哨兵
        from wechat_download.models import PT_SUCCESS, WechatDlPromptTask
        tasks = await _rows(WechatDlPromptTask)
        assert len(tasks) == 2, len(tasks)
        for t in tasks:
            assert t.status == PT_SUCCESS and t.content == SCRIPT
            assert t.provider_task_id is None, "带 provider_task_id 就会被轮询当真实任务查"
            assert str(t.source_url).startswith("paired://"), t.source_url
        assert {str(full.prompt_task_id), str(script_only.prompt_task_id)} == {str(t.id) for t in tasks}
        assert copy_only.prompt_task_id is None and both_missing.prompt_task_id is None
        # 人工稿不该被任何一次外部查询改动：`refresh_prompt_task` 对非 processing 原样返回
        async with dbmod.async_session_factory() as s:
            from wechat_download.prompt_service import refresh_prompt_task
            refreshed = await refresh_prompt_task(s, await s.get(WechatDlPromptTask, tasks[0].id))
            assert refreshed.content == SCRIPT and refreshed.status == PT_SUCCESS

        # ③ 候选：只有带文案的两条，pending、推荐、带豆包网页版提示词
        sums = await _rows(AssetSummary)
        assert len(sums) == 2, len(sums)
        assert all(s.audit_status == RV_PENDING and s.is_recommended for s in sums)
        assert any(s.doubao_prompt == "【完整豆包提示词】镜头1…" for s in sums)
        assert all(s.word_count == len(re.findall(r"\S", CANDIDATES[0]["text"])) for s in sums)
        # 「有文案没稿」那条候选没有来源任务——一致性闸门只能显示"没有稿可对照"，不能假装对照过
        by_asset = {str(s.asset_id): s for s in sums}
        assert by_asset[str(copy_only.id)].source_prompt_task_id is None
        assert str(by_asset[str(full.id)].source_prompt_task_id) == str(full.prompt_task_id)

        # ⑤ 审计
        logs = await _rows(AuditLog, AuditLog.action == "asset.import_paired")
        assert len(logs) == 4, len(logs)
        assert all(x.after["cost"] == 0.0 for x in logs)
        assert sorted(x.after["has_script"] for x in logs) == [False, False, True, True]

        # 批次侧：0 元不是 None（对账页直接显示数字）
        for b in await _rows(AssetBatch):
            assert b.source_kind == "file"
            assert b.cost_estimate == 0.0 and b.cost_actual == 0.0
            assert b.budget_gate == "ok" and "0 模型费" in (b.budget_note or "")
        assert sorted((await _rows(AssetBatch)), key=lambda b: b.item_count)[-1].item_count == 2

        # ③ 续：出文案口**直接吃这条**（有稿没文案，整批排队只认「反推已成功且没出文案」的）
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            gen = await client.post(
                "/api/assets/summaries/generate",
                json={"batch_id": str(script_only.batch_id), "async_mode": False}, headers=hm)
        assert gen.status_code == 200, gen.text
        assert gen.json()["results"][0]["created"] >= 1, gen.json()
        # 反向半边：没稿的那批**排不进**出文案队列（证明本口没把"没稿"粉饰成"有稿"）
        empty = await client.post(
            "/api/assets/summaries/generate",
            json={"batch_id": str(both_missing.batch_id), "async_mode": False}, headers=hm)
        assert empty.status_code == 400 and "没有待出文案的素材" in empty.text, empty.text
        await client.aclose()

    _run(_scenario())


def test_import_paired_refuses_ambiguous_names_and_loudly():
    """同名原片绝不猜：清单里重名、或请求里多传了一份同名文件，都单独点名拒掉。

    这一支是"配对"这件事的全部风险所在：`validate_file_name` 只留 basename，
    A 目录和 B 目录的两支同名 mp4（实测 11.07s / 10.87s 是两个版本）落到素材表上是
    同一个名字。猜错的表现不是报错，而是**画面配错稿**——后面每一环都只看数据库里的
    file_key 和 content，没有任何一处能发现它俩不是一对。所以宁可当场拒。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]

        # ① 清单里两条同名
        m1 = {"items": [
            {"video": "已完成/遇贵人.mp4", "script_text": SCRIPT},
            {"video": "已完成/提示词/遇贵人.mp4", "script_text": SCRIPT},
        ]}
        files = _paired_files([
            ("遇贵人.mp4", VIDEO_BYTES, "video/mp4"),
            ("遇贵人.mp4", b"\x00" * 8000, "video/mp4"),
        ])
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            r = await client.post("/api/assets/import/paired", files=files,
                                  data={"manifest": json.dumps(m1, ensure_ascii=False)}, headers=hm)
        assert r.status_code == 400, r.text
        assert "同名原片" in r.text, r.text
        assert await _count(AssetItem) == 0, "配不上一对就不该留下半批数据"
        assert await _count(AssetBatch) == 0

        # ② 清单 1 条、请求里传了两份同名 → 同样拒（调用方应只投清单引用的那些文件）
        m2 = {"items": [{"video": "遇贵人.mp4", "script_text": SCRIPT}]}
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)):
            r2 = await client.post("/api/assets/import/paired", files=files,
                                   data={"manifest": json.dumps(m2, ensure_ascii=False)}, headers=hm)
        assert r2.status_code == 400, r2.text
        assert "无法判断配哪一个" in r2.text, r2.text

        # ③ 清单引用了请求里没有的文件 → 该条单独失败，其余照常入库（fail-soft）
        m3 = {"items": [
            {"video": "遇贵人.mp4", "title": "遇贵人", "script_text": SCRIPT},
            {"video": "根本不存在.mp4", "title": "不存在", "script_text": SCRIPT},
        ]}
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_image_size", AsyncMock(return_value=(720, 1280))):
            r3 = await client.post("/api/assets/import/paired",
                                   files=_paired_files([("遇贵人.mp4", VIDEO_BYTES, "video/mp4")]),
                                   data={"manifest": json.dumps(m3, ensure_ascii=False)}, headers=hm)
        assert r3.status_code == 201, r3.text
        b3 = r3.json()
        assert b3["created"] == 1 and len(b3["errors"]) == 1, b3
        assert "没收到这个文件" in b3["errors"][0]["error"], b3["errors"]
        assert await _count(AssetItem) == 1
        await client.aclose()

    _run(_scenario())


def test_import_paired_dirty_manifest_shape_bad_copy_and_reimport():
    """脏清单当场 400；形态不合格的人工文案**照样入库**；同批重投默认跳过、force 才放行。

    ③ 是本口与 `/assets/summaries/import-copy` 唯一的行为差异，也是刻意的：
    贴文案导入跳过不合格条目（那是模型产的字，扔了不心疼），而这里被扔掉的会是
    **一线手工写好的一版稿**——扔掉等于让ta白干，还会让这条素材被误判成"没文案"，
    下一步出文案就把这版稿覆盖掉。所以照样收、只在响应里点名，硬拦留给审核口 recheck。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]

        # ① 脏清单：不是 JSON / 没有 items / 空 items
        for bad in ["不是JSON{", '{"items": []}', '{"items": "x"}', '[1, 2]']:
            r = await client.post("/api/assets/import/paired",
                                  files=_paired_files([("a.mp4", VIDEO_BYTES, "video/mp4")]),
                                  data={"manifest": bad}, headers=hm)
            assert r.status_code == 400, (bad, r.text)
            assert "清单" in r.text, (bad, r.text)
        assert await _count(AssetBatch) == 0, "400 的这几次一条都不该留下"

        # ② 形态不合格（超 80 字）照样入库 + 点名
        too_long = "这个太长了，" * 30
        manifest = {"items": [{"video": "长文案.mp4", "title": "长文案",
                               "script_text": SCRIPT, "hook_copy": too_long}]}
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=11.07)), \
             patch("app.api.assets._probe_image_size", AsyncMock(return_value=(1920, 1080))):
            r2 = await client.post("/api/assets/import/paired", files=_paired_files(
                [("长文案.mp4", VIDEO_BYTES, "video/mp4")]),
                data={"manifest": json.dumps(manifest, ensure_ascii=False)}, headers=hm)
            assert r2.status_code == 201, r2.text
            body = r2.json()
            assert body["created"] == 1 and len(body["shape_warnings"]) == 1, body
            assert "超字数" in "".join(body["shape_warnings"][0]["problems"]), body["shape_warnings"]
            assert "形态不合格" in body["message"], body["message"]
            # 横屏原片：画幅当场量出来（这批里有横屏件，界面要标出来靠的就是这一列）
            assert (await _rows(AssetItem))[0].resolution == "1920x1080"
        s = (await _rows(AssetSummary))[0]
        assert s.text == too_long and s.audit_status == RV_PENDING, s.text[:30]
        # 入库 ≠ 能过审：审核口那道形态闸门照旧拦（这条才叫"只提示不拦"落在正确的层）
        rev = await client.post("/api/assets/summaries/review",
                                json={"summary_ids": [str(s.id)], "action": "approve"},
                                headers=h["operator"])
        assert rev.status_code == 200 and rev.json()["results"][0]["ok"] is False, rev.json()

        # ③ 同批重投：默认不收（点名是哪一条），force 才放行
        again = await client.post("/api/assets/import/paired", files=_paired_files(
            [("长文案.mp4", VIDEO_BYTES, "video/mp4")]),
            data={"manifest": json.dumps(manifest, ensure_ascii=False)}, headers=hm)
        assert again.status_code == 400, again.text
        assert "库里已有同名素材" in again.text, again.text
        assert await _count(AssetItem) == 1, "重投默认不收，一条都不许多"
        before_audit = await _count(AuditLog)
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=11.07)), \
             patch("app.api.assets._probe_image_size", AsyncMock(return_value=(1920, 1080))):
            forced = await client.post("/api/assets/import/paired", files=_paired_files(
                [("长文案.mp4", VIDEO_BYTES, "video/mp4")]),
                data={"manifest": json.dumps(manifest, ensure_ascii=False),
                      "force_duplicates": "true"}, headers=hm)
        assert forced.status_code == 201, forced.text
        assert forced.json()["created"] == 1
        assert await _count(AssetItem) == 2
        assert await _count(AuditLog) == before_audit + 1
        await client.aclose()

    _run(_scenario())


def test_upload_batch_records_resolution_for_videos():
    """文件上传口从此也给**视频**写 resolution（以前只有图片写）——横屏标记的数据源。

    11-09 用户拍板"横屏原片全部收进来、界面上要标横屏"。判据只能落在 `resolution`
    （宽>高）上，而这一列只有入库那一刻能免费量到：链接素材是下载后回写，文件素材
    此前压根没写，列表和投产口只能显示"画幅未知"，横屏素材就这样混进竖屏投产里
    （成片画幅由角色卡宽高比决定，提示词写 9:16 压不住——这是实测过的坑）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=9.2)), \
             patch("app.api.assets._probe_image_size", AsyncMock(return_value=(1920, 1080))):
            r = await client.post("/api/assets/upload/batch",
                                  files=_paired_files([("横版原片.mp4", VIDEO_BYTES, "video/mp4")]),
                                  headers=hm)
        assert r.status_code == 201, r.text
        a = (await _rows(AssetItem))[0]
        assert a.media_kind == "video"
        assert a.resolution == "1920x1080", a.resolution
        assert a.duration == 9.2
        # 序列化侧口径：宽>高要能被前端认出"横屏"（后端只给 aspect，判词留一处）
        listed = await client.get("/api/assets?limit=20", headers=hm)
        item = [i for i in listed.json()["items"] if i["id"] == str(a.id)][0]
        assert item["resolution"] == "1920x1080", item
        assert item["aspect"]["orientation"] == "landscape", item["aspect"]
        await client.aclose()

    _run(_scenario())


# ────────────────────────────────────────────────────────────────────
# 批 N（11-09）：文案预取钩子编号（用户口径「现有已经导入的那些文案，你都去取一个编号放着吧」）
# ────────────────────────────────────────────────────────────────────

async def _park(client, headers, items):
    return await client.post("/api/assets/summaries/hook-codes", json={"items": items}, headers=headers)


async def _approve_one(client, h, url=None):
    """跑到「一条已过审文案」，返回 (asset_id, summary_id)。

    `url`：一个场景里要造第二条素材时必须换链接——同一归一化 URL 第二次导入会进
    `duplicates`，`items` 是空列表（不是报错），照默认值写死会在 `_make_ready_asset`
    里 `IndexError`。
    """
    hm, ho = h["material"], h["operator"]
    asset_id, _ = await _make_ready_asset(client, hm, **({"url": url} if url else {}))
    items, _ = await _gen_and_list(asset_id, hm, client)
    sid = _approvable(items)["id"]
    ok = await client.post("/api/assets/summaries/review",
                           json={"summary_ids": [sid], "action": "approve"}, headers=ho)
    assert ok.json()["results"][0]["ok"] is True, ok.text
    return asset_id, sid


def test_parked_hook_code_is_consumed_by_produce_and_cleared():
    """预取号顶进缺号槽位、顶掉当场清空：号一发即烧，留着＝允许第二次开单复用同一个号。

    钉的是三件事：
    - 开单不传号也能带上号（这就是"放着"的意义，一线不用每次现取现粘）；
    - 一个号只顶**一个**槽（n=2 时第二张仍是缺号，导出如实标缺，不会一号两投）；
    - 用完预取位清空（`asset_summaries.hook_code` 为 NULL），列表口回读也是 None——
      不清空的话下一次开单会被"预取号已被用掉"那条判据拦死，那是自锁。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, sid = await _approve_one(client, h)

        # 预取位初始为空，且列表口就暴露这个键（前端靠它画"这条已有号"）
        before = (await client.get(f"/api/assets/summaries?asset_id={asset_id}", headers=ho)).json()["items"]
        assert [x for x in before if x["id"] == sid][0]["hook_code"] is None

        r = await _park(client, ho, [{"summary_id": sid, "hook_code": "7n0k1"}])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["summary_parked"] == 1, body
        after = (await client.get(f"/api/assets/summaries?asset_id={asset_id}", headers=ho)).json()["items"]
        # 小写进来也要存成大写（与开单口同一把尺，别出现"7n0k1 / 7N0K1"两个写法）
        assert [x for x in after if x["id"] == sid][0]["hook_code"] == "7N0K1", after

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce",
                                     json={"summary_ids": [sid], "n": 2,
                                           "recommended_title_count": 1}, headers=ho)
        assert made.status_code == 200, made.text
        listed = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"]
        assert [p["hook_code"] for p in sorted(listed, key=lambda x: x["seq"])] == ["7N0K1", None], listed

        srow = await _row_of(AssetSummary, sid)
        assert srow.hook_code is None, srow.hook_code
        await client.aclose()

    _run(_scenario())


def test_parked_code_not_double_spent_when_request_already_carries_it():
    """预取号被手工粘进 hook_codes 时也算用掉：不重复顶槽，但预取位同样要清。

    前端把预取号显示在编号框里（甚至直接带上）是很自然的动作，如果这里只认"顶空槽"
    那一支，预取位就会留着一个已经在单上的号，下一次开单又要撞上「号已被用掉」那条判据。

    2026-11-11 评审把预取位并入撞号拦查之后，这条路径差点被自己的新闸门 400 掉——
    本批文案自己的预取位不是冲突（号就是给这批备的），必须排掉自己；漏排的话最常见
    的那条链路（带预取号开单）当场全红，所以这里既是合同也是防回归。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, sid = await _approve_one(client, h)
        assert (await _park(client, ho, [{"summary_id": sid, "hook_code": "7N0K2"}])).json()["ok"] is True

        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce",
                                     json={"summary_ids": [sid], "n": 1, "hook_codes": ["7N0K2"],
                                           "recommended_title_count": 1}, headers=ho)
        assert made.status_code == 200, made.text
        listed = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"]
        assert [p["hook_code"] for p in listed] == ["7N0K2"], listed
        assert (await _row_of(AssetSummary, sid)).hook_code is None

        # ── 反向腿：同一个号钉在**别人文案**的预取位上，手工带过来必须当场 400 ──
        # 排掉本批自己之后剩下的那支才是真对撞。不拦的话两条文案各带 7N0K3 投上同一块板，
        # 回收时按号对账直接分不清哪条是哪条——这正是 2026-11-11 评审（业务席 P1）要补的那道。
        _aid_b, sid_b = await _approve_one(client, h, url=DOUYIN_3)
        assert (await _park(client, ho, [{"summary_id": sid_b, "hook_code": "7N0K3"}])).json()["ok"] is True
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            clash = await client.post("/api/assets/produce",
                                      json={"summary_ids": [sid], "n": 1, "hook_codes": ["7N0K3"],
                                            "recommended_title_count": 1}, headers=ho)
        assert clash.status_code == 400, clash.text
        assert "7N0K3" in clash.text and "已预取在素材" in clash.text, clash.text
        # 拦在写库之前：既没建单，也没把别人那个预取位顺手清掉
        assert await _count(AssetProduction) == len(listed), "拒开不该留半张单"
        assert (await _row_of(AssetSummary, sid_b)).hook_code == "7N0K3"
        await client.aclose()

    _run(_scenario())


def test_park_hook_code_rejects_bad_input_and_used_codes():
    """钉号这一口的四种拒绝：脏号／两种 id 都给或都不给／批内重号／号已经在某张单上。

    前三种是 400（请求本身不成立，整批不发），最后一种是 200＋`conflicts` 点名——
    批量动作里"这一行不行、那几行照钉"比一把回滚友好，但 `ok:false` 必须给出来，
    不能让调用方以为 85 条全钉上了。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, sid = await _approve_one(client, h)

        bad = await _park(client, ho, [{"summary_id": sid, "hook_code": "7c0b"}])
        assert bad.status_code == 400 and "禁止手编" in bad.text, bad.text
        shape = await _park(client, ho, [{"hook_code": "7N0K3"}])
        assert shape.status_code == 400 and "二选一" in shape.text, shape.text
        both = await _park(client, ho, [{"summary_id": sid, "production_id": sid, "hook_code": "7N0K3"}])
        assert both.status_code == 400, both.text
        dup = await _park(client, ho, [{"summary_id": sid, "hook_code": "7N0K4"},
                                       {"summary_id": sid, "hook_code": "7N0K4"}])
        assert dup.status_code == 400 and "重号" in dup.text, dup.text
        empty = await _park(client, ho, [])
        assert empty.status_code == 400, empty.text
        # 权限：material 只有导入/出质检，取号是要烧的东西，钉号仍是审核侧的活
        forb = await _park(client, hm, [{"summary_id": sid, "hook_code": "7N0K5"}])
        assert forb.status_code == 403, forb.text

        # 号已经被某张单用掉 → conflicts 点名，且**没有**写进预取位
        _aid2, _sid2, listed = await _order_ready_production(client, h, url=DOUYIN_3,
                                                              n=1, hook_codes=["7C0D9"])
        r = await _park(client, ho, [{"summary_id": sid, "hook_code": "7C0D9"}])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["summary_parked"] == 0, body
        assert "已经用在" in body["conflicts"][0]["reason"], body
        assert (await _row_of(AssetSummary, sid)).hook_code is None
        await client.aclose()

    _run(_scenario())


def test_hook_code_backfill_on_production_and_refusal_after_board_tid():
    """补号：没上板的单可以补（段头/标题/产出清单三处编号是导出时现拼的，补了就生效）；
    已经上了板的**拒绝**——板面任务名与回收对账都按当时的号钉死，这里改一下就对不上账。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1)
        pid = listed[0]["id"]
        assert listed[0]["hook_code"] is None, listed

        r = await _park(client, ho, [{"production_id": pid, "hook_code": "7n0k6"}])
        assert r.status_code == 200 and r.json()["production_filled"] == 1, r.text
        prow = await _row_of(AssetProduction, pid)
        assert prow.hook_code == "7N0K6", prow.hook_code

        # 交付文本当场带上了号（补号的意义就在这：导出/投板用的就是这个字段）
        exp = await client.get(f"/api/assets/productions/export?ids={pid}&format=txt", headers=ho)
        assert exp.status_code == 200, exp.text
        assert "=== 7N0K6 ===" in exp.json()["export_text"], exp.json()["export_text"][:200]

        # 同态：再钉一次不报错也不重复写审计
        same = await _park(client, ho, [{"production_id": pid, "hook_code": "7N0K6"}])
        assert same.json()["production_filled"] == 0, same.json()
        assert same.json()["skipped"][0]["reason"].startswith("同态幂等"), same.json()

        # 上板之后（tid 已钉）→ 拒绝改动
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetProduction, uuid.UUID(pid))
            row.board_tid = "T777"
            await s.commit()
        refuse = await _park(client, ho, [{"production_id": pid, "hook_code": "7N0K7"}])
        assert refuse.json()["ok"] is False, refuse.json()
        assert "已经投上后台任务板" in refuse.json()["conflicts"][0]["reason"], refuse.json()
        assert (await _row_of(AssetProduction, pid)).hook_code == "7N0K6"

        # 清空也走同一道闸：上板的号清不得
        clear = await _park(client, ho, [{"production_id": pid, "hook_code": None}])
        assert clear.json()["ok"] is False, clear.json()
        assert (await _row_of(AssetProduction, pid)).hook_code == "7N0K6"
        await client.aclose()

    _run(_scenario())


def test_produce_clears_stale_parked_code_and_says_so_instead_of_blocking():
    """预取位里躺着一个已经用过的号（陈旧数据）→ 当场清空＋点名，这批照常开单。

    正常路径走不出这个状态（钉号口自己拦、用完即清），所以这里直接写库造脏数据。

    2026-11-11 评审（业务席 P1）把口径从「整批 400 拒开」改成「清位＋往下走」，理由：
    一线拿着一条死号只能手工清位重来，而**同批其余几十条**明明能开单，被一条脏数据一起卡住；
    脏号清掉后这条文案就退化成普通的「缺号」——那条路本来就有兜底（预取池／代取／手工填）。
    判据因此是三条：①不拦（200＋建单）；②号被点名（不能静悄悄换个号就投出去）；
    ③预取位**必须真的清掉**（留着下次还是撞）——原版反过来要求「不许清」，那是配 400 的口径。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        _aid, _sid, _listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0F1"])
        asset_id, sid = await _approve_one(client, h, url=DOUYIN_3)
        async with dbmod.async_session_factory() as s:
            row = await s.get(AssetSummary, uuid.UUID(sid))
            row.hook_code = "7C0F1"   # 这个号已经在别人那张单上
            await s.commit()
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce",
                                     json={"summary_ids": [sid], "n": 1,
                                           "recommended_title_count": 1}, headers=ho)
        assert made.status_code == 200, made.text
        body = made.json()
        assert body["created"] == 1, body
        note = body["results"][0].get("note") or ""
        assert "7C0F1" in note and "已被" in note and "自动清空" in note, note
        # 批次级警告跟着说一句「这批缺号」：清位之后这条文案就是普通缺号，
        # 界面只读 results[].note 的话，运营看不到「还得回去取号」这一步。
        assert any("缺五位钩子编号" in w for w in body["warnings"]), body["warnings"]
        # 单子上绝不能带着这个脏号投出去（顶槽已被清位，缺号兜底也不该把它捡回来）
        listed = (await client.get(f"/api/assets/productions?asset_id={asset_id}", headers=ho)).json()["items"]
        mine = [p for p in listed if p["id"] in {x for x in body["production_ids"]}]
        assert mine and all(p["hook_code"] != "7C0F1" for p in mine), mine
        assert (await _row_of(AssetSummary, sid)).hook_code is None, "脏号当场清位，别留给下一次"
        # 另一支「同一个号同时钉在别人文案的预取位上」没在这里造：0068 给
        # asset_summaries.hook_code 加了部分唯一索引（uq_asset_summaries_hook_code），
        # 两条文案挂同一个号在**建表层面**就不成立了，那段代码只剩现网索引没回填成功时的兜底，
        # 想钉它得先把索引拆掉——那测的是自己搭的现场，不是产品行为。
        await client.aclose()

    _run(_scenario())


# ────────────────────────────────────────────────────────────────────
# 批 O（11-09 深夜）：新文案自动预取编号（用户口径「以后的新文案也自动预取吧」）
#   ＋ 号池不做限制（「那个号池不要做限制了。现在耗池，先不用做限制」）
# ────────────────────────────────────────────────────────────────────

_TAKE_STUB = '''
import pathlib
import sys

path, n = pathlib.Path(sys.argv[1]), int(sys.argv[2])
if n > 50:  # 与 hook_id.py 的 TAKE_MAX=50 同一道墙：超了整枪失败、一个号都不发
    print("一次最多发 50 个号", file=sys.stderr)
    sys.exit(2)
seen = int(path.read_text()) if path.exists() else 0
if FAIL_AFTER and seen >= 50:  # 第二枪模拟"号池当天发完了"
    print("号池今天发完了", file=sys.stderr)
    sys.exit(3)
path.write_text(str(seen + n))
for i in range(seen, seen + n):
    print(f"8P{i:03X}")
'''


def _fake_take_script(fail_after=None):
    """把取号脚本换成真子进程替身：每枪最多发 50 个、按台账文件递增、可指定第二枪起失败。

    为什么要真跑 subprocess 而不是 mock 函数：要钉的是**分块**这件事——
    `hook_id.py` 一次最多发 50 个（现网 88 个号就是分 50＋38 两枪取的），
    mock 掉取号函数就等于把要验的那段代码一起 mock 掉了。
    """
    dirpath = Path(tempfile.mkdtemp(prefix="take-stub-"))
    atexit.register(shutil.rmtree, dirpath, ignore_errors=True)
    ledger = dirpath / "ledger"
    script = dirpath / "stub_take.py"
    script.write_text(
        _TAKE_STUB.replace("FAIL_AFTER", repr(bool(fail_after))), encoding="utf-8"
    )
    return f"{sys.executable} {script} {ledger}", ledger


def _take_stub(codes, err=None, discarded=None):
    """取号底层替身（只测调用次数与结果，不真跑脚本）。

    2026-11-11 评审后 `_take_hook_codes` 签名是三元组 `(codes, discarded, err)`——
    超发丢弃的号已在共享台账烧掉，调用方要拿去写审计，替身必须照形状回。
    """
    calls = []

    async def _fake(count):
        calls.append(int(count))
        return list(codes)[: int(count)], list(discarded or []), err

    return _fake, calls


def test_auto_park_hook_codes_on_import_copy():
    """贴文案导入的当场自动挂预取编号：一条一枪不现实，整批只跑一次取号。

    钉四件事：①号挂在新建的 `asset_summaries.hook_code` 上（开单时自动顶进缺号槽位，
    批 N 那套消费逻辑不用改一行）；②整批只调一次取号（86 条各调一次＝86 倍失败面）；
    ③留痕与手工钉号同一动作名、靠 `source` 分得开；④响应里说清预取了几个。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        fake, calls = _take_stub(["8PZZ1", "8PZZ2", "8PZZ3"])
        good1 = "她替姐姐嫁的第二天，新郎出现在她姐的婚礼上，当着两家长辈问这婚到底算谁的"
        good2 = "总裁摘下手表坐在塑料凳上吃泡面，秘书问他为什么放着办公室的沙发不坐"
        good3 = "婆婆把房产证摔在饭桌上，儿媳妇当场没说话，第二天带着孩子回了娘家"
        with patch("app.api.assets._take_hook_codes", fake):
            r = await client.post(
                "/api/assets/summaries/import-copy",
                json={"batch_name": "批 O 自动预取", "texts": [good1, good2, good3]},
                headers=hm,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 3, body
        assert calls == [3], f"整批一次取号，不在逐条循环里取：{calls}"
        assert body["hook_codes"]["parked"] == 3, body["hook_codes"]
        assert "已自动预取 3 个编号" in body["message"], body["message"]
        # 回体里的 summary_id 是**给人拿去查库的主键**：`summary.id` 由 SQLAlchemy 在
        # INSERT 那一刻才生成，循环最后一条后面再没有 flush 点 → 不显式 flush 就是
        # 字符串 "None"（11-09 现网冒烟实测到，界面今天没读这个字段所以没炸）。
        got_ids = [it["summary_id"] for it in body["items"]]
        assert all(len(u or "") == 36 for u in got_ids), body["items"]
        assert len(set(got_ids)) == 3, got_ids

        rows = {str(x.id): x for x in await _rows(AssetSummary)}
        assert set(got_ids) <= set(rows), "回体报的 id 必须真在库里（不是 None 的字符串形式）"
        assert {x.hook_code for x in rows.values()} == {"8PZZ1", "8PZZ2", "8PZZ3"}, rows
        # ③ 审计：与手工钉号同动作名，source 分得开（查账要能认出"这是系统自动挂的"）
        logs = await _rows(AuditLog, AuditLog.action == "asset.hook_code.park")
        assert len(logs) == 1, logs
        assert logs[0].after["source"] == "auto_park:import_copy", logs[0].after
        assert len(logs[0].after["summaries"]) == 3, logs[0].after

        # ④ 预取号在文案列表口可见（审核台那个紫色「已备号」用的就是这一列）
        listed = (await client.get(
            f"/api/assets/summaries?batch_id={body['batch_id']}", headers=h["operator"])).json()
        assert {i["hook_code"] for i in listed["items"]} == {"8PZZ1", "8PZZ2", "8PZZ3"}, listed["items"]

        # 消费闭环：开单不传号也带上号（批 N 的 parked_code 那套），预取位当场清空
        sid = listed["items"][0]["id"]
        asset_id = listed["items"][0]["asset_id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=h["operator"])
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce",
                                     json={"summary_ids": [sid], "n": 1, "async_mode": False},
                                     headers=h["operator"])
        assert made.status_code == 200, made.text
        prod = (await client.get(f"/api/assets/productions?asset_id={asset_id}",
                                 headers=h["operator"])).json()["items"]
        parked_code = listed["items"][0]["hook_code"]
        assert [p["hook_code"] for p in prod] == [parked_code], prod
        assert (await _row_of(AssetSummary, sid)).hook_code is None, "顶上即清空"
        await client.aclose()

    _run(_scenario())


def test_auto_park_is_fail_soft_and_never_blocks_the_import():
    """取不到号**不许**把导入带崩：号是外部动作（脚本没配、台账锁不上），稿是人写的。

    这条钉子防的是"自动预取"变成"自动前置条件"——那等于把没配取号命令的机器上的
    导入功能整体下线。同时钉反面：真一个号都没挂上时**不写审计**（同批 N 的判据，
    审计的价值在变化点，不在调用点）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        before_audit = await _count(AuditLog)
        fake, calls = _take_stub([], err="未配置自动取号命令（ASSET_HOOK_ID_CMD）")
        good1 = "她替姐姐嫁的第二天，新郎出现在她姐的婚礼上，当着两家长辈问这婚到底算谁的"
        with patch("app.api.assets._take_hook_codes", fake):
            r = await client.post(
                "/api/assets/summaries/import-copy",
                json={"batch_name": "取号坏了也要进", "texts": [good1]}, headers=hm,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1, body
        assert calls == [1]
        assert body["hook_codes"]["parked"] == 0, body["hook_codes"]
        assert body["hook_codes"]["reason"] == "未配置自动取号命令（ASSET_HOOK_ID_CMD）", body
        assert "没预取到编号" in body["message"] and "手工填" in body["message"], body["message"]
        assert (await _rows(AssetSummary))[0].hook_code is None
        assert await _count(AuditLog) == before_audit, "一个号没挂上就不该留钉号审计"

        # 旋钮关掉：连脚本都不该碰（现网想停掉自动预取时改一行 env 就够）
        old = settings.ASSET_AUTO_PARK_HOOK_CODES
        settings.ASSET_AUTO_PARK_HOOK_CODES = False
        try:
            fake2, calls2 = _take_stub(["8PZZ9"])
            with patch("app.api.assets._take_hook_codes", fake2):
                off = await client.post(
                    "/api/assets/summaries/import-copy",
                    json={"batch_name": "关掉自动预取", "texts": [good1]}, headers=hm)
            assert off.status_code == 200, off.text
            assert calls2 == [], "旋钮关了还去跑脚本＝假旋钮"
            assert off.json()["hook_codes"]["attempted"] == 0, off.json()["hook_codes"]
            assert (await _rows(AssetSummary, AssetSummary.text == good1))[0].hook_code is None
        finally:
            settings.ASSET_AUTO_PARK_HOOK_CODES = old
        await client.aclose()

    _run(_scenario())


def test_auto_park_on_paired_import_parks_the_batch_and_reports_it():
    """成稿配对导入（86 条那种大批）也自动预取：一次导入一枪脚本，响应里点名预取了几个。

    这批正是自动预取最该管住的入口——一线就是从 NAS 成稿目录这么进的。
    同时钉「只给缺号的行取号」：`hook_copy` 缺项不建候选，也就不该为它烧号。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        manifest = {
            "batch_name": "批 O 配对",
            "items": [
                {"video": "A.mp4", "hook_copy": CANDIDATES[0]["text"]},
                {"video": "B.mp4", "hook_copy": CANDIDATES[1]["text"]},
                {"video": "C.mp4"},  # 没文案 → 不建候选 → 不该为它取号
            ],
        }
        fake, calls = _take_stub(["8PZZ1", "8PZZ2"])
        with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
             patch("app.api.assets._probe_duration", AsyncMock(return_value=9.0)), \
             patch("app.api.assets._probe_image_size", AsyncMock(return_value=(720, 1280))), \
             patch("app.api.assets._take_hook_codes", fake):
            r = await client.post(
                "/api/assets/import/paired",
                files=_paired_files([(x["video"], VIDEO_BYTES, "video/mp4") for x in manifest["items"]]),
                data={"manifest": json.dumps(manifest, ensure_ascii=False)}, headers=hm,
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["created"] == 3, body
        assert calls == [2], f"两条候选取两个号，第三条没文案不该占号：{calls}"
        assert body["hook_codes"]["parked"] == 2, body["hook_codes"]
        assert "已自动预取 2 个编号" in body["message"], body["message"]
        sums = await _rows(AssetSummary)
        assert len(sums) == 2 and {x.hook_code for x in sums} == {"8PZZ1", "8PZZ2"}, sums
        await client.aclose()

    _run(_scenario())


def test_auto_park_on_generate_only_parks_recommended_and_never_reburns():
    """出文案口：多候选只给**推荐条**挂号；已有候选的批次重出不许再烧号。

    两条判据各自的理由：
    - 一钩一号、发了即烧：三条候选各挂一个号＝一条文案烧掉三个号，280/日的号池当废纸烧；
    - 「已有候选」是早退路径（不建新行），为它跑一枪脚本等于凭空发号、白占台账。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, _ = await _make_ready_asset(client, hm)
        fake, calls = _take_stub(["8PZZ1", "8PZZ2", "8PZZ3"])
        with patch("app.api.assets._call_autoclip", _fake_autoclip()), \
             patch("app.api.assets._take_hook_codes", fake):
            first = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "count": 2, "async_mode": False}, headers=hm)
        assert first.status_code == 200, first.text
        assert first.json()["hook_codes"]["parked"] == 1, first.json()["hook_codes"]
        assert calls == [1], f"整批一次取号、只要推荐条那一个：{calls}"
        rows = await _rows(AssetSummary)
        assert len(rows) == 2, rows
        rec = [x for x in rows if x.is_recommended]
        assert len(rec) == 1 and rec[0].hook_code == "8PZZ1", \
            [(x.is_recommended, x.hook_code) for x in rows]
        assert [x.hook_code for x in rows if not x.is_recommended] == [None], rows

        # 同素材同条数再点一次「出钩子文案」：早退（不建新行）→ 一枪都不该打
        with patch("app.api.assets._call_autoclip", _fake_autoclip()), \
             patch("app.api.assets._take_hook_codes", fake):
            again = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "count": 2, "async_mode": False}, headers=hm)
        assert again.status_code == 200, again.text
        assert again.json()["results"][0]["created"] == 0, again.json()["results"]
        assert again.json()["hook_codes"]["attempted"] == 0, again.json()["hook_codes"]
        assert calls == [1], f"没建新行就不该再烧号：{calls}"
        after = {str(x.id): x.hook_code for x in await _rows(AssetSummary)}
        assert after == {str(x.id): x.hook_code for x in rows}, "重出不许顶掉已有的预取位"
        await client.aclose()

    _run(_scenario())


def test_take_hook_codes_chunks_past_the_script_max_and_keeps_issued_numbers():
    """取号按 50 一块分枪，且**发了即烧**：后面一枪坏了也不把已经到手的号扔掉。

    `hook_id.py` 有 TAKE_MAX=50（现网 88 个号就是分 50＋38 两枪取的）。两种错法都要防：
    - 整批一口要 85 个 → 脚本 rc=2，一个号都拿不到（这就是当初界面「代取」502 的真相）；
    - 分块了但把"第一块已发出去的号"随异常丢掉 → 台账上号已被记走，白白作废。
    """
    _run(_bootstrap())

    async def _scenario():
        cmd, ledger = _fake_take_script()
        old = settings.ASSET_HOOK_ID_CMD
        settings.ASSET_HOOK_ID_CMD = cmd
        try:
            codes, discarded, err = await assets_api._take_hook_codes(85)
            assert err is None, err
            assert discarded == [], "按 50＋35 分枪正好要满 85，不该有超发"
            assert len(codes) == 85 and len(set(codes)) == 85, codes[:5]
            assert ledger.read_text() == "85", "两块分别真跑了 50＋35 枪"
        finally:
            settings.ASSET_HOOK_ID_CMD = old

        # 第二枪起失败：第一枪的 50 个号必须照原样交回去（发了即烧，扔掉等于白烧）
        bad, ledger2 = _fake_take_script(fail_after=True)
        settings.ASSET_HOOK_ID_CMD = bad
        try:
            codes, discarded, err = await assets_api._take_hook_codes(80)
            assert len(codes) == 50, codes
            assert discarded == [], err
            assert err and "第 2 枪" in err, err
            assert ledger2.read_text() == "50", ledger2.read_text()
        finally:
            settings.ASSET_HOOK_ID_CMD = old

        # 界面口现在能一次要 80 个（原来 le=50 会把 85 条那种批次挡在门外）
        client, h = await _client_and_headers()
        ho = h["operator"]
        cmd3, _ = _fake_take_script()
        settings.ASSET_HOOK_ID_CMD = cmd3
        try:
            r = await client.post("/api/assets/hook-codes/take?count=80", headers=ho)
            assert r.status_code == 200, r.text
            assert len(r.json()["codes"]) == 80, r.json()
        finally:
            settings.ASSET_HOOK_ID_CMD = old
        # 没配命令：仍回 501 那句原话（前端提示走手工粘贴）——别被本机 env 里的真命令带跑
        settings.ASSET_HOOK_ID_CMD = ""
        try:
            empty = await client.post("/api/assets/hook-codes/take?count=3", headers=ho)
            assert empty.status_code == 501 and "手工粘贴" in empty.json()["detail"], empty.json()
        finally:
            settings.ASSET_HOOK_ID_CMD = old
        await client.aclose()

    _run(_scenario())


def test_auto_park_never_double_books_a_code_already_used():
    """取回来的号若已被库里的单/别的预取位占着 → 不钉，并如实报数（一钩一号）。

    正常路径走不出这个状态（脚本自己不发重复号），所以脚本替身故意把「已经在单上的号」
    混进返回值：判据是「宁可这条文案没号，也不能让同一个号被两张单投出去」。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        _aid, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["8PZZ1"])
        assert listed[0]["hook_code"] == "8PZZ1", listed

        good1 = "她替姐姐嫁的第二天，新郎出现在她姐的婚礼上，当着两家长辈问这婚到底算谁的"
        good2 = "总裁摘下手表坐在塑料凳上吃泡面，秘书问他为什么放着办公室的沙发不坐"
        fake, _calls = _take_stub(["8PZZ1", "8PZZ2"])
        with patch("app.api.assets._take_hook_codes", fake):
            r = await client.post(
                "/api/assets/summaries/import-copy",
                json={"batch_name": "撞号", "texts": [good1, good2]}, headers=hm)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hook_codes"]["parked"] == 1, body["hook_codes"]
        assert body["hook_codes"]["codes"] == ["8PZZ2"], body["hook_codes"]
        assert "8PZZ1" in body["hook_codes"]["collisions"], body["hook_codes"]
        assert "没全配上" in body["message"], body["message"]
        parked = sorted(x.hook_code for x in await _rows(AssetSummary, AssetSummary.hook_code.isnot(None)))
        assert parked == ["8PZZ2"], parked
        # 撞号来源还在原位：8PZZ1 已经烧在那张单上（预取不许把已开单的号抢回来）
        assert [p.hook_code for p in await _rows(AssetProduction)] == ["8PZZ1"]
        # 没挂上号那条照常能开单：手工填或界面代取是既有旁路，预取只是省事不是门槛
        sid = next(str(x.id) for x in await _rows(AssetSummary) if not x.hook_code)
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            made = await client.post("/api/assets/produce",
                                     json={"summary_ids": [sid], "n": 1, "async_mode": False},
                                     headers=ho)
        assert made.status_code == 200, made.text
        assert made.json()["created"] == 1, made.json()
        await client.aclose()

    _run(_scenario())


ELEMENT_PROMPT_10S = (
    "生成【现言豪门】仿真人写实短剧，参考【《一碗疙瘩汤成少爷后妈》】剧情，"
    "输入素材为 AI 多视图角色设定卡。\n"
    "时长 10 秒，9:16 竖屏，模拟手机竖屏实拍短剧影视质感。\n"
    "剧情：老破小客厅里，婆婆把一只橘猫摔在地上，媳妇抱着橘猫退到阳台。\n"
    "时间轴：0-3 秒强冲突钩子，3-7 秒推进矛盾，7-10 秒情绪定格收束留悬念。\n"
    "负面约束：禁止五官崩坏变脸。 9:16，10s"
)


def test_prompt_elements_catalog_extract_and_apply_api():
    """投产前可替换元素四个口（批 M，11-10，用户口径「确认投产之前要能换元素」）。

    要验的：
    1. material 能读字典、能抽元素、能组稿，但**不能改字典**（写字只 admin）；
    2. 写法编不过／没捕获组／键重复／认法拼错 → 400，**失败请求不写审计**；
    3. admin 存一行 → 生效表立刻能看见（出厂那 16 行原型参数仍在），下一次抽元素就用新表；
    4. 抽元素给出候选池与出现次数（"裂变几种选择"那份数据）；
    5. 组稿时 pattern 槽位**只动命中处**（时长 10→15 不许把⑦时间轴和⑬行尾一起改掉）；
    6. 换上拦级风险词时 apply 当场报 `would_dispatch_block`（和投板那道闸同一判据）；
    7. 全程纯文本进出：不动 `system_config` 以外的任何行，更不动库里的 `prompt_text`。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.api import assets as assets_api  # noqa: F401  （模块级引用，确认口已挂上）
        from app.services import asset_prompt_elements as pe

        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]

        # ① 读：全员能读，看得到生效表／出厂表／能不能改
        r = await client.get("/api/assets/prompt-elements", headers=hm)
        assert r.status_code == 200, r.text
        data = r.json()
        eff_keys = {s["key"] for s in data["effective"]}
        # 出厂表＝用户那份《钩子模版换皮参数设定.docx》里 A–F 的参数项（16 行）。
        # 11-10 用户拍板：`genre`（题材标签）／`drama_name`（剧名）是我自己从投产模板 ① 行加的，
        # 参考文件里没有 → **默认字典里不许有这两行**（要改那几个字走「自定义替换」）。
        assert {"a_animal", "a_scene", "a_speech", "f_plight"} <= eff_keys, sorted(eff_keys)
        assert not ({"genre", "drama_name"} & eff_keys), sorted(eff_keys)
        assert data["defaults"] and data["can_edit"] is False
        r = await client.get("/api/assets/prompt-elements", headers=ha)
        assert r.json()["can_edit"] is True
        # material 改字典 → 403（字典决定投出去的是什么）
        r = await client.put("/api/assets/prompt-elements",
                             json={"slots": [{"key": "scene", "pool": ["出租屋"]}], "inherit": True},
                             headers=hm)
        assert r.status_code == 403, r.text

        # ② 四种脏写法全 400，而且一条审计都不许留
        bad_calls = [
            {"slots": [{"key": "bad_rx", "mode": "pattern", "pattern": "([a-z"}]},
            {"slots": [{"key": "no_group", "mode": "pattern", "pattern": r"生成【[^】]{1,12}】"}]},
            {"slots": [{"key": "dup", "pool": ["a"]}, {"key": "dup", "pool": ["b"]}]},
            {"slots": [{"key": "", "pool": ["a"]}]},
            {"slots": [{"key": "weird", "mode": "fuzzy", "pool": ["a"]}]},
        ]
        for payload in bad_calls:
            r = await client.put("/api/assets/prompt-elements",
                                 json={**payload, "inherit": True}, headers=ha)
            assert r.status_code == 400, f"{payload} 该被拒：{r.text}"
        assert await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.update") == [], \
            "失败的改字典请求不该留痕（登录本身也写审计，所以只数这一类）"

        # ③ admin 存三行（含一个限定原型的槽位）→ 生效表里出厂那 16 行仍在
        r = await client.put(
            "/api/assets/prompt-elements",
            json={
                "inherit": True,
                "slots": [
                    {"key": "scene", "label": "场景", "pool": ["老破小客厅", "出租屋客厅", "医院走廊"],
                     "note": "③剧情里的地点"},
                    {"key": "animal", "label": "出场的动物", "anchors": ["橘猫", "猫"],
                     "pool": ["橘猫", "中华田园犬", "鹦鹉"]},
                    {"key": "duration", "label": "时长（秒）", "mode": "pattern",
                     "pattern": r"时长 (\d+) 秒", "pool": ["10", "15"], "categories": ["悬念"]},
                ],
            },
            headers=ha,
        )
        assert r.status_code == 200, r.text
        eff_keys = {s["key"] for s in r.json()["effective"]}
        assert {"scene", "animal", "duration", "a_animal", "a_scene"} <= eff_keys, r.json()["effective"]
        audits = await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.update")
        assert len(audits) == 1 and audits[0].operator_id is not None
        assert not audits[0].before, "第一次配之前没有覆盖行，before 该是空"
        assert len(audits[0].after["slots"]) == 3
        assert any("只走这一次投递" in n for n in r.json()["notes"]), r.json()["notes"]

        # ④ 抽元素：候选池＋出现次数（"裂变几种选择"就是这份）
        r = await client.post("/api/assets/prompt-elements/extract",
                              json={"texts": {"p1": ELEMENT_PROMPT_10S}}, headers=hm)
        assert r.status_code == 200, r.text
        got = {s["key"]: s for s in r.json()["items"]["p1"]}
        assert {"scene", "animal"} <= set(got), got.keys()
        assert got["scene"]["current"] == "老破小客厅"
        assert got["animal"]["occurrences"] == [{"value": "橘猫", "count": 2}]
        assert got["animal"]["pool"] == ["橘猫", "中华田园犬", "鹦鹉"]
        assert got["animal"]["custom"] is True
        assert "duration" not in got, "没报原型时限定原型的槽位不该出现"
        # ① 行那两个位置（题材标签／剧名）默认字典里已按用户口径去掉 → 不再认成元素
        assert not ({"genre", "drama_name"} & set(got)), got.keys()
        # 认出来的元素要带回**命中处那一行原文**，界面上好做「改前／改后」对照
        assert got["animal"]["context"].startswith("剧情："), got["animal"]
        assert "橘猫" in got["animal"]["context"]

        # 4b 报了原型 → 限定该原型的槽位这才出现
        r = await client.post("/api/assets/prompt-elements/extract",
                              json={"texts": {"p1": ELEMENT_PROMPT_10S}, "category": "悬念"}, headers=hm)
        assert "duration" in {s["key"] for s in r.json()["items"]["p1"]}, r.text
        # 4c 一次给太多条 → 400 白话
        r = await client.post("/api/assets/prompt-elements/extract",
                              json={"texts": {f"p{i}": ELEMENT_PROMPT_10S
                                              for i in range(assets_api._MAX_EXTRACT_ITEMS + 1)}},
                              headers=hm)
        assert r.status_code == 400 and "分批" in r.text, r.text

        # ⑤ 组稿：literal 全处换、pattern 只动命中处
        r = await client.post(
            "/api/assets/prompt-elements/apply",
            json={"text": ELEMENT_PROMPT_10S,
                  "edits": [{"key": "animal", "old": "橘猫", "new": "中华田园犬"},
                            {"key": "duration", "old": "10", "new": "15"}]},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rep = {x["key"]: x for x in body["replaced"]}
        assert rep["animal"]["count"] == 2 and rep["duration"]["count"] == 1, body["replaced"]
        assert "中华田园犬" in body["text"] and "橘猫" not in body["text"]
        assert "时长 15 秒" in body["text"]
        assert "7-10 秒" in body["text"], "⑦时间轴不许被顺手改掉（模板自查第③条硬要求）"
        assert "9:16，10s" in body["text"], "⑬行尾同理"
        assert body["risk"]["block"] == [] and body["would_dispatch_block"] is False

        # 5b 没找到的那一行要说出来，不许静默假装换上了
        r = await client.post("/api/assets/prompt-elements/apply",
                              json={"text": ELEMENT_PROMPT_10S,
                                    "edits": [{"key": "scene", "old": "幼儿园", "new": "公司前台"},
                                              {"key": "scene", "old": "老破小客厅", "new": "出租屋客厅"}]},
                              headers=hm)
        notes = r.json()["notes"]
        rep = {x["from"]: x["count"] for x in r.json()["replaced"]}
        assert rep["幼儿园"] == 0 and rep["老破小客厅"] == 1
        assert any("幼儿园" in n and "没改" in n for n in notes), notes
        assert "出租屋客厅" in r.json()["text"]

        # 5c 自定义替换（字典里没这槽位）照样走得通
        r = await client.post("/api/assets/prompt-elements/apply",
                              json={"text": ELEMENT_PROMPT_10S,
                                    "edits": [{"key": "", "old": "阳台", "new": "楼道口"}]}, headers=hm)
        assert "退到楼道口" in r.json()["text"], r.text

        # ⑥ 换上拦级风险词 → 与投板那道闸同一判据，当场就说会被拦
        r = await client.post("/api/assets/prompt-elements/apply",
                              json={"text": ELEMENT_PROMPT_10S,
                                    "edits": [{"key": "animal", "old": "橘猫", "new": "砍死"}]}, headers=hm)
        body = r.json()
        assert body["would_dispatch_block"] is True, body
        assert [w["word"] for w in body["risk"]["block"]] == ["砍死"], body["risk"]

        # ⑦ 纯文本进出：除了③那一次改字典，抽元素/组稿一次都没往库里写
        assert len(await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.update")) == 1
        async with dbmod.async_session_factory() as s:
            row = await s.get(SystemConfig, pe.PROMPT_ELEMENTS_CONFIG_KEY)
        assert row is not None and len(row.value["slots"]) == 3
        assert await _count(AssetProduction) == 0 and await _count(AssetSummary) == 0
        assert await _count(AssetItem) == 0, "抽元素/组稿不该造任何素材或生产单"
        await client.aclose()

    _run(_scenario())


GUESS_TEXT_10S = "\n".join([
    "【第 1 段 · 建议 10 秒 · 本钩共 6 条 · 编号 8PZXGB1】",
    "钩子原文：黄皮子蹲在院门口说了句别开门",
    "生成【都市脑洞】仿真人写实短剧，参考【《黄皮子拦门》】剧情，"
    "输入素材为 AI 多视图角色设定卡。",
    "时长 10 秒，9:16 竖屏，模拟手机竖屏实拍短剧影视质感。",
    "剧情：【前3秒】出租屋院门口，一只黄皮子拦住门，嘴里念叨「别开门，外头人不对」。",
    "【后7秒】他开门看了一眼，门外空无一人，门槛上放着个布包。",
    "镜头：门口正反打，屋内用侧四十五度中近景。",
    "负面约束：禁止五官崩坏变脸。 9:16，10s",
])


def test_prompt_elements_guess_values_api():
    """11-10「帮我提炼原值」（用户口径「为什么都是稿子里没认出原值？能不能再将它们提炼一下」）。

    这一口与 0 元的 `extract` 唯一的本质区别是**它会调模型**，所以判据全在"敢不敢信它"上：
    1. 模型抄回来的串只有**逐字出现在这一篇稿子的可动区间**才收；编的、落在保护行的、
       字典里没这个键的、同键回了两条的——一律丢弃，且每条在 `dropped` 里说成人话
       （不说人话就等于"没显示＝没找到"，人会白等）；
    2. 花了钱就要留痕：成功一条 `asset.prompt_elements.guess_values` 审计；
       autoclip 挂了（502）时**一条都不许留**，也不许造出半行数据；
    3. 上限：稿子篇数／总字数超限 400，没稿子 400，字典空 400（都是"没得提炼"，不是崩）；
    4. 只读：不改字典、不动任何稿件，库里那张 `system_config` 只有用例自己那一次 PUT。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]

        # 配两行：一行 literal 词表外（extract 认不出）、一行 manual（按设计永不自动认）
        r = await client.put(
            "/api/assets/prompt-elements",
            json={
                "inherit": True,
                "slots": [
                    {"key": "scene", "label": "场景", "pool": ["老破小客厅", "出租屋客厅"],
                     "note": "③剧情里的地点"},
                    {"key": "speech", "label": "动物说的话", "mode": "manual",
                     "note": "⑤它开口那句，稿子里多半是间接转述"},
                ],
            },
            headers=ha,
        )
        assert r.status_code == 200, r.text

        items = [
            # ① 真在稿子里（剧情行那句台词）→ 该收
            {"id": "p1", "key": "speech", "value": "别开门，外头人不对"},
            # ② 只出现在 ① 生成【…》 保护行里（模型把剧名当场景抄回来了）→ 该丢
            {"id": "p1", "key": "scene", "value": "黄皮子拦门"},
            # ③ 稿子里根本没有这串字（模型编的）→ 该丢
            {"id": "p1", "key": "scene", "value": "村口老槐树下"},
            # ④ 字典里没这个键 → 该丢
            {"id": "p1", "key": "weather", "value": "出租屋院门口"},
            # ⑤ 同键第二条 → 只留第一条
            {"id": "p1", "key": "speech", "value": "他开门看了一眼"},
            # ⑥ 没提交过的稿子编号 → 整条不算，notes 里点名
            {"id": "p9", "key": "speech", "value": "门外空无一人"},
        ]

        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_items=items)) as call:
            r = await client.post(
                "/api/assets/prompt-elements/guess-values",
                json={"texts": {"p1": GUESS_TEXT_10S}},
                headers=hm,
            )
        assert r.status_code == 200, r.text
        body = r.json()

        # ① 只收下"逐字出现在可动区间"的那一条，其余全丢
        assert body["values"] == {"p1": {"speech": "别开门，外头人不对"}}, body["values"]
        assert {"scene", "speech"} <= set(body["labels"]), body["labels"]
        # speech 是 manual 行——它进得来才证明这条路真的补的是「按设计永不自动认」那几行
        assert body["slot_count"] >= 2 and body["text_count"] == 1

        joined = "\n".join(body["dropped"])
        assert "黄皮子拦门" in joined and "不动的那两行" in joined, body["dropped"]   # ②只在保护行里
        assert "村口老槐树下" in joined and "找不到" in joined, body["dropped"]        # ③模型编的
        assert "weather" in joined and "没配" in joined, body["dropped"]                # ④没这个参数项
        assert "回了两条" in joined, body["dropped"]                                     # ⑤第二条
        assert len(body["dropped"]) == 4, body["dropped"]

        notes = "\n".join(body["notes"])
        assert "模型" in notes and "钱" in notes, body["notes"]
        assert "p9" not in notes, "编号是内部键，不该原样甩给一线看"
        assert "没提交过" in notes, body["notes"]

        # 发出去的东西：稿子全文＋该型参数项（含 manual 行），且候选词表带着
        payload = call.call_args.args[1]
        assert payload["texts"] == [{"id": "p1", "text": GUESS_TEXT_10S}], payload["texts"]
        # 内部判据不许出本机：`skip_lines`／`mode` 只给校验用，发给模型的只有四个描述字段
        assert all(set(s) == {"key", "label", "note", "pool"} for s in payload["slots"]), payload["slots"]
        sent = {s["key"]: s for s in payload["slots"]}
        assert sent["speech"]["label"] == "动物说的话" and sent["scene"]["pool"][:1] == ["老破小客厅"]
        assert payload["max_retries"] == 1, "重试交给人再点一下，与出文案/展开同口径"

        # ② 花钱要留痕（text/slot 是**这一枪真问出去的量**，缓存命中的部分另记 cached_rows）
        audits = await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.guess_values")
        assert len(audits) == 1 and audits[0].operator_name == MATERIAL_USER, audits
        assert audits[0].after == {
            "text_count": 1, "slot_count": body["slot_count"], "filled_rows": 1,
            "dropped_count": len(body["dropped"]), "model": "fake-llm",
            "auto": False, "cached_rows": 0,
        }, audits[0].after

        # 模型挂了：502 原样传出去，且**不补一条审计**（没花钱的事不能留痕）
        # 必须带 `use_cache=false`：11-11 之后「问过但稿子里没有」也记进缓存，
        # 走到缓存全命中时这一枪根本不会发出去，502 也就无从谈起。
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_error="提炼服务没回话")):
            r = await client.post(
                "/api/assets/prompt-elements/guess-values",
                json={"texts": {"p1": GUESS_TEXT_10S}, "use_cache": False}, headers=hm,
            )
        assert r.status_code == 502 and "提炼服务没回话" in r.text, r.text
        assert len(await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.guess_values")) == 1

        # ③ 四道 400：没稿子／篇数超／字数超／字典空
        r = await client.post("/api/assets/prompt-elements/guess-values",
                              json={"texts": {}}, headers=hm)
        assert r.status_code == 400 and "没有稿子" in r.text, r.text
        r = await client.post(
            "/api/assets/prompt-elements/guess-values",
            json={"texts": {f"p{i}": GUESS_TEXT_10S for i in range(6)}}, headers=hm,
        )
        assert r.status_code == 400 and "分批" in r.text, r.text
        r = await client.post(
            "/api/assets/prompt-elements/guess-values",
            json={"texts": {"p1": GUESS_TEXT_10S + "补" * 13000}}, headers=hm,
        )
        assert r.status_code == 400 and "字" in r.text, r.text
        # 上限内的最大合法请求**不许**被误拦（12000 正好、5 篇正好）
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_items=[])) as call2:
            r = await client.post(
                "/api/assets/prompt-elements/guess-values",
                json={"texts": {f"p{i}": (GUESS_TEXT_10S + "补" * 1300)[:2400] for i in range(5)}},
                headers=hm,
            )
        assert r.status_code == 200, r.text
        assert r.json()["values"] == {}, "空 items 就该回空，不许凭空造值"
        assert call2.call_count == 1
        r = await client.put("/api/assets/prompt-elements", json={"slots": [], "inherit": False},
                             headers=ha)
        assert r.status_code == 200, r.text
        r = await client.post("/api/assets/prompt-elements/guess-values",
                              json={"texts": {"p1": GUESS_TEXT_10S}}, headers=hm)
        assert r.status_code == 400 and "参数项" in r.text, r.text

        # ④ 只读：全程没动过稿件，也没造素材/生产单
        assert await _count(AssetProduction) == 0 and await _count(AssetSummary) == 0
        assert await _count(AssetItem) == 0
        await client.aclose()

    _run(_scenario())


def test_prompt_elements_auto_guess_once_per_row_api():
    """批 Z（11-11 用户口径「你不能按照固定的词典去识别，你要调用大模型的能力去做这个事情」）：

    词表退成第一道免费粗筛，认不出的那几格**自动**问模型。这一枪从按钮变成了跟着开单屏跑的
    默认动作，所以四条判据必须钉死，否则就是"每次打开弹窗都在偷偷烧钱＋把开单这一屏带崩"：

    1. **同一篇稿子的同一格只花一次钱**：第二次同样请求 `paid=false`、一次模型都不打，
       填回来的值与第一次逐字相同（结果进 `asset_element_guesses`，键是正文指纹）；
    2. **已经认出的格子不会被重复问、也不会被覆盖**：`only_missing` 只把缺的那几格端给模型，
       模型顺手多回的那些格子（词表已经认出的）一律不进结果；
    3. **模型那一路炸了不许把开单带崩**（`auto=true`）：照常 200、`paid=false`、一条审计都不留、
       白话说明"这批仍按词表的认法"——人工点的那个按钮仍然把 502 原样红给人看（上面的用例钉的）；
    4. **旋钮关了只吃缓存**：`ASSET_ELEMENT_AUTO_GUESS=false` 时自动那一支一次模型都不打，
       但已经存着的原值照旧填回来（那一分钱已经花过，没理由不给）；
    5. **一次问不完就分批**（超上限不报 400）：剩下的下次打开还会补；
    6. **字典改了 → 陈旧缓存当场作废重问**：缓存存的是原串不是判据，读的时候按**当前**字典
       重过一遍逐字校验，过不了就删行（下次重新问），不能拿存下来那天的口径当今天的结论。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.config import settings
        from app.models.asset import AssetElementGuess
        from app.services import asset_prompt_elements as pesvc

        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]
        G = "/api/assets/prompt-elements/guess-values"

        async def _put_slots(skip: str | None = None, with_scene: bool = False):
            slot = {"key": "speech", "label": "动物说的话", "mode": "manual",
                    "note": "⑤它开口那句，稿子里多半是间接转述"}
            if skip is not None:
                slot["skip_lines"] = skip
            slots = [slot]
            if with_scene:
                # scene 是**字典里配了、这一枪却没问**的那一格（词表已经认出的那种）
                slots.insert(0, {"key": "scene", "label": "场景", "pool": ["老破小客厅"]})
            r = await client.put("/api/assets/prompt-elements",
                                 json={"inherit": False, "slots": slots}, headers=ha)
            assert r.status_code == 200, r.text

        items = [{"id": "p1", "key": "speech", "value": "别开门，外头人不对"}]

        # ── ① 第一次：花钱，且落一行缓存 ────────────────────────────────
        await _put_slots()
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(slots_items=items)) as c1:
            r = await client.post(G, json={"texts": {"p1": GUESS_TEXT_10S}, "auto": True},
                                  headers=hm)
        assert r.status_code == 200, r.text
        first = r.json()
        assert first["paid"] is True and c1.call_count == 1, first
        assert first["values"] == {"p1": {"speech": "别开门，外头人不对"}}, first["values"]
        assert first["from_model"] == {"p1": ["speech"]} and first["from_cache"] == {}
        rows = await _rows(AssetElementGuess)
        assert len(rows) == 1 and rows[0].slot_key == "speech", rows
        assert rows[0].body_hash == pesvc.body_fingerprint(GUESS_TEXT_10S)
        audits_1 = await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.guess_values")
        assert len(audits_1) == 1, audits_1

        # ── ② 第二次：一个字都没变 → 0 元、一次模型都不打、值照旧填回来 ──
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(slots_items=items)) as c2:
            r = await client.post(G, json={"texts": {"p1": GUESS_TEXT_10S}, "auto": True},
                                  headers=hm)
        assert r.status_code == 200, r.text
        second = r.json()
        assert c2.call_count == 0, "同一篇稿子同一格第二次还打模型＝每开一次弹窗烧一次钱"
        assert second["paid"] is False and second["values"] == first["values"], second
        assert second["from_cache"] == {"p1": ["speech"]} and second["from_model"] == {}
        assert await _count(AssetElementGuess) == 1
        assert len(await _rows(AuditLog,
                               AuditLog.action == "asset.prompt_elements.guess_values")) == 1, \
            "没花钱的事不许留痕"
        assert any("上一次抄回来" in n for n in second["notes"]), second["notes"]

        # ── ③ only_missing：词表已经认出的格子不重复问、也不被模型覆盖 ──
        # （`use_cache=false` 是这一枪要**真的**打到模型才看得出问了哪几格；
        #   speech 已经被 ①② 存进缓存了，不绕开缓存这一枪根本不会发出去。）
        await _put_slots(with_scene=True)
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_items=[
            {"id": "p1", "key": "speech", "value": "别开门，外头人不对"},
            {"id": "p1", "key": "scene", "value": "出租屋院门口"},   # 词表已经认出，模型多嘴
        ])) as c3:
            r = await client.post(
                G,
                json={"texts": {"p1": GUESS_TEXT_10S},
                      "only_missing": {"p1": ["speech"]}, "use_cache": False},
                headers=hm,
            )
        assert r.status_code == 200, r.text
        third = r.json()
        assert c3.call_count == 1
        assert {s["key"] for s in c3.call_args.args[1]["slots"]} == {"speech"}, \
            "只缺 speech 却把 scene 也端给模型＝白花一遍钱"
        assert third["values"] == {"p1": {"speech": "别开门，外头人不对"}}, third["values"]
        assert "scene" in third["labels"], third["labels"]  # 清单仍给全（界面要知道有几格）
        assert not any("没配的参数项" in d for d in third["dropped"]), \
            "字典里明明配了 scene，说它「没配」是假话，会让人白跑去改词表"

        # ── ④ 模型炸了（auto）：照常 200、不花钱、不留痕、说明是白话 ─────
        # 用一篇**没进过缓存**的稿子，否则缓存先兜住，这一枪根本不会打到模型
        other = GUESS_TEXT_10S + "\n【另一篇】门口那条黄狗又叫了两声。"
        audits_before = await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.guess_values")
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_error="提炼服务没回话")):
            r = await client.post(
                G, json={"texts": {"p8": other}, "auto": True}, headers=hm,
            )
        assert r.status_code == 200, r.text
        fourth = r.json()
        assert fourth["paid"] is False and fourth["values"] == {}, fourth
        assert any("没通" in n and "照常开单" in n for n in fourth["notes"]), fourth["notes"]
        assert len(await _rows(AuditLog,
                               AuditLog.action == "asset.prompt_elements.guess_values")) == \
            len(audits_before)
        # 人工点的那一下仍然要红（11-10 用例钉的 502）——兜错只兜自动那一支
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_error="提炼服务没回话")):
            r = await client.post(
                G, json={"texts": {"p8": other}}, headers=hm,
            )
        assert r.status_code == 502 and "提炼服务没回话" in r.text, r.text

        # ── ⑤ 旋钮关了：自动那一支只吃缓存，一次模型都不打 ──────────────
        old = settings.ASSET_ELEMENT_AUTO_GUESS
        settings.ASSET_ELEMENT_AUTO_GUESS = False
        try:
            with patch("app.api.assets._call_autoclip",
                       _fake_autoclip(slots_items=items)) as c5:
                r = await client.post(
                    G,
                    json={"texts": {"p1": GUESS_TEXT_10S, "p9": GUESS_TEXT_10S + "补一句"},
                          "auto": True},
                    headers=hm,
                )
            assert r.status_code == 200, r.text
            off = r.json()
            assert c5.call_count == 0, "旋钮关了还打模型＝关掉的是花钱不是关掉一句说明"
            assert off["paid"] is False
            assert off["values"].get("p1") == {"speech": "别开门，外头人不对"}, off["values"]
            assert any("ASSET_ELEMENT_AUTO_GUESS" in n for n in off["notes"]), off["notes"]
            # 关掉旋钮不影响人主动点：use_cache=false＋auto=false 照旧打模型
            with patch("app.api.assets._call_autoclip",
                       _fake_autoclip(slots_items=items)) as c5b:
                r = await client.post(
                    G, json={"texts": {"p1": GUESS_TEXT_10S}, "use_cache": False}, headers=hm,
                )
            assert r.status_code == 200 and c5b.call_count == 1, r.text
        finally:
            settings.ASSET_ELEMENT_AUTO_GUESS = old

        # ── ⑥ 超上限（auto）：不报 400，分批＋白话说明剩下的下次还会补 ───
        bodies = {f"p{i}": GUESS_TEXT_10S + f"补{i}" for i in range(7)}
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_items=[])) as c6:
            r = await client.post(G, json={"texts": bodies, "auto": True}, headers=hm)
        assert r.status_code == 200, r.text
        sixth = r.json()
        assert c6.call_count == 1, "不许在一次请求里连着打多枪模型"
        assert len(c6.call_args.args[1]["texts"]) == pesvc.GUESS_MAX_ITEMS
        assert len(sixth["skipped"]) == 7 - pesvc.GUESS_MAX_ITEMS, sixth["skipped"]
        assert any("一次问不完" in n for n in sixth["notes"]), sixth["notes"]

        # ── ⑦ 字典改了保护行 → 陈旧缓存当场作废并重问（不拿旧口径当今天结论）──
        await _put_slots(skip=r"剧情")   # 那句台词正好在「剧情：」这一行里
        with patch("app.api.assets._call_autoclip", _fake_autoclip(slots_items=items)) as c7:
            r = await client.post(G, json={"texts": {"p1": GUESS_TEXT_10S}, "auto": True},
                                  headers=hm)
        assert r.status_code == 200, r.text
        seventh = r.json()
        assert c7.call_count == 1, "字典改了还端旧缓存＝拿换不动的原值骗人"
        assert seventh["values"] == {}, seventh["values"]
        assert any("不动的那两行" in d or "找不到" in d for d in seventh["dropped"]), \
            seventh["dropped"]
        # 坏值不许再留着端上来：这一格这一枪重问还是没过判据，行里的值必须已经变空
        # （11-11 之前这里断的是「整篇一行都不剩」，那时没结果就不写；现在「问过、没有」
        #  本身是要记的答案，所以判据换成「坏值不在了」。）
        h_p1 = pesvc.body_fingerprint(GUESS_TEXT_10S)
        rows_p1 = await _rows(AssetElementGuess, AssetElementGuess.body_hash == h_p1)
        assert all(str(r.value or "") != "别开门，外头人不对" for r in rows_p1), rows_p1
        assert any(r.slot_key == "speech" and not str(r.value or "") for r in rows_p1), \
            f"重问过还是空，却没记下「这一格稿子里没有」：{rows_p1}"

        assert await _count(AssetProduction) == 0 and await _count(AssetSummary) == 0
        await client.aclose()

    _run(_scenario())


def test_prompt_elements_guess_negative_answer_cached_api():
    """11-11 现网第一枪抓出来的真 bug：**没抄到的那一格也要记下来**，否则同一格反复花钱。

    批 Z 对用户承诺「同一篇稿子同一格最多花一次钱」。缓存当时只写模型**抄到**的值，
    于是稿子里确实没写的那一格（以及模型编的、被逐字校验丢掉的那一格）每次打开开单屏
    都会重新问一遍模型、每次都重新付一次，而且永远问不出结果。现网实测：第二次请求
    `paid` 仍是 true，`asset.prompt_elements.guess_values` 审计从 1 条涨到 3 条。

    钉五件事：
    1. 问过但没结果的格子存**空串**（=「稿子里没有」这个答案本身），第二次一个字都不问；
    2. 空串行**不算坏值**，不因字典重判被清掉，也不端进 `values` 骗人说认出来了；
    3. 人工「再问一次模型」（`use_cache=false`）照样能重问，问出来的新值覆盖空串；
    4. 模型那一路**炸了**（`res` 空）＝没问到，不是没有——不许记成空串，下次照旧重问；
    5. **字典一改，那条「没有」就作废重问**（旧字典答不了新题；真值那一头的陈旧保护
       走 `accept_guessed_values` 逐字复验，不看时间戳）。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.models.asset import AssetElementGuess
        from app.services import asset_prompt_elements as pesvc

        client, h = await _client_and_headers()
        hm = h["material"]
        G = "/api/assets/prompt-elements/guess-values"

        # 两格都是 manual：词表一律认不出，这一枪必然把两格都端给模型
        r = await client.put(
            "/api/assets/prompt-elements",
            headers=h["admin"],
            json={"inherit": False, "slots": [
                {"key": "speech", "label": "动物说的话", "mode": "manual"},
                {"key": "wealth", "label": "发现的财富", "mode": "manual"},
            ]},
        )
        assert r.status_code == 200, r.text
        h1 = pesvc.body_fingerprint(GUESS_TEXT_10S)

        async def _row(slot_key: str, body_hash: str = h1):
            rows = await _rows(
                AssetElementGuess,
                AssetElementGuess.body_hash == body_hash,
                AssetElementGuess.slot_key == slot_key,
            )
            return rows[0] if rows else None

        # ── ① 第一枪：speech 抄到（逐字在稿里），wealth 模型编的 → 被丢 ──────
        called: List[int] = []

        def _counting(items, err=None):
            async def _proxy(path, payload, timeout=180.0):
                called.append(1)
                return await _fake_autoclip(slots_items=items, slots_error=err)(path, payload, timeout)
            return _proxy

        first_items = [
            {"id": "p1", "key": "speech", "value": "别开门，外头人不对"},
            {"id": "p1", "key": "wealth", "value": "一箱金条"},   # 稿子里没有＝模型编的
        ]
        with patch("app.api.assets._call_autoclip", _counting(first_items)):
            r = await client.post(G, json={"texts": {"p1": GUESS_TEXT_10S}, "auto": True},
                                  headers=hm)
        assert r.status_code == 200, r.text
        first = r.json()
        assert len(called) == 1 and first["paid"] is True, first
        assert first["values"] == {"p1": {"speech": "别开门，外头人不对"}}, first["values"]
        assert any("在这篇稿子里找不到" in d for d in first["dropped"]), first["dropped"]
        row_s = await _row("speech")
        assert row_s is not None and row_s.value == "别开门，外头人不对", row_s
        row_w = await _row("wealth")
        assert row_w is not None and row_w.value == "", \
            "问过、没结果的那格没记下来＝下次进来还会再花一次钱问同一个空"

        # ── ② 第二枪（同一个请求）：一次模型都不打、不花钱、值照旧 ───────────
        n = len(called)
        with patch("app.api.assets._call_autoclip", _counting(first_items)):
            r = await client.post(G, json={"texts": {"p1": GUESS_TEXT_10S}, "auto": True},
                                  headers=hm)
        assert r.status_code == 200, r.text
        second = r.json()
        assert len(called) == n, "同一篇同一格第二次还打模型＝这个 bug 没修掉"
        assert second["paid"] is False, second
        assert second["values"] == first["values"], second
        assert second["from_cache"] == {"p1": ["speech"]} and second["from_model"] == {}
        assert any("上一次问过" in x for x in second["notes"]), \
            f"没告诉用户那一格是「问过、稿子里没有」：{second['notes']}"
        assert await _count(AssetElementGuess) == 2, await _rows(AssetElementGuess)
        audits = await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.guess_values")
        assert len(audits) == 1, f"没花钱的一枪不许留痕：{len(audits)} 条"

        # ── ③ 人工「再问一次模型」：能重问，问出来的值覆盖空串 ────────────────
        n = len(called)
        with patch("app.api.assets._call_autoclip", _counting([
            {"id": "p1", "key": "speech", "value": "别开门，外头人不对"},
            {"id": "p1", "key": "wealth", "value": "布包"},   # 「门槛上放着个布包」里有
        ])):
            r = await client.post(
                G, json={"texts": {"p1": GUESS_TEXT_10S}, "use_cache": False}, headers=hm,
            )
        assert r.status_code == 200, r.text
        assert len(called) == n + 1
        assert r.json()["values"]["p1"]["wealth"] == "布包", r.json()["values"]
        assert (await _row("wealth")).value == "布包", "重问出来的值没覆盖那条空串"
        assert await _count(AssetElementGuess) == 2, "同键要覆盖，不许长出一行重复的"

        # ── ④ 模型炸了＝没问到，不许记成「稿子里没有」────────────────────────
        # 缓存键是正文指纹，所以这一枪必须用一篇**没进过缓存**的稿子
        other = GUESS_TEXT_10S + "\n【另一篇】院墙外头又传来两声狗叫。"
        h2 = pesvc.body_fingerprint(other)
        before = await _count(AssetElementGuess)
        n = len(called)
        with patch("app.api.assets._call_autoclip", _counting([], err="提炼服务没回话")):
            r = await client.post(G, json={"texts": {"p7": other}, "auto": True}, headers=hm)
        assert r.status_code == 200, r.text
        assert len(called) == n + 1 and r.json()["paid"] is False, r.json()
        assert await _count(AssetElementGuess) == before, \
            "一次网络抖动就把这一格永久记成「没有」＝以后再也不问了"

        # 下一枪照旧重问（不是被空串拦住的 0 元）
        n = len(called)
        with patch("app.api.assets._call_autoclip", _counting([
            {"id": "p7", "key": "speech", "value": "别开门，外头人不对"},
        ])):
            r = await client.post(G, json={"texts": {"p7": other}, "auto": True}, headers=hm)
        assert r.status_code == 200, r.text
        assert len(called) == n + 1 and r.json()["paid"] is True, r.json()
        assert (await _row("speech", h2)).value == "别开门，外头人不对"

        # ── ⑤ 字典又改过一次 → 「没有」这条作废重问（不拿旧字典的答案糊弄新题）────
        r = await client.put(
            "/api/assets/prompt-elements",
            headers=h["admin"],
            json={"inherit": False, "slots": [
                {"key": "speech", "label": "动物说的话", "mode": "manual"},
                {"key": "wealth", "label": "发现的财富", "pool": ["布包"]},
            ]},
        )
        assert r.status_code == 200, r.text
        n = len(called)
        # 这一腿必须点名**还存着负样本**的那篇（p7／h2）：p1 那两格在第 ③ 腿里已经被
        # 真值覆盖了，拿它来验「作废重问」会验到一个空集——改完字典它照样 0 元，
        # 那不是缓存没作废，是这一篇已经没有空格了。
        with patch("app.api.assets._call_autoclip", _counting(
            [{"id": "p7", "key": "wealth", "value": "布包"}]
        )):
            r = await client.post(G, json={"texts": {"p7": other}, "auto": True}, headers=hm)
        assert r.status_code == 200, r.text
        assert len(called) == n + 1, (
            "改了词表还拿改之前那句「稿子里没有」挡着＝这一格永远问不出来了："
            f"{r.json()}"
        )
        assert r.json()["paid"] is True, r.json()
        rows_h2 = await _rows(AssetElementGuess, AssetElementGuess.body_hash == h2)
        assert (await _row("wealth", h2)).value == "布包", rows_h2

        assert await _count(AssetProduction) == 0 and await _count(AssetSummary) == 0
        await client.aclose()

    _run(_scenario())


def test_prompt_elements_guess_ends_transaction_before_model_call():
    """11-11 现网批量补位实测：问 5 篇要趴几十秒等 autoclip，而接口进来到调模型之间
    那几笔 SELECT 一直开着事务没人收——PG 的 `idle_in_transaction_session_timeout=60s`
    把连接掐掉，模型**成功返回**之后 `_guess_cache_write` 报 connection is closed
    → 整口 500。这比出文案口那次贵：钱已经花了，缓存一行没落，下次进来照旧再花一遍。

    回归判据（与 `test_preview_prompt_ends_transaction_before_model_call` 同一手法）：
    用 `before_commit` 事件记次序——commit 必须发生在调模型**之前**，且回写成功、
    缓存行真的落进去了。
    """
    _run(_bootstrap())

    async def _scenario():
        from sqlalchemy import event
        from sqlalchemy.orm import Session as _SyncSession

        from app.models.asset import AssetElementGuess
        from app.services import asset_prompt_elements as pesvc

        client, h = await _client_and_headers()
        hm = h["material"]

        r = await client.put(
            "/api/assets/prompt-elements",
            headers=h["admin"],
            json={"inherit": False, "slots": [
                {"key": "speech", "label": "动物说的话", "mode": "manual"},
            ]},
        )
        assert r.status_code == 200, r.text

        order: List[str] = []  # "commit" / "model" 按发生顺序

        def _on_commit(session):
            order.append("commit")

        fake = _fake_autoclip(slots_items=[
            {"id": "p1", "key": "speech", "value": "别开门，外头人不对"},
        ])

        async def autoclip_spy(path, payload, timeout=900.0):
            order.append("model")
            return await fake(path, payload, timeout)

        event.listen(_SyncSession, "before_commit", _on_commit)
        try:
            with patch("app.api.assets._call_autoclip", autoclip_spy):
                resp = await client.post(
                    "/api/assets/prompt-elements/guess-values",
                    json={"texts": {"p1": GUESS_TEXT_10S}, "auto": True}, headers=hm,
                )
        finally:
            event.remove(_SyncSession, "before_commit", _on_commit)
        assert resp.status_code == 200, resp.text
        assert resp.json()["paid"] is True, resp.json()
        assert "model" in order, "模型没被调到，探针失效"
        assert "commit" in order[:order.index("model")], (
            "调模型前没收事务：等模型那几十秒里读事务一直趴着，现网 60s 一到连接就被掐，"
            "钱花了、缓存一行没落（11-11 现网两批 500 实录）"
        )
        rows = await _rows(AssetElementGuess,
                           AssetElementGuess.body_hash == pesvc.body_fingerprint(GUESS_TEXT_10S))
        assert [x.value for x in rows] == ["别开门，外头人不对"], rows
        await client.aclose()

    _run(_scenario())


def test_guess_cache_write_retries_on_dead_connection():
    """上面那条是防「连接被掐」，这条是掐了之后的兜底：第一次 commit 抛
    InterfaceError 时**换新事务重放一次**，不能把花钱换来的答案丢了直接 500。
    """
    from sqlalchemy.exc import InterfaceError

    from app.services import asset_prompt_elements as pesvc

    class _FlakySession:
        def __init__(self):
            self.added = []
            self.commits = 0
            self.rollbacks = 0

        def add(self, obj):
            self.added.append(obj)

        async def execute(self, *_a, **_k):
            class _Res:
                def scalars(self):
                    class _S:
                        def first(self):
                            return None
                    return _S()
            return _Res()

        async def commit(self):
            self.commits += 1
            if self.commits == 1:
                raise InterfaceError("COMMIT", None, Exception("connection is closed"))

        async def rollback(self):
            self.rollbacks += 1

    async def _scenario():
        sess = _FlakySession()
        await assets_api._guess_cache_write(
            sess, {"p1": (pesvc.body_fingerprint(GUESS_TEXT_10S), {"speech": "别开门"})},
            "mimo-v2.6-flash", "A",
        )
        assert sess.commits == 2 and sess.rollbacks == 1, \
            f"没做「换新事务重放一次」：commit={sess.commits} rollback={sess.rollbacks}"
        assert len(sess.added) == 1 and sess.added[0].value == "别开门", sess.added

    _run(_scenario())


def test_prompt_elements_manual_rows_protected_lines_and_seeds_api():
    """批 N（11-10 用户逐原型参数清单）四件事，都得从接口口打出来才算数：

    1. **手填项存进去不丢**：mode=manual 一行词面、候选、写法都不给也合法（这行就是要人填）；
    2. **认与换都不碰「钩子原文」行和 ① 生成【…】行**——现网 ① 行里带着《剧名》，
       把「鲸鱼」全文换成「猫」会顺手造出一部不存在的剧，这是取样时看到的真形状；
    3. **场景按位置认**：词表外的「普通民居客厅」也要能自动提出当前值
       （用户原话：「并自动提取原脚本中的参数」）；
    4. **开单屏要的那份**：`include_unmatched=true` 把这个原型的参数项**全**摆出来，
       认不出原值的说"没认出"，不许默默少一行。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.services import asset_prompt_elements as pesvc

        client, h = await _client_and_headers()
        hm, ha = h["material"], h["admin"]

        prompt_a = "\n".join([
            "【第 3 段 · 建议 10 秒 · 本钩共 6 条 · 编号 8PZXGA1】",
            "钩子原文：我家猫开口了，说门口那人不干净",
            "生成【都市脑洞】仿真人写实短剧，参考【《鲸鱼开口指路跳海》】剧情，"
            "输入素材为 AI 多视图角色设定卡。",
            "时长 10 秒，9:16 竖屏，模拟手机竖屏实拍短剧影视质感。",
            "剧情：【前3秒】普通民居客厅，一只猫开口催他赶紧出门，说沙发底下有东西。"
            "【后7秒】河边，他撬开水泥管，捞出一只木箱。",
            "镜头：客厅正反打，河边用侧四十五度中近景。",
            "负面约束：禁止五官崩坏变脸。 9:16，10s",
        ])

        # ① 脏写法照样 400 且不写审计：literal 什么都没给／pattern 没写法／
        #    probe 没捕获组／probe 安在 pattern 槽位上／跳过写法编不过
        bad_calls = [
            {"slots": [{"key": "empty_literal", "mode": "literal"}]},
            {"slots": [{"key": "no_pattern", "mode": "pattern"}]},
            {"slots": [{"key": "probe_nogroup", "mode": "literal", "pool": ["河边"], "probe": r"剧情：[^，]{2,20}"}]},
            {"slots": [{"key": "probe_on_pattern", "mode": "pattern",
                        "pattern": r"时长 (\d+) 秒", "probe": r"剧情：([^，]{2,20})"}]},
            {"slots": [{"key": "bad_skip", "mode": "literal", "pool": ["河边"], "skip_lines": "(("}]},
        ]
        for payload in bad_calls:
            r = await client.put("/api/assets/prompt-elements",
                                 json={**payload, "inherit": True}, headers=ha)
            assert r.status_code == 400, f"{payload} 该被拒：{r.text}"
        assert await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.update") == []

        # ② 手填行可以什么都不带；存进去读出来 mode 不丢
        r = await client.put(
            "/api/assets/prompt-elements",
            json={"inherit": True, "slots": [
                {"key": "a_speech", "label": "动物说的一句话", "mode": "manual", "categories": ["原型 A"],
                 "note": "整句话系统不猜：请从稿子里复制原句，再填新句"},
                {"key": "drama_swap", "label": "剧名（特殊活儿才碰 ① 行）", "mode": "literal",
                 "anchors": ["鲸鱼"], "skip_lines": ""},
            ]},
            headers=ha,
        )
        assert r.status_code == 200, r.text
        eff = {s["key"]: s for s in r.json()["effective"]}
        assert eff["a_speech"]["mode"] == pesvc.MODE_MANUAL
        assert eff["drama_swap"]["skip_lines"] == "", "显式空串＝允许碰保护行，这条得存得住"
        assert eff["a_animal"]["skip_lines"] == pesvc.DEFAULT_SKIP_LINES, "没写的槽位用默认保护"

        # ②b 元素库抽屉「读回来要能还原三态」的契约：GET 除了三层表，还要回默认保护行的原串。
        #     前端靠它分清「这行仍用默认」／「改成了允许碰」／「写了自定义」——后端不吐原串，
        #     前端只能自己抄一份，默认串一改，界面就会把仍在用默认的行显示成被改过。
        r = await client.get("/api/assets/prompt-elements", headers=hm)
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert cfg["default_skip_lines"] == pesvc.DEFAULT_SKIP_LINES
        by_key = {s["key"]: s for s in cfg["override"]}
        assert by_key["drama_swap"]["skip_lines"] == "", "存下来的那道口子要读得回来，不然下一次保存又变回默认"
        assert by_key["a_speech"]["skip_lines"] == pesvc.DEFAULT_SKIP_LINES
        assert by_key["a_speech"]["mode"] == pesvc.MODE_MANUAL and by_key["a_speech"]["anchors"] == []
        scene = next(s for s in cfg["defaults"] if s["key"] == "a_scene")
        assert scene["probe"], "出厂场景行的识别位置必须在：开单屏「自动提取原脚本参数」靠它认原值"

        # ③ 认元素：报原型 A（短前缀）时把这一原型的参数项全摆出来，含认不出原值的手填项
        r = await client.post(
            "/api/assets/prompt-elements/extract",
            json={"texts": {"p1": prompt_a}, "category": "原型 A", "include_unmatched": True},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        got = {s["key"]: s for s in r.json()["items"]["p1"]}
        assert {"a_animal", "a_scene", "a_speech"} <= set(got), got.keys()
        assert not (set(got) & {"d_weak", "d_scene", "d_abuser", "d_line"}), "别的原型的参数项不该串台"
        assert got["a_scene"]["current"] == "普通民居客厅", "词表外的场景要按位置认出来"
        assert got["a_animal"]["current"] == "猫", "①行的《鲸鱼开口…》在保护行里，不该被当成动物认出来"
        assert got["a_speech"]["current"] is None and got["a_speech"]["mode"] == "manual"
        assert "复制" in got["a_speech"]["note"]
        assert any("没认出" in n or "抄" in n for n in r.json()["notes"]), r.json()["notes"]

        # 3b 不报原型时，出厂那 16 行限定原型的种子都不该冒出来（②投产弹窗的老口径不变）
        r = await client.post("/api/assets/prompt-elements/extract",
                              json={"texts": {"p1": prompt_a}}, headers=hm)
        got2 = {s["key"] for s in r.json()["items"]["p1"]}
        assert not {k for k in got2 if k[:2] in {"a_", "b_", "c_", "d_", "e_", "f_"}}, got2

        # ④ 组稿：换动物不碰剧名、不碰过审那句；场景两句都换（认出的整段＋镜头行那个短词）；
        #    手填项换整句
        r = await client.post(
            "/api/assets/prompt-elements/apply",
            json={"text": prompt_a, "edits": [
                {"key": "a_animal", "old": "鲸鱼", "new": "猫"},
                {"key": "a_scene", "old": "普通民居客厅", "new": "建筑工地"},
                {"key": "a_scene", "old": "客厅", "new": "工地"},
                {"key": "a_speech", "old": "一只猫开口催他赶紧出门，说沙发底下有东西",
                 "new": "一只猫开口让他去撬河边那根水泥管，说底下埋着他爹留下的三箱货"},
            ]},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rep = {x["key"]: x for x in body["replaced"]}
        assert [x["count"] for x in body["replaced"]] == [0, 1, 1, 1], body["replaced"]
        assert "《鲸鱼开口指路跳海》" in body["text"], "剧名一个字都不许动"
        assert rep["a_animal"]["count"] == 0, "鲸鱼只在保护行里出现＝这一条就是没改"
        assert any("受保护行" in n for n in body["notes"]), body["notes"]
        assert "建筑工地" in body["text"] and "普通民居客厅" not in body["text"]
        assert "工地正反打" in body["text"], "⑧镜头行那句也得跟着换，否则画面精神分裂"
        assert rep["a_speech"]["count"] == 1 and "三箱货" in body["text"]
        assert "我家猫开口了" in body["text"], "过审那句原话留在稿子里"

        # 4b 那个明确 skip_lines="" 的槽位是口子：它能把 ① 行的剧名换掉（换了就是换皮另一部剧）
        r = await client.post(
            "/api/assets/prompt-elements/apply",
            json={"text": prompt_a, "edits": [{"key": "drama_swap", "old": "鲸鱼", "new": "白鳍豚"}]},
            headers=hm,
        )
        assert "《白鳍豚开口指路跳海》" in r.json()["text"], r.text

        # 4c 原型 F 的「绝境」也是手填项：出厂行的说明要当场说清"系统不猜"
        r = await client.post("/api/assets/prompt-elements/extract",
                              json={"texts": {"p1": prompt_a}, "category": "原型 F",
                                    "include_unmatched": True}, headers=hm)
        f = {s["key"]: s for s in r.json()["items"]["p1"]}
        assert f["f_plight"]["mode"] == pesvc.MODE_MANUAL and f["f_plight"]["current"] is None
        assert "不猜" in f["f_plight"]["note"], f["f_plight"]

        # ⑤ 还是纯文本进出：除了那一次改字典，库里不落任何东西
        assert len(await _rows(AuditLog, AuditLog.action == "asset.prompt_elements.update")) == 1
        assert await _count(AssetProduction) == 0 and await _count(AssetItem) == 0
        await client.aclose()

    _run(_scenario())


def test_produce_element_fanout_one_order_per_parameter_row():
    """批 P（11-10 用户口径「可自定义填入多个场景词、动物名称，并一次性生成多条钩子视频」）。

    1. 填几组参数＝几张单：每张各占一个序号、一个钩子编号，而且编号要**同时**换进正文和
       推荐标题——板上 name 取的是标题第 1 条（B-5），只换正文等于台账改了、板面还是重名，
       正是 11-05 现网那条「两条产物挂到同一张单」的对账坑；
    2. 扇出只换词、不调模型：n=1 时模型只被叫一次，几张单都是那一份稿子的字面变体（0 元）；
    3. 没给原值＝那条不换，但要在结果里点名，不许悄悄出几张一模一样的稿；
    4. 参数写歪（按行配对个数对不齐）和换上去的词带高风险词 → **当场 400 且一张单没建**，
       排在 async_mode 之前：号一旦发出去就烧掉，作废的单也不复用；
    5. 只有拼进句子才凑成的词（"建筑工地"＋原稿的"事故"）→ 只摘那一条，同批其它照常建。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]

        # 原型走**出厂字典**（a_animal/a_scene 是种子行），所以这条文案得先挂上原型 A，
        # 否则 `slot_applies` 一律判不适用 → 扇出来的全是"没认出值"，测不到替换本身。
        cat_a = await _cat_id(client, hm, "A")
        asset_id, _ = await _make_ready_asset(client, hm, category_id=cat_a)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        base_prompt = "\n".join([
            "【第 1 段 · 建议 10 秒 · 本钩共 1 条 · 编号 7C0B1】",
            "剧情：【前3秒】河边，一只猫开口让他赶紧出门。【后7秒】河边，他撬开水泥管。",
            "镜头：河边用侧四十五度中近景。",
        ])
        base_titles = ["7C0B1·河边猫开口了", "备用标题"]

        async def _produce(**extra):
            payload = {"summary_ids": [sid], "n": 1}
            payload.update(extra)
            with patch("app.api.assets._call_autoclip",
                       _fake_autoclip(expand_prompt=base_prompt, expand_titles=base_titles)):
                return await client.post("/api/assets/produce", json=payload, headers=ho)

        # ── ① 两个场景 × 1 份稿 = 2 张单，号与序号各自占一个 ──
        r = await _produce(
            hook_codes=["7C0B1", "7C0B2"],
            element_values={"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["黄鼠狼"]},
            element_base={"a_scene": "河边", "a_animal": "猫"},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["created"] == 2 == await _count(AssetProduction)
        assert j["element_fanout"]["rows_per_copy"] == 2 and j["element_fanout"]["mode"] == "zip"
        assert set(j["element_fanout"]["params"]) == {"场景", "动物／非人物件"}, j["element_fanout"]
        got = sorted(await _rows(AssetProduction), key=lambda x: x.seq)
        assert [x.seq for x in got] == [1, 2], "扇出来的每张各占一个序号（撞 uq_asset_production_seq 会让整批 409）"
        assert [x.hook_code for x in got] == ["7C0B1", "7C0B2"], "一钩一号：每张单自己的号"
        assert "建筑工地" in got[0].prompt_text and "河边" not in got[0].prompt_text
        assert "繁华大街" in got[1].prompt_text and "河边" not in got[1].prompt_text
        assert all("黄鼠狼" in x.prompt_text and "一只猫" not in x.prompt_text for x in got)
        assert "编号 7C0B2" in got[1].prompt_text and "7C0B1" not in got[1].prompt_text
        assert "7C0B2" in (got[1].board_name or "") and "7C0B1" not in (got[1].board_name or ""), \
            f"标题里的编号必须跟着换，否则两张单同名投上同一块板：{got[1].board_name}"
        assert "场景=繁华大街" in (got[1].variant_basis or "") and "动物" in (got[1].variant_basis or "")
        assert any("扇出" in w and "没有再花模型钱" in w for w in j["warnings"]), j["warnings"]
        assert "× 扇出 2 张" in j["message"], j["message"]

        # ── ①b 全组合：2 场景 × 2 动物 = 4 张（不是 2 张）──
        before = await _count(AssetProduction)
        r = await _produce(
            hook_codes=["7C0B3", "7C0B4", "7C0B5", "7C0B6"],
            element_values={"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["狗", "黄鼠狼"]},
            element_base={"a_scene": "河边", "a_animal": "猫"},
            element_mode="product",
        )
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 4 and await _count(AssetProduction) == before + 4
        assert r.json()["element_fanout"]["mode"] == "product"
        combos = {
            (x.prompt_text.count("建筑工地") > 0, x.prompt_text.count("狗") > 0)
            for x in (await _rows(AssetProduction))[before:]
        }
        assert len(combos) == 4, f"全组合该是 4 种配对，实际 {combos}"

        # ── ② 没给原值：两张照建，但当场说"这条没换" ──
        before = await _count(AssetProduction)
        r = await _produce(
            hook_codes=["7C0C1", "7C0C2"],
            element_values={"a_scene": ["建筑工地", "繁华大街"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 2
        tail = sorted((await _rows(AssetProduction))[before:], key=lambda x: x.seq)
        assert all("河边" in x.prompt_text for x in tail), "没有原值就不许乱换"
        assert any("没换" in w for w in r.json()["warnings"]), r.json()["warnings"]

        # ── ③ 逐文稿原值优先于公共兜底（多条文稿同批开单时这才是唯一能换对的路）──
        before = await _count(AssetProduction)
        r = await _produce(
            hook_codes=["7C0D1"],
            element_values={"a_scene": ["海底"]},
            element_base={"a_scene": "客厅"},
            element_base_by_summary={sid: {"a_scene": "河边"}},
        )
        assert r.status_code == 200 and r.json()["created"] == 1, r.text
        assert "海底" in (await _rows(AssetProduction))[-1].prompt_text
        assert "河边" not in (await _rows(AssetProduction))[-1].prompt_text

        # ── ④a 按行配对个数对不齐 → 400，且一张单没建、号没烧 ──
        before = await _count(AssetProduction)
        bad = await _produce(
            hook_codes=["7C0E1", "7C0E2", "7C0E3"],
            element_values={"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["狗", "黄鼠狼", "猫"]},
            element_base={"a_scene": "河边", "a_animal": "猫"},
        )
        assert bad.status_code == 400, bad.text
        assert "对不齐" in bad.json()["detail"], bad.json()["detail"]
        assert await _count(AssetProduction) == before

        # 400 必须排在 async_mode 之前：页面唯一真实路径是提交即回任务号，
        # 若错写成"先接单、后台再炸"，一线只看到一个失败任务，号也已经发出去了。
        bad_async = await _produce(
            async_mode=True,
            hook_codes=["7C0E1", "7C0E2", "7C0E3"],
            element_values={"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["狗", "黄鼠狼", "猫"]},
            element_base={"a_scene": "河边", "a_animal": "猫"},
        )
        assert bad_async.status_code == 400, bad_async.text
        assert "job_id" not in bad_async.json(), bad_async.json()
        assert await _count(AssetProduction) == before

        # ── ④b 换上去的词本身就是高风险词 → 400（改词再来，比事后撤 20 张单便宜）──
        await client.put("/api/assets/risk-lexicon",
                         json={"block": ["黄鼠狼"], "warn": [], "exempt": {}, "inherit": False},
                         headers=ha)
        before = await _count(AssetProduction)
        bad = await _produce(
            hook_codes=["7C0F1", "7C0F2"],
            element_values={"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["黄鼠狼"]},
            element_base={"a_scene": "河边", "a_animal": "猫"},
        )
        assert bad.status_code == 400 and "高风险词" in bad.json()["detail"], bad.text
        assert await _count(AssetProduction) == before

        # ── ⑤ 单看词干净、拼进句子才撞：只摘那一条，另一条照常建 ──
        await client.put("/api/assets/risk-lexicon",
                         json={"block": ["工地事故"], "warn": [], "exempt": {}, "inherit": False},
                         headers=ha)
        accident_prompt = "\n".join([
            "【第 1 段 · 建议 10 秒 · 本钩共 1 条 · 编号 7C1A1】",
            "剧情：【前3秒】河边，一只猫开口让他别去河边事故现场。",
        ])
        before = await _count(AssetProduction)
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt=accident_prompt, expand_titles=["7C1A1·河边猫开口了"])):
            r = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1, "hook_codes": ["7C1A1", "7C1A2"],
                "element_values": {"a_scene": ["建筑工地", "繁华大街"]},
                "element_base": {"a_scene": "河边"},
            }, headers=ho)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["created"] == 1 == (await _count(AssetProduction)) - before
        assert len(j["element_fanout"]["skipped"]) == 1, j["element_fanout"]
        assert "工地事故" in j["element_fanout"]["skipped"][0]["words"], j["element_fanout"]
        assert "繁华大街" in (await _rows(AssetProduction))[-1].prompt_text
        assert any("撞上高风险词" in w for w in j["warnings"]), j["warnings"]

        # ── ⑥ 审计里得能看到这批是扇出来的（事后对账问"20 张哪来的"）──
        trail = await _rows(AuditLog, AuditLog.action == "asset.produce_order")
        assert trail and any(t.after.get("element_fanout") for t in trail), [t.after for t in trail][-1]
        await client.aclose()

    _run(_scenario())


# ══════════════════════════════════════════════════════════════
#  1110 批 Q · 钩子成片回收后自动拼接成「可投放素材」（需求⑤）
#
#  用户口径原话：「钩子成片生成出来以后，需要导入拼接视频自动拼接成可投放素材。」
#  11-10 定下的形态：**回收后自动拼＝钩子成片＋投板那一屏点名的拼接素材**，顺序可选
#  （钩子片在前／素材片段在前），拼成即素材 `stage_compose=success` → 派生态 `ready`。
#
#  这节的替身比批 H 多一层「按内容认段」的探针，理由只有一个：选顺序唯一的实证是
#  **排在最前那一段的规格当目标画幅**。所以 `download_to_file` 按 file_key 写两种可辨认
#  的字节、`probe_media` 按内容回规格，于是断 `concat_segments` 收到的 target
#  ＝断"到底谁在前"，而不是读代码猜。
# ══════════════════════════════════════════════════════════════

Q_HOOK_BYTES = b"QHOOKSEG" + b"\x00" * 4096      # 钩子成片那一段
Q_MATL_BYTES = b"QMATLSEG" + b"\x00" * 2048      # 人点名的拼接素材那一段
Q_OUT_BYTES = b"QCOMPOUT" + b"\x00" * 3072       # ffmpeg 拼出来的产物

Q_VERT = {"duration": 10.08, "width": 720, "height": 1280, "fps": "25/1", "has_audio": True}
Q_HORIZ = {"duration": 6.0, "width": 1280, "height": 720, "fps": "30/1", "has_audio": False}
Q_COMPOSED = {"duration": 16.08, "width": 720, "height": 1280, "fps": "25/1", "has_audio": True}


@contextlib.contextmanager
def _q_concat_off(calls: List[dict], *, concat_error: Optional[str] = None,
                  concat_return_error: Optional[str] = None):
    """拼接那段（取回两段 → 探规格 → ffmpeg → 落桶）的替身，全程不出网、不跑真 ffmpeg。

    `concat_return_error`＝ffmpeg 那一步**回错串**（拼接失败的原形状，不是抛异常）。
    `concat_error`＝抛异常（形状不同，走的是 `_auto_concat_recovered` 里那条
    `except Exception` 兜底，两种都得能兜住才会"拼不上不连累回收"）。

    ⚠️ 落桶也在这里钉：批 H 的 `_patch_board` 同样钉了 `upload_file_from_path`，
    两层钉的是同一个替身形状（返回 True）。不钉的话自动拼那一步会去连本机没起的
    MinIO:9000，用例挂成 ConnectionRefused 而不是"拼接没落库"。
    """
    async def _download(bucket, key, local):
        with open(local, "wb") as fh:
            fh.write(Q_HOOK_BYTES if str(key).startswith("asset/board/") else Q_MATL_BYTES)
        return True

    async def _concat(paths, target, out_path):
        with open(paths[0], "rb") as fh:
            first_head = fh.read(8)
        calls.append({"target": dict(target), "first_is_hook": first_head == Q_HOOK_BYTES[:8],
                      "n_paths": len(paths)})
        if concat_error is not None:
            raise RuntimeError(concat_error)
        with open(out_path, "wb") as fh:
            fh.write(Q_OUT_BYTES)
        return concat_return_error

    def _probe(path):
        with open(path, "rb") as fh:
            head = fh.read(8)
        if head == Q_MATL_BYTES[:8]:
            return Q_HORIZ
        if head == Q_OUT_BYTES[:8]:
            return Q_COMPOSED
        # 钩子那一段＋回收侧那个假 ftyp 文件都按竖屏成片回（和现网豆包出片规格一致）
        return Q_VERT

    with contextlib.ExitStack() as st:
        st.enter_context(patch("app.api.assets.download_to_file", _download))
        st.enter_context(patch("app.services.asset_compose_service.concat_segments", _concat))
        st.enter_context(patch("app.services.asset_compose_service.probe_media",
                               AsyncMock(side_effect=_probe)))
        st.enter_context(patch("app.api.assets.upload_file_from_path",
                               AsyncMock(return_value=True)))
        yield


async def _q_video_asset(client, hm, name):
    """入库一条**文件素材**（有 file_key、能当拼接的一段），返回该素材行。"""
    with patch("app.api.assets.upload_file_from_path", AsyncMock(return_value=True)), \
         patch("app.api.assets._ffprobe_duration", lambda p: 6.0):
        resp = await client.post("/api/assets/upload/batch",
                                 files=[("files", (name, VIDEO_BYTES, "video/mp4"))], headers=hm)
    assert resp.status_code == 201, resp.text
    return resp.json()["items"][0]


def test_dispatch_poll_discards_downloaded_output_when_cancelled_before_writeback():
    """删单抢在轮询写库前：已下载但未落库的成片必须随 cancelled 一起作废。

    精确时序：板面已 succ → _fetch_board_output 已下载并落桶 → 用户删单提交
    cancelled → 轮询写回前 FOR UPDATE 看到取消态。修法前 _reown 只让状态，仍会把
    内存里的 outputs 插进 asset_outputs，刷新成片墙就把已删任务复活了。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, hadm = h["material"], h["admin"]
        asset_id, _sid, listed = await _order_ready_production(client, h, hook_codes=["7C0E1"])
        pid = listed[0]["id"]
        material = await _q_video_asset(client, hm, "删单并发拼接段.mp4")
        original_fetch = assets_api._fetch_board_output
        cancel_status = []

        async def _fetch_then_cancel(*args, **kwargs):
            rec = await original_fetch(*args, **kwargs)
            resp = await client.post(f"/api/assets/productions/{pid}/cancel", headers=hadm)
            cancel_status.append(resp.status_code)
            return rec

        calls: List[dict] = []
        fb = _FakeBoard()
        with _board_off(fb), _q_concat_off(calls), \
             patch("app.api.assets._fetch_board_output", side_effect=_fetch_then_cancel):
            resp = await _dispatch(client, h["operator"], [pid], concat_asset_id=material["id"])
        assert cancel_status == [200], cancel_status
        assert resp.status_code == 200, resp.text
        body = resp.json()

        row = await _row_of(AssetProduction, pid)
        assert row.status == PR_CANCELLED, row.status
        assert "人工删单" in (row.error or "") and ADMIN_USER in (row.error or ""), row.error
        assert await _rows(AssetOutput) == [], "cancelled 单的晚到产物不许落库"
        assert calls == [], "产物没落库，自动拼接也不许被触发"
        result = body["results"][pid]
        assert result["status"] == PR_CANCELLED
        assert "随作废丢弃" in (result.get("note") or ""), result
        assert "新增产物" not in body["message"], body["message"]
        wall = await client.get("/api/assets/outputs", params={"production_id": pid}, headers=hadm)
        assert wall.status_code == 200 and wall.json()["items"] == [], wall.text
        await client.aclose()

    _run(_scenario())


def test_auto_concat_discards_render_when_production_is_cancelled_mid_render():
    """轮询已 commit 后用户仍可删 queued/running 单：拼接渲染中途删单也不能落 composed。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, hadm = h["material"], h["admin"]
        asset_id, _sid, listed = await _order_ready_production(client, h, hook_codes=["7C0E2"])
        pid = listed[0]["id"]
        material = await _q_video_asset(client, hm, "渲染中删单拼接段.mp4")
        out_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            prod = await s.get(AssetProduction, uuid.UUID(pid))
            prod.concat_asset_id = uuid.UUID(material["id"])
            prod.concat_order = "hook_first"
            prod.status = PR_QUEUED
            prod.started_at = datetime.utcnow()
            s.add(AssetOutput(
                id=out_id, production_id=prod.id, asset_id=prod.asset_id,
                kind="doubao_raw", file_key=f"asset/board/{out_id}.mp4",
                bucket=settings.MINIO_BUCKET_RAW, file_name="已回收钩子.mp4",
                duration=10.08, resolution="720x1280",
            ))
            await s.commit()
        outcome = {
            "outputs": [{
                "production_id": pid, "_inserted": True, "_output_id": str(out_id),
                "file_key": f"asset/board/{out_id}.mp4", "bucket": settings.MINIO_BUCKET_RAW,
                "file_name": "已回收钩子.mp4",
            }],
            "prods": {pid: prod},
        }
        original_render = assets_api._concat_render
        cancel_status = []

        async def _render_then_cancel(*args, **kwargs):
            rendered = await original_render(*args, **kwargs)
            resp = await client.post(f"/api/assets/productions/{pid}/cancel", headers=hadm)
            cancel_status.append(resp.status_code)
            return rendered

        operator = (await _rows(User, User.username == ADMIN_USER))[0]
        async with dbmod.async_session_factory() as s:
            live_prod = await s.get(AssetProduction, uuid.UUID(pid))
            outcome["prods"] = {pid: live_prod}
            with _q_concat_off([]), patch("app.api.assets._concat_render", side_effect=_render_then_cancel):
                note = await assets_api._auto_concat_recovered(s, outcome, operator=operator)

        assert cancel_status == [200], cancel_status
        assert note["composed"] == 0 and note["attempted"] == 1, note
        assert note["results"][0]["result"] == "cancelled", note
        row = await _row_of(AssetProduction, pid)
        assert row.status == PR_CANCELLED and row.concat_last_result is None, row.concat_last_result
        outs = await _rows(AssetOutput)
        assert len(outs) == 1 and outs[0].kind == "doubao_raw", "真实已回收成片保留，不新增拼接产物"
        assert await _rows(AuditLog, AuditLog.action == "asset.concat.auto") == []
        await client.aclose()

    _run(_scenario())


def test_dispatch_auto_concat_composes_each_hook_and_lights_the_asset_ready():
    """批 Q 主干：投板点名拼接素材 → 回收到的每支豆包成片自动拼一条、素材推到 ready。

    钉的都是"这算不算可投放素材"上不能错的几件：
    - 产物**每条一行、不挂生产单**（`production_id=NULL`——批 I 定过的口径：挂上会让
      生产单行上「成片」那列一支算两支）；
    - 幂等键 `composed_from_output_id` 指向回收那条 doubao_raw，来源单走 `hook_production_id`；
    - 拼成功才点亮 `stage_compose`，派生态从 composing 走到 ready（与手工口同一套 derive）；
    - **0 元**：不写任何 cost_*，但逐条留 `asset.concat.auto` 审计（谁拼的、哪两段、什么顺序）；
    - 拼完的产物照旧补首帧；回收结果本身一个字都不许被拼接改动（succeeded 照旧）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(
            client, h, n=2, hook_codes=["7C0Q1", "7C0Q2"])
        material = await _q_video_asset(client, hm, "正文片段.mp4")
        asset_code = (await _row_of(AssetItem, asset_id)).code
        ids = [p["id"] for p in listed]

        calls: List[dict] = []
        fb = _FakeBoard()
        with _board_off(fb), _q_concat_off(calls), \
             patch("app.api.assets._enqueue_frames", AsyncMock(
                 return_value={"queued": True, "job_id": "jq", "note": "抽帧已排后台"})) as enq:
            resp = await _dispatch(client, ho, ids, concat_asset_id=material["id"])
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # ① 回收那条线不许因为拼接改判
        assert body["succeeded"] == 2 and body["failed"] == 0, body
        note = body["concat"]
        assert note["attempted"] == 2 and note["composed"] == 2 and note["failed"] == 0, note
        assert "自动拼接：拼成 2 支" in body["message"], body["message"]

        # ② 产物：2 条 doubao_raw ＋ 2 条 composed，composed 的挂法就是需求⑤的落库形状
        outs = await _rows(AssetOutput)
        raws = [o for o in outs if o.kind == "doubao_raw"]
        comp = [o for o in outs if o.kind == "composed"]
        assert len(raws) == 2 and len(comp) == 2, [(o.kind, o.production_id) for o in outs]
        for o in comp:
            assert o.production_id is None, "拼接产物挂生产单＝「成片」列一支算两支（批 I 口径）"
            assert o.hook_production_id is not None and o.composed_from_output_id is not None
            assert o.bucket == settings.MINIO_BUCKET_RAW
            assert o.file_key.startswith(f"asset/composed/{asset_code}/"), o.file_key
            assert (o.duration, o.resolution) == (16.08, "720x1280"), (o.duration, o.resolution)
            assert o.sha256 and len(o.sha256) == 64
            assert o.board_out_url is None, "拼出来的不是板上的东西，不许带 outUrl 去污染回收幂等"
        assert {o.composed_from_output_id for o in comp} == {o.id for o in raws}
        assert {o.hook_production_id for o in comp} == {uuid.UUID(i) for i in ids}

        # ③ 默认档＝钩子片在前：目标画幅跟钩子片（720 宽），两段都取回来了才有得拼
        assert len(calls) == 2, calls
        for c in calls:
            assert c["n_paths"] == 2 and c["first_is_hook"] is True, c
            assert c["target"]["width"] == 720, c

        # ④ 「可投放素材」＝ready：stage_compose 是五阶段里唯一靠拼接才点亮的那一个
        hook_row = await _row_of(AssetItem, asset_id)
        assert hook_row.stage_compose == "success" and hook_row.status == "ready"
        assert body["asset_status"][str(asset_id)] == "ready", body["asset_status"]

        # ⑤ 逐条审计＋0 元
        audits = await _rows(AuditLog, AuditLog.action == "asset.concat.auto")
        assert len(audits) == 2, len(audits)
        for a in audits:
            assert a.after["order"] == "hook_first" and a.after["cost"] == 0, a.after
            assert str(a.after["concat_asset_id"]) == material["id"]
            assert a.after["first"].startswith("钩子·7C0Q"), a.after
            assert "正文片段" in a.after["second"], a.after
        assert float((await _row_of(AssetItem, asset_id)).cost_prompt or 0) == 0.0

        # ⑥ 补帧：③b 排豆包成片、③c 排拼出来的产物，两次都在
        assert len(enq.await_args_list) == 2, [c.kwargs for c in enq.await_args_list]
        second = enq.await_args_list[1].kwargs
        assert second["why"].startswith("回收自动拼接") and second["asset_ids"] == []
        assert set(second["output_ids"]) == {str(o.id) for o in comp}, second

        # ⑦ 行上钉着的拼装要求＋「拼没拼」结果，接口必须带得出来（前端列读它）
        listed2 = (await client.get("/api/assets/productions",
                                    params={"asset_id": asset_id}, headers=ho)).json()["items"]
        assert len(listed2) == 2
        for r2 in listed2:
            assert r2["concat_asset_id"] == material["id"], r2
            assert r2["concat_order"] == "hook_first", r2
            assert r2["concat_last_result"]["status"] == "success", r2["concat_last_result"]
            assert r2["concat_last_result"]["ok"] == 1 and r2["concat_last_result"]["failed"] == 0
        await client.aclose()

    _run(_scenario())


def test_dispatch_auto_concat_material_first_swaps_the_front_segment():
    """`concat_order="material_first"`＝素材片段排最前，于是**目标画幅跟着素材走**。

    这是"选顺序"唯一的真实作用（11-04 口径）：把横屏片段放前面就出横屏框。
    顺带钉产物命名——两支片子拼一条，文件名必须同时点出编号和拼接素材，
    否则成片墙上几十个 `composed.mp4` 没人知道是哪条拼的哪条。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0Q3"])
        material = await _q_video_asset(client, hm, "片头彩蛋.mp4")

        calls: List[dict] = []
        fb = _FakeBoard()
        with _board_off(fb), _q_concat_off(calls):
            resp = await _dispatch(client, ho, [listed[0]["id"]],
                                   concat_asset_id=material["id"],
                                   concat_order="material_first")
        assert resp.status_code == 200, resp.text
        assert resp.json()["concat"]["composed"] == 1, resp.json()

        assert len(calls) == 1 and calls[0]["first_is_hook"] is False, calls
        assert calls[0]["target"]["width"] == 1280, "素材在前 → 画幅必须跟素材（横屏）"

        comp = [o for o in await _rows(AssetOutput) if o.kind == "composed"]
        assert len(comp) == 1
        assert "7C0Q3" in comp[0].file_name and material["code"] in comp[0].file_name
        row = await _row_of(AssetProduction, listed[0]["id"])
        assert row.concat_order == "material_first"
        assert row.concat_last_result["order"] == "material_first"
        audit = (await _rows(AuditLog, AuditLog.action == "asset.concat.auto"))[-1]
        assert audit.after["order"] == "material_first"
        assert audit.after["first"].startswith(f"{material['code']}·"), audit.after
        await client.aclose()

    _run(_scenario())


def test_dispatch_auto_concat_refuses_bad_params_before_burning_the_pool():
    """拼装要求要是等回收到了才发现拼不了，号池已经烧了——所以全部在投出去**之前**挡。

    四张脸：图片素材／链接素材还没取回原片／素材不存在／顺序词不认识。
    话术与手工拼接口**共用 `_resolve_concat_input`**（口径只有一套），
    这里顺带钉住"一个包都没出网、一张单都没动"。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0Q4"])
        pid = listed[0]["id"]
        good = await _q_video_asset(client, hm, "能拼的片段.mp4")
        link_asset, _ = await _make_ready_asset(client, hm, url=DOUYIN_3)
        # 遗留图片素材行（11-25 批 W 起上传口收不了图，但库里的旧图行仍在，拼接口照样要挡）
        img_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetItem(
                id=img_id, media_kind="image", source_kind="file",
                file_name="角色卡.png", file_key="asset/2026/11/24/角色卡.png",
                bucket=settings.MINIO_BUCKET_RAW, created_by=None,
            ))
            await s.commit()
        img_id = str(img_id)

        fb = _FakeBoard()
        with _board_off(fb):
            cases = [
                ({"concat_asset_id": img_id}, 400, "是图片"),
                ({"concat_asset_id": link_asset}, 400, "/assets/resolve"),
                ({"concat_asset_id": str(uuid.uuid4())}, 404, "不存在"),
                ({"concat_asset_id": good["id"], "concat_order": "middle"}, 400, "拼接顺序只能是"),
            ]
            for extra, want, needle in cases:
                r = await _dispatch(client, ho, [pid], **extra)
                assert r.status_code == want, (extra, r.status_code, r.text)
                assert needle in r.json()["detail"], (extra, r.json()["detail"])
            assert fb.creates == [], "被拦下的拼装要求一个包都不许出网"

        row = await _row_of(AssetProduction, pid)
        assert row.status == PR_ORDER_READY and row.concat_asset_id is None
        assert await _count(AssetOutput) == 0
        await client.aclose()

    _run(_scenario())


def test_dispatch_auto_concat_failure_never_downgrades_the_recovery():
    """拼不上 ≠ 回收失败：片子是真金白银烧号池收回来的，产物照旧、状态照旧、成因写进行上。

    两种坏法分开测：ffmpeg **回错串**（原形状）和拼接那段**抛异常**（兜底形状）。
    混成一个"投递失败"会让人以为号池白烧，其实成片就在产物里，只是还得人工拼一遍。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0Q5"])
        material = await _q_video_asset(client, hm, "正文片段.mp4")

        calls: List[dict] = []
        fb = _FakeBoard()
        with _board_off(fb), _q_concat_off(calls, concat_return_error="ffmpeg 拼接失败（退出码 234）：Invalid argument"):
            resp = await _dispatch(client, ho, [listed[0]["id"]], concat_asset_id=material["id"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["succeeded"] == 1 and body["failed"] == 0, body
        assert body["concat"]["composed"] == 0 and body["concat"]["failed"] == 1, body["concat"]
        assert "失败 1 支" in body["message"], body["message"]

        outs = await _rows(AssetOutput)
        assert [o.kind for o in outs] == ["doubao_raw"], [(o.kind, o.file_key) for o in outs]
        row = await _row_of(AssetProduction, listed[0]["id"])
        assert row.status == PR_SUCCESS
        assert row.concat_last_result["status"] == "failed"
        assert "退出码 234" in row.concat_last_result["last_error"], row.concat_last_result
        hook_row = await _row_of(AssetItem, asset_id)
        assert hook_row.stage_compose != "success" and hook_row.status == "composing"
        assert await _rows(AuditLog, AuditLog.action == "asset.concat.auto") == []

        # 第二种坏法：抛异常（比如桶连不上），同一套 fail-soft，成因带上异常类型
        _a2, _s2, listed2 = await _order_ready_production(client, h, url=DOUYIN_3, n=1,
                                                          hook_codes=["7C0Q6"])
        calls.clear()
        fb2 = _FakeBoard()
        with _board_off(fb2), _q_concat_off(calls, concat_error="MinIO 连不上"):
            r2 = await _dispatch(client, ho, [listed2[0]["id"]], concat_asset_id=material["id"])
        assert r2.status_code == 200, r2.text
        assert r2.json()["succeeded"] == 1, r2.json()
        row2 = await _row_of(AssetProduction, listed2[0]["id"])
        assert row2.status == PR_SUCCESS and row2.concat_last_result["status"] == "failed"
        assert "RuntimeError" in row2.concat_last_result["last_error"], row2.concat_last_result
        assert [o.kind for o in await _rows(AssetOutput)].count("composed") == 0
        await client.aclose()

    _run(_scenario())


def test_dispatch_auto_concat_pins_the_row_so_a_later_recover_still_composes():
    """接续回收（进程重启后 `recover_only=true` 再跑一次）也必须拼——靠钉在行上的两列。

    需求⑤那句「生成出来以后自动拼」里的"以后"是几十分钟：投板协程很可能不在了。
    拼装要求要是只活在请求里，重跑回收就会静默不拼，一线只能手工再拼一遍，
    而那正是需求⑤要消掉的那一步。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _sid, listed = await _order_ready_production(client, h, n=2, hook_codes=["7C0Q7", "7C0Q8"])
        material = await _q_video_asset(client, hm, "正文片段.mp4")
        ids = [p["id"] for p in listed]

        fb = _FakeBoard(status_fn=lambda created_index, read_round: "waiting")
        # ── 第一轮：板子还在跑，一支都没到手 → 什么都没拼，但拼装要求已经钉在行上 ──
        with _board_off(fb), _q_concat_off([]):
            first = await _dispatch(client, ho, ids, concat_asset_id=material["id"])
        assert first.status_code == 200, first.text
        b1 = first.json()
        assert b1["succeeded"] == 0 and b1["still_running"] == 2, b1
        assert b1["concat"]["attempted"] == 0 and b1["concat"]["composed"] == 0, b1["concat"]
        for pid in ids:
            p = await _row_of(AssetProduction, pid)
            # 板面非终态 → 单标 running（正在出片），既没判死也没到期
            assert p.status == PR_RUNNING and str(p.concat_asset_id) == material["id"]
            assert p.concat_order == "hook_first" and p.concat_last_result is None
        assert await _count(AssetOutput) == 0

        # ── 第二轮：只回读回收，请求里**一个字都不带**，拼不拼全看行上那两列 ──
        fb.status_fn = lambda created_index, read_round: "succ"
        calls: List[dict] = []
        with _board_off(fb), _q_concat_off(calls):
            again = await _dispatch(client, ho, ids, recover_only=True)
        assert again.status_code == 200, again.text
        b2 = again.json()
        assert b2["recovered"] == 2 and b2["succeeded"] == 2, b2
        assert b2["concat"]["composed"] == 2, b2["concat"]
        assert len(calls) == 2 and all(c["first_is_hook"] for c in calls), calls
        comp = [o for o in await _rows(AssetOutput) if o.kind == "composed"]
        assert len(comp) == 2, [o.kind for o in await _rows(AssetOutput)]
        assert (await _row_of(AssetItem, asset_id)).status == "ready"
        await client.aclose()

    _run(_scenario())


def test_auto_concat_idempotency_and_names_every_skip_reason():
    """幂等键与三条"跳过"成因（素材被删／挑的是图片／成片没落桶）只能在这里钉。

    为什么直接调 `_auto_concat_recovered` 而不走接口：这三条在**接口层已经被 400 挡掉**
    （见上一条用例），能真的走到这里的只有"投出去之后那行才坏掉"那种事后变化——
    而幂等键命中的场景（同一支被重跑两次）在 HTTP 面上更是走不到
    （成功的单再点投递会被闸门挡回 order_ready 不让重建）。这两个分支是**兜底的那一道**，
    平时看不见，一旦回收被重跑就会变成"同一条片子拼出两遍"，所以必须单独钉住。
    """
    from app.api import assets as assets_api

    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7C0Q9"])
        pid = listed[0]["id"]
        material = await _q_video_asset(client, hm, "正文片段.mp4")
        # 遗留图片素材行（批 W 起上传口收不了图；自动拼对旧图行的"是图片"拦截照旧要钉）
        img_id = uuid.uuid4()
        async with dbmod.async_session_factory() as s:
            s.add(AssetItem(
                id=img_id, media_kind="image", source_kind="file",
                file_name="角色卡.png", file_key="asset/2026/11/24/角色卡.png",
                bucket=settings.MINIO_BUCKET_RAW, created_by=None,
            ))
            await s.commit()
        img_id = str(img_id)

        # 手工造两支"已经回收落库的豆包成片"＋把拼装要求钉在生产单上（等价于投板成功之后）。
        # 第二支专门给后面三条"跳过"成因用：幂等预查排在最前，同一支只会回 already。
        async with dbmod.async_session_factory() as s:
            prod = await s.get(AssetProduction, uuid.UUID(pid))
            prod.concat_asset_id = uuid.UUID(material["id"])
            prod.concat_order = "hook_first"
            raw = AssetOutput(production_id=prod.id, asset_id=prod.asset_id, kind="doubao_raw",
                              file_key="asset/board/q/v1.mp4", bucket=settings.MINIO_BUCKET_RAW,
                              file_name="v1.mp4", duration=10.08, resolution="720x1280",
                              board_out_url="/out/T000009.mp4")
            s.add(raw)
            raw2 = AssetOutput(production_id=prod.id, asset_id=prod.asset_id, kind="doubao_raw",
                               file_key="asset/board/q/v2.mp4", bucket=settings.MINIO_BUCKET_RAW,
                               file_name="v2.mp4", duration=10.08, resolution="720x1280",
                               board_out_url="/out/T000010.mp4")
            s.add(raw2)
            await s.commit()
            raw_id, raw2_id = str(raw.id), str(raw2.id)

        ok_rec = {"file_key": "asset/board/q/v1.mp4", "bucket": settings.MINIO_BUCKET_RAW,
                  "file_name": "v1.mp4", "_output_id": raw_id, "_inserted": True}
        rec2 = {"file_key": "asset/board/q/v2.mp4", "bucket": settings.MINIO_BUCKET_RAW,
                "file_name": "v2.mp4", "_output_id": raw2_id, "_inserted": True}

        async def _auto(rec: Dict[str, Any], *, concat_id=None) -> Dict[str, Any]:
            async with dbmod.async_session_factory() as s:
                p = await s.get(AssetProduction, uuid.UUID(pid))
                if concat_id is not None:
                    p.concat_asset_id = uuid.UUID(str(concat_id))
                    await s.commit()
                operator = (await s.execute(
                    select(User).where(User.username == OPERATOR_USER))).scalar_one()
                outcome = {"prods": {str(p.id): p},
                           "outputs": [dict(rec, production_id=str(p.id))]}
                out = await assets_api._auto_concat_recovered(s, outcome, operator=operator)
                await s.commit()
                return out

        calls: List[dict] = []
        with _q_concat_off(calls):
            # ① 正常拼一条（作为后面三段的对照：幂等键就是它留下的）
            n1 = await _auto(ok_rec)
            assert n1["composed"] == 1 == len(calls), n1
            comp_ids = {o.id for o in await _rows(AssetOutput) if o.kind == "composed"}
            assert len(comp_ids) == 1

            # ② 同一支再来一次 → 幂等键命中：不拼第二遍，也不算失败
            n2 = await _auto(ok_rec)
            assert (n2["already"], n2["composed"], n2["failed"]) == (1, 0, 0), n2
            assert len(calls) == 1, "幂等命中时不许再碰一次 ffmpeg"
            assert "此前已拼" in n2["note"], n2["note"]
            assert {o.id for o in await _rows(AssetOutput) if o.kind == "composed"} == comp_ids
            assert (await _row_of(AssetProduction, pid)).concat_last_result["status"] == "already"

            # ③ 成片没有落桶路径（回收那步就没成）→ 点名这条，不开 ffmpeg
            n3 = await _auto({k: v for k, v in rec2.items() if k != "file_key"})
            assert n3["failed"] == 1 and "没有落桶路径" in n3["results"][0]["error"], n3

            # ④ 拼接素材换成了图片（事后改行才会有的形状）→ 白话理由，与手工口同一句
            n4 = await _auto(rec2, concat_id=img_id)
            assert n4["failed"] == 1 and "是图片" in n4["results"][0]["error"], n4

            # ⑤ 拼接素材整行没了（被删）→ 说"已不在库里"，别让人以为是 ffmpeg 坏了
            n5 = await _auto(rec2, concat_id=uuid.uuid4())
            assert n5["failed"] == 1 and "已不在库里" in n5["results"][0]["error"], n5
            assert (await _row_of(AssetProduction, pid)).concat_last_result["status"] == "failed"

        # 全程只拼成过那一条，失败的四次一条都没留下产物、也没留下审计
        assert len(calls) == 1, "四条跳过的成因里不许有一次真去开 ffmpeg"
        assert [o.kind for o in await _rows(AssetOutput)].count("composed") == 1
        assert len(await _rows(AuditLog, AuditLog.action == "asset.concat.auto")) == 1
        await client.aclose()

    _run(_scenario())


def test_fanout_preview_shows_replaced_text_and_matches_produce():
    """11-10 用户口径「我刚选了几个元素，但是没有看到正文被替换的地方」→ 开单前先给人看换完长什么样。

    这一口的存在理由不是"多一个接口"，是**换词这件事必须在按「生成生产单」之前就能看见**。
    所以用例的重心全在"预览和开单是不是同一套口径"上：

    1. **同一引擎**：预览第 1 条的正文，必须与开单后落在生产单上的 `prompt_text` **逐字相同**
       （同稿、同值、同原值、且第一行不换号）——前端另拼一套字符串迟早和后端对不上，
       那时人在预览里看到的和投出去的是两份稿，比没有预览更坏；
    2. **0 元、不落库、不占号**：调模型的那个函数一旦被碰就直接炸，台账一张单也不许多出来；
    3. **拦人的判据同一条话术**：按行配对个数对不齐 → 预览与 produce 的 400 `detail` 完全相等；
    4. **风险词只说不拦**：预览 200 并把词列进 `risk_words`，produce 同样入参照样 400——
       人还在试词，不该被闸打死；真要投时那道闸还在原地；
    5. 没有原值 → 这一条不换，并在 `missing` 里点名（不许出一张"看起来换过了"的假稿）。
    """
    _run(_bootstrap())

    async def _scenario():
        from app.api import assets as assets_api  # noqa: F401  （取上限常量，别把 50 写死在测试里）
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        base_prompt = "\n".join([
            "【第 1 段 · 建议 10 秒 · 本钩共 1 条 · 编号 7D0B1】",
            "剧情：【前3秒】河边，一只猫开口让他赶紧出门。【后7秒】河边，他撬开水泥管。",
            "镜头：河边用侧四十五度中近景。",
        ])
        base_titles = ["7D0B1·河边猫开口了", "备用标题"]
        values = {"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["黄鼠狼"]}
        base = {"a_scene": "河边", "a_animal": "猫"}

        # ── ① 同一引擎：拿开单后的真稿逐字比 ──
        # 原型名要拿**字典里的全名**（「原型 A：非人物件 / 动物开口说话…」）：扇出只换
        # 适用该原型的参数项，名字给错＝槽位集体不适用＝预览一片"没认出值"，看着像接口坏了。
        cats = (await client.get("/api/assets/categories", headers=hm)).json()["items"]
        cat_a_row = [c for c in cats if c["name"].startswith("原型 A：")]
        assert len(cat_a_row) == 1, cats
        cat_a, cat_name = cat_a_row[0]["id"], cat_a_row[0]["name"]
        asset_id, _ = await _make_ready_asset(client, hm, category_id=cat_a)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        r = await client.post(
            "/api/assets/prompt-elements/fanout-preview",
            json={"texts": {sid: base_prompt}, "category": cat_name,
                  "values": values, "base": base},
            headers=ho,
        )
        assert r.status_code == 200, r.text
        pv = r.json()
        assert pv["rows"] == 2 and pv["mode"] == "zip", pv
        assert len(pv["items"]) == 1 and pv["items"][0]["id"] == sid, pv
        variants = pv["items"][0]["variants"]
        assert [v["seq"] for v in variants] == [1, 2]
        assert variants[0]["values"]["a_scene"] == "建筑工地"
        assert "建筑工地" in variants[0]["text"] and "河边" not in variants[0]["text"]
        assert "繁华大街" in variants[1]["text"]
        assert all("黄鼠狼" in v["text"] and "一只猫" not in v["text"] for v in variants), \
            "只填一个值的参数每行复用同一个（zip 口径）"
        assert variants[0]["changed"] is True and variants[0]["missing"] == []

        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt=base_prompt, expand_titles=base_titles)):
            r = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1,
                "hook_codes": ["7D0B1", "7D0B2"],
                "element_values": values, "element_base": base,
            }, headers=ho)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 2
        got = sorted(await _rows(AssetProduction), key=lambda x: x.seq)
        assert variants[0]["text"] == got[0].prompt_text, (
            "预览与开单必须逐字同稿（同一个 expand_matrix＋compose_variants）："
            f"\n预览：{variants[0]['text']!r}\n开单：{got[0].prompt_text!r}"
        )
        # 第 2 条只差"编号换成本行自己的号"——那是 produce 的扇出口干的（板面按标题回收），
        # 预览不带号也带不了，除此之外一个字都不许多改。
        assert variants[1]["text"].replace("7D0B1", "7D0B2") == got[1].prompt_text, (
            f"\n预览：{variants[1]['text']!r}\n开单：{got[1].prompt_text!r}"
        )

        # ── ② 0 元、不落库、不占号 ──
        calls = []

        async def _boom(*a, **k):
            calls.append(1)
            raise AssertionError("预览口不许碰模型（碰一次＝烧一次钱）")

        before = await _count(AssetProduction)
        summaries_before = await _count(AssetSummary)
        spare = str(uuid.uuid4())
        with patch("app.api.assets._call_autoclip", _boom):
            r = await client.post(
                "/api/assets/prompt-elements/fanout-preview",
                json={"texts": {spare: base_prompt},
                      "values": {"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["狗", "黄鼠狼"]},
                      "base": {**base, "a_animal": "猫"},
                      "mode": "product"},
                headers=hm,
            )
        assert r.status_code == 200, r.text
        assert calls == [], "预览走的是纯字面替换，一次模型都不该调"
        assert r.json()["rows"] == 4, "全组合＝2 场景 × 2 动物"
        assert "×".join(["2", "2"]) in r.json()["notes"][0], r.json()["notes"]
        assert await _count(AssetProduction) == before, "预览不建单、不占号、不落库"
        assert await _count(AssetSummary) == summaries_before, "预览也不该造文案行"

        # ── ③ 配对不齐：预览与开单同一条 400 话术（人在预览里就该看到，不该等提交才挨打）──
        bad_values = {"a_scene": ["建筑工地", "繁华大街"], "a_animal": ["狗", "黄鼠狼", "猫"]}
        r1 = await client.post("/api/assets/prompt-elements/fanout-preview",
                               json={"texts": {sid: base_prompt}, "values": bad_values, "base": base},
                               headers=ho)
        assert r1.status_code == 400 and "对不齐" in r1.json()["detail"], r1.text
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt=base_prompt, expand_titles=base_titles)):
            r2 = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1, "element_values": bad_values, "element_base": base,
            }, headers=ho)
        assert r2.status_code == 400, r2.text
        assert r1.json()["detail"] == r2.json()["detail"], (
            f"同一个错两处话术不一样，一线就分不清是预览坏了还是开单坏了：\n{r1.json()}\n{r2.json()}"
        )
        assert await _count(AssetProduction) == before

        # ── ④ 风险词：预览只说不拦，produce 照旧拦 ──
        await client.put("/api/assets/risk-lexicon",
                         json={"block": ["黄鼠狼"], "warn": [], "exempt": {}, "inherit": False},
                         headers=h["admin"])
        r = await client.post("/api/assets/prompt-elements/fanout-preview",
                              json={"texts": {sid: base_prompt}, "values": values, "base": base},
                              headers=ho)
        assert r.status_code == 200, r.text
        assert any("黄鼠狼" in w and "高风险词" in w for w in r.json()["risk_words"]), r.json()
        with patch("app.api.assets._call_autoclip",
                   _fake_autoclip(expand_prompt=base_prompt, expand_titles=base_titles)):
            r = await client.post("/api/assets/produce", json={
                "summary_ids": [sid], "n": 1, "element_values": values, "element_base": base,
            }, headers=ho)
        assert r.status_code == 400 and "高风险词" in r.json()["detail"], r.text
        assert await _count(AssetProduction) == before
        await client.put("/api/assets/risk-lexicon",
                         json={"block": [], "warn": [], "exempt": {}, "inherit": True},
                         headers=h["admin"])

        # ── ⑤ 没有原值：这一条不换，但必须点名（出一张"看着换过了"的假稿比不给看更坏）──
        r = await client.post("/api/assets/prompt-elements/fanout-preview",
                              json={"texts": {sid: base_prompt}, "values": {"a_scene": ["海底"]}},
                              headers=ho)
        assert r.status_code == 200, r.text
        v0 = r.json()["items"][0]["variants"][0]
        assert v0["text"] == base_prompt and v0["changed"] is False
        assert v0["missing"] == ["场景"], v0
        assert any("没有原值" in n for n in v0["notes"]), v0["notes"]

        # ── ⑥ 上限与权限：和抽元素同一套（50 条封顶、未登录 401）──
        r = await client.post(
            "/api/assets/prompt-elements/fanout-preview",
            json={"texts": {str(uuid.uuid4()): base_prompt
                            for _ in range(assets_api._MAX_EXTRACT_ITEMS + 1)}, "values": values},
            headers=ho,
        )
        assert r.status_code == 400 and "分批" in r.json()["detail"], r.text
        r = await client.post("/api/assets/prompt-elements/fanout-preview",
                              json={"texts": {sid: base_prompt}, "values": values})
        assert r.status_code == 401, r.text
        await client.aclose()

    _run(_scenario())


# ────────────────  24. 职能闸与成片打包合同（2026-11-11 七席评审·测试席 P0） ────────────────
#
# 这两块是本轮改动里**唯一零覆盖**的口子，也是评审给测试席打 6/10 的直接原因：
#   · `require_functions` 刚从 `getattr(user, fn, True)`（列缺失静默放行）改成直接访问列，
#     改完没有任何用例证明四个端点各认各的列、admin 恒过、关掉再打开真的可逆；
#   · `POST /assets/outputs/package` 本轮重写过（下载移出事务、CA bundle 强校验、
#     manifest 补对账主键、包名带日期条数、单支失败 502 点名），此前一条断言都没有。
# 判据都写成「关掉会怎样」而不是「代码长这样」——列改错名、闸门口径漂了，测试必须先红。


async def _set_flags(username: str, **flags):
    """按用户名改 users.can_review / can_produce（岗位隔离的唯一入口＝管理员改这两列）。"""
    async with dbmod.async_session_factory() as s:
        u = (await s.execute(select(User).where(User.username == username))).scalar_one()
        for k, v in flags.items():
            setattr(u, k, v)
        await s.commit()


async def _approved_summary(client, h, url):
    """造一条**已过审**的文案并返回 (asset_id, summary_id)：职能闸用例的正向腿要用它。"""
    aid, _ = await _make_ready_asset(client, h["material"], url)
    items, _ = await _gen_and_list(aid, h["material"], client)
    sid = _approvable(items)["id"]
    r = await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=h["admin"])
    assert r.status_code == 200, r.text
    return aid, sid


def test_function_flags_gate_the_four_endpoints_and_are_reversible():
    """can_review / can_produce 两列真的是闸：各认各的端点、admin 恒过、关→开立刻可用。

    钉五件事（评审 2026-11-11 测试席 P0 的原始问句：「把 getattr 去掉之后，谁保证闸还在？」）：
    ① 关 can_review ⇒ 审核口 403，且**库里状态没动**（拦在写库之前，不是写完再报错）；
    ② 关 can_review **不牵连**投产/导出/投板（它们读的是 can_produce）——
       投产口照常干活，错误话术是业务侧的「文案未过审」，不是「未启用审核职能」；
       （实测合同：投产口对未过审文案返回 **200 信封 + results[].error**，整单不抛 400）
    ③ 关 can_produce ⇒ 投产、导出、投板三口**全部** 403 且一张单都不落
       （投板口连 `is_configured()` 都没走到：闸在外部动作之前）；
    ④ 打开即恢复：同一个请求、同一份入参，200 可用——防「写死一句 403」的假闸门；
    ⑤ admin 恒过：把管理员的两列一起关掉，过审与投产照旧 200（岗位隔离不拆管理员）。
    403 文案还得点名是哪项职能，否则一线只知道被拦、不知道该找谁开。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, had = h["material"], h["operator"], h["admin"]
        aid, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(aid, hm, client)
        sid = _approvable(items)["id"]

        # ── ① 审核闸：403 + 库里没动 ──
        await _set_flags(OPERATOR_USER, can_review=False)
        blocked = await client.post("/api/assets/summaries/review",
                                    json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        assert blocked.status_code == 403, blocked.text
        msg = blocked.json()["detail"]
        assert "审核（质检）" in msg and "职能" in msg, msg
        assert (await _row_of(AssetSummary, sid)).audit_status == RV_PENDING, "拦在写库之前：状态还是待审"

        # ── ② 不牵连：can_review 关着，投产口照常过闸，拿到的是业务话术而不是「未启用审核职能」──
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            not_review = await client.post("/api/assets/produce",
                                           json={"summary_ids": [sid], "n": 1, "async_mode": False},
                                           headers=ho)
        # 实测口径（本轮把它钉下来）：投产口对**未过审文案**不抛 400，而是 200 信封 +
        # results[].error 逐条说明。所以这里的判据只能是「没被审核职能闸拦掉」＋「一单没建」，
        # 断状态码 400 是把业务实现当成合同，将来把逐条失败改成整单 400 反而会误红。
        assert not_review.status_code == 200, not_review.text
        body = not_review.json()
        assert "职能" not in str(body), body
        assert body["created"] == 0, "文案还在待审，不该借这条腿建单"
        assert any("未过审" in str(r.get("error")) for r in body["results"]), body

        # ── ④ 打开即恢复（同一份入参再来一次就是 200）──
        await _set_flags(OPERATOR_USER, can_review=True)
        again = await client.post("/api/assets/summaries/review",
                                  json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        assert again.status_code == 200, again.text
        assert again.json()["results"][0]["ok"] is True, again.json()
        assert (await _row_of(AssetSummary, sid)).audit_status == RV_APPROVED

        # ── ③ 投产闸：三口一起拦，且一张单都不落 ──
        await _set_flags(OPERATOR_USER, can_produce=False)
        orders_before = await _count(AssetProduction)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            p = await client.post("/api/assets/produce",
                                  json={"summary_ids": [sid], "n": 1, "async_mode": False}, headers=ho)
        assert p.status_code == 403, p.text
        assert "投产（挑选、投板）" in p.json()["detail"], p.json()["detail"]
        assert await _count(AssetProduction) == orders_before, "闸在建单之前：关掉不该留半张单"

        e = await client.get("/api/assets/productions/export", headers=ho)
        assert e.status_code == 403 and "投产" in e.json()["detail"], e.text

        # 投板口：闸必须走在 `is_configured()` 和任何板侧动作之前（拿不存在的 id 也拦得住）
        d = await client.post("/api/assets/productions/dispatch",
                              json={"ids": [str(uuid.uuid4())], "confirm": True}, headers=ho)
        assert d.status_code == 403, d.text
        assert "自动投板还没启用" not in d.json()["detail"], "先过闸再谈凭据：外部动作一步都不该碰"

        # ── ④′ 打开：投产 200、导出 200、投板拿到的是凭据话术（说明闸真的让开了）──
        await _set_flags(OPERATOR_USER, can_produce=True)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            ok = await client.post("/api/assets/produce",
                                   json={"summary_ids": [sid], "n": 1, "async_mode": False}, headers=ho)
        assert ok.status_code == 200, ok.text
        prod = (await _rows(AssetProduction, AssetProduction.asset_id == uuid.UUID(aid)))[0]
        ex = await client.get(f"/api/assets/productions/export?ids={prod.id}", headers=ho)
        assert ex.status_code == 200, ex.text
        with patch("app.services.aivideo_board.is_configured", return_value=False):
            dd = await client.post("/api/assets/productions/dispatch",
                                   json={"ids": [str(prod.id)], "confirm": True}, headers=ho)
        assert dd.status_code == 400 and "自动投板还没启用" in dd.json()["detail"], dd.text

        # ── ⑤ admin 恒过：两列全关也不拦（岗位隔离不拆管理员）──
        await _set_flags(ADMIN_USER, can_review=False, can_produce=False)
        aid2, sid2 = await _approved_summary(client, h, DOUYIN_3)
        assert (await _row_of(AssetSummary, sid2)).audit_status == RV_APPROVED, "admin 关列也应能过审"
        orders_before_admin = await _count(AssetProduction)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            admin_produce = await client.post("/api/assets/produce",
                                              json={"summary_ids": [sid2], "n": 1, "async_mode": False},
                                              headers=had)
        assert admin_produce.status_code == 200, admin_produce.text
        assert admin_produce.json()["created"] == 1, admin_produce.json()
        # 基线取「admin 这一枪之前」而不是 orders_before：④′ 里 operator 已经建过一张了
        assert await _count(AssetProduction) == orders_before_admin + 1
        await client.aclose()

    _run(_scenario())


def test_outputs_package_contract_manifest_and_ca_bundle():
    """成片打包口的合同：入参形状、验收闸门、manifest 对账主键、包名、CA bundle、单支失败。

    为什么每条都值得钉（评审 2026-11-11 测试席 P0＋安全席 P2＋业务席 P1）：
    ① `ids` 用 `Body(..., embed=True)` ⇒ 必须是 `{"ids":[…]}`。裸数组是 422——
       前端当年就是按裸数组写的，接口照样挂着，**没有一条断言会红**；
    ② 验收 failed 的单条下载口拦、打包口也必须拦（409 并点名是哪条），
       否则「一条废片混在包里发出去」这条路是通的；勾选里全查不到 ⇒ 404 而不是空包；
    ③ manifest 是发布侧「下载即落位」的输入：`production_id`（＝板侧 reqID，对账主键）、
       `board_tid`、`hook_code`、`asset_title` 少一个就要人肉改名贴标题；
    ④ 包名带日期与条数（同一周打多个包要对得上批次）；
    ⑤ 本轮把 `verify=False` 换成自签 CA bundle：bundle 有值时 httpx **必须拿到它**，
       没值时退回 `False`（本地 HTTP 部署零变化）——写死任何一个都不算这条纪律；
    ⑥ 单支 presign 失败 ⇒ 502 点名到哪一支，且**不产出半个包**（打包是原子的）。
    """
    _run(_bootstrap())

    import httpx
    import io as _io
    import time as _time
    import zipfile

    payload = b"FAKE-MP4-BYTES"
    seen_kwargs: list = []

    class _PkgResp:
        content = payload

        def raise_for_status(self):
            return None

    def _client_factory(recorder):
        class _Client:
            def __init__(self, **kwargs):
                recorder.append(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                return _PkgResp()

        return _Client

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        aid, sid = await _approved_summary(client, h, DOUYIN_2)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            r = await client.post("/api/assets/produce",
                                  json={"summary_ids": [sid], "n": 1, "async_mode": False},
                                  headers=h["admin"])
        assert r.status_code == 200, r.text
        prod = (await _rows(AssetProduction))[0]
        # 板侧对账主键直接钉进库（投板链路有专项用例，本口只管"能不能带出去"）
        async with dbmod.async_session_factory() as s:
            p = await s.get(AssetProduction, prod.id)
            p.hook_code, p.board_tid = "8PZ12", "TID-9527"
            p.video_titles = ["总裁摘下手表坐在塑料凳上吃泡面"]
            await s.commit()

        async def _add(qc, name):
            oid = uuid.uuid4()
            async with dbmod.async_session_factory() as s:
                s.add(AssetOutput(
                    id=oid, production_id=prod.id, asset_id=uuid.UUID(aid),
                    kind="doubao_raw", file_key=f"asset-out/{oid}.mp4",
                    bucket=settings.MINIO_BUCKET_SLICED, file_name=name,
                    qc_status=qc, qc_note="字幕压脸" if qc == "failed" else None,
                    duration=11.0, resolution="720x1280",
                ))
                await s.commit()
            return str(oid)

        good = await _add("passed", "解压片A.mp4")
        bad = await _add("failed", "解压片B.mp4")

        http_ns = SimpleNamespace(AsyncClient=_client_factory(seen_kwargs), HTTPError=httpx.HTTPError)
        presign = AsyncMock(return_value="http://minio:9000/o/clip.mp4?sig=abc")
        with patch("app.api.assets.get_presigned_url", presign), \
             patch("app.api.assets.extra_ca_bundle_path",
                   return_value="/etc/clip/self-signed-ca.pem"), \
             patch("app.api.assets.httpx", http_ns):

            # ── ②′ 形状回归：裸数组必须 422（embed=True 的合同）──
            bare = await client.post("/api/assets/outputs/package", json=[good], headers=hm)
            assert bare.status_code == 422, bare.text

            # ── ② 空勾选/全查不到：404，不是 200 空包 ──
            none = await client.post("/api/assets/outputs/package",
                                     json={"ids": [str(uuid.uuid4())]}, headers=hm)
            assert none.status_code == 404, none.text

            # ── ② 混进一条废片：409 点名，且不改投出去任何东西 ──
            mixed = await client.post("/api/assets/outputs/package",
                                      json={"ids": [good, bad]}, headers=hm)
            assert mixed.status_code == 409, mixed.text
            assert "验收不合格" in mixed.json()["detail"] and "解压片B" in mixed.json()["detail"], mixed.text

            # ── ①③④⑤ 正向腿：zip 内容、manifest 合同、包名、CA bundle ──
            ok = await client.post("/api/assets/outputs/package", json={"ids": [good]}, headers=hm)
            assert ok.status_code == 200, ok.text
            assert ok.headers["content-type"] == "application/zip", ok.headers
            cd = ok.headers["content-disposition"]
            assert f"-1items.zip" in cd and _time.strftime("%m%d") in cd, cd
            with zipfile.ZipFile(_io.BytesIO(ok.content)) as zf:
                names = set(zf.namelist())
                assert names == {"解压片A.mp4", "manifest.json"}, names
                assert zf.read("解压片A.mp4") == payload
                manifest = json.loads(zf.read("manifest.json"))
            assert manifest["exported_by"] == MATERIAL_USER, manifest
            assert len(manifest["items"]) == 1, manifest
            item = manifest["items"][0]
            asset_row = await _row_of(AssetItem, aid)
            assert item["production_id"] == str(prod.id), item       # 板侧 reqID＝对账主键
            assert item["board_tid"] == "TID-9527", item
            assert item["hook_code"] == "8PZ12", item
            assert item["asset_title"] == asset_row.title, item
            assert item["recommended_title"] == "总裁摘下手表坐在塑料凳上吃泡面", item
            assert item["qc_status"] == "passed" and item["duration"] == 11.0, item
            assert item["thumb_url"] is None, item                  # 没抽帧就照实说没有
            # 归属人灰字：`_user_names` 返回的键是 str(uuid)，拿 UUID 去 get 会静默 None
            # ——这条断言专门钉那个键型（正向腿过审＋投产都是 admin 账号）
            assert item["produced_by"] == "管理员", item
            assert item["reviewed_by"] == "管理员", item
            assert seen_kwargs and seen_kwargs[-1]["verify"] == "/etc/clip/self-signed-ca.pem", seen_kwargs
            assert seen_kwargs[-1]["timeout"] == 300, seen_kwargs
            assert presign.await_count >= 1

            # ── ⑥ 单支 presign 失败：502 点名，不产出半个包 ──
            presign.return_value = None
            broken = await client.post("/api/assets/outputs/package", json={"ids": [good]}, headers=hm)
            assert broken.status_code == 502, broken.text
            assert "解压片A.mp4" in broken.json()["detail"], broken.text
            assert not (broken.content[:2] == b"PK"), "失败不该吐半个 zip"

        # ── ⑤ 反面：bundle 缺失（本地 HTTP 部署）必须退回 verify=False，且功能不变 ──
        seen2: list = []
        with patch("app.api.assets.get_presigned_url", AsyncMock(return_value="http://minio:9000/o/a.mp4")), \
             patch("app.api.assets.extra_ca_bundle_path", return_value=""), \
             patch("app.api.assets.httpx",
                   SimpleNamespace(AsyncClient=_client_factory(seen2), HTTPError=httpx.HTTPError)):
            plain = await client.post("/api/assets/outputs/package", json={"ids": [good]}, headers=hm)
        assert plain.status_code == 200, plain.text
        assert seen2[-1]["verify"] is False, seen2

        # ── 下载口不是只有 admin 能用：交付口全员可达（与 11-03 可见范围口径一致）──
        audits = await _rows(AuditLog, AuditLog.action == "asset.outputs_package")
        # 留痕＝两次成功打包（废片那次 409、presign 失败那次 502 都不该写审计）
        assert len(audits) == 2, f"打包是交付动作，必须留痕：{[a.after for a in audits]}"
        await client.aclose()

    _run(_scenario())


# ═════════════════════════════════════════════════════════════════════════════════════
#  极简模式 S1/S2（2026-11-23）：脚本库＋界面偏好
#
#  用户原话：「个人可自定义脚本库，把想要的脚本添加到个人脚本库，并可打开脚本修改。」
#            「勾选脚本（打开个人脚本库可一次多选）→上传三视图→豆包生成视频（生成数量可选）」
#
#  这里的「脚本」＝直接投给豆包的成品提示词，不是钩子文案（不过 ≤80 字形态闸、不展开）。
#  钉五件事：①定稿即冻结、派生不覆盖；②同一人不留两条同内容定稿；③生产载体默认不进
#  五环的 ②③ 列表、也不能拿 script_texts 绕过复核；④轻量过审的角色/职能/自审闸与审核口
#  同口径、且响应逐条带 ok（HTTP 200 ≠ 全过）；⑤投产走同一个 produce＋dispatch，
#  不调模型展开、成片照进成片墙。
# ═════════════════════════════════════════════════════════════════════════════════════

_SCRIPT_URL = "/api/assets/scripts"
_SCRIPT_BODY = (
    "镜头1：清晨的小巷，一个穿灰外套的女孩推开木门。"
    "镜头2：她抬头，看见墙上挂着一张泛黄的照片。"
    "镜头3：她伸手取下照片，笑了笑。"
)


def _block_word() -> str:
    return svc.DEFAULT_RISK_LEXICON[svc.RISK_LEVEL_BLOCK][0]


async def _mk_script(client, h, name="灰外套女孩", body=None, **extra):
    """新建一条脚本（断言成功），返回响应体。"""
    r = await client.post(
        _SCRIPT_URL,
        json={"name": name, "body": body or _SCRIPT_BODY, "source_kind": "manual", **extra},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _finalize(client, h, sid, **extra):
    return await client.post(f"{_SCRIPT_URL}/{sid}/finalize", json=extra, headers=h)


async def _ready_and_approved(client, h_owner, h_approver, name="待投脚本"):
    """走到「已定稿＋已过审」，返回 (脚本行, 载体 id)。"""
    s = await _mk_script(client, h_owner, name=name)
    fin = await _finalize(client, h_owner, s["id"])
    assert fin.status_code == 200, fin.text
    ap = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [s["id"]]}, headers=h_approver)
    assert ap.status_code == 200 and ap.json()["results"][0]["ok"] is True, ap.text
    return ap.json()["results"][0]


def test_script_library_crud_finalize_fork_and_retire():
    """脚本库基本盘：建/列/详/改/定稿/派生/下架——定稿即冻结，改定稿＝派生新草稿。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]

        # 新建（201）＋ 同内容再建幂等（200 回原行，不堆重复）
        s = await _mk_script(client, ho)
        assert s["state"] == "draft" and s["reused"] is False and s["body"] == _SCRIPT_BODY
        again = await client.post(
            _SCRIPT_URL, json={"name": "换个名字也是同一篇", "body": _SCRIPT_BODY}, headers=ho)
        assert again.status_code == 200, again.text
        assert again.json()["reused"] is True and again.json()["id"] == s["id"]

        # 列表不随正文（只给预览＋字数）；默认只看自己的，owner=all 看所有人的
        mine = await client.get(_SCRIPT_URL, headers=ho)
        assert mine.json()["total"] == 1
        item = mine.json()["items"][0]
        assert "body" not in item and item["preview"] and item["body_chars"] > 0
        assert item["state_label"] == "库稿" and item["owner_name"]
        assert (await client.get(_SCRIPT_URL, headers=hm)).json()["total"] == 0
        all_view = await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=hm)
        assert all_view.json()["total"] == 1 and all_view.json()["items"][0]["owner_id"] != ""

        # 详情带全文（读全员可见）
        one = await client.get(f"{_SCRIPT_URL}/{s['id']}", headers=hm)
        assert one.status_code == 200 and one.json()["body"] == _SCRIPT_BODY

        # 入参校验：空名 422 / 超长正文 413 / 不存在的原型 400 / 不认的来源 400
        assert (await client.post(_SCRIPT_URL, json={"name": " ", "body": "x"}, headers=ho)).status_code == 422
        assert (await client.post(
            _SCRIPT_URL, json={"name": "长", "body": "字" * 20001}, headers=ho)).status_code == 413
        assert (await client.post(
            _SCRIPT_URL, json={"name": "原型", "body": "x", "category_id": str(uuid.uuid4())},
            headers=ho)).status_code == 400
        assert (await client.post(
            _SCRIPT_URL, json={"name": "来源", "body": "x", "source_kind": "reverse"},
            headers=ho)).status_code == 400

        # 改草稿（原地）；别人不能改
        up = await client.put(
            f"{_SCRIPT_URL}/{s['id']}", json={"name": "改名了", "note": "给自己看的备注"}, headers=ho)
        assert up.status_code == 200 and up.json()["name"] == "改名了" and up.json()["forked"] is False
        assert (await client.put(
            f"{_SCRIPT_URL}/{s['id']}", json={"name": "乱改"}, headers=hm)).status_code == 403

        # 定稿 → 可投稿；重复定稿幂等
        fin = await _finalize(client, ho, s["id"])
        assert fin.status_code == 200 and fin.json()["state"] == "ready" and fin.json()["reused"] is False
        fin2 = await _finalize(client, ho, s["id"])
        assert fin2.status_code == 200 and fin2.json()["reused"] is True

        # 定稿后改正文＝派生新草稿（201），原稿一字不动；重复派生幂等（200 回同一条）
        new_body = _SCRIPT_BODY + "镜头4：她把照片放进口袋。"
        fork = await client.put(f"{_SCRIPT_URL}/{s['id']}", json={"body": new_body}, headers=ho)
        assert fork.status_code == 201, fork.text
        fk = fork.json()
        assert fk["forked"] is True and fk["state"] == "draft" and fk["based_on_script_id"] == s["id"]
        assert fk["id"] != s["id"]
        fork2 = await client.put(f"{_SCRIPT_URL}/{s['id']}", json={"body": new_body}, headers=ho)
        assert fork2.status_code == 200 and fork2.json()["id"] == fk["id"]
        origin = await client.get(f"{_SCRIPT_URL}/{s['id']}", headers=ho)
        assert origin.json()["state"] == "ready" and origin.json()["body"] == _SCRIPT_BODY

        # 别人也能基于它派生自己的草稿（读全员可见，派生不用问人）
        fork_m = await client.put(f"{_SCRIPT_URL}/{s['id']}", json={}, headers=hm)
        assert fork_m.status_code == 201 and fork_m.json()["state"] == "draft"
        assert fork_m.json()["name"].endswith("（副本）")

        # 下架＝软删；幂等；默认列表不再回它，显式点名才回
        assert (await client.delete(f"{_SCRIPT_URL}/{fk['id']}", headers=ho)).json()["state"] == "retired"
        assert (await client.delete(f"{_SCRIPT_URL}/{fk['id']}", headers=ho)).status_code == 200
        assert (await client.get(_SCRIPT_URL, headers=ho)).json()["total"] == 1
        gone = await client.get(_SCRIPT_URL, params={"state": "retired"}, headers=ho)
        assert gone.json()["total"] == 1 and gone.json()["items"][0]["id"] == fk["id"]
        # 已下架的不能再改、不能再定稿
        assert (await client.put(f"{_SCRIPT_URL}/{fk['id']}", json={"name": "x"}, headers=ho)).status_code == 409
        assert (await _finalize(client, ho, fk["id"])).status_code == 409

        # 审计：定稿动作留了改前原文（strict），谁点的查得到
        logs = [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.finalize")
                if str(a.target_id) == s["id"] and not (a.after or {}).get("reused_script_id")]
        assert logs and logs[0].after["state"] == "ready" and logs[0].after["body"] == _SCRIPT_BODY
        assert logs[0].operator_name == OPERATOR_USER
        # 管理员代改别人的要留痕（admin_edit）
        admin_edit = await client.put(f"{_SCRIPT_URL}/{fork_m.json()['id']}", json={"name": "管理员改的"}, headers=ha)
        assert admin_edit.status_code == 200 and admin_edit.json()["name"] == "管理员改的"
        alog = [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.update")
                if str(a.target_id) == fork_m.json()["id"]]
        assert alog and alog[-1].after.get("admin_edit") is True
        await client.aclose()

    _run(_scenario())


def test_script_finalize_blocks_risk_words_and_keeps_one_ready_per_body():
    """定稿的两道硬闸：风险词 block 命中即 409；同一人不留两条内容相同的可投稿脚本
    （应用层幂等＋库级部分唯一索引兜底并发）。"""
    _run(_bootstrap())

    async def _scenario():
        from app.models.asset import SCRIPT_DRAFT, SCRIPT_READY, SCRIPT_RETIRED, AssetScript
        from sqlalchemy import exc as saexc

        client, h = await _client_and_headers()
        ho = h["operator"]

        # ① 风险词 block：命中即拦，点名是哪个词，状态不变
        bad = await _mk_script(client, ho, name="含险词", body=f"镜头1：这个药能{_block_word()}所有病。")
        fin = await _finalize(client, ho, bad["id"])
        assert fin.status_code == 409 and _block_word() in fin.json()["detail"], fin.text
        assert (await client.get(f"{_SCRIPT_URL}/{bad['id']}", headers=ho)).json()["state"] == "draft"

        # ② 同内容定稿去重：先有一条定稿 Y；另一条草稿原地改成 Y 再定稿 → 回已有的那条
        y_body = _SCRIPT_BODY + "（Y 版）"
        first = await _mk_script(client, ho, name="Y 定稿", body=y_body)
        assert (await _finalize(client, ho, first["id"])).json()["state"] == "ready"
        second = await _mk_script(client, ho, name="先叫 Z", body=_SCRIPT_BODY + "（Z 版）")
        assert second["id"] != first["id"]
        assert (await client.put(
            f"{_SCRIPT_URL}/{second['id']}", json={"body": y_body}, headers=ho)).status_code == 200
        twin = await _finalize(client, ho, second["id"])
        assert twin.status_code == 200 and twin.json()["reused"] is True
        assert twin.json()["id"] == first["id"]
        # 那条重复草稿随之收起（不堆两条一样的可投稿脚本）
        assert (await client.get(f"{_SCRIPT_URL}/{second['id']}", headers=ho)).json()["state"] == "retired"

        # ③ 库级兜底：绕过接口直接插第二条同 (owner, body_hash) 的 ready 行 → 撞唯一索引；
        #    草稿不受这条索引约束（派生草稿在改字前与母稿逐字相同是正常的）
        ready = (await _rows(AssetScript, AssetScript.id == uuid.UUID(first["id"])))[0]
        async with dbmod.async_session_factory() as s:
            s.add(AssetScript(owner_id=ready.owner_id, name="并发撞车", body=y_body,
                              state=SCRIPT_READY, body_hash=ready.body_hash))
            try:
                await s.flush()
                await s.commit()
                raised = False
            except saexc.IntegrityError:
                raised = True
                await s.rollback()
        assert raised, "同一个人第二条同内容 ready 行必须被唯一索引挡下"
        async with dbmod.async_session_factory() as s:
            s.add(AssetScript(owner_id=ready.owner_id, name="重复草稿", body=y_body,
                              state=SCRIPT_DRAFT, body_hash=ready.body_hash))
            await s.commit()   # 草稿重复：不报错
        await client.aclose()

    _run(_scenario())


def test_script_carrier_is_hidden_from_five_rings_and_cannot_bypass_recheck():
    """生产载体不是钩子文案：五环的 ②③ 列表默认看不到它；也不能拿 script_texts 把普通
    过审文案当成脚本绕过投产前复核。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        cats = (await client.get("/api/assets/categories", headers=ho)).json()["items"]
        cat_id = next(c["id"] for c in cats if c.get("active", True))

        pend_before = (await client.get(
            "/api/assets/summaries", params={"audit_status": "pending", "page_size": 1}, headers=ho)).json()["total"]
        assets_before = (await client.get("/api/assets", params={"page_size": 200}, headers=ho)).json()["total"]

        s = await _mk_script(client, ho, category_id=cat_id)
        assert (await _finalize(client, ho, s["id"])).status_code == 200
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=ho)
        assert sub.status_code == 200 and sub.json()["results"][0]["ok"] is True, sub.text
        carrier_id = sub.json()["results"][0]["carrier_summary_id"]
        row = (await _rows(AssetSummary, AssetSummary.id == uuid.UUID(carrier_id)))[0]

        # 审核列表：默认看不到载体（角标不受污染）；显式 include_carriers 才回
        hidden = await client.get(
            "/api/assets/summaries", params={"asset_id": str(row.asset_id)}, headers=ho)
        assert hidden.json()["total"] == 0, hidden.text
        shown = await client.get(
            "/api/assets/summaries",
            params={"asset_id": str(row.asset_id), "include_carriers": "true"}, headers=ho)
        assert shown.json()["total"] == 1 and shown.json()["items"][0]["id"] == carrier_id
        pend_after = (await client.get(
            "/api/assets/summaries", params={"audit_status": "pending", "page_size": 1}, headers=ho)).json()["total"]
        assert pend_after == pend_before, "送审一条脚本不该让五环的「等审核」角标 +1"

        # 素材列表：壳默认不出现
        assert (await client.get("/api/assets", params={"page_size": 200}, headers=ho)).json()["total"] == assets_before
        with_shell = await client.get(
            "/api/assets", params={"page_size": 200, "include_carriers": "true"}, headers=ho)
        assert str(row.asset_id) in {a["id"] for a in with_shell.json()["items"]}
        # 原型字典的引用计数不把载体算进去
        cat_after = {c["id"]: c for c in (await client.get("/api/assets/categories", headers=ho)).json()["items"]}
        assert cat_after[cat_id].get("asset_count", 0) == next(
            c for c in cats if c["id"] == cat_id).get("asset_count", 0)

        # 过审后，载体仍不出现在「已过审」挑选列表里（对它做 autoclip 展开＝把脚本当文案展开）
        ap = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [s["id"]]}, headers=ho)
        assert ap.json()["results"][0]["ok"] is True, ap.text
        approved = await client.get(
            "/api/assets/summaries", params={"audit_status": "approved", "page_size": 300}, headers=ho)
        assert carrier_id not in {x["id"] for x in approved.json()["items"]}

        # 绕过尝试一：不带 script_texts、直接对载体调普通投产口 → 400，两种形态都拒
        #   （expand=false 会建出没有正文的裸单；expand=true 会把整篇脚本当钩子文案送去展开）
        #   ⚠️ 这条用例的脚本只有 60 字、能过 ≤80 字形态闸——所以拦住它的**不能是形态闸**，
        #   必须是「脚本载体只认脚本直投」这道闸本身（首跑时这里真的建出了单，才补的闸）。
        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as expand_spy:
            bare = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [carrier_id], "n": 1, "expand": False,
                      "hook_codes": ["7Z901"], "async_mode": False},
                headers=ho)
            expanded = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [carrier_id], "n": 1, "hook_codes": ["7Z905"], "async_mode": False},
                headers=ho)
            async_mode = await client.post(
                "/api/assets/produce",
                json={"summary_ids": [carrier_id], "n": 1, "hook_codes": ["7Z906"], "async_mode": True},
                headers=ho)
        for refused in (bare, expanded, async_mode):
            assert refused.status_code == 400, refused.text
            assert "脚本的生产载体" in refused.json()["detail"]
        assert expand_spy.call_count == 0, "被拒的那几次不许真的去调模型展开"
        assert (await _count(AssetProduction)) == 0, "被拒的那几次一张单都不许落库"

        # 绕过尝试二：给一条**不挂在任何脚本上的裸候选**塞 script_texts → 400（键必须是脚本载体）。
        # 批 AC 起，凡进过脚本库的候选（送审壳 or 出文案/导入镜像）都是合法直投键——只要投的是
        # 它的过审正文（绕过三钉逐字比对）。这里先把挂在这条候选上的脚本行全摘掉，
        # 测的就是「没进过脚本库 → 不许把 script_texts 当绕展开的后门」这道闸本身。
        asset_id, _sid, listed = await _order_ready_production(client, h, n=1, hook_codes=["7Z902"])
        carrier_text = (await _rows(AssetSummary, AssetSummary.id == uuid.UUID(carrier_id)))[0].text
        normal_sid = str((await _row_of(AssetProduction, uuid.UUID(listed[0]["id"]))).summary_id)
        async with dbmod.async_session_factory() as s:
            from app.models.asset import AssetScript as _AS
            orphans = (await s.execute(
                select(_AS).where(_AS.carrier_summary_id == uuid.UUID(normal_sid))
            )).scalars().all()
            for o in orphans:
                await s.delete(o)
            await s.commit()
        not_carrier = await client.post(
            "/api/assets/produce",
            json={"summary_ids": [normal_sid], "n": 1, "script_texts": {normal_sid: carrier_text},
                  "hook_codes": ["7Z903"], "async_mode": False},
            headers=ho)
        assert not_carrier.status_code == 400 and "不是已定稿脚本的生产载体" in not_carrier.json()["detail"]

        # 绕过尝试三：载体的投递正文与过审正文不一致 → 400（审的必须就是投的）
        mismatch = await client.post(
            "/api/assets/produce",
            json={"summary_ids": [carrier_id], "n": 1, "expand": False,
                  "script_texts": {carrier_id: carrier_text + "偷偷加一句"},
                  "hook_codes": ["7Z904"], "async_mode": False},
            headers=ho)
        assert mismatch.status_code == 400 and "不一致" in mismatch.json()["detail"]
        await client.aclose()

    _run(_scenario())


def test_script_submit_approve_follows_review_role_and_self_review_knob():
    """轻量过审与审核口同口径：角色/职能闸、自审闸读同一个旋钮、审计同一个动作名；
    响应逐条带 ok（没定稿的要如实说，不能让人以为整批都过了）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]

        # 素材专员能建稿、能定稿、能送审；但没有审核职能 → approve 403
        s = await _mk_script(client, hm, name="素材专员的脚本")
        assert (await _finalize(client, hm, s["id"])).status_code == 200
        forbidden = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [s["id"]]}, headers=hm)
        assert forbidden.status_code == 403, forbidden.text
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=hm)
        assert sub.status_code == 200 and sub.json()["results"][0]["audit_status"] == "pending", sub.text
        # 幂等：再送一次不新建载体
        again = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=hm)
        assert again.json()["submitted"] == 0
        assert again.json()["results"][0]["carrier_summary_id"] == sub.json()["results"][0]["carrier_summary_id"]

        # 运营在「待过审」里看得到同事送来的脚本
        pending = await client.get(
            _SCRIPT_URL, params={"owner": "all", "carrier_status": "pending"}, headers=ho)
        assert pending.json()["total"] == 1 and pending.json()["items"][0]["id"] == s["id"]

        # 运营自己送审自己的脚本：旋钮关 → 自审被拦（逐条 ok:false ＋ 错误码）；旋钮开 → 放行并留痕
        mine = await _mk_script(client, ho, name="运营自己的脚本", body=_SCRIPT_BODY + "（运营版）")
        assert (await _finalize(client, ho, mine["id"])).status_code == 200
        assert (await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [mine["id"]]}, headers=ho)).status_code == 200
        saved = settings.ASSET_SELF_PRODUCE_ALLOWED
        try:
            settings.ASSET_SELF_PRODUCE_ALLOWED = False
            blocked = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [mine["id"]]}, headers=ho)
            r0 = blocked.json()["results"][0]
            assert blocked.status_code == 200 and r0["ok"] is False, blocked.text
            assert r0["error_code"] == "ASSET_SELF_REVIEW_BLOCKED"
        finally:
            settings.ASSET_SELF_PRODUCE_ALLOWED = saved
        ok = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [mine["id"], s["id"]]}, headers=ho)
        assert ok.status_code == 200, ok.text
        assert [r["ok"] for r in ok.json()["results"]] == [True, True]
        # 再点一次：已过审的如实回 already，不重复写审计
        repeat = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [mine["id"]]}, headers=ho)
        assert repeat.json()["results"][0]["ok"] is True and repeat.json()["results"][0]["already"] is True

        # 审计：与审核口同一个动作名（admin 撤审抽检靠它），带 via/script/self_review 标记
        logs = [a for a in await _rows(AuditLog, AuditLog.action == "asset.summary_review.approve")
                if (a.after or {}).get("via") == "simple_script"]
        assert len(logs) == 2
        self_log = next(a for a in logs if str(a.target_id) == sub.json()["results"][0]["carrier_summary_id"])
        assert self_log.after["self_review"] is None, "运营审素材专员送来的不算自审"
        mine_log = next(a for a in logs if a.target_id != self_log.target_id)
        assert mine_log.after["self_review"]["self"] is True
        assert mine_log.after["script"]["id"] == mine["id"]

        # 没定稿的脚本 approve：逐条 ok:false，HTTP 仍是 200（所以界面必须念出失败条数）
        draft = await _mk_script(client, ho, name="没定稿", body=_SCRIPT_BODY + "（没定稿）")
        mixed = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [draft["id"], mine["id"]]}, headers=ho)
        assert mixed.status_code == 200
        assert mixed.json()["results"][0]["ok"] is False and "还没定稿" in mixed.json()["results"][0]["error"]
        assert "未通过 1 条" in mixed.json()["message"]
        # 载体在库里的审核态确实变了（审的＝投的那一版）
        rows = {str(r.id): r for r in await _rows(AssetSummary)}
        assert rows[sub.json()["results"][0]["carrier_summary_id"]].audit_status == RV_APPROVED
        assert rows[sub.json()["results"][0]["carrier_summary_id"]].reviewed_by is not None
        await client.aclose()

    _run(_scenario())


def test_script_batch_review_cap_is_review_pane_300_not_50():
    """批 AB（11-25 用户「批量审核通过去掉50条限制」）：送审/轻量过审单次上限
    从 50 抬到与审核台批量审核同口径的 300——一屏全选 51 条一把过不能再被入口
    拒掉；301 条才提示分批（防一次点穿整个库把几百次载体补建塞进同一同步请求）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        # 51 个不存在的 id：不再整口 400（旧上限 50 就是在这里拒的），
        # 放进闸门后逐条 ok:false（不在库里），HTTP 200——口径与真脚本混批一致
        ids51 = [str(uuid.uuid4()) for _ in range(51)]
        ap = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": ids51}, headers=ho)
        assert ap.status_code == 200, ap.text
        assert len(ap.json()["results"]) == 51
        assert all(not r["ok"] and "不在库里" in r["error"] for r in ap.json()["results"])
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": ids51}, headers=ho)
        assert sub.status_code == 200 and len(sub.json()["results"]) == 51, sub.text
        # 301 条仍然入口拒，且话术念的是新数
        ids301 = [str(uuid.uuid4()) for _ in range(301)]
        big = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": ids301}, headers=ho)
        assert big.status_code == 400 and "300" in big.text, big.text
        await client.aclose()

    _run(_scenario())


def test_script_batch_retire_soft_deletes_own_and_names_others():
    """批 AB-2（11-25 用户「素材库增加批量删除」）：批量下架＝软删，与逐行「下架」同一颗内核。

    钉四件事：①自己的草稿/定稿混批都能删，列表按 retired 显式点名才回；
    ②别人的删不动——逐条点名，**删成的不连带回滚**（HTTP 200＋逐条 ok，界面必须念未成数）；
    ③幂等：已下架的再点还是 ok（带 already）；admin 可代删；
    ④上限沿用 _SCRIPT_BATCH_MAX（300，与送审/过审同口径），空名单入口就拒。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]

        mine1 = await _mk_script(client, hm, name="批量删我1")          # 草稿
        # 正文必须与 mine1 不同：create 对同内容幂等，会返回同一行（撞车过一次才发现）
        mine2 = await _mk_script(client, hm, name="批量删我2",          # 定稿
                                 body=_SCRIPT_BODY + "镜头4：她把照片放回原处，关上门。")
        assert (await _finalize(client, hm, mine2["id"])).status_code == 200
        theirs = await _mk_script(client, ho, name="不是我写的")
        assert len({mine1["id"], mine2["id"], theirs["id"]}) == 3, "三条必须各不相同行"

        # 空名单＝入口拒（与 approve/submit 同一句话术风格）
        empty = await client.post(f"{_SCRIPT_URL}/retire", json={"script_ids": []}, headers=hm)
        assert empty.status_code == 400 and "点名" in empty.text, empty.text

        # 混批：自己 2 ＋ 别人 1 ＋ 不存在的 id 1
        r = await client.post(
            f"{_SCRIPT_URL}/retire",
            json={"script_ids": [mine1["id"], mine2["id"], theirs["id"], str(uuid.uuid4())]},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        by = {x["script_id"]: x for x in r.json()["results"]}
        assert by[mine1["id"]]["ok"] and by[mine2["id"]]["ok"], r.text
        assert by[theirs["id"]]["ok"] is False and "另存为草稿" in by[theirs["id"]]["error"], r.text
        assert "下架 2 条" in r.json()["message"] and "未成 2 条" in r.json()["message"], r.json()["message"]

        # 删生效：默认列表不回，显式 state=retired 才回；别人的那条照旧在池子里
        gone = await client.get(_SCRIPT_URL, params={"state": "retired"}, headers=hm)
        gone_ids = {x["id"] for x in gone.json()["items"]}
        assert {mine1["id"], mine2["id"]} <= gone_ids and theirs["id"] not in gone_ids, gone.json()
        assert (await client.get(f"{_SCRIPT_URL}/{theirs['id']}", headers=ho)).json()["state"] != "retired"

        # 幂等：已下架的再点还是 ok，带 already
        again = await client.post(f"{_SCRIPT_URL}/retire", json={"script_ids": [mine1["id"]]}, headers=hm)
        row = again.json()["results"][0]
        assert again.status_code == 200 and row["ok"] and row.get("already"), again.text

        # admin 可代删别人的（审计 batch/admin_edit 在后端口里写）
        adm = await client.post(f"{_SCRIPT_URL}/retire", json={"script_ids": [theirs["id"]]}, headers=ha)
        assert adm.status_code == 200 and adm.json()["results"][0]["ok"], adm.text

        # 上限 301 入口拒，话术念的是新数
        big = await client.post(
            f"{_SCRIPT_URL}/retire", json={"script_ids": [str(uuid.uuid4()) for _ in range(301)]}, headers=ha
        )
        assert big.status_code == 400 and "300" in big.text, big.text
        await client.aclose()

    _run(_scenario())


def test_script_produce_dispatches_to_board_without_model_expansion():
    """屏 2「投豆包」：已定稿脚本 → 一脚本一单 → 直投板上，不调模型展开。

    草稿仍拒投；别人已定稿/已过审的脚本无需跨人确认即可投产，
    实际操作人、脚本作者与候选审核人都保留在审计/归属字段里。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        taken: List[int] = []

        async def fake_take(n):
            taken.append(n)
            return ([f"7Z5{i:02d}" for i in range(1, n + 1)], [], None)

        s = await _mk_script(client, hm, name="要投的脚本")

        fb = _FakeBoard()
        with _board_off(fb), patch("app.api.assets._take_hook_codes", fake_take), \
                patch("app.api.assets._call_autoclip", _fake_autoclip()) as expand:
            # ① 草稿仍拒投：不取号、不建单，也不伪造人工审核。
            early = await client.post(f"{_SCRIPT_URL}/produce", json={"script_ids": [s["id"]]}, headers=ho)
            assert early.status_code == 400 and "还没定稿" in early.json()["detail"], early.text
            assert taken == []
            assert await _count(AssetProduction) == 0
            assert [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.direct_ready")] == []

            assert (await _finalize(client, hm, s["id"])).status_code == 200
            # ② 管理员过审 → 运营投同事的稿：无需跨人确认，直接建单并取号。
            ap = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [s["id"]]}, headers=ha)
            assert ap.json()["results"][0]["ok"] is True, ap.text
            cross = await client.post(
                f"{_SCRIPT_URL}/produce",
                json={"script_ids": [s["id"]], "board_total": 2}, headers=ho)
            assert cross.status_code == 200, cross.text
            body = cross.json()
            assert taken == [1] and len(body["production_ids"]) == 1
            assert not {"capacity_hint", "board_capacity", "capacity"} & body.keys(), body
            assert not {"capacity_hint", "board_capacity", "capacity"} & body["dispatch"].keys(), \
                body["dispatch"]
            r0 = body["results"][0]
            assert r0["ok"] is True and r0["hook_code"] == "7Z501" and r0["production_id"]
            assert body["dispatch"]["queued"] is True and body["dispatch"]["job_id"]

            # 生产单：正文＝脚本正文（没有模型展开）、板上出 2 版、板面名＝脚本名、不是试产
            prod = await _row_of(AssetProduction, uuid.UUID(r0["production_id"]))
            assert prod.prompt_text == _SCRIPT_BODY and prod.prompt_snapshot == _SCRIPT_BODY
            assert prod.board_total == 2 and prod.board_name and prod.is_trial is False
            ho_user = (await _rows(User, User.username == OPERATOR_USER))[0]
            hm_user = (await _rows(User, User.username == MATERIAL_USER))[0]
            ha_user = (await _rows(User, User.username == ADMIN_USER))[0]
            assert prod.created_by == ho_user.id and prod.hook_code == "7Z501"
            script_row = await _row_of(AssetScript, s["id"])
            carrier = await _row_of(AssetSummary, script_row.carrier_summary_id)
            assert script_row.owner_id == hm_user.id, "投产不转移脚本作者"
            assert carrier.reviewed_by == ha_user.id and carrier.reviewed_at is not None, \
                "候选审核人不能被直投动作抹掉"
            order_audits = [a for a in await _rows(AuditLog, AuditLog.action == "asset.produce_order")
                            if (a.after or {}).get("owner_cross")]
            order_audit = order_audits[-1]
            direct = order_audit.after["owner_cross"]["direct_scripts"][0]
            assert order_audit.operator_id == ho_user.id, "审计人记实际投产人"
            assert direct["script_id"] == s["id"] and direct["cross"] is True
            assert direct["owner_id"] == str(hm_user.id) and direct["owner_name"] == "素材专员"

            # 后台投板任务跑完：板上建了任务、提示词原样、成片进了成片墙
            job = await _wait_job(client, ho, body["dispatch"]["job_id"])
            assert job["status"] == "succeeded", job
            assert len(fb.creates) == 1 and fb.creates[0]["prompt"] == _SCRIPT_BODY
            assert int(fb.creates[0]["total"]) == 2
            assert prod.status in ("success",) or (await _row_of(AssetProduction, prod.id)).status == "success"
            outs = await client.get("/api/assets/outputs", params={"owner": "all", "limit": 10}, headers=ho)
            assert outs.json()["total"] == 2, outs.text
            assert all(o["kind"] == "doubao_raw" for o in outs.json()["items"])
            # 全程没调过模型展开（脚本本身就是提示词）
            assert expand.call_count == 0

            # ④ 留痕：脚本 → 生产单的对账链
            logs = [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.produce")]
            assert len(logs) == 1 and logs[0].after["production_ids"] == body["production_ids"]
            assert logs[0].after["hook_codes"] == ["7Z501"]
            # 留痕口径 11-25 起与导入/出文案那三个入口对齐：极简开单走的是「预取位」，
            # 一次烧号 = 一条 `hook_code.park`（里面带 codes 与 source），不再另写一条
            # `hook_code.take`——那会跟生产单落单时清槽的动作对不上。取号**整体失败**才写
            # take 失败留痕（见 test_script_produce_reuses_parked_hook_codes 的 ①）。
            park_logs = [a for a in await _rows(AuditLog, AuditLog.action == "asset.hook_code.park")
                         if (a.after or {}).get("source") == "auto_park:script_produce"]
            assert len(park_logs) == 1
            assert [c["hook_code"] for c in park_logs[0].after["summaries"]] == ["7Z501"]
            assert [a for a in await _rows(AuditLog, AuditLog.action == "asset.hook_code.take")
                    if (a.after or {}).get("via") == "script_produce"] == []

        # ⑤ 素材专员有关投产职能才可用；关掉即 403；⑥ 不存在的脚本 → 400
        await _set_flags(MATERIAL_USER, can_produce=False)
        assert (await client.post(
            f"{_SCRIPT_URL}/produce", json={"script_ids": [s["id"]]}, headers=hm)).status_code == 403
        ghost = await client.post(f"{_SCRIPT_URL}/produce", json={"script_ids": [str(uuid.uuid4())]}, headers=ho)
        assert ghost.status_code == 400 and ghost.json()["detail"].startswith("这几条还不能投")
        await client.aclose()

    _run(_scenario())


def test_material_produces_ready_script_without_review_and_keeps_guards():
    """素材专员定稿直投：无审核职能也无需送审；风险词、草稿、自审旋钮的边界仍保留。"""
    _run(_bootstrap())

    async def _scenario():
        from app.models.asset import AssetScript

        client, h = await _client_and_headers()
        hm = h["material"]
        await _set_flags(MATERIAL_USER, can_review=False, can_produce=True)
        taken: List[int] = []

        async def fake_take(n):
            taken.append(n)
            start = len(taken)
            return ([f"7Z6{i:02d}" for i in range(start, start + n)], [], None)

        mine = await _mk_script(client, hm, name="专员定稿直投")
        assert (await _finalize(client, hm, mine["id"])).status_code == 200
        risky_ready = await _mk_script(
            client, hm, name="定稿后词表变严", body=_SCRIPT_BODY + "镜头4：灰外套女孩停下脚步。")
        assert (await _finalize(client, hm, risky_ready["id"])).status_code == 200
        draft = await _mk_script(client, hm, name="还没定稿", body=_SCRIPT_BODY + "镜头4：她继续往前走。")

        fb = _FakeBoard()
        with _board_off(fb), patch("app.api.assets._take_hook_codes", fake_take), \
                patch("app.api.assets._call_autoclip", _fake_autoclip()) as expand, \
                patch.object(settings, "ASSET_SELF_PRODUCE_ALLOWED", False):
            res = await client.post(f"{_SCRIPT_URL}/produce", json={"script_ids": [mine["id"]]}, headers=hm)
            assert res.status_code == 200, res.text
            prod = await _row_of(AssetProduction, uuid.UUID(res.json()["results"][0]["production_id"]))
            assert prod.prompt_text == _SCRIPT_BODY and prod.created_by is not None
            assert (await _wait_job(client, hm, res.json()["dispatch"]["job_id"]))["status"] == "succeeded"
            assert expand.call_count == 0
            assert taken == [1]

            blocked_draft = await client.post(
                f"{_SCRIPT_URL}/produce", json={"script_ids": [draft["id"]]}, headers=hm)
            assert blocked_draft.status_code == 400 and "还没定稿" in blocked_draft.json()["detail"]
            assert taken == [1]

            await _write_lexicon({"block": ["灰外套"]})
            blocked_risk = await client.post(
                f"{_SCRIPT_URL}/produce", json={"script_ids": [risky_ready["id"]]}, headers=hm)
            assert blocked_risk.status_code == 400 and "灰外套" in blocked_risk.json()["detail"], blocked_risk.text
            assert taken == [1] and await _count(AssetProduction) == 1
            carrier = (await _row_of(AssetScript, uuid.UUID(risky_ready["id"]))).carrier_summary_id
            assert carrier is None, "风险词拦在取号与载体创建之前，不该留下待审载体"

            await _write_lexicon({"block": []})
            from app.api.assets.misc import _ensure_script_carrier
            async with dbmod.async_session_factory() as s:
                script_row = await s.get(AssetScript, uuid.UUID(risky_ready["id"]))
                operator = (await s.execute(select(User).where(User.username == MATERIAL_USER))).scalar_one()
                carrier = await _ensure_script_carrier(s, script_row, operator=operator)
                carrier.text = "这是待审载体的旧占位正文，不是定稿脚本正文。"
                await s.commit()
            retry = await client.post(
                f"{_SCRIPT_URL}/produce", json={"script_ids": [risky_ready["id"]]}, headers=hm)
            assert retry.status_code == 200, retry.text
            prod2 = await _row_of(AssetProduction, uuid.UUID(retry.json()["results"][0]["production_id"]))
            assert prod2.prompt_text == risky_ready["body"]
            assert (await _wait_job(client, hm, retry.json()["dispatch"]["job_id"]))["status"] == "succeeded"
            assert taken == [1, 1]

        direct_logs = [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.direct_ready")]
        assert len(direct_logs) == 2
        assert any((a.after or {}).get("text_changed") is True for a in direct_logs)
        assert all((a.after or {}).get("via") == "simple_script_direct_produce" for a in direct_logs)
        audit_before_fields = {
            "audit_status", "text", "word_count", "reviewed_by", "reviewed_at",
            "reject_reason", "resubmit_note", "risk_hit",
        }
        assert all(audit_before_fields <= set(a.before or {}) for a in direct_logs)
        assert [a for a in await _rows(AuditLog, AuditLog.action == "asset.summary_review.approve")] == []
        assert [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.submit")] == []

        human_self = await _mk_script(client, h["operator"], name="人工自审稿", body=_SCRIPT_BODY + "镜头4：她坐到窗边。")
        assert (await _finalize(client, h["operator"], human_self["id"])).status_code == 200
        approved = await client.post(
            f"{_SCRIPT_URL}/approve", json={"script_ids": [human_self["id"]]}, headers=h["operator"])
        assert approved.json()["results"][0]["ok"] is True, approved.text
        with patch.object(settings, "ASSET_SELF_PRODUCE_ALLOWED", False):
            self_blocked = await client.post(
                f"{_SCRIPT_URL}/produce", json={"script_ids": [human_self["id"]]}, headers=h["operator"])
        assert self_blocked.status_code == 400 and "自己过审" in self_blocked.json()["detail"], self_blocked.text
        assert taken == [1, 1] and await _count(AssetProduction) == 2
        await client.aclose()

    _run(_scenario())


def test_script_texts_cannot_bypass_pending_carrier_readiness():
    """待就绪载体不能绕过定稿直投口的风险复核、自动就绪与独立审计。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        s = await _mk_script(client, ho, name="本人待就绪载体", body=_SCRIPT_BODY + "镜头5：他停下脚步。")
        assert (await _finalize(client, ho, s["id"])).status_code == 200
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=ho)
        assert sub.status_code == 200 and sub.json()["results"][0]["ok"] is True, sub.text
        carrier_id = sub.json()["results"][0]["carrier_summary_id"]
        carrier_text = (await _row_of(AssetSummary, uuid.UUID(carrier_id))).text
        refused = await client.post(
            "/api/assets/produce",
            json={
                "summary_ids": [carrier_id], "n": 1, "expand": False,
                "script_texts": {carrier_id: carrier_text}, "hook_codes": ["7Z703"], "async_mode": False,
            },
            headers=ho,
        )
        assert refused.status_code == 400 and "生产载体尚未就绪" in refused.json()["detail"], refused.text
        assert await _count(AssetProduction) == 0
        assert not [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.direct_ready")]
        await client.aclose()

    _run(_scenario())


def test_script_produce_rereads_carrier_locked_after_manual_review_commit():
    """人工审核在初次读载体后提交：直投必须锁内重读，使用最新过审正文且不抹审核人。"""
    _run(_bootstrap())

    async def _scenario():
        from app.api.assets import misc as misc_mod
        from app.models.asset import AssetScript

        client, h = await _client_and_headers()
        ho = h["operator"]
        s = await _mk_script(client, ho, name="审核与直投竞态", body=_SCRIPT_BODY + "镜头5：他停下脚步。")
        assert (await _finalize(client, ho, s["id"])).status_code == 200
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=ho)
        assert sub.status_code == 200 and sub.json()["results"][0]["ok"] is True, sub.text
        carrier_id = uuid.UUID(sub.json()["results"][0]["carrier_summary_id"])
        human_text = _SCRIPT_BODY + "镜头6：这是人工审核提交的最新正文。"
        original = misc_mod._ensure_script_carrier

        async def review_between_reads(db, script, *, operator):
            stale = await original(db, script, operator=operator)
            async with dbmod.async_session_factory() as review_db:
                carrier = await review_db.get(AssetSummary, carrier_id)
                reviewer = (await review_db.execute(
                    select(User).where(User.username == OPERATOR_USER)
                )).scalar_one()
                carrier.text = human_text
                carrier.audit_status = RV_APPROVED
                carrier.reviewed_by = reviewer.id
                carrier.reviewed_at = datetime.utcnow()
                await review_db.commit()
            return stale

        fb = _FakeBoard()
        with _board_off(fb), patch.object(misc_mod, "_ensure_script_carrier", review_between_reads), \
                patch("app.api.assets._take_hook_codes", AsyncMock(return_value=(["7Z704"], [], None))), \
                patch("app.api.assets._call_autoclip", _fake_autoclip()) as expand:
            res = await client.post(f"{_SCRIPT_URL}/produce", json={"script_ids": [s["id"]]}, headers=ho)
            assert res.status_code == 200, res.text
            assert (await _wait_job(client, ho, res.json()["dispatch"]["job_id"]))["status"] == "succeeded"
            assert expand.call_count == 0

        prod = await _row_of(AssetProduction, uuid.UUID(res.json()["results"][0]["production_id"]))
        carrier = await _row_of(AssetSummary, carrier_id)
        assert prod.prompt_text == human_text
        assert fb.creates[0]["prompt"] == human_text
        assert carrier.text == human_text and carrier.audit_status == RV_APPROVED
        assert carrier.reviewed_by is not None and carrier.reviewed_at is not None
        assert not [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.direct_ready")]
        await client.aclose()

    _run(_scenario())


def test_script_texts_cannot_bypass_ready_state_and_preserve_ownership():
    """底层 script_texts 通道也不是后门：草稿/下架拒投；他人脚本无需确认可投且归属留痕。"""
    _run(_bootstrap())

    async def _scenario():
        from app.models.asset import SCRIPT_DRAFT, SCRIPT_RETIRED

        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        hm_user = (await _rows(User, User.username == MATERIAL_USER))[0]
        ho_user = (await _rows(User, User.username == OPERATOR_USER))[0]
        ha_user = (await _rows(User, User.username == ADMIN_USER))[0]
        s = await _mk_script(client, hm, name="同事的定稿", body=_SCRIPT_BODY + "镜头4：她走进屋里。")
        assert (await _finalize(client, hm, s["id"])).status_code == 200
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=ho)
        carrier_id = sub.json()["results"][0]["carrier_summary_id"]
        carrier_text = (await _row_of(AssetSummary, uuid.UUID(carrier_id))).text

        approved = await client.post(f"{_SCRIPT_URL}/approve", json={"script_ids": [s["id"]]}, headers=ha)
        assert approved.json()["results"][0]["ok"] is True, approved.text

        # ① 极简脚本直投：同事已定稿/已过审的脚本无需跨人确认即可建单。
        # 板凭据故意关掉，只验证建单；真实投板链路由专项直投用例覆盖。
        with patch("app.api.assets._take_hook_codes", AsyncMock(return_value=(["7Z700"], [], None))), \
                patch("app.services.aivideo_board.is_configured", return_value=False):
            direct = await client.post(
                f"{_SCRIPT_URL}/produce", json={"script_ids": [s["id"]]}, headers=ho)
        assert direct.status_code == 200, direct.text
        direct_body = direct.json()
        assert len(direct_body["production_ids"]) == 1
        assert direct_body["dispatch"]["queued"] is False, "没配板凭据只降级投板，不否定已建生产单"
        assert not {"capacity_hint", "board_capacity", "capacity"} & direct_body.keys(), direct_body
        direct_prod = await _row_of(AssetProduction, uuid.UUID(direct_body["production_ids"][0]))
        assert direct_prod.created_by == ho_user.id
        assert await _count(AssetProduction) == 1
        direct_audits = await _rows(AuditLog, AuditLog.action == "asset.script.produce")
        assert direct_audits[-1].operator_id == ho_user.id

        # ② 完整模式 script_texts 同路投产：无需确认，作者/审核人仍保留。
        payload = {
            "summary_ids": [carrier_id], "n": 1, "expand": False,
            "script_texts": {carrier_id: carrier_text}, "hook_codes": ["7Z701"], "async_mode": False,
        }
        bypass = await client.post("/api/assets/produce", json=payload, headers=ha)
        assert bypass.status_code == 200 and bypass.json()["created"] == 1, bypass.text
        assert not {"capacity_hint", "board_capacity", "capacity"} & bypass.json().keys(), bypass.json()
        assert await _count(AssetProduction) == 2

        script_row = await _row_of(AssetScript, s["id"])
        carrier = await _row_of(AssetSummary, uuid.UUID(carrier_id))
        assert script_row.owner_id == hm_user.id, "投产不转移脚本作者"
        assert carrier.reviewed_by == ha_user.id and carrier.reviewed_at is not None, \
            "候选审核人不能被直投动作抹掉"
        order_audits = [a for a in await _rows(AuditLog, AuditLog.action == "asset.produce_order")
                        if (a.after or {}).get("owner_cross")]
        order_audit = order_audits[-1]
        direct_meta = order_audit.after["owner_cross"]["direct_scripts"][0]
        assert order_audit.operator_id == ha_user.id, "审计人记实际投产人"
        assert direct_meta["script_id"] == s["id"] and direct_meta["cross"] is True
        assert direct_meta["owner_id"] == str(hm_user.id) and direct_meta["owner_name"] == "素材专员"
        assert not [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.direct_ready")], \
            "已人工过审的脚本不再伪装成自动就绪"

        # ③ 状态闸仍在：草稿/下架脚本即使走 script_texts 也不能投产。
        for state in (SCRIPT_DRAFT, SCRIPT_RETIRED):
            async with dbmod.async_session_factory() as sess:
                row = await sess.get(AssetScript, uuid.UUID(s["id"]))
                row.state = state
                await sess.commit()
            refused = await client.post(
                "/api/assets/produce",
                json={**payload, "hook_codes": ["7Z702"]}, headers=ho)
            assert refused.status_code == 400 and "不是已定稿脚本" in refused.json()["detail"], refused.text
            assert await _count(AssetProduction) == 2
        await client.aclose()

    _run(_scenario())


def test_script_save_from_asset_is_free_and_rejects_without_reverse_draft():
    """「钩子视频导入 → 反推 → 收进脚本库」的后半段：读库里已有的反推稿（0 元）；
    素材还没有可用反推稿时如实拒绝并说清下一步。"""
    _run(_bootstrap())

    async def _scenario():
        from app.models.asset import AssetScript

        client, h = await _client_and_headers()
        hm = h["material"]
        custom_script = "镜头1：雨夜的便利店，男孩把伞递给女孩。" + "（专属反推稿）"
        asset_id, _task = await _make_ready_asset(client, hm, script=custom_script, category_id=None)
        got = await client.post(f"{_SCRIPT_URL}/save-from-asset", json={"asset_id": asset_id}, headers=hm)
        assert got.status_code == 201, got.text
        row = got.json()
        assert row["source_kind"] == "reverse" and row["body"] == custom_script and row["state"] == "draft"
        assert row["origin_asset_id"] == asset_id and row["reused"] is False
        # 幂等：同一条素材再收一次 → 回原行
        twice = await client.post(f"{_SCRIPT_URL}/save-from-asset", json={"asset_id": asset_id}, headers=hm)
        assert twice.status_code == 200 and twice.json()["id"] == row["id"]

        # 素材还没反推过 → 404 ＋ 下一步
        resp = await _import(client, hm, [DOUYIN_1])
        bare = resp.json()["items"][0]["id"]
        none = await client.post(f"{_SCRIPT_URL}/save-from-asset", json={"asset_id": bare}, headers=hm)
        assert none.status_code == 404 and "还没反推过" in none.json()["detail"], none.text
        assert (await client.post(
            f"{_SCRIPT_URL}/save-from-asset", json={"asset_id": str(uuid.uuid4())}, headers=hm)).status_code == 404

        # 素材被强制删除后脚本还在（这正是脚本不挂在候选文案上的原因）
        stored = (await _rows(AssetScript, AssetScript.id == uuid.UUID(row["id"])))[0]
        assert stored.origin_asset_id == uuid.UUID(asset_id)
        await client.aclose()

    _run(_scenario())


def test_ui_preferences_default_by_role_and_roundtrip():
    """极简开关＝用户级偏好：没存过按角色给默认值（运营＝极简、管理员＝全量），存了就跨设备生效。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho, ha = h["operator"], h["admin"]

        op_default = (await client.get("/api/assets/ui/preferences", headers=ho)).json()["ui_config"]
        ad_default = (await client.get("/api/assets/ui/preferences", headers=ha)).json()["ui_config"]
        assert op_default["asset_library_mode"] == "simple"
        assert ad_default["asset_library_mode"] == "full"

        saved = await client.put(
            "/api/assets/ui/preferences", json={"ui_config": {"asset_library_mode": "full"}}, headers=ho)
        assert saved.status_code == 200 and saved.json()["ui_config"]["asset_library_mode"] == "full"
        assert (await client.get("/api/assets/ui/preferences", headers=ho)).json()["ui_config"][
            "asset_library_mode"] == "full"
        # 只动自己那一行：管理员的不受影响
        assert (await client.get("/api/assets/ui/preferences", headers=ha)).json()["ui_config"][
            "asset_library_mode"] == "full"

        # 入参校验：不是对象 422 / 不认的模式 422
        assert (await client.put(
            "/api/assets/ui/preferences", json={"ui_config": ["simple"]}, headers=ho)).status_code == 422
        bad = await client.put(
            "/api/assets/ui/preferences", json={"ui_config": {"asset_library_mode": "极简"}}, headers=ho)
        assert bad.status_code == 422, bad.text
        await client.aclose()

    _run(_scenario())


# ══════════════════════════════════════════════════════════════
#  25. 组合导出矩阵 ＋ 叠加预设（11-24 需求三 S3）
#
#  验收判据就是 1123 §需求三 S3 那五条，逐条对上号：
#  ① 拼接 **0 元**（主干用例把 cost / 审计 / 文案三处都钉住）；
#  ② N×M>20 得 **400**（用默认旋钮 20 真撞一次，再证旋钮独立、不是复用投板 cap）；
#  ③ **校验先于投出**——拿 `_start_asset_job` 的假身断言"一次都没被 await"，
#     而不是只断言"台账里没有行"（后者挡不住"先起任务再校验"这种写法）；
#  ④ composed 产物在**成片墙**可预览、可下载，且带 `compose` 说明；
#  ⑤ concat 唯一性守卫在 `tests/unit/test_asset_concat_single_impl.py`。
#
#  替身分三层，各钉各的，别混：
#  - `_mx_env`：取段 → 探规格 → ffmpeg → 落桶（＋抽帧排程）。段"是谁"靠**文件头 8 字节**
#    认，不靠调用次数猜——这样"矩阵的行序＝界面勾选序"才是被测出来的，不是排出来的。
#  - `_mx_overlay`：叠加引擎那一层。本机没挂 `./engines`，`engine_available()` 在本地**恒为
#    False**（现网 backend 才挂了只读卷），不钉这一层的话主干用例会在校验那步被"这台机器
#    叠不了"挡在门外，测不到渲染。
#  - 钩子那一段**走真链路造**（开单 → 投板 → 回收落 `doubao_raw` 行），因为"试产片不许进
#    矩阵"和"composed 行带 hook_production_id"两条只有拿真形状的行才测得出来。
# ══════════════════════════════════════════════════════════════

MX_MATRIX = "/api/assets/compose/matrix"
MX_PRESETS = "/api/assets/overlay-presets"

MX_HOOK_BYTES = [f"MXHOOK{i:02d}".encode() for i in range(1, 13)]
MX_MATL_BYTES = [f"MXMATL{i:02d}".encode() for i in range(1, 13)]
MX_TAIL_BYTES = b"MXTAIL01"
MX_OUT_BYTES = b"MXOUT001"

# 各段的"实测规格"：钩子竖屏、正片**横屏**——正片故意给成横的，"换顺序＝换画幅"这条口径
# 才有东西可断（两段同规格时 target 怎么取都看不出写错）。
MX_HOOK_SPEC = {"duration": 16.08, "width": 720, "height": 1280, "fps": "25/1", "has_audio": True}
MX_MATL_SPEC = {"duration": 42.5, "width": 1280, "height": 720, "fps": "25/1", "has_audio": True}
MX_TAIL_SPEC = {"duration": 4.0, "width": 1280, "height": 720, "fps": "30/1", "has_audio": False}
MX_OUT_SPEC = {"duration": 58.58, "width": 720, "height": 1280, "fps": "25/1", "has_audio": True}

MX_STAMP: Dict[bytes, Tuple[str, Dict[str, Any]]] = {}
for _i, _b in enumerate(MX_HOOK_BYTES):
    MX_STAMP[_b] = (f"钩子{_i + 1}", MX_HOOK_SPEC)
for _i, _b in enumerate(MX_MATL_BYTES):
    MX_STAMP[_b] = (f"正片{_i + 1}", MX_MATL_SPEC)
MX_STAMP[MX_TAIL_BYTES] = ("片尾", MX_TAIL_SPEC)
MX_STAMP[MX_OUT_BYTES] = ("产物", MX_OUT_SPEC)


@contextlib.contextmanager
def _mx_env(registry: Dict[str, bytes], calls: List[dict], *,
            broken: Tuple[str, ...] = (), events: Optional[List[str]] = None,
            concat_return_error: Optional[str] = None):
    """组合导出那四步（取回→探规格→ffmpeg→落桶）的替身，全程不出网、不跑真 ffmpeg。

    `registry`＝`file_key → 这段的字节内容`。故意按 **key** 而不是按前缀分派（批 Q 那层
    是按 `asset/board/` 前缀判的）：矩阵有三类原料，前缀判法一旦漏一类就会把"取错了段"
    测成"取到了默认那段"——那是假绿。没登记的 key 直接 AssertionError。
    `broken`＝点了名的 key 取回失败（回 False），用来测"一格坏不连累整批"。
    `events`＝按顺序记 "overlay" / "upload"，用来钉"叠完才上传"这条硬口径。
    """
    async def _download(bucket, key, local):
        key = str(key)
        if key in broken:
            return False
        if key not in registry:
            raise AssertionError(f"矩阵替身没登记这段内容，代码却去桶里取了它：{key}")
        with open(local, "wb") as fh:
            fh.write(registry[key])
        return True

    def _head(path):
        with open(path, "rb") as fh:
            return fh.read(8)

    async def _concat(paths, target, out_path):
        tags = [MX_STAMP.get(_head(p), ("未知段", None))[0] for p in paths]
        calls.append({"tags": tags, "target": dict(target)})
        with open(out_path, "wb") as fh:
            fh.write(MX_OUT_BYTES)
        return concat_return_error

    def _probe(path):
        return dict(MX_STAMP.get(_head(path), ("未知段", MX_HOOK_SPEC))[1])

    uploaded: List[str] = []

    async def _upload(bucket, key, path, **kw):
        if events is not None:
            events.append("upload")
        # 0 字节产物不许落桶（11-04 现网那个"上传成功但桶里是空对象"的真事故）
        assert os.path.getsize(path) > 0, f"落桶的文件是空的：{key}"
        uploaded.append(str(key))
        return True

    frames = AsyncMock(return_value={"queued": True, "job_id": "jmx", "note": None})
    with contextlib.ExitStack() as st:
        st.enter_context(patch("app.api.assets.download_to_file", _download))
        st.enter_context(patch("app.services.asset_compose_service.concat_segments", _concat))
        st.enter_context(patch("app.services.asset_compose_service.probe_media",
                               AsyncMock(side_effect=_probe)))
        st.enter_context(patch("app.api.assets.upload_file_from_path", _upload))
        st.enter_context(patch("app.api.assets._enqueue_frames", frames))
        yield {"frames": frames, "uploaded": uploaded}


@contextlib.contextmanager
def _mx_overlay(events: List[str], *, engine_ok: bool = True, apply_error: Optional[str] = None):
    """叠加那一层：角标取图（走 `minio_service`，和段下载**不是一个绑定名**）＋引擎可用性＋叠层。

    `engine_ok=False` 是现网之外的另一种真实：本机没挂 engines，`compose_matrix` 必须
    **在起后台任务之前**就把话说清楚（否则台账里躺着一条"组合导出 失败"，一线不知道为
    什么）。这里把可用性一起钉住，主干用例才测得到渲染那一段。

    ⚠️ 角标取图打的是 `app.services.minio_service.download_to_file`，而**段**下载打的是
    `app.api.assets.download_to_file`（misc 里是 from-import 进来的另一个绑定）。两个名字
    打成一个，另一层就会去连本机没起的 MinIO:9000——用例挂成 ConnectionRefused，
    看着像"叠加没做"，其实是替身没盖全。
    """
    async def _pull(bucket, key, local):
        with open(local, "wb") as fh:
            fh.write(PNG_PORTRAIT)
        return True

    async def _apply(src, out, badges, texts, *, threads=1):
        assert os.path.getsize(src) > 0, "叠层的输入必须是刚拼出来的非空文件"
        for badge in badges:
            assert os.path.isfile(str(badge.get("path"))), f"角标没落成本地文件：{badge}"
            assert str(badge.get("position")), "传给引擎的角标必须带位置"
        events.append("overlay")
        if apply_error is not None:
            return apply_error
        with open(out, "wb") as fh:
            fh.write(MX_OUT_BYTES)
        return None

    with contextlib.ExitStack() as st:
        st.enter_context(patch("app.services.minio_service.download_to_file", _pull))
        st.enter_context(patch(
            "app.services.asset_overlay_service.engine_available",
            lambda: (engine_ok, None if engine_ok else "测试钉住：这台机器没挂 engines"),
        ))
        st.enter_context(patch("app.services.asset_overlay_service.apply_overlay", _apply))
        yield


def _mx_overlay_params(badge_id: str) -> Dict[str, Any]:
    """一套"角标 ＋ 警示语"的现场参数（预设里存的也是这个形状）。"""
    return {
        "badges": [{"asset_id": badge_id, "position": "top-right", "width": 160, "offset": 24}],
        "text_overlays": [{"text": "本剧纯属虚构", "position": "bottom-center", "font_size": 40}],
    }


MX_OVERLAY_SUMMARY = "1 个角标（top-right） ＋ 1 行字（本剧纯属虚构）"


async def _mx_inputs(client, h, *, hooks=2, materials=2, with_tail=False, codes=None):
    """造一批**真形状**的原料：hooks 支豆包成片（走开单→投板→回收落库）＋ M 条正片素材。

    钩子侧不手插行是有原因的：`_load_matrix_hooks` 要看 `kind`、`file_key`、以及**它挂的
    生产单是不是试产**——这三样全靠投板那条线自然写出来，手插一行很容易插成一个
    "库里根本不可能存在"的形状，用例绿了但代码没被考到。
    """
    hm, ho = h["material"], h["operator"]
    hook_codes = codes or [f"8MX{str(i + 1).zfill(2)}" for i in range(hooks)]
    assert len(hook_codes) == hooks
    _asset_id, _sid, listed = await _order_ready_production(client, h, n=hooks, hook_codes=hook_codes)
    fb = _FakeBoard()
    with _board_off(fb):
        resp = await _dispatch(client, ho, [p["id"] for p in listed])
    assert resp.status_code == 200, resp.text

    registry: Dict[str, bytes] = {}
    hook_ids: List[str] = []
    ordered_codes: List[str] = []
    for idx, prod in enumerate(listed):
        rows = [o for o in await _rows(AssetOutput)
                if str(o.production_id) == str(prod["id"]) and o.kind == "doubao_raw" and o.file_key]
        assert rows, f"投板回收没有落下豆包成片行：{prod['id']}"
        hook_ids.append(str(rows[0].id))
        registry[rows[0].file_key] = MX_HOOK_BYTES[idx]
        # 生产单列表口是**最新在上**，`listed` 的次序不等于请求里 hook_codes 的次序。
        # 所以"这段内容 ↔ 这个钩子编号"要成对按同一顺序登记；否则用例变成拿两个
        # 不同顺序的数组比大小，"行序＝勾选序"这条恰恰没被考到。
        ordered_codes.append(str(prod["hook_code"]))
    assert sorted(set(ordered_codes)) == sorted(set(hook_codes))

    matl_ids: List[str] = []
    for idx in range(materials):
        m = await _q_video_asset(client, hm, f"正片{idx + 1}.mp4")
        row = await _row_of(AssetItem, m["id"])
        assert row.file_key, m
        registry[row.file_key] = MX_MATL_BYTES[idx]
        matl_ids.append(m["id"])

    tail_id = None
    if with_tail:
        t = await _q_video_asset(client, hm, "片尾.mp4")
        trow = await _row_of(AssetItem, t["id"])
        registry[trow.file_key] = MX_TAIL_BYTES
        tail_id = t["id"]

    # 角标图：11-25 批 W 起叠角标与角色卡同读一张 asset_cards 表（旧预设 asset_id 随
    # 搬迁原 id 直迁），这里直插一行卡当角标
    badge_id = uuid.uuid4()
    async with dbmod.async_session_factory() as s:
        s.add(AssetCard(
            id=badge_id, name="角标", file_name="角标.png",
            file_key="asset/overlay/badge.png",
            bucket=settings.MINIO_BUCKET_RAW, owner_id=None,
        ))
        await s.commit()

    return {"asset_id": _asset_id, "hook_ids": hook_ids, "matl_ids": matl_ids,
            "tail_id": tail_id, "img_id": str(badge_id), "registry": registry,
            "productions": listed, "hook_codes": ordered_codes}


def _mx_payload(env, **extra):
    body = {"hook_output_ids": env["hook_ids"], "material_ids": env["matl_ids"], **extra}
    return body


async def _mx_composed_rows():
    return [o for o in await _rows(AssetOutput) if o.kind == "composed"]


def test_compose_matrix_trunk_lays_every_cell_on_the_wall_for_zero_yuan():
    """S3 主干：2 支钩子 × 2 条正片 ＝ 4 条组合成片，一条不落全摆上成片墙，**0 元**。

    这条用例同时钉死判据 ①（0 元）与 ④（墙上可预览可下载），外加三件"矩阵"特有的语义：
    - 行序＝勾选序（界面勾的顺序就是产物的顺序，不能悄悄按 id 重排）；
    - 目标画幅＝**排在最前那一段**（钩子竖屏 ⇒ 出竖屏），这是 11-04 定的拼接口径在矩阵里的延续；
    - 产物行**不挂生产单**（`production_id=NULL`）但带 `hook_production_id`——挂上会让
      生产单行上"成片"那一列一支算两支（批 I 定过的口径）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=2, materials=2)
        calls: List[dict] = []
        with _mx_env(env["registry"], calls) as stub, \
             patch("app.api.assets._start_asset_job",
                   AsyncMock(side_effect=AssertionError("同步档不许起后台任务"))):
            resp = await client.post(MX_MATRIX, json=_mx_payload(env, async_mode=False), headers=ho)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["queued"] is False
            assert (body["requested"], body["ok"], body["failed"]) == (4, 4, 0), body["results"]
            assert body["cost"] == 0, "拼接一分钱不花——写了成本就是造账"
            assert body["overlay"] == "不叠加"
            assert "0 元" in body["message"] and "成片墙" in body["message"], body["message"]
            assert [c["tags"] for c in calls] == [
                ["钩子1", "正片1"], ["钩子1", "正片2"], ["钩子2", "正片1"], ["钩子2", "正片2"]]
            assert all(c["target"]["width"] == 720 and c["target"]["height"] == 1280 for c in calls)
            assert all(r["ok"] is True for r in body["results"])
            r0 = body["results"][0]
            assert r0["segments"][0] == f"钩子·{env['hook_codes'][0]}"
            assert r0["material"] == r0["segments"][1] and len(r0["segments"]) == 2
            assert r0["hook_output_id"] == env["hook_ids"][0]

            rows = await _mx_composed_rows()
            assert len(rows) == 4, [r.file_key for r in rows]
            for r in rows:
                assert r.production_id is None and r.hook_production_id is not None
                assert r.file_key.startswith("asset/composed/8MX"), r.file_key
                assert r.duration == 58.58 and r.resolution == "720x1280", (r.duration, r.resolution)
                meta = r.compose_meta
                assert meta["via"] == "matrix" and meta["cost"] == 0 and meta["tail"] is None
                assert meta["order"] == "hook_first"
                assert meta["hook_output_id"] in env["hook_ids"]
                assert meta["overlay"]["preset_id"] is None and meta["overlay"]["preset_name"] is None
                assert meta["overlay"]["params"] == {"badges": [], "text_overlays": []}
                assert meta["overlay"]["summary"] == "不叠加"
                assert r.composed_from_output_id is None, "矩阵是一次一格，不是回收自动拼的幂等行"
            assert stub["uploaded"] and len(stub["uploaded"]) == 4
            assert stub["frames"].await_count == 1
            assert sorted(stub["frames"].await_args.kwargs["output_ids"]) == sorted(
                r["output_id"] for r in body["results"])

            # 素材的五阶段里 compose 被点亮（拼接是它的写入方）
            asset = await _row_of(AssetItem, env["asset_id"])
            assert asset.stage_compose == "success"
            assert (asset.cost_prompt, asset.cost_parse) == (0.0, 0.0), "0 元不许反写素材成本"

            # 判据④：成片墙看得见、能预览、能下载
            listed = (await client.get("/api/assets/outputs?kind=composed", headers=ho)).json()
            assert listed["total"] == 4 and len(listed["items"]) == 4, listed["total"]
            briefs = [it["compose"] for it in listed["items"]]
            assert all(b and b["via"] == "matrix" and b["cost"] == 0 for b in briefs)
            assert all(b["tail"] is None and b["preset_name"] is None for b in briefs)
            assert any(b["hook_code"] == "8MX01" for b in briefs) and any(
                b["hook_code"] == "8MX02" for b in briefs)
            oid = str(rows[0].id)
            with patch("app.api.assets.get_presigned_url",
                       AsyncMock(return_value="http://minio/signed?x=1")) as ps:
                pv = await client.get(f"/api/assets/outputs/{oid}/preview", headers=hm)
            assert pv.status_code == 200 and "attachment" not in pv.json()["url"]
            # 批 E 定过的口径在这里同样适用于 composed：预览**不许**带 attachment，
            # 带了给 <video> 就是黑屏（"接口 200 但播不了"的根因）。
            assert ps.await_count == 1 and "as_attachment" not in ps.await_args.kwargs
            with patch("app.api.assets.get_presigned_url",
                       AsyncMock(return_value="http://minio/signed?d=1")) as ps2:
                dl = await client.get(f"/api/assets/outputs/{oid}/download", headers=hm)
            assert dl.status_code == 200 and dl.json()["kind"] == "composed"
            assert ps2.await_args.kwargs.get("as_attachment") is True, "下载就该落盘"

        # 判据①的最后一道：审计说这次 0 元、4 条全成
        logs = await _rows(AuditLog, AuditLog.action == "asset.compose.matrix")
        assert len(logs) == 1, len(logs)
        after = logs[0].after
        assert after["cost"] == 0 and after["ok"] == 4 and after["failed"] == 0
        assert after["hooks"] == 2 and after["materials"] == 2 and after["tail"] is None
        assert after["order"] == "hook_first" and after["overlay"] == "不叠加"
        assert await _count(AssetJob) == 0, "同步档不该在台账里留行"
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_tail_and_order_change_segments_and_the_frame():
    """片尾当第三段、顺序换前两段——两件都会改变**这条片子长什么样**，所以钉死。

    - 片尾恒在最后（「片尾」就该在片尾），第三段既进 `segments` 也进 `compose_meta.tail`；
    - `material_first` 把正片挪到最前 ⇒ 目标画幅跟着换成横屏。这不是口味问题：
      11-04 定的口径是「目标画幅＝排在最前那一段」，界面让人选顺序就等于让人选画幅，
      代码不许在背后替他决定（`MX_MATL_SPEC` 故意给成 1280×720 就是为了让这一条可测）；
    - 片尾与某条正片是**同一个文件** ⇒ 400。判的是 `file_key` 不是 id：同一条素材
      以两条 id 分别当选照样坏，只比 id 会漏；
    - 非法顺序当场 400，不许像有些代码那样悄悄回落默认档（回落＝人以为选了，其实没选）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=1, materials=2, with_tail=True)
        calls: List[dict] = []
        with _mx_env(env["registry"], calls):
            r1 = await client.post(MX_MATRIX, json=_mx_payload(
                env, async_mode=False, tail_asset_id=env["tail_id"]), headers=ho)
            assert r1.status_code == 200, r1.text
            b1 = r1.json()
            assert b1["ok"] == 2 and b1["failed"] == 0
            assert [c["tags"] for c in calls] == [
                ["钩子1", "正片1", "片尾"], ["钩子1", "正片2", "片尾"]]
            assert all(c["target"]["width"] == 720 for c in calls)
            first = b1["results"][0]
            assert len(first["segments"]) == 3
            assert first["segments"][0] == f"钩子·{env['hook_codes'][0]}"
            assert first["segments"][1] == first["material"]
            rows = await _mx_composed_rows()
            assert len(rows) == 2
            tail_labels = set()
            for r in rows:
                meta = r.compose_meta
                assert meta["tail"] is not None and meta["tail"]["file_key"]
                assert meta["segments"][2] == meta["tail"]["label"]
                assert meta["segments"][0] == f"钩子·{meta['hook_code']}"
                assert meta["cost"] == 0 and meta["via"] == "matrix"
                tail_labels.add(meta["tail"]["label"])
            assert len(tail_labels) == 1, tail_labels
            audits = await _rows(AuditLog, AuditLog.action == "asset.compose.matrix")
            assert audits[-1].after["tail"] in tail_labels
            assert audits[-1].after["materials"] == 2 and audits[-1].after["hooks"] == 1

            before = await _count(AssetOutput)
            calls.clear()
            r2 = await client.post(MX_MATRIX, json=_mx_payload(
                env, async_mode=False, order="material_first"), headers=ho)
            assert r2.status_code == 200, r2.text
            assert [c["tags"] for c in calls] == [["正片1", "钩子1"], ["正片2", "钩子1"]]
            assert all(c["target"]["width"] == 1280 for c in calls), "顺序换了画幅没换＝代码替他决定了"
            assert await _count(AssetOutput) == before + 2
            new_ids = {rr["output_id"] for rr in r2.json()["results"]}
            fresh = [r for r in await _mx_composed_rows() if str(r.id) in new_ids]
            assert len(fresh) == 2
            assert all(r.compose_meta["order"] == "material_first" for r in fresh)
            assert all(r.compose_meta["tail"] is None for r in fresh), \
                "这一轮没带片尾，不许把上一轮的片段尾串过来"

            r3 = await client.post(MX_MATRIX, json=_mx_payload(
                env, async_mode=False, tail_asset_id=env["matl_ids"][0]), headers=ho)
            assert r3.status_code == 400 and "是同一个文件" in r3.text, r3.text
            assert await _count(AssetOutput) == before + 2, "拒收不该留下半成品"

            r4 = await client.post(MX_MATRIX, json=_mx_payload(
                env, async_mode=False, order="middle"), headers=ho)
            assert r4.status_code == 400 and "拼接顺序只能是" in r4.text, r4.text
            assert await _count(AssetOutput) == before + 2
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_over_capacity_says_split_it_and_burns_nothing():
    """判据②＋缺口 4b：N×M 超上限 ⇒ 400 且什么都不产生；拼接的 cap 与投板的 cap **各管各的**。

    两个旋钮凑巧默认都是 20，语义毫无关系：投板那个管「当天号池额度」，这个管
    「一次压给服务器多少秒 CPU」。谁要是图省事复用，将来把号池 cap 调到 40，
    拼接的单次上限就被连带放宽到 40 格——一个看不见摸不着的性能事故就这么埋下了。
    所以这里既断言「调小拼接 cap 会挡」，也断言「把投板 cap 调到 1 挡不住拼接」，
    两个方向都验才算独立。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        assert int(settings.ASSET_COMPOSE_MAX_PER_CALL) == 20, "默认值被改过＝这条用例不再考 20"

        env = await _mx_inputs(client, h, hooks=3, materials=7)   # 21 格 > 20
        calls: List[dict] = []
        jobs_before = await _count(AssetJob)
        outs_before = await _count(AssetOutput)
        with _mx_env(env["registry"], calls), \
             patch("app.api.assets._start_asset_job",
                   AsyncMock(side_effect=AssertionError("超上限连台账都不该碰"))):
            r = await client.post(MX_MATRIX, json=_mx_payload(env), headers=ho)
            assert r.status_code == 400, r.text
            assert "请分两次点" in r.text and "ASSET_COMPOSE_MAX_PER_CALL" in r.text, r.text
            assert "3 支钩子 × 7 条正片 ＝ 21 条" in r.text, r.text
            assert calls == [] and await _count(AssetOutput) == outs_before
            assert await _count(AssetJob) == jobs_before

            small = int(settings.ASSET_COMPOSE_MAX_PER_CALL)
            settings.ASSET_COMPOSE_MAX_PER_CALL = 3
            try:
                r2 = await client.post(MX_MATRIX, json=_mx_payload(env), headers=ho)
                assert r2.status_code == 400 and "超过单次上限 3" in r2.text, r2.text
                assert calls == []
            finally:
                settings.ASSET_COMPOSE_MAX_PER_CALL = small

            # cap 独立：把投板的 cap 拧到 1，拼接（3×7＝21）照样被**自己的** cap 挡住，
            # 而 2×2＝4 格不该被投板 cap 误伤。
            dispatch_cap = settings.ASSET_DISPATCH_MAX_PER_CALL
            settings.ASSET_DISPATCH_MAX_PER_CALL = 1
            try:
                r3 = await client.post(MX_MATRIX, json={
                    "hook_output_ids": env["hook_ids"][:2],
                    "material_ids": env["matl_ids"][:2],
                    "async_mode": False,
                }, headers=ho)
                assert r3.status_code == 200, r3.text
                assert r3.json()["ok"] == 4, r3.text
            finally:
                settings.ASSET_DISPATCH_MAX_PER_CALL = dispatch_cap
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_refuses_every_bad_selection_before_touching_anything():
    """**判据③「校验先于投出」**：每一种坏选择都当场说人话，台账一行不留、一条产物不落。

    为什么这条值得单独一条用例：矩阵默认走后台档（D-1 口径），而排进后台的活儿是
    **先落一行 `asset_jobs` 再开始跑**的。校验只要漏在后面，一线看到的就是「组合导出
    失败」四个字，得点开 result 才知道"第 1 个角标挑的是视频"——可那是**入参错**，
    不是运行故障，本来就不该占用一次任务号、更不该在台账里留一条失败。
    所以这里把排程口换成一张计数纸：跑完每一种坏选择，它都必须**一次都没被点过**，
    拼接替身也必须一次都没被叫过（`calls == []`＝连桶都没碰）。

    顺带把 11-24 定下的两条口径钉在同一处：钩子侧**只认非试产片**（缺口 4a）；
    角标挑错类型在**投出之前**就拒（缺口 4b，`resolve_badge_refs` 那一层拆开的意义）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=2, materials=2)
        base = _mx_payload(env)          # 不带 async_mode ＝ 默认后台档，最考验"校验排在前面"

        # 两种"库里真会有、但不该进矩阵"的行：交付包（zip）和回收落坏的（桶里没文件）
        async with dbmod.async_session_factory() as s:
            prod = await s.get(AssetProduction, uuid.UUID(env["productions"][0]["id"]))
            pkg = AssetOutput(production_id=prod.id, asset_id=prod.asset_id, kind="package",
                              file_key="asset/package/交付包.zip", bucket=settings.MINIO_BUCKET_RAW,
                              file_name="交付包.zip")
            nofile = AssetOutput(production_id=prod.id, asset_id=prod.asset_id, kind="doubao_raw",
                                 file_key=None, bucket=settings.MINIO_BUCKET_RAW,
                                 file_name="回收没落下的坏片.mp4")
            s.add_all([pkg, nofile])
            await s.commit()
            pkg_id, nofile_id = str(pkg.id), str(nofile.id)

        link = (await _import(client, hm, [DOUYIN_1])).json()["items"][0]   # 链接素材：还没文件

        calls: List[dict] = []
        events: List[str] = []
        started = AsyncMock(return_value={"job_id": "不该出现", "status": JB_QUEUED})
        outs_before = await _count(AssetOutput)

        with _mx_env(env["registry"], calls, events=events), \
             _mx_overlay(events), \
             patch("app.api.assets._start_asset_job", started):
            async def _bad(payload, code, phrase, headers=None):
                r = await client.post(MX_MATRIX, json=payload, headers=headers or ho)
                assert r.status_code == code, f"{phrase} → {r.status_code} {r.text[:240]}"
                assert phrase in r.text, r.text
                return r

            await _bad({**base, "hook_output_ids": []}, 400, "钩子成片一个都没选")
            await _bad({**base, "material_ids": []}, 400, "正片一个都没选")
            await _bad({**base, "hook_output_ids": [str(uuid.uuid4())]}, 400, "在库里找不到")
            await _bad({**base, "hook_output_ids": [pkg_id]}, 400, "那些不是能拼的视频")
            await _bad({**base, "hook_output_ids": [nofile_id]}, 400, "桶里没有文件")

            # 正片侧：不存在的素材 / 图片 / 还没回源解析的链接
            await _bad({**base, "material_ids": [str(uuid.uuid4())]}, 404, "素材不存在")
            # env["img_id"] 批 W 起是卡表的 id——卡不是素材，拼接口按「素材不存在」拒（404）。
            # 「是图片」那个 400 分支由自动拼接两条用例直插的遗留图行钉着，不在这里重复。
            await _bad({**base, "material_ids": [env["img_id"]]}, 404, "素材不存在")
            await _bad({**base, "material_ids": [link["id"]]}, 400, "还没有可拼的文件")
            await _bad({**base, "material_ids": [link["id"]]}, 400, "/assets/resolve")

            # 入参形状
            await _bad({**base, "material_source": "yuanbao"}, 400, "material_source 只能是")
            await _bad({**base, "order": "middle"}, 400, "拼接顺序只能是")

            # 缺口 4a：试产片的成片不能当原料（转正了才能用），话术要给出路
            async with dbmod.async_session_factory() as s:
                row = await s.get(AssetProduction, uuid.UUID(env["productions"][0]["id"]))
                row.is_trial = True
                await s.commit()
            await _bad({**base, "hook_output_ids": [env["hook_ids"][0]]},
                       400, "试产片的成片不能进组合导出")
            async with dbmod.async_session_factory() as s:
                row = await s.get(AssetProduction, uuid.UUID(env["productions"][0]["id"]))
                row.is_trial = False
                await s.commit()

            # 叠加预设：二选一 / 已停用 / 别人的个人预设 / 这台机器没引擎 / 角标挑了视频
            pid = (await client.post(MX_PRESETS, json={"name": "8MX剧名片尾警示",
                                                       "params": _mx_overlay_params(env["img_id"])},
                                     headers=ho)).json()["id"]
            await _bad({**base, "overlay_preset_id": pid,
                        "overlay_params": _mx_overlay_params(env["img_id"])},
                       400, "只能带一个")
            await _bad({**base, "overlay_params": {"badges": [{"position": "top-left"}]}},
                       400, "没挑图")
            # 批 W：角标与卡同表，"不是图片"这个分支随表合一消失；素材 id 现在落在「不在卡库里」（仍 400）
            await _bad({**base, "overlay_params": _mx_overlay_params(env["matl_ids"][0])},
                       400, "不在卡库里")
            await _bad({**base, "overlay_preset_id": str(uuid.uuid4())}, 404, "叠加预设不存在")
            mine = (await client.post(MX_PRESETS, json={"name": "8MX别人的私人预设",
                                                        "params": _mx_overlay_params(env["img_id"])},
                                      headers=ho)).json()["id"]
            await _bad({**base, "overlay_preset_id": mine}, 403, "没有使用这套个人预设的权限", headers=hm)
            await client.request("DELETE", f"{MX_PRESETS}/{pid}", headers=ho)
            await _bad({**base, "overlay_preset_id": pid}, 400, "已停用")

            with _mx_overlay([], engine_ok=False):
                await _bad({**base, "overlay_params": _mx_overlay_params(env["img_id"])},
                           400, "这台机器用不了叠加引擎")

            async with dbmod.async_session_factory() as s:
                s.add(User(id=uuid.uuid4(), username="mx_pub",
                           password_hash=get_password_hash(PASSWORD), display_name="发布专员",
                           role="publisher", data_scope="all", is_active=True))
                await s.commit()
            pub = (await client.post("/api/auth/login",
                                     json={"username": "mx_pub", "password": PASSWORD})).json()
            r_pub = await client.post(MX_MATRIX, json=base,
                                      headers={"Authorization": f"Bearer {pub['access_token']}"})
            assert r_pub.status_code == 403, f"发布专员不该能拼：{r_pub.status_code} {r_pub.text[:200]}"
            assert "权限不足" in r_pub.text

        # ★ 判据③的落点：上面二十来次请求，**没有一次**排到后台、没有一次碰过桶
        assert started.await_count == 0, f"校验没过却排了 {started.await_count} 次后台任务"
        assert calls == [] and events == [], "一次都没该渲染，拼接/落桶/叠层却被叫过"
        assert [j for j in await _rows(AssetJob) if j.kind == JOB_COMPOSE] == []
        assert await _count(AssetOutput) == outs_before
        assert await _mx_composed_rows() == []
        assert (await client.get(MX_MATRIX, headers=ho)).status_code == 405, "矩阵只有 POST"
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_async_mode_goes_through_the_ledger_and_replays_the_same_endpoint():
    """默认档（不给 `async_mode` ＝ true）：当场回任务号，后台**把同一个接口再跑一遍**。

    这条真正要钉的不是"能跑完"，而是**没有第二套实现**：`_job_endpoint(JOB_COMPOSE)`
    交出去的就是 `compose_matrix` 本体，后台重放靠一个透明代理数得出来它被调了两次
    （第一次 async=true 只落台账，第二次 async=false 真干活）。写两套早晚分叉——
    投产/审核/导出三个入口那次口径不一致（R-6）就是这么来的，这个新 kind 不重来一遍。

    另钉三件：①台账里躺的是**整份**同步响应（逐格明细都在，界面不用二次请求）；
    ②跑完之后重提同样的选择**不挡**——防重复判据只看还没结束的活；
    ③`done_note` 说清产物在哪看（11-10 口径③：「已完成」三个字必须带去向）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=2, materials=2)
        calls: List[dict] = []
        real = assets_api.compose_matrix
        seen: List[bool] = []

        async def _spy(data, current_user, db):
            seen.append(bool(data.async_mode))
            return await real(data, current_user, db)

        with _mx_env(env["registry"], calls) as stub, \
             patch("app.api.assets.compose_matrix", _spy):
            sub = await client.post(MX_MATRIX, json=_mx_payload(env), headers=ho)
            assert sub.status_code == 200, sub.text
            ack = sub.json()
            assert ack["queued"] is True and ack["status"] == JB_QUEUED, ack
            assert ack["planned_units"] == 4, "台账要先知道这次要转几格，进度条才写得出来"
            assert "已排到后台" in ack["message"] and "不用守着页面等" in ack["message"]
            assert ack["poll_url"] == f"/api/assets/jobs/{ack['job_id']}"
            assert calls == [], "提交这一趟只该落台账，一条都不该现在就渲染"

            done = await _wait_job(client, ho, ack["job_id"], timeout=20.0)
            assert done["status"] == JB_SUCCEEDED, done
            assert done["running"] is False and done["kind"] == JOB_COMPOSE
            assert done["kind_label"] == "组合导出" and done["planned_units"] == 4
            assert done["done_note"] == assets_api.ASSET_JOB_DONE_NOTES[JOB_COMPOSE]
            assert "成片墙" in done["done_note"] and "0 元" in done["done_note"]
            body = done["result"]
            assert body is not None and body["queued"] is False, "重放那一趟不能再排一份任务"
            assert (body["requested"], body["ok"], body["failed"], body["cost"]) == (4, 4, 0, 0)
            assert all(r["ok"] for r in body["results"])
            assert [c["tags"] for c in calls] == [
                ["钩子1", "正片1"], ["钩子1", "正片2"], ["钩子2", "正片1"], ["钩子2", "正片2"]]
            assert seen == [True, False], f"重放没走同一个接口：{seen}"
            assert done["error"] is None, done["error"]

            rows = await _mx_composed_rows()
            assert len(rows) == 4
            assert stub["frames"].await_count == 1

            # ★ 跑完之后重提：防重复判据只看"还没结束"的活，终态不该永久占坑
            again = await client.post(MX_MATRIX, json=_mx_payload(env), headers=ho)
            assert again.status_code == 200, again.text
            ack2 = again.json()
            assert ack2["queued"] is True and ack2["job_id"] != ack["job_id"]
            done2 = await _wait_job(client, ho, ack2["job_id"], timeout=20.0)
            assert done2["status"] == JB_SUCCEEDED, done2
            assert done2["result"]["ok"] == 4
            # 两次都真跑了：矩阵一格一条新行、不覆盖（这正是 twin 判据存在的理由）
            assert len(await _mx_composed_rows()) == 8

        assert len(await _rows(AuditLog, AuditLog.action == "asset.compose.matrix")) == 2, \
            "后台重放那一趟也要留审计，不然花钱台账查不到机器干的活"
        subs = await _rows(AuditLog, AuditLog.action == f"asset.job.{JOB_COMPOSE}.submit")
        assert len(subs) == 2 and all(s.after["planned_units"] == 4 for s in subs)
        asset = await _row_of(AssetItem, env["asset_id"])
        assert asset.stage_compose == "success"
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_twin_guard_is_conservative_on_shared_materials():
    """同样的料已经在后台拼，就**不再起一份**——而且判据故意偏保守。

    `asset_jobs` 台账里躺一条没结束的组合同类活时：

    - 完全一样的一批 → 409；
    - **只共用一支钩子**（正片全换了）→ 也 409。这不是漏判，是 11-24 定的档位：一次
      矩阵提交本来就该把要的正片一起选完，而"等它跑完"的代价远小于让两份转码在现网
      高峰期叠起来（同一台机器上还跑着切片和回收）。要改成按格精确判，先动这条用例。
    - 两头的 id 都不沾 → 放行。这一条必须有，否则"保守"就变成"一次只能拼一批"。

    话术上最要紧的是别把它说成"不花钱随便点"：拼接 0 元模型费，但重复一次＝服务器白转
    一遍码 ＋ 桶里多存一整批重样片子（没人回收）。所以 409 里必须出现这句真话。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=2, materials=2)
        calls: List[dict] = []

        async with dbmod.async_session_factory() as s:
            twin = AssetJob(
                kind=JOB_COMPOSE,
                status=JB_QUEUED,
                params={"hook_output_ids": [env["hook_ids"][0]],
                        "material_ids": [env["matl_ids"][0]], "async_mode": True},
                planned_units=1,
                created_by=None,
            )
            s.add(twin)
            await s.commit()
            twin_id = str(twin.id)
        jobs_before = await _count(AssetJob)

        # ⚠️ 这里**不能**把 `_start_asset_job` 换成替身：防重复判据就写在那个函数里，
        # 一替身就替掉了被测对象（第一版就是这么假绿的）。改用真函数＋"没有新行、
        # 一次都没渲染"两条硬证据来判它有没有挡下来。
        with _mx_env(env["registry"], calls):
            for payload in ({**_mx_payload(env), "async_mode": True},
                            {"hook_output_ids": [env["hook_ids"][0]],
                             "material_ids": [env["matl_ids"][1]]}):
                r = await client.post(MX_MATRIX, json=payload, headers=ho)
                assert r.status_code == 409, r.text
                assert "正在后台跑「组合导出」" in r.text, r.text
                assert twin_id in r.text, "409 要点名是哪条任务占着"
                assert "不花模型费，但重复占服务器转码" in r.text, r.text
                assert "桶里多存一整批重样片子" in r.text, r.text
            assert calls == [] and await _count(AssetJob) == jobs_before, \
                "被挡住的重复提交不许在台账里留一行失败的活"

        # 两头的 id 都不沾 ⇒ 放行，而且真跑得完
        with _mx_env(env["registry"], calls):
            ok = await client.post(MX_MATRIX,
                                   json={"hook_output_ids": [env["hook_ids"][1]],
                                         "material_ids": [env["matl_ids"][1]]},
                                   headers=ho)
            assert ok.status_code == 200, ok.text
            ack = ok.json()
            assert ack["queued"] is True and ack["planned_units"] == 1, ack
            done = await _wait_job(client, ho, ack["job_id"], timeout=20.0)
            assert done["status"] == JB_SUCCEEDED, done
        assert [c["tags"] for c in calls] == [["钩子2", "正片2"]], calls
        assert await _count(AssetJob) == jobs_before + 1
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_one_broken_cell_fails_only_itself():
    """一格取不到文件只坏那一格：剩下的照拼照落，失败的那格在 results 里点名说原因。

    钉的是矩阵最容易出事的那条纪律：**一格一提交**。20 格跑到第 7 格桶里取不到文件，
    要是攒到批末统一提交，前 6 格的文件已经进了桶、行却被 rollback 掉——变成"桶里有片、
    库里没行"的孤儿，谁也不会去回收。所以这里逐格验：

    - 坏的是**正片侧**的一个 key（两条钩子都配它 ⇒ 恰好坏两格、好两格）；
    - `results` 的失败原因用人话（`取回第2段失败（桶/key）`），不是 `ConnectionError`；
    - 只有成功的格子落 composed 行、进抽帧清单、进审计的 `ok`；
    - 一句"拼好 2 条，失败 2 条"，别让一线以为整批废了。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=2, materials=2)
        bad_row = await _row_of(AssetItem, env["matl_ids"][0])
        good_row = await _row_of(AssetItem, env["matl_ids"][1])
        assert bad_row.file_key and good_row.file_key and bad_row.file_key != good_row.file_key

        calls: List[dict] = []
        with _mx_env(env["registry"], calls, broken=(bad_row.file_key,)) as stub:
            resp = await client.post(MX_MATRIX, json=_mx_payload(env, async_mode=False), headers=ho)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert (body["requested"], body["ok"], body["failed"]) == (4, 2, 2), body
            assert body["cost"] == 0
            assert [r["ok"] for r in body["results"]] == [False, True, False, True], body["results"]
            for cell in body["results"]:
                if cell["ok"]:
                    assert cell["material"] == f"{good_row.code}·{good_row.title or good_row.file_name}"
                else:
                    assert "取回第2段失败" in cell["error"], cell["error"]
                    assert str(bad_row.file_key)[:30] in cell["error"], cell["error"]
                    assert "稍后重试" in cell["error"]
            assert "拼好 2 条" in body["message"] and "失败 2 条" in body["message"], body["message"]
            # 坏格子连 ffmpeg 都不该叫起来：calls 里只剩两格，且都是配那条好正片
            assert [c["tags"] for c in calls] == [["钩子1", "正片2"], ["钩子2", "正片2"]], calls
            assert len(stub["uploaded"]) == 2, "取回失败的那格不许往桶里落东西"

        rows = await _mx_composed_rows()
        assert len(rows) == 2
        assert all(r.compose_meta["material"]["file_key"] == good_row.file_key for r in rows)
        assert sorted(r.id for r in rows) == sorted(
            uuid.UUID(x["output_id"]) for x in body["results"] if x["ok"])
        assert stub["frames"].await_count == 1
        assert sorted(stub["frames"].await_args.kwargs["output_ids"]) == sorted(
            x["output_id"] for x in body["results"] if x["ok"])

        logs = await _rows(AuditLog, AuditLog.action == "asset.compose.matrix")
        assert len(logs) == 1
        after = logs[0].after
        assert (after["ok"], after["failed"], after["cost"]) == (2, 2, 0)
        assert len(after["failures"]) == 2 and all("取回第2段失败" in f["error"] for f in after["failures"])
        # 有格子成就 ⇒ 阶段照样点亮（不能让一条坏原料把素材的 compose 阶段判成没做）
        assert (await _row_of(AssetItem, env["asset_id"])).stage_compose == "success"
        await client.aclose()

    _run(_scenario())


def test_compose_matrix_overlays_before_uploading_the_final_file():
    """叠加排在落桶**之前**：叠坏了就一条都不许进桶，界面上不能出现"没卡但已发出去"的片。

    这条用例唯一有价值的断言是 `events` 那串顺序——它把 `_concat_render` 的步骤钉成
    「拼好 → 叠 → 才上传」。顺序反过来的话，叠加失败会留下一个"已经在桶里、但没叠角标"
    的对象，而行没落库；一线下次点导出又多一份，谁都不知道桶里那批干净的片是哪来的。
    （11-04 那个"上传成功但桶里 0 字节"就是同一族：落桶这一步一旦和校验脱钩就会造脏数据。）

    顺带钉三件读侧口径：
    - `compose_meta.overlay` 存的是**当时校验后的参数快照**＋一句人话 summary；
    - 成片墙 brief 与审计都读这个快照，不读预设现值（预设改了不许回头改历史）；
    - 一格失败不许连累另一格：两格都坏才是两格都坏。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        env = await _mx_inputs(client, h, hooks=1, materials=2)
        params = _mx_overlay_params(env["img_id"])
        calls: List[dict] = []
        events: List[str] = []

        with _mx_env(env["registry"], calls, events=events) as stub1, _mx_overlay(events):
            r1 = await client.post(MX_MATRIX,
                                   json=_mx_payload(env, async_mode=False, overlay_params=params),
                                   headers=ho)
            assert r1.status_code == 200, r1.text
            b1 = r1.json()
            assert (b1["requested"], b1["ok"], b1["failed"], b1["cost"]) == (2, 2, 0, 0)
            assert b1["overlay"] == MX_OVERLAY_SUMMARY, b1["overlay"]
            # ★ 口径本体：每一格都是"叠完才上传"，没有一次 upload 排在 overlay 前面
            assert events == ["overlay", "upload", "overlay", "upload"], events
            assert len(stub1["uploaded"]) == 2

            rows = await _mx_composed_rows()
            assert len(rows) == 2
            for row in rows:
                ov = row.compose_meta["overlay"]
                assert ov["preset_id"] is None and ov["preset_name"] is None
                assert ov["summary"] == MX_OVERLAY_SUMMARY
                assert ov["params"]["badges"][0]["asset_id"] == env["img_id"]
                assert ov["params"]["badges"][0]["position"] == "top-right"
                assert ov["params"]["badges"][0]["width"] == 160
                assert "opacity" in ov["params"]["badges"][0], "校验后的形状才进快照"
                assert ov["params"]["text_overlays"][0]["text"] == "本剧纯属虚构"
            briefs = (await client.get("/api/assets/outputs?kind=composed", headers=ho)
                      ).json()["items"]
            # 只判**这一轮拼出来的那两条**：文件里前面还有批 Q 自动拼、手工两段拼留下的
            # composed 行，那些没叠东西，`compose` 是另一套形状（甚至 null）。
            mine = [it for it in briefs if it["id"] in {x["output_id"] for x in b1["results"]}]
            assert len(mine) == 2, [it["id"] for it in mine]
            assert all(it["compose"]["overlay_summary"] == MX_OVERLAY_SUMMARY for it in mine)
            assert all(it["compose"]["preset_name"] is None for it in mine)
            matrix_logs = [l for l in await _rows(AuditLog, AuditLog.action == "asset.compose.matrix")
                           if (l.after or {}).get("overlay") == MX_OVERLAY_SUMMARY]
            assert len(matrix_logs) == 1, "前面几轮矩阵都不带叠加，这里只该有这一条"
            assert matrix_logs[0].after["ok"] == 2
            assert matrix_logs[0].after["overlay_preset_id"] is None

        # 第 2 轮：引擎这一趟报错 ⇒ 一条都不落，桶里也不许多出"没叠卡"的对象
        events.clear()
        calls.clear()
        with _mx_env(env["registry"], calls, events=events) as stub2, \
             _mx_overlay(events, apply_error="测试钉住：引擎第 2 遍叠不上"):
            r2 = await client.post(MX_MATRIX,
                                   json=_mx_payload(env, async_mode=False, overlay_params=params),
                                   headers=ho)
            assert r2.status_code == 200, r2.text
            b2 = r2.json()
            assert (b2["ok"], b2["failed"]) == (0, 2), b2["results"]
            assert all("叠加失败：" in x["error"] for x in b2["results"]), b2["results"]
            assert events == ["overlay", "overlay"], "叠坏了还往桶里传，就是造脏数据"
            assert stub2["uploaded"] == []
            assert stub2["frames"].await_count == 0, "一格都没成，不该排抽帧"
            assert b2["frames"]["queued"] is False
        assert len(await _mx_composed_rows()) == 2, "失败那一轮不许新增行，也别把好的删掉"
        await client.aclose()

    _run(_scenario())


def test_overlay_presets_are_scoped_audited_and_never_stored_empty():
    """叠加预设的四条边界：空壳存不了、名字不并存、私有的看不见、改预设不回改历史。

    预设是"存下来反复用"的东西，所以这里的判错比现场调用**更严**：现场调错了这一次废掉，
    预设里存错了一套，之后每一批出片都错。所以：
    - 既无角标又无文字 → 当场 400（存进去＝界面上多一个"选了等于没选"的选项，一定被当 bug 报）；
    - 同名 → 409 并指路去改原来那套（不加 DB 唯一索引的理由和 `asset_scripts` 一样：
      163 老库 `ADD COLUMN` 补不出约束，会出现两套行为）；
    - `scope="shared"`（全员可选）只有管理员能设——共享出去改的是别人的片子外观；
    - 别人的个人预设既不在我列表里、直接拿 id 打接口也挡（防靠猜 id 读别人参数）。

    最后一档是 11-24 需求三自己踩出来的真 bug：**停用**口的职能闸以前挂的是审核口径
    （`_REVIEW_ROLES`），于是素材专员能建、能改自己的预设，却永远关不掉它——死局。
    现在跟着 `_PROD_ROLES`，所有权判断留在函数里（本人或管理员）。这条用例把死局钉成回归。
    """
    _run(_bootstrap())

    from app.services import asset_overlay_service as ov_svc

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho, ha = h["material"], h["operator"], h["admin"]
        env = await _mx_inputs(client, h, hooks=1, materials=2)
        params = _mx_overlay_params(env["img_id"])

        created = await client.post(MX_PRESETS,
                                    json={"name": "8MX剧名＋后果自负", "params": params,
                                          "note": "竖屏剧名条"}, headers=ho)
        assert created.status_code == 201, created.text
        p1 = created.json()
        pid = p1["id"]
        assert p1["scope"] == OVERLAY_PRESET_USER and p1["active"] is True
        assert p1["summary"] == MX_OVERLAY_SUMMARY and p1["note"] == "竖屏剧名条"
        assert p1["owner_name"]

        bad = await client.post(MX_PRESETS, json={"name": "8MX空壳", "params": {}}, headers=ho)
        assert bad.status_code == 400 and "一个角标、一行字都没有" in bad.text, bad.text
        dup = await client.post(MX_PRESETS, json={"name": "8MX剧名＋后果自负",
                                                 "params": params}, headers=hm)
        assert dup.status_code == 409 and "换个名字或直接改它" in dup.text, dup.text
        shared = await client.post(MX_PRESETS, json={"name": "8MX全员台标", "scope": "shared",
                                                     "params": params}, headers=hm)
        assert shared.status_code == 403 and "只有管理员能把叠加预设设成「全员可选」" in shared.text

        listed = (await client.get(MX_PRESETS, headers=ho)).json()
        assert listed["total"] == 1 and listed["items"][0]["id"] == pid
        assert listed["positions"] == list(ov_svc.BADGE_POSITIONS)
        assert (listed["max_badges"], listed["max_text_overlays"], listed["max_text_chars"]) == (6, 6, 30)
        # 个人预设不进别人的列表（素材专员看不见运营专员存的那套）
        assert (await client.get(MX_PRESETS, headers=hm)).json()["total"] == 0

        admin_shared = await client.post(MX_PRESETS,
                                         json={"name": "8MX全员警示", "scope": "shared",
                                               "params": params}, headers=ha)
        assert admin_shared.status_code == 201, admin_shared.text
        sid = admin_shared.json()["id"]
        both = (await client.get(MX_PRESETS, headers=hm)).json()["items"]
        assert [it["id"] for it in both] == [sid], both

        # 拿预设跑一次矩阵：产物里存的是 preset_id ＋ preset_name ＋ 参数快照
        # ⚠️ 必须连 `_mx_overlay` 一起打：本机没挂 engines，`engine_available()` 恒 False，
        # 而这道闸排在**校验之后、落库之前**——不钉它，用例只会拿到一句
        # "这台机器用不了叠加引擎"，测到的是替身缺失而不是预设口径。
        with _mx_env(env["registry"], []), _mx_overlay([]):
            hit = await client.post(MX_MATRIX,
                                    json=_mx_payload(env, async_mode=False, overlay_preset_id=pid),
                                    headers=ho)
            assert hit.status_code == 200, hit.text
            assert hit.json()["overlay"] == MX_OVERLAY_SUMMARY
        row_ids = [r["output_id"] for r in hit.json()["results"]]
        assert len(row_ids) == 2, hit.json()["results"]
        for oid in row_ids:
            meta = (await _row_of(AssetOutput, oid)).compose_meta["overlay"]
            assert meta["preset_id"] == pid and meta["preset_name"] == "8MX剧名＋后果自负"
            assert meta["summary"] == MX_OVERLAY_SUMMARY

        # ★ 管理员事后改预设：历史片子的快照一个字都不许跟着变（对账以快照为准）
        # 个人预设的编辑权＝本人**或管理员**（管理员要能替离岗的人收拾），所以这里用 ha 改 ho 的。
        edited = await client.put(f"{MX_PRESETS}/{pid}",
                                  json={"name": "8MX剧名改过了",
                                        "params": {"badges": [],
                                                   "text_overlays": [{"text": "仅供内部预览",
                                                                      "position": "bottom-center",
                                                                      "font_size": 40}]}},
                                  headers=ha)
        assert edited.status_code == 200, edited.text
        assert edited.json()["name"] == "8MX剧名改过了"
        assert edited.json()["summary"] == "1 行字（仅供内部预览）", edited.json()["summary"]
        again = (await _row_of(AssetOutput, row_ids[0])).compose_meta["overlay"]
        assert again["preset_name"] == "8MX剧名＋后果自负", "改预设把历史片子也改了＝对账全乱"
        assert again["params"]["badges"][0]["asset_id"] == env["img_id"]
        # 别人的个人预设不是别人的改不了？反例：运营专员改不了素材专员那套（下面 own 建好后验）

        # 停用：本人关得掉（`_PROD_ROLES` 修的就是这一条），别人关不掉，共享的要管理员
        own = await client.post(MX_PRESETS, json={"name": "8MX素材专员自己的",
                                                 "params": params}, headers=hm)
        assert own.status_code == 201, own.text
        oid_own = own.json()["id"]
        edit_others = await client.put(f"{MX_PRESETS}/{oid_own}",
                                       json={"note": "运营专员想替素材专员改"}, headers=ho)
        assert edit_others.status_code == 403 and "没有修改个人预设" in edit_others.text and "另存一套" in edit_others.text
        not_mine = await client.request("DELETE", f"{MX_PRESETS}/{pid}", headers=hm)
        assert not_mine.status_code == 403 and "没有停用个人预设" in not_mine.text, not_mine.text
        not_shared = await client.request("DELETE", f"{MX_PRESETS}/{sid}", headers=hm)
        assert not_shared.status_code == 403 and "只有管理员能停" in not_shared.text
        retired = await client.request("DELETE", f"{MX_PRESETS}/{oid_own}", headers=hm)
        assert retired.status_code == 200 and retired.json()["active"] is False, retired.text
        assert "以后选不到了" in retired.json()["message"]
        twice = await client.request("DELETE", f"{MX_PRESETS}/{oid_own}", headers=hm)
        assert twice.status_code == 200 and "早就是停用状态" in twice.json()["message"]
        assert (await client.get(MX_PRESETS, headers=hm)).json()["total"] == 1
        inactive = [it["id"] for it in (await client.get(
            f"{MX_PRESETS}?include_inactive=true", headers=hm)).json()["items"]]
        # 不比顺序：列表按 created_at 倒序，同一秒内建的两套在 SQLite 上分不出先后，
        # 而"停用的默认不列、带上才列出来"才是这条要判的事。
        assert set(inactive) == {sid, oid_own}, inactive

        # 停用的预设选不了，话术给出路（另存一套）
        with _mx_env(env["registry"], []):
            off = await client.post(MX_MATRIX,
                                    json=_mx_payload(env, async_mode=False,
                                                     overlay_preset_id=oid_own), headers=hm)
            assert off.status_code == 400 and "已停用" in off.text and "另存一套" in off.text, off.text

        for action in ("asset.overlay_preset.create", "asset.overlay_preset.update",
                       "asset.overlay_preset.deactivate"):
            logs = await _rows(AuditLog, AuditLog.action == action)
            assert logs, f"{action} 没留痕：预设是反复用的东西，改了没人知道谁改的"
        upd = (await _rows(AuditLog, AuditLog.action == "asset.overlay_preset.update"))[0]
        assert upd.before["name"] == "8MX剧名＋后果自负", upd.before
        assert upd.after["name"] == "8MX剧名改过了", upd.after
        dec = (await _rows(AuditLog, AuditLog.action == "asset.overlay_preset.deactivate"))[0]
        assert dec.before["active"] is True and dec.after["active"] is False
        # 矩阵那条审计要把「用的哪套预设」也钉住，否则事后查不到这批片是谁的哪套参数叠的
        mtx = (await _rows(AuditLog, AuditLog.action == "asset.compose.matrix"))[0]
        assert mtx.after["overlay_preset_id"] == pid, mtx.after
        assert mtx.after["overlay"] == MX_OVERLAY_SUMMARY
        await client.aclose()

    _run(_scenario())


# ══════════════════════════════════════════════════════════════
#  26. 素材隔离 ＋ 脚本收藏（11-24 批 T）
#
#  用户原话：「加入素材隔离的概念，但默认是要能看到全部的，但是可以加入一个开关或者
#            复选框，仅看自己。这个仅看自己，不是说仅仅是自己导入的文案也可以在已有的
#            脚本库里面勾选，然后收藏起来。」
#
#  拆成三条用例，各钉各的：
#  ① 收藏＝**关系表**，不是所有权转移——收藏后 owner_id 没变、原作者照样能改，
#     收藏者也拿不到改稿权；取消收藏只删自己那一行，别人看不见影响。
#  ② `owner=me` 的口径＝我写的 ∪ 我收藏的（脚本口）／我导入的（素材口），
#     缺省仍是 all（看全部）——「默认要能看到全部的」这条不许被接口默认改掉。
#  ③ 偏好按键合并：界面有两颗开关（极简/仅看自己），各自 PUT 各自的键，
#     后一次不能把前一次静默清掉（整体覆盖语义在只有一个键时看不出问题）。
# ══════════════════════════════════════════════════════════════

async def _user_id(username: str):
    return (await _rows(User, User.username == username))[0].id


def test_script_favorites_move_others_scripts_into_my_view():
    """收藏别人的脚本＝把它拉进自己那一侧；不改归属、不授予写权、不影响别人。"""
    _run(_bootstrap())

    from app.models.asset import AssetScript, AssetScriptFavorite, SCRIPT_READY

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        op_id = await _user_id(OPERATOR_USER)

        # 运营专员建一条并定稿；素材专员一条也没有 → 缺省（me）看不到东西
        s = await _mk_script(client, ho, name="运营的好稿")
        assert (await _finalize(client, ho, s["id"])).status_code == 200
        assert (await client.get(_SCRIPT_URL, headers=hm)).json()["total"] == 0
        assert (await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=hm)).json()["total"] == 1

        # 收藏：幂等（重复点只有一行），且**不改 owner、不改状态**
        fav = await client.put(f"{_SCRIPT_URL}/{s['id']}/favorite", headers=hm)
        assert fav.status_code == 200 and fav.json()["favorited"] is True, fav.text
        again = await client.put(f"{_SCRIPT_URL}/{s['id']}/favorite", headers=hm)
        assert again.status_code == 200 and again.json()["favorited"] is True
        assert await _count(AssetScriptFavorite) == 1, "重复收藏不该长出第二行"
        row = await _row_of(AssetScript, s["id"])
        assert row.owner_id == op_id and row.state == SCRIPT_READY, "收藏把归属或状态带跑了"

        # 收藏后「我的」里有它，且带着 favorited 标记与原作者名（界面要能说清这不是你写的）
        mine = await client.get(_SCRIPT_URL, headers=hm)
        assert mine.json()["total"] == 1 and mine.json()["items"][0]["id"] == s["id"]
        assert mine.json()["items"][0]["favorited"] is True
        assert mine.json()["items"][0]["owner_name"] == "运营专员"
        # 详情口也按观察者给 favorited（点开那条时要显示星是亮着的）
        assert (await client.get(f"{_SCRIPT_URL}/{s['id']}", headers=hm)).json()["favorited"] is True

        # 只影响自己：素材专员的收藏不改变运营专员（作者本人）的视图，也不串到别人
        op_view = (await client.get(_SCRIPT_URL, headers=ho)).json()["items"]
        assert [it["id"] for it in op_view] == [s["id"]]
        assert op_view[0]["favorited"] is False, "作者本人没收藏，星不该亮"

        # 收藏≠拥有（读得到≠改得动）：素材专员的视图里多了一条，原作者的写权一点没变
        assert (await client.get(f"{_SCRIPT_URL}/{s['id']}", headers=hm)).status_code == 200

        # 取消收藏：只删自己那一行，重复取消幂等
        off = await client.request("DELETE", f"{_SCRIPT_URL}/{s['id']}/favorite", headers=hm)
        assert off.status_code == 200 and off.json()["favorited"] is False
        assert off.json()["removed"] == 1, off.json()
        assert (await client.get(_SCRIPT_URL, headers=hm)).json()["total"] == 0
        twice = await client.request("DELETE", f"{_SCRIPT_URL}/{s['id']}/favorite", headers=hm)
        assert twice.status_code == 200 and twice.json()["removed"] == 0, twice.json()
        assert (await _rows(AssetScriptFavorite)) == []

        # 收藏不授予写权限：别人的**草稿**收藏前后都改不动（403 同口径）；
        # 别人的**定稿** PUT＝派生自己的新草稿（201，归收藏者）——这条老路本来就不问人，
        # 收藏既没打开它、也没让它多改到原稿。
        d = await _mk_script(client, ho, name="运营还没定稿的", body=_SCRIPT_BODY + "镜头4：运营自己的收尾。")
        assert d["id"] != s["id"] and d["state"] == "draft"
        denied = await client.put(f"{_SCRIPT_URL}/{d['id']}", json={"name": "没收藏时想改名"}, headers=hm)
        assert denied.status_code == 403 and "另存为草稿" in denied.text, denied.text
        await client.put(f"{_SCRIPT_URL}/{d['id']}/favorite", headers=hm)
        denied2 = await client.put(f"{_SCRIPT_URL}/{d['id']}", json={"name": "收藏后想改名"}, headers=hm)
        assert denied2.status_code == 403 and "另存为草稿" in denied2.text, denied2.text
        fork = await client.put(f"{_SCRIPT_URL}/{s['id']}", json={"name": "我另存一份"}, headers=hm)
        assert fork.status_code == 201 and fork.json()["owner_id"] != str(op_id), fork.text
        assert (await _row_of(AssetScript, s["id"])).owner_id == op_id, "派生把原稿归属带走了"

        # 入参边界：不存在的脚本 404；owner 只认 me/all（拼错不能静默给全量）
        assert (await client.put(f"{_SCRIPT_URL}/{uuid.uuid4()}/favorite", headers=hm)).status_code == 404
        bad = await client.get(_SCRIPT_URL, params={"owner": "mine"}, headers=hm)
        assert bad.status_code == 400 and "我写的＋我收藏的" in bad.text, bad.text

        # 下架的脚本：收藏不复活它（默认列表仍按 state 过滤），显式点名才回
        await client.put(f"{_SCRIPT_URL}/{s['id']}/favorite", headers=hm)
        assert (await client.delete(f"{_SCRIPT_URL}/{s['id']}", headers=ho)).json()["state"] == "retired"
        after = await client.get(_SCRIPT_URL, headers=hm)
        ids = {it["id"] for it in after.json()["items"]}
        assert s["id"] not in ids, after.json()
        assert ids == {fork.json()["id"], d["id"]}, "只剩自己那条派生稿＋收藏的运营草稿；被下架的收藏不该冒出来"
        gone = await client.get(_SCRIPT_URL, params={"state": "retired"}, headers=hm)
        assert gone.json()["total"] == 1 and gone.json()["items"][0]["favorited"] is True
        await client.aclose()

    _run(_scenario())


def test_my_view_pending_filter_does_not_leak_others_drafts():
    """11-24 用户反馈②：「选择"我的"之后，好像未定稿的即使不在我的收藏里也会展现」。

    真因在**前端**——极简页「待过审」区那次请求（`carrier_status=pending`）没带 `owner`，
    于是把全员的待审稿摆进了「我的」。已修（`fetchPending` 跟着开关注入 owner）。

    这条钉的是后端这一侧，防的是另一类回退：假如哪天有人把 owner 与 carrier_status 做成
    「各自查一次再取并集」，别人的 pending 稿就会从 carrier 那条腿漏回来。口径是
    **同一批 WHERE 条件里的 AND**（misc.py `list_scripts`：conds 依次 append，最后 and_），
    所以任何筛选组合下都不该出现「不是我的、且我没收藏」的行。默认列表（含 draft）同一条。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        def ids(resp):
            assert resp.status_code == 200, resp.text
            return {it["id"] for it in resp.json()["items"]}

        # 运营侧三行：定稿并送审（载体 pending）／定稿没送审／纯草稿。
        # ⚠️ 三条正文必须各不相同——同一个人第二条**同内容 ready** 行会被唯一索引挡下
        #    （见 test_script_ready_unique），拿默认 _SCRIPT_BODY 复制两条会当场 400。
        op_pending = await _mk_script(client, ho, name="运营的待审稿",
                                      body=_SCRIPT_BODY + "镜头4：运营的待审收尾。")
        assert (await _finalize(client, ho, op_pending["id"])).status_code == 200
        sub = await client.post(
            f"{_SCRIPT_URL}/submit", json={"script_ids": [op_pending["id"]]}, headers=ho)
        assert sub.status_code == 200 and sub.json()["results"][0]["ok"] is True, sub.text
        op_ready = await _mk_script(client, ho, name="运营的没送审",
                                    body=_SCRIPT_BODY + "镜头4：运营的另写一条。")
        assert (await _finalize(client, ho, op_ready["id"])).status_code == 200
        op_draft = await _mk_script(client, ho, name="运营的草稿",
                                    body=_SCRIPT_BODY + "镜头4：运营还没写完。")
        # 素材专员自己的一条草稿（用户原话里的「未定稿」就是这个态）
        my_draft = await _mk_script(client, hm, name="我的草稿")

        # ① 「我的」＋待过审：一条也没有。同参数 owner=all 能捞到运营那条——
        #    对照着看才知道 0 是**过滤掉**的结果，不是数据压根没建上。
        assert ids(await client.get(_SCRIPT_URL, params={
            "owner": "me", "carrier_status": "pending"}, headers=hm)) == set()
        assert ids(await client.get(_SCRIPT_URL, params={
            "owner": "all", "carrier_status": "pending"}, headers=hm)) == {op_pending["id"]}

        # ② 未定稿同理：owner=me 只看得到自己的草稿；owner=all 才摆出运营的 ready 与 draft
        assert ids(await client.get(_SCRIPT_URL, params={
            "owner": "me", "state": "draft"}, headers=hm)) == {my_draft["id"]}
        assert {op_pending["id"], op_ready["id"], op_draft["id"], my_draft["id"]} <= ids(
            await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=hm))

        # ③ 收藏＝把别人的稿子拉进「我的」的唯一动作，而且**跟着每一颗筛选一起生效**：
        #    收藏后它在待过审区出现、在定稿区出现；取消收藏后两处又都干净。
        #    （只做在默认列表上的话，待过审区照样漏——正是用户看到的那个现象。）
        await client.put(f"{_SCRIPT_URL}/{op_pending['id']}/favorite", headers=hm)
        pend = {"owner": "me", "carrier_status": "pending"}
        assert ids(await client.get(_SCRIPT_URL, params=pend, headers=hm)) == {op_pending["id"]}
        assert ids(await client.get(_SCRIPT_URL, params={
            "owner": "me", "state": "ready"}, headers=hm)) == {op_pending["id"]}
        await client.request("DELETE", f"{_SCRIPT_URL}/{op_pending['id']}/favorite", headers=hm)
        assert ids(await client.get(_SCRIPT_URL, params=pend, headers=hm)) == set()
        assert ids(await client.get(_SCRIPT_URL, params={
            "owner": "me", "state": "ready"}, headers=hm)) == set()

        # ④ 作者本人不受影响：运营的「我的」里自己三条全在（隔离只收别人的）
        assert {op_pending["id"], op_ready["id"], op_draft["id"]} <= ids(
            await client.get(_SCRIPT_URL, params={"owner": "me"}, headers=ho))
        await client.aclose()

    _run(_scenario())


def test_owner_id_names_one_person_in_scripts_and_outputs():
    """批 AA「按上传人筛选」：owner_id 点名某一个人。

    钉两条口径：
    - 脚本口：owner_id＝谁**写的**；收藏不改归属（收藏只在 owner=me 那一侧生效），
      给了 owner_id 时 owner 让位——前端不必自己算该藏哪颗开关；
    - 成片口：owner_id 走 production.created_by 点名，拼接产物（production_id NULL）
      ＝公共，不冒充任何人的作品，点名时不出；行内回 owner_id 供前端下拉候选直接用。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        op_id = await _user_id(OPERATOR_USER)
        mat_id = await _user_id(MATERIAL_USER)

        s_op = await _mk_script(client, ho, name="AA·运营写的", body=_SCRIPT_BODY + "AA镜头：运营写的一条。")
        s_mat = await _mk_script(client, hm, name="AA·我写的", body=_SCRIPT_BODY + "AA镜头：我写的一条。")

        def ids(resp):
            assert resp.status_code == 200, resp.text
            return {it["id"] for it in resp.json()["items"]}

        # ① 素材专员身份点名运营：只回运营那条（owner 缺省 me，owner_id 让位给点名）
        assert ids(await client.get(_SCRIPT_URL, params={"owner_id": str(op_id)}, headers=hm)) == {s_op["id"]}
        # ② 收藏不算归属：我把运营那条收藏进"我的"，点名我自己时仍不含它
        await client.put(f"{_SCRIPT_URL}/{s_op['id']}/favorite", headers=hm)
        assert ids(await client.get(_SCRIPT_URL, params={"owner_id": str(mat_id)}, headers=hm)) == {s_mat["id"]}
        # ③ 同一批 WHERE 的 AND：点名＋一个没有的状态＝空集，不是拿全量糊弄
        assert ids(await client.get(_SCRIPT_URL, params={
            "owner_id": str(op_id), "state": "ready"}, headers=hm)) == set()

        # ④ 成片：两张单各归一人＋一条公共拼接产物
        a_id, _t = await _make_ready_asset(client, hm, DOUYIN_2)
        async with dbmod.async_session_factory() as s:
            summ = AssetSummary(asset_id=uuid.UUID(a_id), seq=1, text="AA候选")
            s.add(summ)
            await s.flush()
            p_op = AssetProduction(asset_id=uuid.UUID(a_id), summary_id=summ.id, seq=1, created_by=op_id)
            p_mat = AssetProduction(asset_id=uuid.UUID(a_id), summary_id=summ.id, seq=2, created_by=mat_id)
            s.add_all([p_op, p_mat])
            await s.flush()
            s.add(AssetOutput(production_id=p_op.id, asset_id=uuid.UUID(a_id), kind="doubao_raw",
                              file_key="aa/op.mp4", bucket=settings.MINIO_BUCKET_SLICED))
            s.add(AssetOutput(production_id=p_mat.id, asset_id=uuid.UUID(a_id), kind="doubao_raw",
                              file_key="aa/mat.mp4", bucket=settings.MINIO_BUCKET_SLICED))
            s.add(AssetOutput(asset_id=uuid.UUID(a_id), kind="composed",
                              file_key="aa/pub.mp4", bucket=settings.MINIO_BUCKET_SLICED))
            await s.commit()

        def keyed(resp):
            assert resp.status_code == 200, resp.text
            return {i["file_key"]: i for i in resp.json()["items"]}

        all_rows = keyed(await client.get("/api/assets/outputs", params={"owner": "all"}, headers=hm))
        assert set(all_rows) == {"aa/op.mp4", "aa/mat.mp4", "aa/pub.mp4"}
        assert all_rows["aa/op.mp4"]["owner_id"] == str(op_id), "行内要回 owner_id，前端候选靠它"
        assert all_rows["aa/pub.mp4"]["owner_id"] is None, "公共拼接产物无主"
        only_op = keyed(await client.get("/api/assets/outputs", params={"owner_id": str(op_id)}, headers=hm))
        assert set(only_op) == {"aa/op.mp4"}, f"点名筛：公共产物与别人的片都不该出：{set(only_op)}"
        await client.aclose()

    _run(_scenario())


def test_owner_scope_defaults_to_everything_and_prefers_the_user():
    """素材隔离的两条默认值：查询口缺省＝看全部；`owner=me` 才收进自己那一侧。

    素材口（`GET /assets`）此前只有 `created_by`（点某人名），没有"我这一侧"这颗开关，
    前端要么塞当前用户 UUID 进 `created_by`（把"仅看自己"变成一个特殊的人，四个列表
    四种写法），要么自己算——这次统一成和文案/生产单/成片同名的 `owner`。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        await _make_ready_asset(client, hm, DOUYIN_2)      # 素材专员导入的一条
        await _make_ready_asset(client, ho, DOUYIN_3)      # 运营专员导入的一条

        # 缺省＝全部（用户原话「默认是要能看到全部的」）
        default = await client.get("/api/assets", headers=hm)
        assert default.status_code == 200 and default.json()["total"] == 2, default.text
        # 仅看自己：素材专员只剩自己那条，且 created_by 与本人 UUID 一致
        mine = await client.get("/api/assets", params={"owner": "me"}, headers=hm)
        assert mine.json()["total"] == 1
        ids = await _rows(AssetItem)
        me_id = await _user_id(MATERIAL_USER)
        assert all(str(it["created_by"]) == str(me_id) for it in mine.json()["items"]), ids
        assert (await client.get("/api/assets", params={"owner": "me"}, headers=ho)).json()["total"] == 1
        assert (await client.get("/api/assets", params={"owner": "all"}, headers=ho)).json()["total"] == 2

        # `owner` 与 `created_by` 各管各的：同时给就是取交集（不是二选一打架）
        op_id = await _user_id(OPERATOR_USER)
        cross = await client.get("/api/assets", params={"owner": "me", "created_by": op_id}, headers=hm)
        assert cross.status_code == 200 and cross.json()["total"] == 0, cross.text
        # 非法值当场 400：拼错 all→al1 若静默按缺省走，界面显示的是全量、人以为是自己的
        assert (await client.get("/api/assets", params={"owner": "al1"}, headers=hm)).status_code == 400
        await client.aclose()

    _run(_scenario())


def test_ui_preferences_merge_per_key_and_validate_scope_switch():
    """界面偏好：`asset_scope_mine` 缺省关（看全部）、只认布尔，且 PUT 是**按键合并**。

    合并这条是真会踩的：极简/全量与仅看自己是两颗独立开关，各自 PUT 一个键。整体覆盖
    语义下，切一次界面模式就把用户刚勾上的「仅看自己」清回默认——用户看到的是开关自己
    跳回去，且全程没有任何报错（比崩掉难查）。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]

        # 缺省：模式按角色给，隔离一律关（「默认是要能看到全部的」）
        p0 = (await client.get("/api/assets/ui/preferences", headers=ho)).json()["ui_config"]
        assert p0["asset_library_mode"] == "simple" and p0["asset_scope_mine"] is False
        a0 = (await client.get("/api/assets/ui/preferences", headers=hm)).json()["ui_config"]
        assert a0["asset_scope_mine"] is False

        # 按键合并：先存模式，再只存开关——前一个键必须活着
        await client.put("/api/assets/ui/preferences",
                         json={"ui_config": {"asset_library_mode": "full"}}, headers=ho)
        saved = await client.put("/api/assets/ui/preferences",
                                 json={"ui_config": {"asset_scope_mine": True}}, headers=ho)
        assert saved.status_code == 200, saved.text
        cfg = saved.json()["ui_config"]
        assert cfg == {"asset_library_mode": "full", "asset_scope_mine": True}, cfg
        assert (await client.get("/api/assets/ui/preferences", headers=ho)).json()["ui_config"] == cfg

        # 关掉开关要留痕：存的仍是 False，不能让"关"回落到"没存过"（那会跟着角色重新给默认）
        off = await client.put("/api/assets/ui/preferences",
                              json={"ui_config": {"asset_scope_mine": False}}, headers=ho)
        stored = off.json()["ui_config"]
        assert stored == {"asset_library_mode": "full", "asset_scope_mine": False}, stored

        # 只认布尔："false"／0 这种一旦 accept，前端读回的是真值——开关显示开着、
        # 列表却在拉全量（比直接报错难查得多，同 11-04 风险词库级别键的教训）
        for bad_value in ("false", "0", 1, 0, [], {}):
            r = await client.put("/api/assets/ui/preferences",
                                 json={"ui_config": {"asset_scope_mine": bad_value}}, headers=ho)
            assert r.status_code == 422, f"{bad_value!r} 应被拒：{r.status_code} {r.text}"
        # 非法模式仍然 422，且不会因为一次坏请求把已存的偏好改掉
        assert (await client.put("/api/assets/ui/preferences",
                                 json={"ui_config": {"asset_library_mode": "极简"}},
                                 headers=ho)).status_code == 422
        assert (await client.get("/api/assets/ui/preferences", headers=ho)).json()["ui_config"] == stored

        # 各人管各人：素材专员的偏好不受运营专员影响
        assert (await client.get("/api/assets/ui/preferences", headers=hm)).json()["ui_config"][
            "asset_scope_mine"] is False
        await client.aclose()

    _run(_scenario())
def test_script_produce_reuses_parked_hook_codes():
    """极简开单：先吃文案名下已预取的号，缺几个补几个，取到一半也不白烧。

    2026-11-25 用户本机点「投豆包」一枪撞出两个真问题（旧写法是无条件
    `_take_hook_codes(len(picked))`）：① 导入/出文案那三个入口早把号预取在
    `asset_summaries.hook_code` 上了（批 O 的 `_auto_park_hook_codes`），极简开单
    不看预取位、整批新取一遍＝同一篇稿烧两次号；② 只取到一半就把号丢进审计然后 502，
    那几个号在共享台账已经烧掉、系统侧谁也不认，重发再取一批＝白废。
    钉四件事：
    ① 没装配号命令：502 话术带【需要手工贴号】标记（前端靠它当场摆出贴号框）＋讲清
      「一个号也没烧／重试没有用／两条出路」，不落生产单，但留一条失败取号审计；
    ② 只回一半：已取到的号**留在**对应文案的预取位（不回滚），重发只补差的那 1 个——
      `calls == [2, 1]` 就是「不白烧」的硬判据，第二枪两张单都建成、号顶上即清空；
    ③ 预取位本来就满：整批一次取号都不调（这才是「不重复烧号」的正向证据）；
    ④ 手工贴号退路：数量不符／重号各自 400，贴对了直接建单且不再自动取号。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ha = h["admin"]
        from app.models.asset import AssetScript

        async def _approved(name: str, tail: str) -> Tuple[str, str]:
            """走到「已定稿＋已过审」，返回 (脚本 id, 载体文案 id)。"""
            s = await _mk_script(client, ha, name=name, body=_SCRIPT_BODY + tail)
            assert (await _finalize(client, ha, s["id"])).status_code == 200
            ap = await client.post(
                f"{_SCRIPT_URL}/approve", json={"script_ids": [s["id"]]}, headers=ha)
            assert ap.status_code == 200 and ap.json()["results"][0]["ok"] is True, ap.text
            carrier = (await _row_of(AssetScript, s["id"])).carrier_summary_id
            return s["id"], str(carrier)

        async def _parked(cid: str) -> str:
            row = await _row_of(AssetSummary, uuid.UUID(cid))
            return str(row.hook_code or "")

        async def _set_parked(cid: str, code: str) -> None:
            """模拟导入/出文案那一路已经预取好的号（批 O 落库后的样子）。"""
            async with dbmod.async_session_factory() as sess:
                row = await sess.get(AssetSummary, uuid.UUID(cid))
                row.hook_code = code
                await sess.commit()

        fb = _FakeBoard()

        # ── ① 这台服务没装配号命令：0 个号＝台账上一次都没烧，重试也救不回来 ──
        s1, c1 = await _approved("本机试产", "镜头4：她转身离开。")
        fake0, calls0 = _take_stub([], err="未配置自动取号命令（ASSET_HOOK_ID_CMD）")
        with patch.object(settings, "ASSET_HOOK_ID_CMD", ""), \
                patch("app.api.assets._take_hook_codes", fake0):
            r0 = await client.post(f"{_SCRIPT_URL}/produce",
                                   json={"script_ids": [s1], "board_total": 1}, headers=ha)
        assert r0.status_code == 502, r0.text
        assert calls0 == [1], calls0
        d0 = r0.json()["detail"]
        assert "【需要手工贴号:1】" in d0, f"前端靠这个标记（带缺口数）摆贴号框：{d0}"
        assert "没装配号命令" in d0 and "重试没有用" in d0, d0
        assert "我自己贴号" in d0, f"得给一条走得通的出路：{d0}"
        assert "已记在共享台账" not in d0, f"一个号都没取到，不许说烧了号：{d0}"
        assert "共享台账上一个号也没取" in d0, d0
        assert await _count(AssetProduction) == 0, "取号没成不许落生产单"
        assert await _parked(c1) == "", "没取到号，预取位也不该被写脏"
        # 旧路径靠 `_take_hook_codes_audited` 必留一条取号审计，改走预取位后这条纪律不能丢
        takes0 = [a for a in await _rows(AuditLog, AuditLog.action == "asset.hook_code.take")
                  if (a.after or {}).get("via") == "script_produce"]
        assert len(takes0) == 1, [a.after for a in takes0]
        assert takes0[0].after["codes"] == [] and "ASSET_HOOK_ID_CMD" in takes0[0].after["error"]

        # ── ② 命令配好了、脚本只回一半：号留在预取位等下一枪，重发只补差额 ──
        s2, c2 = await _approved("甲稿", "镜头4：甲稿收尾。")
        s3, c3 = await _approved("乙稿", "镜头4：乙稿收尾。")
        queue = [["8PZK1"], ["8PZK2"]]
        calls2: List[int] = []

        async def fake_partial(count):
            calls2.append(int(count))
            batch = queue.pop(0) if queue else []
            return batch[: int(count)], [], "取号脚本第 2 枪超过 30 秒没回话"

        with patch.object(settings, "ASSET_HOOK_ID_CMD", "python3 /srv/hook_id.py"), \
                patch("app.api.assets._take_hook_codes", fake_partial), _board_off(fb):
            r1 = await client.post(f"{_SCRIPT_URL}/produce",
                                   json={"script_ids": [s2, s3], "board_total": 1}, headers=ha)
            assert r1.status_code == 502, r1.text
            d1 = r1.json()["detail"]
            assert "差 1 个" in d1, d1
            assert "挂在对应文案的预取位上" in d1 and "不重复取号" in d1, d1
            assert "【需要手工贴号:1】" in d1, f"缺口数＝下一枪要贴几个：{d1}"
            assert "重试没有用" not in d1, f"命令是配好的，这一支不该套未配置的话：{d1}"
            assert await _count(AssetProduction) == 0, "缺号那一次同样不落单"
            assert queue == [["8PZK2"]], "这一枪只调了一次取号（不自己重试到烧完）"
            # 号不回滚＝这一枪烧掉的号还挂在文案名下等着，下一枪直接复用
            assert await _parked(c2) == "8PZK1", await _parked(c2)
            assert await _parked(c3) == ""
            assert calls2 == [2], f"取号没成不该自己重试到烧完：{calls2}"

            r2 = await client.post(f"{_SCRIPT_URL}/produce",
                                   json={"script_ids": [s2, s3], "board_total": 1}, headers=ha)
            assert r2.status_code == 200, r2.text
        assert calls2 == [2, 1], f"重发只补缺口才算不白烧：{calls2}"
        body = r2.json()
        assert sorted(x["hook_code"] for x in body["results"]) == ["8PZK1", "8PZK2"], body["results"]
        assert await _count(AssetProduction) == 2
        # 顶上即清空：号进了生产单，预取位不再占着（与批 N/O 同一套消费口径）
        assert await _parked(c2) == "" and await _parked(c3) == ""
        # 后台投板任务不在本用例射程内：`_board_off` 一退出凭据就还原成空，
        # 协程走到投板口当场自拒（批 H 有用例专门管它），这里只核建单与号。

        # ── ③ 预取位本来就满：整批一次取号都不调 ──
        s4, c4 = await _approved("丙稿", "镜头4：丙稿收尾。")
        await _set_parked(c4, "8PZK3")
        calls3: List[int] = []

        async def fake_never(count):
            calls3.append(int(count))
            return ["9XXXX"], [], None

        with patch.object(settings, "ASSET_HOOK_ID_CMD", "python3 /srv/hook_id.py"), \
                patch("app.api.assets._take_hook_codes", fake_never):
            r3 = await client.post(f"{_SCRIPT_URL}/produce",
                                   json={"script_ids": [s4], "board_total": 1}, headers=ha)
            assert r3.status_code == 200, r3.text
        assert calls3 == [], f"预取位有号就不该再烧一批：{calls3}"
        assert r3.json()["results"][0]["hook_code"] == "8PZK3"
        # 11-25 本机实测抓出来的真 bug：这台没配后台板凭据，投板口当场 400——旧写法会把
        # 「单已建好」这一枪整个打成 400，界面显示「投豆包没成功」，人再点一次＝重复建单。
        # 现在投板被拒只降级成响应里的 dispatch 结果，并把「单没投上板」写进那句话。
        b3 = r3.json()
        assert b3["dispatch"]["queued"] is False and "自动投板还没启用" in b3["dispatch"]["error"], b3["dispatch"]
        assert "没投上板" in b3["message"] and "补投" in b3["message"], b3["message"]
        assert await _count(AssetProduction) == 3

        # ── ④ 手工贴号退路：**只补缺口**——预取位上已有的号不让人再贴一遍 ──
        s5, c5 = await _approved("丁稿", "镜头4：丁稿收尾。")
        s6, c6 = await _approved("戊稿", "镜头4：戊稿收尾。")
        calls4: List[int] = []

        async def fake_never2(count):
            calls4.append(int(count))
            return [], [], "手工贴号那一枪不该调自动取号"

        fb4 = _FakeBoard()
        with patch.object(settings, "ASSET_HOOK_ID_CMD", "python3 /srv/hook_id.py"), \
                patch("app.api.assets._take_hook_codes", fake_never2), _board_off(fb4):
            bad_n = await client.post(f"{_SCRIPT_URL}/produce", json={
                "script_ids": [s5, s6], "board_total": 1, "hook_codes": ["8PZK4"]}, headers=ha)
            assert bad_n.status_code == 400 and "还缺 2 个号，收到 1 个" in bad_n.json()["detail"], bad_n.text
            bad_dup = await client.post(f"{_SCRIPT_URL}/produce", json={
                "script_ids": [s5, s6], "board_total": 1,
                "hook_codes": ["8pzk4", "8PZK4"]}, headers=ha)
            assert bad_dup.status_code == 400 and "重号" in bad_dup.json()["detail"], bad_dup.text
            # 丁稿那条已经有预取号 → 只贴戊稿缺的那 1 个，小写也认（后端统一大写）
            await _set_parked(c5, "8PZK6")
            ok = await client.post(f"{_SCRIPT_URL}/produce", json={
                "script_ids": [s5, s6], "board_total": 1, "hook_codes": ["8pzk7"]}, headers=ha)
            assert ok.status_code == 200, ok.text
            assert calls4 == [], "手工贴号那一枪不许再自动取号"
            b4 = ok.json()
            assert sorted(x["hook_code"] for x in b4["results"]) == ["8PZK6", "8PZK7"], b4["results"]
            # 配好凭据那一支（`_board_off` 里给了假凭据）：受理即回 job，投板照常排队。
            # ⚠️ 必须**在 with 块里**等完——出块后 settings 还原成「凭据为空」，
            # 后台协程走到投板口会自己拒掉（job 变 failed），那时测的就不是这条路了。
            assert b4["dispatch"]["queued"] is True and b4["dispatch"]["job_id"], b4["dispatch"]
            assert "没投上板" not in b4["message"], b4["message"]
            job4 = await _wait_job(client, ha, b4["dispatch"]["job_id"])
            assert job4["status"] == "succeeded", job4
            # 两张单（丁稿＋戊稿）＝板上两条任务，每条 total=1（一个脚本出几版走 total，不是拆单）
            assert len(fb4.creates) == 2 and all(int(c["total"]) == 1 for c in fb4.creates), fb4.creates

        # 留痕：自动挂号走 park（两条），①② 那两枪都没落成单 → take 审计只有失败那一次
        parks = [a for a in await _rows(AuditLog, AuditLog.action == "asset.hook_code.park")
                 if (a.after or {}).get("source") == "auto_park:script_produce"]
        assert len(parks) == 2, [a.after for a in parks]
        assert await _count(AssetProduction) == 5
        await client.aclose()

    _run(_scenario())


# ─────────────  16. 文案写入面打通（11-25 批 X：候选 ↔ 脚本）  ─────────────

_X_HOOK = "总裁摘下手表扔进火锅，全场安静。秘书递上一份新合同：该签字了。"


def test_paste_import_mirrors_script_rows_and_candidate_stays_visible():
    """贴文案导入的候选同步镜像成脚本行（ready/mirror/载体=真候选），真候选不被藏。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        r = await client.post(
            "/api/assets/summaries/import-copy",
            json={"batch_name": "批X门禁", "texts": [_X_HOOK]}, headers=ho)
        assert r.status_code == 200, r.text
        sid = r.json()["items"][0]["summary_id"]

        # ① 镜像脚本：ready + mirror + 载体=真候选（pending）
        lst = await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=ho)
        row = next(x for x in lst.json()["items"] if x["source_kind"] == "mirror")
        assert row["state"] == "ready" and row["body_chars"] == len(_X_HOOK)
        assert row["carrier"]["summary_id"] == sid, row["carrier"]
        assert row["carrier"]["audit_status"] == "pending"

        # ② 真候选不被藏：summaries 默认口径可见且 is_shell=false
        lst2 = await client.get("/api/assets/summaries", params={"page_size": 300}, headers=ho)
        hit = next(x for x in lst2.json()["items"] if x["id"] == sid)
        assert hit["is_shell"] is False, hit

        # ③ 镜像行带「候选」来源，普通手写行不受影响
        assert all(x["source_kind"] != "mirror" for x in lst.json()["items"] if x["name"] != row["name"])

    _run(_scenario())


def test_mirror_becomes_producible_when_candidate_approved():
    """候选在 ③ 过审的那一刻，镜像脚本立即可投（carrier_status=approved 捞得到）——无同步写。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        r = await client.post(
            "/api/assets/summaries/import-copy",
            json={"batch_name": "批X门禁2", "texts": [_X_HOOK + "他站起身。"]}, headers=ho)
        sid = r.json()["items"][0]["summary_id"]

        ap = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid], "action": "approve"}, headers=ho)
        assert ap.status_code == 200, ap.text
        assert ap.json()["results"][0]["ok"] is True, ap.text

        lst = await client.get(
            _SCRIPT_URL, params={"owner": "all", "carrier_status": "approved"}, headers=ho)
        mirror = [x for x in lst.json()["items"] if x["source_kind"] == "mirror"]
        assert len(mirror) == 1 and mirror[0]["carrier"]["audit_status"] == "approved", mirror

    _run(_scenario())


def test_mirror_from_full_mode_produces_latest_approved_text():
    """批 AC 门（11-25 用户「从完整模式导过来的文案无法进行豆包投产」）。

    旧 bug：script_texts 校验 join `is_shell=true` 只认壳载体——完整模式导入镜像出来的
    稿（载体=真候选，is_shell=false）在极简②整批 400「不是脚本的生产载体」。
    这条钉三件事：① 没过审的 ready 镜像稿可直接投，投的是冻结的脚本正文、不调模型展开；
    ② 人工审核改正文后，镜像再投自动跟到最新过审稿（审的＝投的）；
    ③ 无需跨人确认，自动就绪不伪装成人工过审，作者/审核人/实际操作人留痕都保留。
    """
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        hm_user = (await _rows(User, User.username == MATERIAL_USER))[0]
        ho_user = (await _rows(User, User.username == OPERATOR_USER))[0]

        seq = {"n": 0}

        async def fake_take(n):
            out = []
            for _ in range(n):
                seq["n"] += 1
                out.append(f"7Z5{seq['n']:02d}")
            return (out, [], None)

        r = await client.post(
            "/api/assets/summaries/import-copy",
            json={"batch_name": "AC门禁", "texts": [_X_HOOK]},
            headers=hm,
        )
        assert r.status_code == 200, r.text
        sid = r.json()["items"][0]["summary_id"]

        lst = await client.get(_SCRIPT_URL, params={"owner": "me"}, headers=hm)
        mirror = [x for x in lst.json()["items"] if x["source_kind"] == "mirror"]
        assert len(mirror) == 1, mirror
        mid = mirror[0]["id"]

        fb = _FakeBoard()
        with _board_off(fb), patch("app.api.assets._take_hook_codes", fake_take), \
                patch("app.api.assets._call_autoclip", _fake_autoclip()) as expand:
            # ① 没过审的镜像稿：ready 即可直投，按冻结正文投产，没烧冤枉号
            early = await client.post(f"{_SCRIPT_URL}/produce", json={"script_ids": [mid]}, headers=hm)
            assert early.status_code == 200, early.text
            pid0 = early.json()["results"][0]["production_id"]
            prod0 = await _row_of(AssetProduction, uuid.UUID(pid0))
            assert prod0.prompt_text == _X_HOOK and prod0.prompt_snapshot == _X_HOOK
            assert prod0.created_by == hm_user.id
            assert not {"capacity_hint", "board_capacity", "capacity"} & early.json().keys(), early.json()
            assert expand.call_count == 0, "镜像稿走脚本直投路：不该调模型展开"
            job0 = await _wait_job(client, hm, early.json()["dispatch"]["job_id"])
            assert job0["status"] == "succeeded", job0
            assert seq["n"] == 1
            direct_logs = [a for a in await _rows(AuditLog, AuditLog.action == "asset.script.direct_ready")]
            assert len(direct_logs) == 1 and direct_logs[0].after["via"] == "simple_script_direct_produce"
            carrier0 = await _row_of(AssetSummary, uuid.UUID(sid))
            assert carrier0.audit_status == RV_APPROVED and carrier0.reviewed_by is None

            # ② 人工驳回后「改后通过」换正文 → 镜像稿照投，正文=最新过审文案，不调展开
            rev = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [sid], "action": "reject", "reason": "AC门禁要改词"}, headers=ho)
            assert rev.status_code == 200, rev.text
            edit_text = _X_HOOK[:-1] + "新画面：他当场撕了合同。"
            ed = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [sid], "action": "pass_edited", "new_text": edit_text}, headers=ho)
            assert ed.json()["results"][0]["ok"] is True, ed.text

            res = await client.post(
                f"{_SCRIPT_URL}/produce",
                json={"script_ids": [mid], "board_total": 1}, headers=ho)
            assert res.status_code == 200, res.text
            assert not {"capacity_hint", "board_capacity", "capacity"} & res.json().keys(), res.json()
            pid = res.json()["results"][0]["production_id"]
            assert pid, res.text
            prod = await _row_of(AssetProduction, uuid.UUID(pid))
            assert prod.prompt_text == edit_text and prod.prompt_snapshot == edit_text, prod.prompt_text
            assert prod.prompt_text != _X_HOOK
            assert prod.created_by == ho_user.id, "谁投产记谁"
            script_row = await _row_of(AssetScript, uuid.UUID(mid))
            carrier = await _row_of(AssetSummary, uuid.UUID(sid))
            assert script_row.owner_id == hm_user.id, "投产不转移脚本作者"
            assert carrier.reviewed_by == ho_user.id and carrier.reviewed_at is not None
            order_audits = [a for a in await _rows(AuditLog, AuditLog.action == "asset.produce_order")
                            if (a.after or {}).get("owner_cross")]
            direct_meta = order_audits[-1].after["owner_cross"]["direct_scripts"][0]
            assert order_audits[-1].operator_id == ho_user.id, "审计人记实际投产人"
            assert direct_meta["script_id"] == mid and direct_meta["cross"] is True
            assert direct_meta["owner_id"] == str(hm_user.id) and direct_meta["owner_name"] == "素材专员"
            assert expand.call_count == 0, "镜像稿走脚本直投路：不该调模型展开"
            job = await _wait_job(client, ho, res.json()["dispatch"]["job_id"])
            assert job["status"] == "succeeded", job
            assert seq["n"] == 2

            # ③ 再改一次并过审 → 再投仍跟最新过审稿
            rev2 = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [sid], "action": "reject", "reason": "AC门禁二次改词"}, headers=ho)
            assert rev2.status_code == 200, rev2.text
            edit_text2 = _X_HOOK[:-1] + "新画面：他把合同折好放进包里。"
            ed2 = await client.post(
                "/api/assets/summaries/review",
                json={"summary_ids": [sid], "action": "pass_edited", "new_text": edit_text2}, headers=ho)
            assert ed2.json()["results"][0]["ok"] is True, ed2.text

            res2 = await client.post(
                f"{_SCRIPT_URL}/produce",
                json={"script_ids": [mid], "board_total": 1}, headers=ho)
            assert res2.status_code == 200, res2.text
            assert not {"capacity_hint", "board_capacity", "capacity"} & res2.json().keys(), res2.json()
            pid2 = res2.json()["results"][0]["production_id"]
            prod2 = await _row_of(AssetProduction, uuid.UUID(pid2))
            assert prod2.prompt_text == edit_text2, prod2.prompt_text
            assert prod2.created_by == ho_user.id
            job2 = await _wait_job(client, ho, res2.json()["dispatch"]["job_id"])
            assert job2["status"] == "succeeded", job2
            assert seq["n"] == 3

    _run(_scenario())


def test_shell_hidden_by_default_visible_for_review():
    """极简送审的壳：② 素材/③ 文案默认口径继续藏；include_carriers=true 显形带 is_shell。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        s = await _mk_script(client, ho, name="批X壳稿")
        fin = await _finalize(client, ho, s["id"])
        assert fin.status_code == 200, fin.text
        sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=ho)
        assert sub.status_code == 200, sub.text

        # 载体 id 从脚本列表拿
        lst = await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=ho)
        row = next(x for x in lst.json()["items"] if x["id"] == s["id"])
        shell_sid = row["carrier"]["summary_id"]
        assert row["carrier"]["audit_status"] == "pending"

        # ③ 默认藏壳
        hidden = await client.get("/api/assets/summaries", params={"page_size": 300}, headers=ho)
        assert all(x["id"] != shell_sid for x in hidden.json()["items"]), "默认口径不该看到壳"
        # include_carriers=true 显形且带 is_shell=true
        shown = await client.get(
            "/api/assets/summaries", params={"page_size": 300, "include_carriers": "true"}, headers=ho)
        hit = next(x for x in shown.json()["items"] if x["id"] == shell_sid)
        assert hit["is_shell"] is True, hit

        # ② 素材列表看不到壳素材（壳素材 id 从显形行的 asset_id 拿）
        shell_asset = hit["asset_id"]
        items = await client.get("/api/assets", params={"page_size": 300}, headers=ho)
        assert all(x["id"] != shell_asset for x in items.json()["items"]), "壳素材不该进素材列表"

    _run(_scenario())


def test_review_shell_routes_to_light_approve():
    """③ 审核台审壳：approve 委托轻量口径放行；pass_edited 拒；reject 走通用路径。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]

        async def _shell(name):
            # 三条壳必须各用独立正文：finalize 对「同 owner 同正文」幂等返回已有 ready 行
            # （定稿即冻结的既有设计），同正文会把甲乙丙并成一条
            s = await _mk_script(client, ho, name=name, body=_SCRIPT_BODY + f"{name}收尾。")
            fin = await _finalize(client, ho, s["id"])
            assert fin.status_code == 200, fin.text
            sub = await client.post(f"{_SCRIPT_URL}/submit", json={"script_ids": [s["id"]]}, headers=ho)
            assert sub.status_code == 200, sub.text
            lst = await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=ho)
            row = next(x for x in lst.json()["items"] if x["id"] == s["id"])
            return s, row["carrier"]["summary_id"]

        # ① approve 委托轻量口径：壳没有原片，通用复核的形态闸不吃它
        s1, sid1 = await _shell("批X壳甲")
        ap = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid1], "action": "approve"}, headers=ho)
        assert ap.status_code == 200, ap.text
        assert ap.json()["results"][0]["ok"] is True, ap.text
        lst = await client.get(
            _SCRIPT_URL, params={"owner": "all", "carrier_status": "approved"}, headers=ho)
        assert any(x["id"] == s1["id"] for x in lst.json()["items"])

        # ② pass_edited 对壳没有意义：脚本定稿即冻结
        s2, sid2 = await _shell("批X壳乙")
        pe = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid2], "action": "pass_edited", "new_text": _X_HOOK}, headers=ho)
        assert pe.status_code == 200, pe.text
        assert pe.json()["results"][0]["ok"] is False, pe.text
        assert "脚本稿不支持" in pe.json()["results"][0]["error"], pe.text

        # ③ reject 走通用路径：载体育 rejected，脚本仍 ready（可投闸门拦住它，不靠状态同步）
        s3, sid3 = await _shell("批X壳丙")
        rj = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [sid3], "action": "reject", "reason": "钩子太软"}, headers=ho)
        assert rj.status_code == 200, rj.text
        assert rj.json()["results"][0]["ok"] is True, rj.text
        lst = await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=ho)
        row = next(x for x in lst.json()["items"] if x["id"] == s3["id"])
        assert row["state"] == "ready" and row["carrier"]["audit_status"] == "rejected", row

    _run(_scenario())


def test_mirror_twin_adopts_candidate():
    """同正文的手写稿已存在（ready）→ 镜像不新建，把真候选收编为它的载体。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        ho = h["operator"]
        s = await _mk_script(client, ho, name="撞稿手写", body=_X_HOOK)
        fin = await _finalize(client, ho, s["id"])
        assert fin.status_code == 200, fin.text

        r = await client.post(
            "/api/assets/summaries/import-copy",
            json={"batch_name": "批X门禁3", "texts": [_X_HOOK]}, headers=ho)
        assert r.status_code == 200, r.text
        sid = r.json()["items"][0]["summary_id"]

        lst = await client.get(_SCRIPT_URL, params={"owner": "all"}, headers=ho)
        mirrors = [x for x in lst.json()["items"] if x["source_kind"] == "mirror"]
        assert mirrors == [], "同正文已有 ready 脚本，不该再镜像一条"
        row = next(x for x in lst.json()["items"] if x["id"] == s["id"])
        assert row["carrier"]["summary_id"] == sid, row["carrier"]
        assert row["carrier"]["audit_status"] == "pending"

    _run(_scenario())
