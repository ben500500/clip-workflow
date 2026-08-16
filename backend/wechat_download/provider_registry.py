"""视频号解析 Provider 注册表（多服务商灵活配置，兜底链）。

设计目标（用户需求：灵活配置多家解析服务）：
- 解析链路从「硬编码 yuanbao → preview」升级为 **配置驱动的有序 provider 列表**，
  任一成功即返回，全部失败聚合错误。
- 新增一家解析服务商 **零代码改动**：只需在 163 `.env` 增加
  `WECHAT_DL_PROVIDERS` 追加名字 + 该名字对应 `WECHAT_DL_<NAME>_BASE/_KEY/_PATH` 等。
- 内置三类 adapter：
    * yuanbao   —— 复用既有 YuanbaoClient（POST get_parse_result，占位端点 405 跳过）
    * preview   —— 复用既有 PreviewClient（CDP 登录态兜底，架构上拿不到视频流）
    * http      —— 通用 HTTP API adapter，覆盖 17zhiling/wxshares（GET ?key=&url=）、
                   getoneapi（POST Bearer）等第三方，靠 env 配置适配，无需改代码。

配置示例（.env）：
    WECHAT_DL_PROVIDERS = yuanbao,zhiling,wxshares,preview
    WECHAT_DL_ZHILING_BASE  = https://api.17zhiling.com
    WECHAT_DL_ZHILING_KEY   = xxxx
    WECHAT_DL_ZHILING_PATH  = /api/video/parse-video-url
    WECHAT_DL_WXSHARES_BASE = https://api.wxshares.com
    WECHAT_DL_WXSHARES_KEY  = xxxx
    WECHAT_DL_WXSHARES_PATH = /api/qsy/sphzy

未设置 WECHAT_DL_PROVIDERS 时回退为 "yuanbao,preview"（完全向后兼容）。
"""

import logging
import os
from typing import List, Optional

import httpx

from wechat_download.yuanbao_client import (
    ParseResult,
    YuanbaoClient,
    YuanbaoParseError,
)
from wechat_download.preview_client import (
    PreviewClient,
    PreviewUnavailableError,
)

logger = logging.getLogger(__name__)


class ProviderParseError(Exception):
    """某一家解析 provider 解析失败（触发兜底链下一家）。"""


class BaseParseClient:
    """解析 provider 抽象基类。channel 即逻辑名，也用作 WechatParseRecord.channel。"""

    channel: str = "base"

    async def parse(self, share_url: str, db=None) -> ParseResult:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class YuanbaoAdapter(BaseParseClient):
    """包装既有 YuanbaoClient（POST get_parse_result）。"""

    channel = "yuanbao"

    def __init__(self) -> None:
        self._c = YuanbaoClient()

    async def parse(self, share_url: str, db=None) -> ParseResult:
        try:
            return await self._c.parse(share_url)
        except YuanbaoParseError as e:
            raise ProviderParseError(str(e)) from e

    async def close(self) -> None:
        try:
            await self._c.close()
        except Exception:
            pass


class PreviewAdapter(BaseParseClient):
    """包装既有 PreviewClient（CDP 登录态兜底）。"""

    channel = "preview"

    def __init__(self) -> None:
        self._c = PreviewClient()

    async def parse(self, share_url: str, db=None) -> ParseResult:
        try:
            return await self._c.parse(share_url, db=db)
        except PreviewUnavailableError as e:
            raise ProviderParseError(str(e)) from e

    async def close(self) -> None:
        try:
            await self._c.close()
        except Exception:
            pass


def _dig(d: dict, path: str):
    """按点分路径取嵌套字段，如 'data.play_url'。"""
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def _is_image_url(u: str) -> bool:
    """封面图直链特征（与 preview_client 一致）：含 picformat / wxampicformat 的是图片，排除。"""
    return bool(u) and ("picformat" in u or "wxampicformat" in u)


class HttpApiAdapter(BaseParseClient):
    """通用第三方 HTTP 解析 API adapter（配置驱动，零代码接入新家）。

    支持 GET/POST、query/bearer/header 三种鉴权、请求 URL 字段名、响应 URL 字段
    （点分路径）可配。响应归一化兼容常见字段名（play_url/url/video_url/data.url…），
    并排除封面图直链，只返回真实视频流。
    """

    def __init__(self, name: str, base: str) -> None:
        self.channel = name
        self.name = name
        p = name.upper()
        self.base = base.rstrip("/")
        self.key = os.getenv(f"WECHAT_DL_{p}_KEY", "") or ""
        self.path = (os.getenv(f"WECHAT_DL_{p}_PATH", "") or "").strip()
        self.method = (os.getenv(f"WECHAT_DL_{p}_METHOD", "GET") or "GET").strip().upper()
        self.auth = (os.getenv(f"WECHAT_DL_{p}_AUTH", "query") or "query").strip().lower()
        self.key_param = os.getenv(f"WECHAT_DL_{p}_KEY_PARAM", "key") or "key"
        self.url_param = os.getenv(f"WECHAT_DL_{p}_URL_PARAM", "url") or "url"
        self.resp_url_field = (os.getenv(f"WECHAT_DL_{p}_RESP_URL_FIELD", "") or "").strip()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (clip-workflow/wechat-dl)"},
        )

    def _build_url(self) -> str:
        if self.path:
            return f"{self.base}/{self.path.lstrip('/')}"
        return self.base

    async def parse(self, share_url: str, db=None) -> ParseResult:
        if not self.key and self.auth in ("query", "bearer", "header"):
            raise ProviderParseError(
                f"[{self.channel}] 未配置 WECHAT_DL_{self.name.upper()}_KEY，跳过"
            )
        url = self._build_url()
        headers = {}
        params = {}
        json_body = None
        if self.auth == "bearer" and self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        elif self.auth == "header" and self.key:
            headers["X-API-Key"] = self.key

        if self.method == "POST":
            json_body = {self.url_param: share_url}
            if self.auth == "query" and self.key:
                json_body[self.key_param] = self.key
        else:  # GET
            params[self.url_param] = share_url
            if self.auth == "query" and self.key:
                params[self.key_param] = self.key

        try:
            resp = await self._client.request(
                self.method, url, params=params or None, json=json_body, headers=headers
            )
        except httpx.HTTPError as e:
            raise ProviderParseError(f"[{self.channel}] 请求失败: {e}") from e

        if resp.status_code != 200:
            raise ProviderParseError(
                f"[{self.channel}] http {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except Exception:
            # 非 JSON 响应（如 Cloudflare 1010 拦截页）→ 视为被墙/未授权
            raise ProviderParseError(
                f"[{self.channel}] 响应非 JSON（可能被 WAF 拦截或未授权），body 前 120 字节: "
                f"{resp.text[:120]}"
            )

        result = self._normalize(data, raw=resp.text)
        if not result.success:
            raise ProviderParseError(result.error or f"[{self.channel}] 响应无可用视频直链")
        return result

    def _normalize(self, data: dict, raw: str = "") -> ParseResult:
        """把第三方响应归一化为 ParseResult；找不到视频直链则 success=False。"""
        candidates = []
        if self.resp_url_field:
            candidates.append(self.resp_url_field)
        candidates += [
            "play_url", "url", "video_url", "media",
            "data.play_url", "data.url", "data.video_url",
            "video_info.play_url", "video_info.url",
            "result.url", "result.play_url",
        ]
        play_url = None
        for c in candidates:
            v = _dig(data, c) if "." in c else data.get(c)
            if isinstance(v, str) and v.startswith("http") and not _is_image_url(v):
                play_url = v
                break
        if not play_url:
            # 提取失败信息（若有）
            msg = (
                data.get("msg") or data.get("message") or data.get("error")
                or data.get("errmsg") or (data.get("data") or {}).get("msg")
                if isinstance(data.get("data"), dict) else data.get("msg")
            )
            return ParseResult(
                success=False, channel=self.channel,
                error=f"无可用视频直链（响应 code={data.get('code')}, msg={msg}）",
                raw=raw[:4000],
            )
        title = _dig(data, "title") or data.get("title") or data.get("name") or _dig(data, "data.title")
        cover = data.get("cover") or data.get("cover_url") or _dig(data, "data.cover")
        duration = data.get("duration") or _dig(data, "data.duration")
        return ParseResult(
            success=True, channel=self.channel,
            play_url=str(play_url),
            title=str(title) if title else None,
            cover_url=str(cover) if cover else None,
            duration=float(duration) if duration else None,
            meta=data, raw=raw,
        )

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


def build_providers() -> List[BaseParseClient]:
    """按 WECHAT_DL_PROVIDERS 有序构建 provider 列表（默认 yuanbao,preview）。"""
    raw = os.getenv("WECHAT_DL_PROVIDERS", "yuanbao,preview") or "yuanbao,preview"
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    clients: List[BaseParseClient] = []
    for n in names:
        if n == "yuanbao":
            clients.append(YuanbaoAdapter())
        elif n == "preview":
            clients.append(PreviewAdapter())
        else:
            base = os.getenv(f"WECHAT_DL_{n.upper()}_BASE")
            if not base:
                logger.warning(
                    "provider '%s' 未配置 WECHAT_DL_%s_BASE，已跳过", n, n.upper()
                )
                continue
            clients.append(HttpApiAdapter(name=n, base=base))
    return clients


async def dispatch_parse(share_url: str, db=None) -> ParseResult:
    """遍历 provider 兜底链，返回首个成功的 ParseResult；全部失败抛 ProviderParseError。

    调用方负责写 WechatParseRecord（需要 task_id）；本函数只做解析尝试与聚合，
    不直接写库，保持纯解析语义，便于复用与测试。
    """
    errors: List[str] = []
    for client in build_providers():
        try:
            return await client.parse(share_url, db=db)
        except ProviderParseError as e:
            errors.append(str(e))
            logger.warning("provider %s parse failed: %s", client.channel, e)
        finally:
            try:
                await client.close()
            except Exception:
                pass
    raise ProviderParseError(" | ".join(errors) or "无可用解析服务")
