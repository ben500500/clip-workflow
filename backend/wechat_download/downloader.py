"""拉流下载服务（立项设计 §2 第③层：finder.video.qq.com 拉 MP4）。

功能：
- 从解析结果 play_url 拉取视频字节流到本地临时文件
- 支持直链 MP4 流式下载
- 对 m3u8 分片（HLS/DASH）做基础拼接（TTL 短、需拼接/续传）
- P0 单链接完整下载；断点续传在 P1 增强
"""

import asyncio
import logging
import os
import re
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.net_guard import UnsafeURLError, assert_public_http_url

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
        P1：支持断点续传——若 local_path 已存在（上次中断残留），直链用
        HTTP Range 从已下载字节处继续；分片用已下载片段数续接。
        """
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        if ".m3u8" in play_url:
            return await self._download_hls(play_url, local_path)
        return await self._download_direct(play_url, local_path)

    async def _download_direct(self, url: str, local_path: str) -> int:
        resume_from = 0
        mode = "wb"
        if os.path.exists(local_path):
            resume_from = os.path.getsize(local_path)
            if resume_from > 0:
                mode = "ab"  # 已有部分内容，断点续传追加
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"
            # SSRF 防护：入口校验 + 手写跳转环逐跳复检（follow_redirects=True 会把
            # 公网 30x 悄悄带进内网，审计实锤的第二条腿）
            await asyncio.to_thread(assert_public_http_url, url)
            total = resume_from
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=False,
                headers=headers,
            ) as client:
                for _hop in range(5):
                    resp = await client.send(client.build_request("GET", url), stream=True)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location", "")
                        await resp.aclose()
                        if not loc:
                            raise DownloadError("redirect without location")
                        url = str(resp.next_request.url) if resp.next_request else loc
                        await asyncio.to_thread(assert_public_http_url, url)
                        continue
                    # 若服务端不支持 Range，忽略已存在内容，全量重下
                    if resume_from > 0 and resp.status_code != 206:
                        resume_from = 0
                        mode = "wb"
                        total = 0
                    if resp.status_code not in (200, 206):
                        await resp.aclose()
                        raise DownloadError(f"direct download http {resp.status_code}")
                    with open(local_path, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
                            total += len(chunk)
                    await resp.aclose()
                    return total
                raise DownloadError("direct download: too many redirects")
        except UnsafeURLError as e:
            raise DownloadError(f"unsafe url blocked: {e}") from e
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(f"direct download failed: {e}") from e

    async def _download_hls(self, master_url: str, local_path: str) -> int:
        """HLS 分片下载：拉 m3u8 索引 → 依次下载 .ts 分片并拼接。"""
        # SSRF 防护：入口与每个分片地址都要过公网校验（分片 host 可能与索引不同）
        await asyncio.to_thread(assert_public_http_url, master_url)
        checked_hosts: set[str] = set()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            try:
                index = None
                hop_url = master_url
                for _hop in range(5):
                    resp = await client.get(hop_url)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        hop_url = str(resp.next_request.url) if resp.next_request else resp.headers.get("location", "")
                        if not hop_url:
                            raise DownloadError("hls redirect without location")
                        await asyncio.to_thread(assert_public_http_url, hop_url)
                        continue
                    if resp.status_code != 200:
                        raise DownloadError(f"hls index http {resp.status_code}")
                    index = resp.text
                    break
                if index is None:
                    raise DownloadError("hls index: too many redirects")
            except UnsafeURLError as e:
                raise DownloadError(f"unsafe url blocked: {e}") from e
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
                    seg_host = urlsplit(seg_url).hostname
                    if seg_host and seg_host not in checked_hosts:
                        await asyncio.to_thread(assert_public_http_url, seg_url)
                        checked_hosts.add(seg_host)
                    try:
                        # 分片跟随跳转也逐跳复检（CDN 常见 302）
                        seg_resp_url = seg_url
                        for _hop in range(5):
                            sresp = await client.send(client.build_request("GET", seg_resp_url))
                            if sresp.status_code in (301, 302, 303, 307, 308):
                                seg_resp_url = str(sresp.next_request.url) if sresp.next_request else sresp.headers.get("location", "")
                                if not seg_resp_url:
                                    raise DownloadError("segment redirect without location")
                                seg_host = urlsplit(seg_resp_url).hostname
                                if seg_host and seg_host not in checked_hosts:
                                    await asyncio.to_thread(assert_public_http_url, seg_resp_url)
                                    checked_hosts.add(seg_host)
                                continue
                            break
                        if sresp.status_code != 200:
                            raise DownloadError(f"segment http {sresp.status_code}: {seg_url}")
                        f.write(sresp.content)
                        total += len(sresp.content)
                    except DownloadError:
                        raise
                    except UnsafeURLError as e:
                        raise DownloadError(f"unsafe url blocked: {e}") from e
                    except Exception as e:
                        raise DownloadError(f"segment download failed: {e}") from e
            return total


_downloader: Optional[WechatDownloader] = None


def get_downloader() -> WechatDownloader:
    global _downloader
    if _downloader is None:
        _downloader = WechatDownloader()
    return _downloader
