"""lan_source 直链下载器（cdn 静态 MP4 直链流式下载）。

复用 wechat_download 的直链下载模式（HTTP Range 断点续传），仅针对纯静态直链
精简实现；不走 HLS 拼接（cdn 直链均为单文件 MP4）。
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LanSourceDownloadError(Exception):
    """直链下载失败。"""


class LanSourceDownloader:
    """cdn 直链下载器。"""

    def __init__(self) -> None:
        self.timeout = settings.LAN_SOURCE_DOWNLOAD_TIMEOUT

    async def download_to_file(self, url: str, local_path: str) -> int:
        """下载直链 url 到 local_path，返回字节数（支持断点续传）。"""
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        resume_from = 0
        mode = "wb"
        if os.path.exists(local_path):
            resume_from = os.path.getsize(local_path)
            if resume_from > 0:
                mode = "ab"
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers=headers,
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resume_from > 0 and resp.status_code != 206:
                        resume_from = 0
                        mode = "wb"
                    if resp.status_code not in (200, 206):
                        raise LanSourceDownloadError(f"download http {resp.status_code}: {url}")
                    total = resume_from
                    with open(local_path, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
                            total += len(chunk)
                    return total
        except LanSourceDownloadError:
            raise
        except Exception as e:
            raise LanSourceDownloadError(f"download failed {url}: {e}") from e


_downloader: Optional[LanSourceDownloader] = None


def get_downloader() -> LanSourceDownloader:
    global _downloader
    if _downloader is None:
        _downloader = LanSourceDownloader()
    return _downloader


async def probe_file_size(url: str) -> Optional[int]:
    """HEAD 探测直链文件大小（用于导入前展示；失败返回 None）。"""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            resp = await client.head(url)
            if resp.status_code == 200:
                return int(resp.headers.get("Content-Length") or 0) or None
    except Exception:
        return None
    return None


async def run_bounded_downloads(url_path_pairs: list[tuple[str, str]]) -> list[str]:
    """并发受限批量下载（LAN_SOURCE_CONCURRENCY）。返回成功与否列表。

    供 Celery 任务在下载阶段并发拉取多集；每项独立 try，单项失败不影响其他集。
    """
    sem = asyncio.Semaphore(max(1, settings.LAN_SOURCE_CONCURRENCY))
    dl = get_downloader()

    async def _one(pair):
        url, path = pair
        async with sem:
            try:
                await dl.download_to_file(url, path)
                return True
            except Exception:
                logger.warning("lan_source download failed: %s", url, exc_info=True)
                return False

    return await asyncio.gather(*[asyncio.ensure_future(_one(p)) for p in url_path_pairs])
