"""第三方 provider 余量查询（`_fetch_http_balance`）的单测。

为什么单独立一个文件：11-03 接 163 现网时实测出两个"配了也不生效"的坑——
1. adapter 的 httpx 客户端**没有 base_url**，`QUOTA_PATH` 写相对路径会抛
   「Request URL must include a protocol」，报出来是一句 ValueError，看不出是没拼 base；
2. 余量请求**不自动带 Key**，想鉴权只能把密钥再抄一份进 `QUOTA_PARAM`
   （同一个 Key 在 .env 里躺两遍）。
现在相对路径自动拼 `<NAME>_BASE`、鉴权复用 adapter 的 `auth` 口径。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_balance_probe.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 导入链上 app.config 是模块级单例（导入即校验必填项）——先给齐测试 env
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_zl_balance.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from wechat_download import provider_registry as pr  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"code": 0, "data": {"balance": "12340"}}

    def json(self):
        return self._payload


class _RecordingClient:
    """假 httpx 客户端：记下每次请求的 url / params / headers / json。"""

    def __init__(self, resp=None):
        self.calls = []
        self.resp = resp or _Resp()

    async def request(self, method, url, params=None, headers=None, json=None):
        self.calls.append({"method": method, "url": url, "params": params,
                           "headers": headers, "json": json})
        return self.resp


def _set_env(monkeypatch, name: str, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(f"WECHAT_DL_{name}_{k}", v)
    if "QUOTA_PATH" not in kv:
        monkeypatch.delenv(f"WECHAT_DL_{name}_QUOTA_PATH", raising=False)


# ─────────────  1. 相对路径必须拼上 BASE（曾经的头号坑） ─────────────

@pytest.mark.asyncio
async def test_relative_quota_path_is_joined_with_base(monkeypatch):
    _set_env(monkeypatch, "ZHA", QUOTA_PATH="/api/user/balance", QUOTA_FIELD="data.balance", QUOTA_UNIT="点")
    client = _RecordingClient()
    out = await pr._fetch_http_balance(client, "zha", base="https://api.example.com/", key="k123")
    assert client.calls[0]["url"] == "https://api.example.com/api/user/balance", client.calls
    assert out == {"balance": 12340, "unit": "点"}, out


@pytest.mark.asyncio
async def test_absolute_quota_url_is_used_as_is(monkeypatch):
    _set_env(monkeypatch, "ZHB", QUOTA_PATH="https://other.host/api/balance", QUOTA_FIELD="balance")
    client = _RecordingClient(_Resp(payload={"balance": 12.34}))
    out = await pr._fetch_http_balance(client, "zhb", base="https://api.example.com")
    assert client.calls[0]["url"] == "https://other.host/api/balance"
    assert out == {"balance": 12.34, "unit": "次"}, out


# ─────────────  2. 鉴权复用 adapter 的口径，Key 不抄第二遍 ─────────────

@pytest.mark.asyncio
async def test_query_auth_attaches_key_param(monkeypatch):
    _set_env(monkeypatch, "ZHC", QUOTA_PATH="/api/balance")
    client = _RecordingClient()
    await pr._fetch_http_balance(client, "zhc", base="https://a.test", key="SECRET", auth="query", key_param="apikey")
    assert client.calls[0]["params"] == {"apikey": "SECRET"}


@pytest.mark.asyncio
async def test_bearer_auth_goes_into_header(monkeypatch):
    _set_env(monkeypatch, "ZHD", QUOTA_PATH="/api/balance")
    client = _RecordingClient()
    await pr._fetch_http_balance(client, "zhd", base="https://a.test", key="SECRET", auth="bearer")
    assert client.calls[0]["headers"] == {"Authorization": "Bearer SECRET"}
    assert not client.calls[0]["params"]


@pytest.mark.asyncio
async def test_quota_param_still_merges_and_can_override(monkeypatch):
    _set_env(monkeypatch, "ZHE", QUOTA_PATH="/api/balance", QUOTA_PARAM='{"key":"OVERRIDE","tag":"x"}')
    client = _RecordingClient()
    await pr._fetch_http_balance(client, "zhe", base="https://a.test", key="SECRET")
    assert client.calls[0]["params"] == {"key": "OVERRIDE", "tag": "x"}


@pytest.mark.asyncio
async def test_post_sends_body(monkeypatch):
    _set_env(monkeypatch, "ZHF", QUOTA_PATH="/api/balance", QUOTA_METHOD="POST")
    client = _RecordingClient()
    await pr._fetch_http_balance(client, "zhf", base="https://a.test", key="SECRET")
    call = client.calls[0]
    assert call["method"] == "POST" and call["json"] == {"key": "SECRET"} and call["params"] is None


# ─────────────  3. 没配 / 查不到 的降级口径 ─────────────

@pytest.mark.asyncio
async def test_no_quota_path_means_unknown_without_request(monkeypatch):
    monkeypatch.delenv("WECHAT_DL_ZHG_QUOTA_PATH", raising=False)
    client = _RecordingClient()
    out = await pr._fetch_http_balance(client, "zhg", base="https://a.test", key="SECRET")
    assert out == {} and client.calls == []


@pytest.mark.asyncio
async def test_http_error_is_reported_not_swallowed(monkeypatch):
    _set_env(monkeypatch, "ZHH", QUOTA_PATH="/api/balance")
    client = _RecordingClient(_Resp(status_code=404, payload={}))
    out = await pr._fetch_http_balance(client, "zhh", base="https://a.test", key="SECRET")
    assert out == {"error": "http 404"}, out


@pytest.mark.asyncio
async def test_missing_field_names_the_field(monkeypatch):
    _set_env(monkeypatch, "ZHI", QUOTA_PATH="/api/balance", QUOTA_FIELD="data.remain")
    client = _RecordingClient(_Resp(payload={"code": 0, "data": {"balance": 1}}))
    out = await pr._fetch_http_balance(client, "zhi", base="https://a.test")
    assert out == {"error": "响应中未找到字段 data.remain"}, out


# ─────────────  4. 智令现网实测：没有余量接口（别再把猜测写进 .env） ─────────────

@pytest.mark.asyncio
async def test_zhiling_has_no_public_balance_endpoint(monkeypatch):
    """11-03 在 163 容器内实测：`/api/user/balance` 等 12 个候选路径全 404。

    所以 `WECHAT_DL_ZHILING_QUOTA_*` 三行**填了也查不到数**，闸门按「余额未知＝放行 +
    事后对账」走是正确行为，不是故障。哪天智令开放了余量接口，把本注释删掉、
    配上 QUOTA_PATH 即可（相对路径会自动拼 BASE，Key 自动带）。
    """
    _set_env(monkeypatch, "ZHILING", QUOTA_PATH="/api/user/balance", QUOTA_FIELD="data.balance", QUOTA_UNIT="点")
    client = _RecordingClient(_Resp(status_code=404, payload={}))
    out = await pr._fetch_http_balance(
        client, "zhiling", base="https://api.17zhiling.com", key="whatever", auth="query",
    )
    assert out == {"error": "http 404"}, out
    assert client.calls[0]["url"] == "https://api.17zhiling.com/api/user/balance"
