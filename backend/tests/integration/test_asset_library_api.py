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
   把卡住的顶到最前；素材**原文件**有下载口（文件素材 presigned + 审计，链接素材如实回 external）。

运行：cd backend && python -m pytest tests/integration/test_asset_library_api.py -v
"""

import asyncio
import re
import atexit
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
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

    from app.auth import get_password_hash
    from app.config import settings
    from app.database import Base
    from fastapi import HTTPException
    from app.main import app
    from app.models.asset import (
        AS_READY_TO_PRODUCE,
        PRODUCTION_STATES,
        RV_APPROVED,
        RV_PENDING,
        RV_PASSED_EDITED,
        RV_REJECTED,
        AssetBatch,
        AssetItem,
        AssetOutput,
        AssetProduction,
        AssetSummary,
    )
    from app.models.audit import AuditLog
    from app.models.material import SystemConfig
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


def _run(coro):
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

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(WechatDownloadBase.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(WechatDownloadBase.metadata.create_all)
    async with dbmod.async_session_factory() as s:
        s.add_all([
            User(id=uuid.uuid4(), username=MATERIAL_USER, password_hash=get_password_hash(PASSWORD),
                 display_name="素材专员", role="material", data_scope="all", is_active=True),
            User(id=uuid.uuid4(), username=OPERATOR_USER, password_hash=get_password_hash(PASSWORD),
                 display_name="运营专员", role="operator", data_scope="own", is_active=True),
            User(id=uuid.uuid4(), username=ADMIN_USER, password_hash=get_password_hash(PASSWORD),
                 display_name="管理员", role="admin", data_scope="all", is_active=True),
        ])
        await s.commit()


async def _client_and_headers():
    """一个 client + 三个角色的 Authorization 头。"""
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30)
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


async def _import(client, h, links, **extra):
    resp = await client.post("/api/assets/import/batch", json={"links": links, **extra}, headers=h)
    return resp


async def _make_ready_asset(client, h, url=DOUYIN_2, *, script=SCRIPT):
    """导入一条链接，并把它的反推任务伪造成**已成功**（直接写 prompt 任务行 + 阶段态），
    返回 (asset_id, task_id)。文案生成/审核/生产这一段只依赖 content，不依赖智令网络。"""
    resp = await _import(client, h, [url])
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
        asset.status = "summarizing"
        await s.commit()
    return asset_id, task_id


def _fake_autoclip(*, candidates=None, expand_prompt=None, expand_error=None, generate_error=None):
    """autoclip 文案服务替身：按 path 分发，expand 默认把过审钩子**原样**包进提示词。"""

    async def _call(path, payload, timeout=180.0):
        if path.endswith("hook-copy/generate"):
            if generate_error:
                raise HTTPException(status_code=502, detail=generate_error)
            count = int(payload.get("count") or 3)
            return {"candidates": (candidates or CANDIDATES)[:count], "model": "fake-llm", "raw": {}}
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
            return {
                "prompt_text": text,
                "video_titles": [f"标题{i + 1}" for i in range(k)],
                "hook_copy_kept_verbatim": hook in text,
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

        with patch("wechat_download.prompt_service.PromptClient", _fake_client), \
             patch("app.api.assets._ffprobe_duration", _probe):
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

        # 再点名同一条：已有时长就跳过，绝不替人再花一次
        calls.clear()
        again = await client.post(
            "/api/assets/resolve", json={"asset_ids": [by_url[SHARE_1]]}, headers=hm)
        assert again.status_code == 200, again.text
        assert again.json()["results"] == [] and again.json()["skipped"][0]["reason"].startswith("已有时长")
        assert calls == []

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
                "/api/assets/resolve", json={"asset_ids": [by_url[SHARE_3]]}, headers=ha)
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
            # 11-03 取消隔离：operator 也能对素材专员的素材发起反推（旧口径这里 404），
            # 但**钱**的闸门不分人 —— 余额不足照样 409，一次外部提交都不发
            cross = await client.post("/api/assets/analyze/batch", json=payload, headers=h["operator"])
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
                "/api/assets/analyze/batch", json=payload, headers=h["admin"])
            assert admin_no_force.status_code == 409, "admin 不表决心也不放行"
            assert cpt.await_count == 0

            admin_force = await client.post(
                "/api/assets/analyze/batch", json={**payload, "force": True}, headers=h["admin"])
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
                "/api/assets/analyze/batch", json=payload, headers=h["admin"])
            assert admin_unconfirmed.status_code == 409, "admin 也要先确认成本"

            ok = await client.post(
                "/api/assets/analyze/batch", json={**payload, "confirmed": True}, headers=h["admin"])
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
        assert "都已处理过" in blocked.json()["detail"]

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
        assert body["asset"]["status"] == "summarizing"
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
    """三条候选落库：字数、高风险词、一致性校验各归各位，且带一个推荐条。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm = h["material"]
        asset_id, task_id = await _make_ready_asset(client, hm)

        with patch("app.api.assets._call_autoclip", _fake_autoclip()) as call:
            gen = await client.post(
                "/api/assets/summaries/generate",
                json={"asset_ids": [asset_id], "extra_requirements": "突出医院门口"},
                headers=hm,
            )
        assert gen.status_code == 200, gen.text
        assert gen.json()["results"][0]["created"] == 3
        payload = call.await_args.args[1]
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


def test_overwrite_refuses_when_a_copy_already_approved():
    """过审文案已挂生产单 → overwrite 拒绝（删了会让 summary 外键悬空）。"""
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        with patch("app.api.assets._call_autoclip", _fake_autoclip()):
            await client.post("/api/assets/summaries/generate", json={"asset_ids": [asset_id]}, headers=hm)
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

    CANDIDATES 的第 2、3 条是故意造的坏样本（实体对不上 / 含 block 风险词），
    A2-1 之后它们**过不了审也投不了产**，happy path 必须显式挑干净的那条，
    别靠队列顺序（顺序是 created_at 倒序，等于随机）。
    """
    good = [i for i in items if not i["risk_hit"] and i["consistency_ok"]]
    assert len(good) == 1, [i["text"] for i in items]
    return good[0]


def _risky(items):
    """含 block 级风险词的那条，用来验复核真的会拦。"""
    return next(i for i in items if i["risk_hit"])


def test_review_rejects_self_review_and_requires_reason():
    """生产者不得自审（admin 除外）；驳回/需改写必填理由；发布专员无权审核。"""
    _run(_bootstrap())

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

        # operator 自审：自己导入的素材，自己过审 → 挡下（先让它有自己的「反推已成功」素材）
        own_asset, _ = await _make_ready_asset(client, ho, url=DOUYIN_1)
        own_items, _ = await _gen_and_list(own_asset, ho, client)
        assert own_items and all(i["asset_id"] == own_asset for i in own_items)
        blocked = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [own_items[0]["id"]], "action": "approve"}, headers=ho)
        assert blocked.status_code == 200
        assert blocked.json()["results"][0]["ok"] is False
        assert "生产者不能审核自己" in blocked.json()["results"][0]["error"]

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
        audits = await _rows(AuditLog, AuditLog.action == "asset.summary_review.approve")
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
                    "summary_ids": [clean_id], "n": 3, "accounts": 2, "duration": 10,
                    "hook_codes": ["7C0B1", "7C0B2", "7C0B3"], "recommended_title_count": 4,
                    "character_card_key": "asset-cards/card-1.jpg",
                },
                headers=ho)
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 3
        assert resp.json()["capacity_hint"]["days"] == 1
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
        assert ex["capacity"]["capacity_per_day"] == 4 * settings.ASSET_DOUBAO_PER_ACCOUNT_PER_DAY

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


def test_produce_board_channel_validation_and_capacity():
    """后台板口径的四条校验：时长、board_total、编号、当日投放量软提示（B-1/B-4/B-8）。"""
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

        # B-8：软提示不硬限——把上限调到 2，投 3 条仍然成功，但要提示分日
        old_cap = settings.ASSET_BOARD_DAILY_SOFT_CAP
        settings.ASSET_BOARD_DAILY_SOFT_CAP = 2
        try:
            with patch("app.api.assets._call_autoclip", _fake_autoclip()):
                heavy = await client.post(
                    "/api/assets/produce",
                    json={"summary_ids": [sid], "n": 3, "board_total": 4}, headers=ho)
            assert heavy.status_code == 200, "产能不限：软闸门不许拒绝"
            cap = heavy.json()["board_capacity"]
            assert cap["planned"] == 12 and cap["over_cap"] > 0
            assert cap["advisory"] and "号池实测" in cap["advisory"] and "分日" in cap["advisory"]
            assert any("号池实测" in w for w in heavy.json()["warnings"])
        finally:
            settings.ASSET_BOARD_DAILY_SOFT_CAP = old_cap
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
    """A2-1：block 风险词 / 一致性假的候选**approve 真的拦**；只有 admin 能带理由豁免，豁免进审计。

    改前的行为是"只记录不拦"——risk_hit 非空照样过审、照样投产，审核台等于橡皮章。
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

        # 一致性假的那条同样拦（成因是"实体对不上"，不是风险词）
        refused2 = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [bad_consist["id"]], "action": "approve"}, headers=ho)
        assert {p["code"] for p in refused2.json()["results"][0]["problems"]} == {"consistency"}

        # 豁免只对 admin 生效：operator 带理由也照样拦
        op_waive = await client.post(
            "/api/assets/summaries/review",
            json={"summary_ids": [risky["id"]], "action": "approve", "waive_reason": "剧情需要"}, headers=ho)
        assert op_waive.json()["results"][0]["ok"] is False

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
            "/api/assets/summaries/generate", json={"asset_ids": [asset_id], "overwrite": True}, headers=ha)
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
                "/api/assets/summaries/generate", json={"asset_ids": [asset_id], "overwrite": True}, headers=ha)
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

        # 正常：第 1 条投上板
        q = await client.post("/api/assets/productions/status",
                              json={"ids": [ids[0]], "status": "queued", "board_tid": "T-9001"}, headers=ho)
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

        # 撤审只作废**未投递**那张（A2-2）：已投的是既成事实，不抹号池当日量
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "reject", "reason": "角度不对"}, headers=ho)
        assert (await _row_of(AssetProduction, ids[3])).status == "superseded"
        assert (await _row_of(AssetProduction, ids[0])).status == "running"
        after_revoke = await client.post(
            "/api/assets/productions/status",
            json={"ids": [ids[3]], "status": "success"}, headers=ho)
        assert after_revoke.status_code == 200 and after_revoke.json()["updated"] == 0
        assert "作废" in after_revoke.json()["blocked"][0]["reason"]
        d2 = after_revoke.json()["dispatch"]
        assert d2["by_status"] == {"running": 1, "success": 1, "failed": 1, "superseded": 1}
        assert d2["dispatched"] == 3 and d2["today"]["dispatched"] == 3, "作废不该把已投的量抹成没投"

        logs = await _rows(AuditLog, AuditLog.action == "asset.production_status")
        assert logs, "改台账必须留痕"
        assert logs[0].before["from"][ids[0]] == "order_ready"
        assert logs[0].after["to"] == "queued" and logs[0].after["board_tid"] == "T-9001"
        assert logs[-1].after["blocked"][0]["id"] == ids[3]
        await client.aclose()

    _run(_scenario())


def test_dispatch_today_counts_uses_board_rows_not_row_count():
    """`dispatch.today` 的**单位**必须钉在「号池吃掉的条数」（Σ board_total），不是生产单行数。

    软提示线 `ASSET_BOARD_DAILY_SOFT_CAP` 是「条/日」（实测 ≈120 条出片），
    而一张板 `total=3` 就是 3 条。若拿行数去比线，6 张 ×20＝120 条只会被读成 6，
    永远提示不到人——正好在真出事的那天失灵。
    """
    from app.config import settings
    _run(_bootstrap())

    async def _scenario():
        client, h = await _client_and_headers()
        hm, ho = h["material"], h["operator"]
        asset_id, _ = await _make_ready_asset(client, hm)
        items, _ = await _gen_and_list(asset_id, hm, client)
        sid = _approvable(items)["id"]
        await client.post("/api/assets/summaries/review",
                          json={"summary_ids": [sid], "action": "approve"}, headers=ho)

        old_cap = settings.ASSET_BOARD_DAILY_SOFT_CAP
        settings.ASSET_BOARD_DAILY_SOFT_CAP = 2
        try:
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

            # 没投上板：号池当日 0 条（未投的单不吃额度，不许算进当日事实）
            t0 = made.json()["dispatch"]["today"]
            assert t0["tasks"] == 0 and t0["board_rows"] == 0 and t0["over_cap"] == 0

            st = await client.post("/api/assets/productions/status",
                                   json={"ids": [pid], "status": "queued"}, headers=ho)
            assert st.status_code == 200, st.text
            t1 = st.json()["dispatch"]["today"]
            assert t1["tasks"] == 1, "行数＝1 张板"
            assert t1["board_rows"] == 3, "号池吃掉的是 Σ total＝3 条"
            assert t1["soft_cap"] == 2 and t1["over_cap"] == 1, "超线按条数算：3-2＝1"
            assert "已超号池实测" in t1["note"]

            # 列表口同一套数（不跟 status= 筛选走）
            lst = await client.get("/api/assets/productions?status=queued", headers=ho)
            assert lst.json()["dispatch"]["today"]["over_cap"] == 1
        finally:
            settings.ASSET_BOARD_DAILY_SOFT_CAP = old_cap
        await client.aclose()

    _run(_scenario())
