"""SSRF 防护（net_guard）回归：用户可控 URL 在服务端发请求前必须过公网校验。

背景：11-05 安全审计实锤——`looks_like_direct_url` 只看路径后缀，material 角色贴一条
`http://169.254.169.254/....mp4` 就能让服务端 ffprobe/下载器去探内网。这里钉住校验口径。
"""

import ipaddress
import socket
from unittest.mock import patch

import pytest

from app.services.net_guard import UnsafeURLError, assert_public_http_url


def _fake_addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


class TestLiteralIPs:
    def test_rejects_metadata_link_local(self):
        with pytest.raises(UnsafeURLError):
            assert_public_http_url("http://169.254.169.254/latest/meta-data/x.mp4")

    def test_rejects_private(self):
        for host in ("10.0.0.5", "192.168.1.163", "172.16.0.9", "127.0.0.1", "0.0.0.0"):
            with pytest.raises(UnsafeURLError):
                assert_public_http_url(f"http://{host}/a.mp4")

    def test_accepts_public_literal(self):
        assert assert_public_http_url("https://1.1.1.1/a.mp4") == "https://1.1.1.1/a.mp4"


class TestSchemes:
    def test_rejects_file_and_other_schemes(self):
        for u in ("file:///etc/passwd", "gopher://1.1.1.1/a", "ftp://1.1.1.1/a.mp4"):
            with pytest.raises(UnsafeURLError):
                assert_public_http_url(u)

    def test_rejects_missing_host(self):
        with pytest.raises(UnsafeURLError):
            assert_public_http_url("http:///a.mp4")


class TestDomains:
    def test_domain_resolving_to_private_is_rejected(self):
        with patch.object(socket, "getaddrinfo", return_value=_fake_addrinfo("192.168.1.1")):
            with pytest.raises(UnsafeURLError):
                assert_public_http_url("http://evil.example/a.mp4")

    def test_domain_resolving_public_ok(self):
        with patch.object(socket, "getaddrinfo", return_value=_fake_addrinfo("93.184.216.34")):
            assert assert_public_http_url("http://ok.example/a.mp4") == "http://ok.example/a.mp4"

    def test_unresolvable_domain_rejected(self):
        with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror(8, "nodename")):
            with pytest.raises(UnsafeURLError):
                assert_public_http_url("http://nope.example/a.mp4")

    def test_multi_record_all_global_required(self):
        infos = _fake_addrinfo("93.184.216.34") + _fake_addrinfo("10.0.0.1")
        with patch.object(socket, "getaddrinfo", return_value=infos):
            with pytest.raises(UnsafeURLError):
                assert_public_http_url("http://mixed.example/a.mp4")
