"""lan_source 客户端剧目清单发现 / 归一化模糊匹配兜底 单测。

覆盖 ISSUE #142 修复：
1. `_discover_from_dupload` 应请求 `manage_base`（21:8800），而非 `base`（163:8765）；
2. `discover_dramas` 合并 manage + dupload 两个清单（去重），manage 非空也拉 dupload；
3. 「扫地出门三胎宝妈是千金」经归一化模糊匹配命中「扫地出门，三胎宝妈是千金」。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lan_source.client as mod
from lan_source.client import LanSourceClient, ManageDrama, normalize_drama_name
from lan_source.config import LanSourceConfig

# 与生产默认一致：base=163:8765（cdn 源），manage_base=21:8800（管理平台）
BASE = "http://192.168.1.163:8765"
MANAGE = "http://192.168.1.21:8800"

# dupload/tasks 返回结构（{data:[{dramaName,...}]}，317 个剧，含「扫地出门，三胎宝妈是千金」）
DUP_ITEMS = [
    {"dramaName": "扫地出门，三胎宝妈是千金", "dramaId": 10001, "total": 30, "desc": "含全角逗号"},
    {"dramaName": "双宝牵线", "dramaId": 10002, "total": 48, "desc": ""},
]
DUP_DATA = {"data": DUP_ITEMS}

# sync/tasks 返回结构（{tasks:[{dramaInfo:{dramaName,...}}]}，21 个剧，与 dupload 部分重叠）
SYNC_TASKS = [
    {"dramaInfo": {"dramaName": "双宝牵线", "dramaId": 20001, "total": 48, "desc": "重叠剧"}, "status": 1},
    {"dramaInfo": {"dramaName": "六年房贷", "dramaId": 20002, "total": 24, "desc": ""}, "status": 1},
]
SYNC_DATA = {"tasks": SYNC_TASKS}


class FakeResp:
    def __init__(self, status_code, payload, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else ("" if isinstance(payload, (dict, list)) else str(payload))

    def json(self):
        return self._payload


class FakeClient:
    """httpx.AsyncClient 双替身：类级记录请求，按 path 返回对应响应。"""

    requests = []

    @classmethod
    def reset(cls):
        cls.requests = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.__class__.requests.append(url)
        if url.endswith("/api/bg/sync/tasks"):
            return FakeResp(200, SYNC_DATA)
        if url.endswith("/api/dupload/tasks"):
            return FakeResp(200, DUP_DATA)
        raise AssertionError(f"unexpected url: {url}")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("lan_source.client.httpx.AsyncClient", FakeClient)
    FakeClient.reset()
    cfg = LanSourceConfig(base_url=BASE, manage_base=MANAGE)
    return LanSourceClient(config=cfg)


def names(dramas):
    return [d.name for d in dramas]


# ── 修复点 1：dupload 清单走 manage_base ──
async def test_dupload_uses_manage_base(client):
    out = await client._discover_from_dupload()
    assert FakeClient.requests == [f"{MANAGE}/api/dupload/tasks"]
    assert names(out) == ["扫地出门，三胎宝妈是千金", "双宝牵线"]


async def test_dupload_fallback_to_base_when_no_manage(monkeypatch):
    monkeypatch.setattr("lan_source.client.httpx.AsyncClient", FakeClient)
    FakeClient.reset()
    cfg = LanSourceConfig(base_url=BASE, manage_base="")
    c = LanSourceClient(config=cfg)
    out = await c._discover_from_dupload()
    assert FakeClient.requests == [f"{BASE}/api/dupload/tasks"]
    assert len(out) == 2


# ── 修复点 2：两源合并去重，manage 非空不跳过 dupload ──
async def test_discover_merges_both_sources(client):
    out = await client.discover_dramas()
    # manage 2 个（双宝牵线/六年房贷）+ dupload 2 个，重叠的「双宝牵线」去重 → 3 个
    assert names(out) == ["双宝牵线", "六年房贷", "扫地出门，三胎宝妈是千金"]
    keys = [normalize_drama_name(d.name) for d in out]
    assert len(keys) == len(set(keys))


async def test_discover_skips_failed_manage(monkeypatch, client):
    """manage 源失败不阻塞：仍返回 dupload 清单。"""

    class FailManage(FakeClient):
        async def get(self, url):
            self.requests.append(url)
            if url.endswith("/api/bg/sync/tasks"):
                raise RuntimeError("manage down")
            return await super().get(url)

    monkeypatch.setattr("lan_source.client.httpx.AsyncClient", FailManage)
    FailManage.reset()
    out = await client.discover_dramas()
    assert names(out) == ["扫地出门，三胎宝妈是千金", "双宝牵线"]


async def test_discover_skips_failed_dupload(client):
    """dupload 源失败不阻塞：仍返回 manage 清单。"""

    class FailDup(FakeClient):
        async def get(self, url):
            self.requests.append(url)
            if url.endswith("/api/dupload/tasks"):
                raise RuntimeError("dupload down")
            return await super().get(url)

    mod.httpx.AsyncClient = FailDup
    FailDup.reset()
    try:
        out = await client.discover_dramas()
    finally:
        mod.httpx.AsyncClient = FakeClient
    assert names(out) == ["双宝牵线", "六年房贷"]


# ── 修复点 3：归一化模糊匹配兜底命中「扫地出门」 ──
def test_normalize_strips_fullwidth_punct():
    assert normalize_drama_name("扫地出门，三胎宝妈是千金") == normalize_drama_name("扫地出门三胎宝妈是千金")


async def test_find_matched_drama_hits_dupload_only(client):
    matched = await client._find_matched_drama("扫地出门三胎宝妈是千金")
    assert matched == "扫地出门，三胎宝妈是千金"


async def test_fetch_episodes_fuzzy_fallback(client):
    """精确查 400 drama not found → 模糊匹配命中 dupload 清单剧名 → 重查返回 30 集。"""
    from urllib.parse import quote

    exact_url = f"{MANAGE}/api/ext/drama/{quote('扫地出门三胎宝妈是千金')}/videos"
    retry_url = f"{MANAGE}/api/ext/drama/{quote('扫地出门，三胎宝妈是千金')}/videos"

    class FuzzyFake(FakeClient):
        async def get(self, url):
            self.requests.append(url)
            if url == exact_url:
                return FakeResp(400, {"error": "drama not found"}, text='{"error": "drama not found"}')
            if url == retry_url:
                return FakeResp(200, {
                    "items": [{"episode": i, "url": f"http://cdn/{i}.mp4"} for i in range(1, 31)]
                })
            return await super().get(url)

    mod.httpx.AsyncClient = FuzzyFake
    FuzzyFake.reset()
    try:
        episodes = await client.fetch_episodes("扫地出门三胎宝妈是千金")
    finally:
        mod.httpx.AsyncClient = FakeClient

    assert exact_url in FuzzyFake.requests
    assert retry_url in FuzzyFake.requests
    assert len(episodes) == 30
    assert episodes[0].episode == 1 and episodes[-1].episode == 30
