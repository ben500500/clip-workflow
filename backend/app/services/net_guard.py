"""SSRF 防护：用户可控 URL 在服务端发请求前必须过公网校验。

背景（11-05 安全审计）：`looks_like_direct_url` 只看路径后缀，`http://169.254.169.254/....mp4`
这类内网/元数据地址会被 ffprobe 探时长、被拉流下载器直接抓回，形成 SSRF 探测/外带面。
所有「拿用户给的 URL 去请求」的入口都必须先过 `assert_public_http_url`。

口径：
- scheme 只放行 http/https；
- host 解析出的**每一个** IP 都必须 `is_global`（排除私网/环回/链路本地/保留段/组播）；
- 重定向不算安全边界：调用方必须对每一次跳转后的新地址复检（见 downloader 的手写跳转环）；
- 已知残留：DNS rebinding（校验后到真正请求前换解析）未防，内网工具可接受，
  服务器本身也不持有可被 rebinding 直接打到的强凭据。
"""

import ipaddress
import socket
from urllib.parse import urlsplit

import asyncio

_ALLOWED_SCHEMES = ("http", "https")


class UnsafeURLError(ValueError):
    """URL 未通过公网校验（内网/环回/非 http(s) 等）。"""


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> None:
    if not ip.is_global:
        raise UnsafeURLError(f"非公网地址被拒绝：{host} -> {ip}")


def _check_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"域名解析失败：{host}: {e}") from e
    seen = set()
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip in seen:
            continue
        seen.add(ip)
        _check_ip(ip, host)


def assert_public_http_url(url: str) -> str:
    """同步版校验：返回原 url；不合法抛 UnsafeURLError。"""
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"只允许 http/https 直链：{url[:120]}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError(f"URL 缺少主机名：{url[:120]}")
    # 字面 IP 直接判；域名走解析（对每条 A/AAAA 记录都判）
    try:
        ip = ipaddress.ip_address(host)
        _check_ip(ip, host)
    except ValueError:
        _check_host(host)
    return url


async def assert_public_http_url_async(url: str) -> str:
    """异步版：getaddrinfo 是阻塞调用，丢线程池跑。"""
    parts = urlsplit((url or "").strip())
    host = parts.hostname
    if parts.scheme.lower() in _ALLOWED_SCHEMES and host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            await asyncio.to_thread(_check_host, host)
            return url
    return assert_public_http_url(url)
