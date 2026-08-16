"""拉流下载服务（立项设计 §2 第③层：finder.video.qq.com 拉 MP4）。

功能：
- 从解析结果 play_url 拉取视频字节流到本地临时文件
- 支持直链 MP4 流式下载
- 对 m3u8 分片（HLS/DASH）做基础拼接（评审 R4：TTL 短、需拼接/续传）
- P0 单链接完整下载；断点续传在 P1 增强

合规：仅对「已授权素材」（wechat_source_auths 绑定）执行拉流，未授权由上层拦截。
"""

import asyncio
import logging
import os
import re
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_HLS_MASTER_RE = re.compile(r'"(https?://[^"]+\.m3u8[^"]*)"')
_HLS_SEGMENT_RE = re.compile(r"(https?://\S+\.ts(?:\?[^\s\"]*)?)")


class DownloadError(Exception):
    """拉流下载失败。"""


class WechatDownloader:
    """finder 拉流下载器。"""

    def __init__(self) -> None:
        self.timeout = settings.WECHAT_DL_DOWNLOAD_TIMEOUT
        self.finder_base = settings.WECHAT_DL_FINDER_BASE

    async def download_to_file(self, play_url: str, local_path: str) -> int:
        """下载 play_url 到 local_path，返回字节数。

        若 play_url 是 m3u8 索引则解析分片并顺序拼接；否则按直链流式下载。
        """
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        if ".m3u8" in play_url:
            return await self._download_hls(play_url, local_path)
        return await self._download_direct(play_url, local_path)

    async def _download_direct(self, url: str, local_path: str) -> int:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise DownloadError(f"direct download http {resp.status_code}")
                    total = 0
                    with open(local_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
                            total += len(chunk)
                    return total
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(f"direct download failed: {e}") from e

    async def _download_hls(self, master_url: str, local_path: str) -> int:
        """HLS 分片下载：拉 m3u8 索引 → 依次下载 .ts 分片并拼接。"""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            try:
                resp = await client.get(master_url)
                if resp.status_code != 200:
                    raise DownloadError(f"hls index http {resp.status_code}")
                index = resp.text
            except DownloadError:
                raise
            except Exception as e:
                raise DownloadError(f"hls index fetch failed: {e}") from e

            # 解析分片 URL（优先绝对地址，其次相对索引目录）
            segments = _HLS_SEGMENT_RE.findall(index)
            if not segments:
                raise DownloadError("hls index contains no segments")
            base_dir = master_url.rsplit("/", 1)[0] if "/" in master_url else ""
            total = 0
            with open(local_path, "wb") as f:
                for seg in segments:
                    seg_url = seg if seg.startswith("http") else f"{base_dir}/{seg.lstrip('/')}"
                    try:
                        sresp = await client.get(seg_url)
                        if sresp.status_code != 200:
                            raise DownloadError(f"segment http {sresp.status_code}: {seg_url}")
                        f.write(sresp.content)
                        total += len(sresp.content)
                    except DownloadError:
                        raise
                    except Exception as e:
                        raise DownloadError(f"segment download failed: {e}") from e
            return total


_downloader: Optional[WechatDownloader] = None


def get_downloader() -> WechatDownloader:
    global _downloader
    if _downloader is None:
        _downloader = WechatDownloader()
    return _downloader
