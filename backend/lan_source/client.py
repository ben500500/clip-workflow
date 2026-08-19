"""lan_source 局域网源客户端（dupload cdn 直链 + 剧目清单发现）。

对接两条外部服务：
1. `LAN_SOURCE_MANAGE_BASE`（可选，IAA 小程序管理平台）`GET /api/bg/sync/tasks`
   → 剧目清单 [{dramaInfo:{dramaName, dramaId, total, desc}, status}]
2. `LAN_SOURCE_BASE_URL`（dupload cdn 源）`GET /videos/{drama}/cdn`
   → 每集直链 [{url, episode}]；`GET /videos/{drama}/compressed` → 已压缩版列表

cdn 直链为纯静态 MP4（无鉴权/UA 要求），可直接 HTTP 拉流入库。
"""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LanSourceError(Exception):
    """局域网源客户端错误。"""


class CdnEpisode:
    """单集直链信息。"""

    __slots__ = ("episode", "url", "title", "size")

    def __init__(self, episode, url, title=None, size=None):
        self.episode = episode
        self.url = url
        self.title = title
        self.size = size


class ManageDrama:
    """剧目清单项（来自管理平台 /api/bg/sync/tasks）。"""

    __slots__ = ("name", "drama_id", "total", "desc")

    def __init__(self, name, drama_id=None, total=None, desc=None):
        self.name = name
        self.drama_id = drama_id
        self.total = total
        self.desc = desc


def _norm_base(base: str) -> str:
    return (base or "").rstrip("/")


class LanSourceClient:
    """局域网 cdn 源客户端。"""

    def __init__(self) -> None:
        self.base = _norm_base(settings.LAN_SOURCE_BASE_URL)
        self.manage_base = _norm_base(settings.LAN_SOURCE_MANAGE_BASE)
        self.prefix = (settings.LAN_SOURCE_API_PREFIX or "").strip("/")
        self.timeout = settings.LAN_SOURCE_DOWNLOAD_TIMEOUT

    async def _get_json(self, url: str, *, base: Optional[str] = None) -> dict:
        b = base or self.base
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(f"{b}{url}")
                if resp.status_code != 200:
                    raise LanSourceError(f"{url} http {resp.status_code}")
                return resp.json()
        except LanSourceError:
            raise
        except Exception as e:
            raise LanSourceError(f"{url} 请求失败: {e}") from e

    # ── 剧目清单发现（管理平台 /api/bg/sync/tasks）──
    async def discover_dramas(self) -> list[ManageDrama]:
        """从管理平台拉取剧目清单（未配置 MANAGE_BASE 时返回空列表）。"""
        if not self.manage_base:
            return []
        data = await self._get_json("/api/bg/sync/tasks", base=self.manage_base)
        tasks = data.get("tasks") if isinstance(data, dict) else data
        if not isinstance(tasks, list):
            return []
        dramas: list[ManageDrama] = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            info = t.get("dramaInfo") if isinstance(t.get("dramaInfo"), dict) else {}
            name = (info.get("dramaName") or "").strip()
            if not name:
                continue
            dramas.append(
                ManageDrama(
                    name=name,
                    drama_id=info.get("dramaId"),
                    total=info.get("total"),
                    desc=info.get("desc"),
                )
            )
        return dramas

    # ── 剧集直链发现（dupload /videos/{drama}/cdn）──
    def _drama_path(self, drama_name: str) -> str:
        import urllib.parse
        encoded = urllib.parse.quote(drama_name)
        prefix = f"/{self.prefix}" if self.prefix else ""
        return f"{prefix}/videos/{encoded}/cdn"

    async def fetch_episodes(self, drama_name: str) -> list[CdnEpisode]:
        """拉取某剧目全部剧集直链（按 episode 升序）。"""
        url = self._drama_path(drama_name)
        data = await self._get_json(url)
        items = data if isinstance(data, list) else data.get("items") or data.get("videos") or []
        episodes: list[CdnEpisode] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                ep_url = it.get("url") or it.get("play_url")
                if not ep_url:
                    continue
                episodes.append(
                    CdnEpisode(
                        episode=it.get("episode"),
                        url=ep_url,
                        title=it.get("title"),
                        size=it.get("size"),
                    )
                )
        # 按集号排序
        episodes.sort(key=lambda e: (e.episode is None, e.episode or 0))
        return episodes


_client: Optional[LanSourceClient] = None


def get_client() -> LanSourceClient:
    global _client
    if _client is None:
        _client = LanSourceClient()
    return _client
