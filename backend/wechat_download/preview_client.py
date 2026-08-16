"""预览层兜底客户端（立项决策②：预览层作为元宝失效时的降级）。

端点：`channels.weixin.qq.com/finder-preview/...` 预览页
作用：校验 / 兜底拿 `finder_id` 与播放密钥，最终 `finder.video.qq.com` 拉流。

该层需要**视频号登录态 cookie**，复用主系统「多运营者登录态」（RPA/CDP）：
- 从启用账号（platform=wechat_channel）取一个已登录的 profile
- 通过 multi_operator 路由拿到其 CDP 连接（CHROME_DEBUG_HOST:port）
- Playwright CDP 连接已登录 Chromium 访问预览页，抓取播放地址

若多运营者未启用 / 无可用已登录账号（多运营者 flag=false 或路由为空），
则 preview 兜底不可用，返回明确提示（由上层决定是否降级失败）。

注意：真实预览页 JS 渲染 & 接口字段会随前端演进，这里提供稳定封装与
足够注释，字段名需在运行时按实际页面微调（评审 R1）。
"""

import logging
import re
from typing import Optional

from app.config import settings

from wechat_download.yuanbao_client import ParseResult

logger = logging.getLogger(__name__)

# finder_id 常见提取正则（预览页内嵌数据）
_FINDER_ID_RE = re.compile(r'"finder_id"\s*:\s*"?([0-9A-Za-z_-]+)"?')
# 播放地址常见提取正则（预览页 video 播放配置）
_PLAY_RE = re.compile(r'"(https?://finder\.video\.qq\.com[^"]+)"')


class PreviewClient:
    """预览层兜底：复用已登录视频号账号（CDP）解析预览页拿播放地址。"""

    def __init__(self) -> None:
        self.preview_base = settings.WECHAT_DL_PREVIEW_BASE
        self.finder_base = settings.WECHAT_DL_FINDER_BASE
        self._playwright = None

    async def _connect(self, cdp_url: str, token: Optional[str] = None):
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        headers = {"Authorization": f"Bearer {token}"} if token else None
        browser = await self._playwright.chromium.connect_over_cdp(
            cdp_url, headers=headers
        )
        return browser

    async def _pick_account_cdp(self, db) -> Optional[dict]:
        """从启用账号中挑一个已登录（multi_operator 路由 ready）的视频号账号。"""
        from sqlalchemy import select

        from app.services import multi_operator
        if not await multi_operator.multi_operator_enabled():
            return None
        from app.models.models import VideoAccount
        result = await db.execute(
            select(VideoAccount).where(
                VideoAccount.platform == "wechat_channel",
                VideoAccount.enabled.is_(True),
            )
        )
        accounts = result.scalars().all()
        for acc in accounts:
            route = await multi_operator.get_route(str(acc.id))
            if not route:
                continue
            port = route.get("port") or ""
            host = settings.CHROME_DEBUG_HOST
            cdp_url = f"http://{host}:{port}"
            return {"cdp_url": cdp_url, "account_id": str(acc.id)}
        return None

    async def parse(self, share_url: str, db=None) -> ParseResult:
        """通过预览页兜底解析分享链接，返回 ParseResult。

        需要可用已登录账号；否则抛 PreviewUnavailableError。
        """
        cdp = await self._pick_account_cdp(db) if db is not None else None
        if not cdp:
            from wechat_download.preview_client import PreviewUnavailableError
            raise PreviewUnavailableError(
                "预览层兜底不可用：未启用多运营者或没有已登录的视频号账号"
            )
        try:
            browser = await self._connect(cdp["cdp_url"])
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(share_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)
                content = await page.content()
                finder_id = _FINDER_ID_RE.search(content)
                play = _PLAY_RE.search(content)
                if not play:
                    raise PreviewUnavailableError("预览页未提取到 finder 播放地址")
                return ParseResult(
                    success=True,
                    channel="preview",
                    play_url=play.group(1),
                    title=finder_id.group(1) if finder_id else None,
                    meta={"finder_id": finder_id.group(1) if finder_id else None},
                )
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
        except PreviewUnavailableError:
            raise
        except Exception as e:
            from wechat_download.preview_client import PreviewUnavailableError
            raise PreviewUnavailableError(f"preview parse failed: {e}") from e

    async def close(self) -> None:
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


class PreviewUnavailableError(Exception):
    """预览层兜底不可用或解析失败。"""


_preview_client: Optional[PreviewClient] = None


def get_preview_client() -> PreviewClient:
    global _preview_client
    if _preview_client is None:
        _preview_client = PreviewClient()
    return _preview_client
