"""lan_source 局域网源客户端（dupload cdn 直链 + 剧目清单发现）。

对接两条外部服务：
1. `LAN_SOURCE_MANAGE_BASE`（可选，IAA 小程序管理平台）`GET /api/bg/sync/tasks`
   → 剧目清单 [{dramaInfo:{dramaName, dramaId, total, desc}, status}]
2. `LAN_SOURCE_BASE_URL`（dupload cdn 源）`GET /videos/{drama}/cdn`
   → 每集直链 [{url, episode}]；`GET /videos/{drama}/compressed` → 已压缩版列表

cdn 直链为纯静态 MP4（无鉴权/UA 要求），可直接 HTTP 拉流入库。

## 剧名模糊匹配（剧名归一化兜底）

管理平台 `GET /api/ext/drama/{name}/videos` 为**精确匹配**：本地剧目库剧名与
平台剧名存在细微差异（全/半角标点、空格、大小写）时返回 400
`{"error": "drama not found"}`。为此当精确查 400 时自动做归一化模糊匹配：

1. 拉取平台剧目清单（`GET /api/bg/sync/tasks`，未配置 manage_base 时也尝试
   dupload `GET /api/dupload/tasks` 的 `{data:[{dramaName}]}` 结构）；
2. 对目标剧名与清单剧名做**归一化**（去标点、全角转半角、去空格、转小写）后比对；
3. 命中后用平台正确剧名重新调 `GET /api/ext/drama/{name}/videos` 取剧集。
"""

import logging
import re
import unicodedata
from typing import Optional

import httpx

from lan_source.config import LanSourceConfig, load_lan_source_config

logger = logging.getLogger(__name__)

# 归一化时去除的标点（含全/半角），与用户约定一致：
# ，,。.！!？?、()（）「」『』『』等
_PUNCT_RE = re.compile(
    r"[，,。.！!？?、()（）「」『』〈〉《》【】\[\]\"'\"'‘’“”…·:：;；\-—_/\\|*&^%$#@~`+=<>]"
)
# 全角空白/空格（含 \u3000 全角空格、\u2003 em 空格等）
_SPACE_RE = re.compile(r"[\s\u3000\u2000-\u200b]+")


def normalize_drama_name(name: str) -> str:
    """剧名归一化：全角转半角 → 去标点 → 去空格 → 转小写。

    用于「精确匹配失败」时与平台剧目清单做模糊比对（比较时不区分大小写）。
    """
    if not name:
        return ""
    # 1. 全角转半角（NFKC 统一，含全角字母/数字/标点）
    s = unicodedata.normalize("NFKC", name)
    # 2. 去除标点（全/半角逗号、顿号、括号、引号、书名号等）
    s = _PUNCT_RE.sub("", s)
    # 3. 去空白（含全角空格）
    s = _SPACE_RE.sub("", s)
    # 4. 转小写（比较时不区分大小写）
    return s.lower()


class LanSourceError(Exception):
    """局域网源客户端错误。"""


class LanSourceNotFound(LanSourceError):
    """剧集/剧目不存在（管理平台返回 400 + drama not found）。

    是 LanSourceError 的子类：service 层按 LanSourceError 统一捕获时语义不变，
    需要区分「剧不存在」的调用方（api preview 返回 404、导入任务友好报错）可单独捕获。
    """


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


class LanSourceClient:
    """局域网 cdn 源客户端。"""

    def __init__(self, config: Optional[LanSourceConfig] = None) -> None:
        # 未显式注入时回退到 settings(.env) 默认值，保证向后兼容
        cfg = config or load_lan_source_config()
        self.base = cfg.base_url.rstrip("/")
        self.manage_base = cfg.manage_base.rstrip("/")
        self.prefix = (cfg.api_prefix or "").strip("/")
        self.timeout = cfg.download_timeout
        self.config = cfg

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
                    # 400 + drama not found：剧不存在（精确匹配失败），抛专门异常供模糊匹配兜底
                    if resp.status_code == 400 and "drama not found" in (resp.text or "").lower():
                        raise LanSourceNotFound(f"{url} http {resp.status_code}: drama not found")
                    raise LanSourceError(f"{url} http {resp.status_code}")
                return resp.json()
        except LanSourceError:
            raise
        except Exception as e:
            raise LanSourceError(f"{url} 请求失败: {e}") from e

    # ── 剧目清单发现（管理平台 /api/bg/sync/tasks，兜底 dupload /api/dupload/tasks）──
    async def discover_dramas(self) -> list[ManageDrama]:
        """从管理平台拉取剧目清单（未配置 MANAGE_BASE 时也尝试 dupload 源）。

        优先 `GET {manage_base}/api/bg/sync/tasks`（dramaInfo.dramaName 结构）；
        未配置 manage_base 或清单为空时，回退 `GET {base}/api/dupload/tasks`
        （兼容 `{data:[{dramaName,...}]}` 结构）。均失败/为空返回 []。
        """
        tasks = []
        if self.manage_base:
            try:
                tasks = await self._discover_from_manage()
            except Exception as e:
                logger.warning("从管理平台拉取剧目清单失败，尝试 dupload 源: %s", e)
        if not tasks:
            tasks = await self._discover_from_dupload()
        return tasks

    async def _discover_from_manage(self) -> list[ManageDrama]:
        """从管理平台 `GET /api/bg/sync/tasks` 解析剧目清单。"""
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

    async def _discover_from_dupload(self) -> list[ManageDrama]:
        """从 dupload 源 `GET /api/dupload/tasks` 解析剧目清单（兼容 `{data:[{dramaName}]}`）。"""
        if not self.base:
            return []
        try:
            data = await self._get_json("/api/dupload/tasks", base=self.base)
        except Exception as e:
            logger.debug("dupload 源剧目清单拉取失败（忽略）: %s", e)
            return []
        # 兼容 {data:[...]} / {items:[...]} / {tasks:[...]} / 裸数组
        items = data
        if isinstance(data, dict):
            for key in ("data", "items", "tasks", "list"):
                val = data.get(key)
                if isinstance(val, list):
                    items = val
                    break
            else:
                items = []
        if not isinstance(items, list):
            return []
        dramas: list[ManageDrama] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = (it.get("dramaName") or it.get("drama_name") or it.get("name") or "").strip()
            if not name:
                continue
            dramas.append(
                ManageDrama(
                    name=name,
                    drama_id=it.get("dramaId") or it.get("drama_id") or it.get("id"),
                    total=it.get("total"),
                    desc=it.get("desc") or it.get("description"),
                )
            )
        return dramas

    # ── 剧集直链发现 ──
    # 优先走管理平台 /api/ext/drama/{name}/videos（21:8800）；未配置 MANAGE_BASE
    # 时回退到 dupload cdn 源 /videos/{drama}/cdn。返回结构兼容（episode+url）。
    def _drama_path(self, drama_name: str) -> str:
        import urllib.parse
        encoded = urllib.parse.quote(drama_name)
        prefix = f"/{self.prefix}" if self.prefix else ""
        return f"{prefix}/videos/{encoded}/cdn"

    async def _fetch_ext_episodes(self, drama_name: str) -> list[CdnEpisode]:
        """请求管理平台 `GET /api/ext/drama/{name}/videos` 并解析剧集直链。

        Raises:
            LanSourceNotFound: 剧不存在（精确匹配失败，400 + drama not found）
            LanSourceError: 其它请求/解析错误
        """
        import urllib.parse
        encoded = urllib.parse.quote(drama_name)
        url = f"/api/ext/drama/{encoded}/videos"
        data = await self._get_json(url, base=self.manage_base)
        return self._parse_episodes(data)

    @staticmethod
    def _parse_episodes(data) -> list[CdnEpisode]:
        """把 ext/drama videos 接口响应解析为 CdnEpisode 列表（按集号升序）。"""
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

    async def _find_matched_drama(self, drama_name: str) -> Optional[str]:
        """剧名归一化模糊匹配：在平台剧目清单里找与目标剧名归一化后相等的剧名。

        返回平台侧正确剧名（原始形式）；未命中返回 None。
        """
        target = normalize_drama_name(drama_name)
        if not target:
            return None
        for d in await self.discover_dramas():
            if normalize_drama_name(d.name) == target:
                return d.name
        return None

    async def fetch_episodes(self, drama_name: str) -> list[CdnEpisode]:
        """拉取某剧目全部剧集直链（按 episode 升序）。

        优先请求管理平台 `GET /api/ext/drama/{name}/videos`（21:8800）；
        未配置 MANAGE_BASE 时回退到 dupload cdn 源 `GET /videos/{drama}/cdn`。

        管理平台精确匹配失败（400 + drama not found，剧名存在全/半角标点、空格
        等细微差异）时，自动做**剧名归一化模糊匹配兜底**：拉取平台剧目清单，
        归一化比对后命中平台正确剧名，用正确剧名重新取剧集。
        """
        if not self.manage_base:
            url = self._drama_path(drama_name)
            data = await self._get_json(url, base=self.base)
            return self._parse_episodes(data)

        try:
            return await self._fetch_ext_episodes(drama_name)
        except LanSourceNotFound:
            # 精确匹配失败 → 归一化模糊匹配兜底
            matched = await self._find_matched_drama(drama_name)
            if matched and matched != drama_name:
                logger.info(
                    "《%s》精确匹配失败，归一化模糊命中平台剧名《%s》，用正确剧名重查",
                    drama_name, matched,
                )
                try:
                    return await self._fetch_ext_episodes(matched)
                except LanSourceNotFound as e:
                    # 平台清单里的剧名仍查不到（清单与剧集库不同步），如实上报
                    raise LanSourceError(str(e)) from e
            # 未命中：剧确实不存在（清单里也没有该剧），保持 404 语义
            raise


_client: Optional[LanSourceClient] = None


def get_client(config: Optional[LanSourceConfig] = None) -> LanSourceClient:
    """获取客户端；显式传入 config 时重建（用于 system_config 热更）。"""
    global _client
    if _client is None or config is not None:
        _client = LanSourceClient(config=config)
    return _client
