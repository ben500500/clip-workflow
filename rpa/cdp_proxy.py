#!/usr/bin/env python3
"""CDP 反向代理：0.0.0.0:<listen> -> 127.0.0.1:<target>

背景：
- Chromium 127+ 强制远程调试只监听 127.0.0.1（忽略 --remote-debugging-address）
- DevTools HTTP 服务有 DNS-rebinding 防护：Host 头非 localhost/127.0.0.1 时返回 500
- /json/version 等响应里的 webSocketDebuggerUrl 会按请求 Host 头生成（如 ws://localhost/devtools/...）

本代理：
- 请求方向：把首个 HTTP 请求的 Host 头改写为 localhost（绕过 Host 校验）
- 响应方向：把 JSON body 里的 localhost 替换回客户端原始 Host，
  使 playwright 拿到的 ws URL 能通过本代理回连；WebSocket 升级后双向透传。

多运营者（R5/R19）：
- 每个 PublishProfile 对应一个独立 cdp_proxy 实例（独立监听端口），
  由环境变量 CDP_PROFILES（JSON 数组 [{listen_port, target_port, account_id}]）驱动。
- 多实例模式下启用鉴权中间件：校验请求头 `Authorization: Bearer <token>`，
  token 由 app 层签发并存入 Redis（pub:cdp_token:<token>，单次使用，TTL 60s，R19）。
  校验通过即消费（删除），防重放；无/过期/scope 不符一律 401。
- 未设置 CDP_PROFILES 时退化为一期单实例（9222->9223，无鉴权，保持旧链路零侵入）。
"""

import asyncio
import json
import logging
import os
import re

logger = logging.getLogger("cdp_proxy")
logging.basicConfig(level=logging.INFO)

LISTEN_HOST = os.getenv("CDP_PROXY_BIND", "127.0.0.1")  # 默认仅绑 loopback，避免公网零凭据暴露
BUF = 65536
LOCALHOST_RE = re.compile(rb"localhost(?=[:/]|$)")
MAX_HEAD = 64 * 1024

# Redis 用于 token 校验（R19）。rpa_worker 容器内有 REDIS_URL env。
REDIS_URL = os.getenv("REDIS_URL", "")
TOKEN_PREFIX = "pub:cdp_token:"


async def _verify_token(token: str, account_id: str) -> bool:
    """校验 cdp_proxy token：存在、未过期、account 匹配；校验即消费（单次，防重放）。"""
    if not REDIS_URL or not token:
        return False
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            key = f"{TOKEN_PREFIX}{token}"
            raw = await r.get(key)
            if not raw:
                return False
            data = json.loads(raw)
            import time
            if int(data.get("exp") or 0) < int(time.time()):
                await r.delete(key)
                return False
            if str(data.get("account_id")) != str(account_id):
                return False
            await r.delete(key)  # 单次消费
            return True
        finally:
            await r.close()
    except Exception as e:
        logger.warning(f"token verify failed: {e}")
        return False


async def _pipe(src_reader, dst_writer):
    """把一端数据透传到另一端，直到 EOF/异常。"""
    try:
        while True:
            data = await src_reader.read(BUF)
            if not data:
                break
            dst_writer.write(data)
            await dst_writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            dst_writer.close()
        except Exception:
            pass


async def _read_head(reader) -> bytes:
    """精确读到 \\r\\n\\r\\n 为止（不多读 body）。"""
    try:
        return await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = await asyncio.wait_for(reader.read(1024), 10)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_HEAD:
                break
        return data


def _rewrite_request_host(header: bytes) -> bytes:
    """改写请求 Host 头为 localhost（绕过 chromium Host 校验）。"""
    try:
        lines = []
        for line in header.decode("latin1").split("\r\n"):
            if line.lower().startswith("host:"):
                line = "Host: localhost"
            lines.append(line)
        return "\r\n".join(lines).encode("latin1")
    except Exception:
        return header


def _extract_bearer(header: bytes) -> str:
    """从请求头提取 Authorization: Bearer <token>。"""
    try:
        for line in header.decode("latin1").split("\r\n"):
            low = line.lower()
            if low.startswith("authorization:"):
                parts = line.split(":", 1)[1].strip().split()
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    return parts[1]
    except Exception:
        pass
    return ""


def _rewrite_response_body(body: bytes, orig_host: bytes) -> bytes:
    """把响应 body 中的 localhost 替换回原始 Host（ws URL 回连用）。"""
    if not orig_host:
        return body
    return LOCALHOST_RE.sub(orig_host, body)


def _http_401(body: bytes = b"{\"error\":\"unauthorized\"}") -> bytes:
    return (
        b"HTTP/1.1 401 Unauthorized\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )


async def _handle(target_port: int, require_auth: bool, account_id: str,
                  client_reader, client_writer):
    try:
        # 读取首个请求头
        req_head = await _read_head(client_reader)
        if not req_head:
            client_writer.close()
            return

        # 多实例模式下鉴权（R19）：校验 Authorization: Bearer <token>
        # 例外：/json/version 为只读健康探活端点（watcher 秒级探活用，R12），不泄露控制能力，
        # 放行；其余（含 WebSocket 控制、/json/new 等）一律要求有效 token。
        if require_auth:
            is_health = req_head.split(b"\r\n", 1)[0].split(b" ", 2)[:1] == [b"GET"] and b"/json/version" in req_head
            if not is_health:
                token = _extract_bearer(req_head)
                if not await _verify_token(token, account_id):
                    client_writer.write(_http_401())
                    await client_writer.drain()
                    client_writer.close()
                    logger.info(f"[cdp_proxy:{target_port}] 401 token rejected for account={account_id}")
                    return

        server_reader, server_writer = await asyncio.open_connection("127.0.0.1", target_port)
    except Exception:
        client_writer.close()
        return

    try:
        orig_host = None
        for line in req_head.decode("latin1").split("\r\n"):
            if line.lower().startswith("host:"):
                orig_host = line.split(":", 1)[1].strip().encode("latin1")
                break
        server_writer.write(_rewrite_request_host(req_head))
        await server_writer.drain()

        resp_head = await _read_head(server_reader)
        if not resp_head:
            client_writer.close()
            server_writer.close()
            return
        status_line = resp_head.split(b"\r\n", 1)[0]
        is_upgrade = b"101" in status_line.split(b" ", 2)[:2]
        content_length = 0
        for line in resp_head.split(b"\r\n"):
            low = line.lower()
            if low.startswith(b"content-length:"):
                try:
                    content_length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    content_length = 0

        if is_upgrade:
            client_writer.write(resp_head)
            await client_writer.drain()
            await asyncio.gather(
                _pipe(client_reader, server_writer),
                _pipe(server_reader, client_writer),
                return_exceptions=True,
            )
        else:
            body = b""
            while len(body) < content_length:
                chunk = await asyncio.wait_for(server_reader.read(BUF), 10)
                if not chunk:
                    break
                body += chunk
            rewritten = _rewrite_response_body(body, orig_host)
            if len(rewritten) != len(body):
                resp_head = re.sub(
                    rb"(?i)\r\nContent-Length:\s*\d+",
                    b"\r\nContent-Length: " + str(len(rewritten)).encode(),
                    resp_head,
                )
            client_writer.write(resp_head)
            client_writer.write(rewritten)
            await client_writer.drain()
            if len(body) >= content_length:
                await asyncio.gather(
                    _pipe(client_reader, server_writer),
                    _pipe(server_reader, client_writer),
                    return_exceptions=True,
                )
    except Exception:
        pass
    finally:
        try:
            client_writer.close()
            server_writer.close()
        except Exception:
            pass


async def main():
    # 多运营者模式：CDP_PROFILES = [{listen_port, target_port, account_id}]
    # 优先读 /app/profiles.json（bootstrap.py 落盘），其次读环境变量 CDP_PROFILES
    profiles = []
    raw = os.getenv("CDP_PROFILES", "")
    if os.path.exists("/app/profiles.json"):
        try:
            with open("/app/profiles.json") as f:
                data = json.load(f)
            profiles = data.get("cdp_profiles") or []
        except Exception:
            profiles = []
    if not profiles and raw:
        try:
            profiles = json.loads(raw)
        except Exception:
            profiles = []

    if profiles:
        servers = []
        for p in profiles:
            listen_port = int(p.get("listen_port", 9222))
            target_port = int(p.get("target_port", 9223))
            account_id = str(p.get("account_id", ""))
            server = await asyncio.start_server(
                lambda cr, cw, t=target_port, a=account_id: _handle(t, True, a, cr, cw),
                LISTEN_HOST, listen_port,
            )
            servers.append(server)
            print(f"[cdp_proxy] listening {LISTEN_HOST}:{listen_port} -> 127.0.0.1:{target_port} (auth on, account={account_id})", flush=True)
        await asyncio.gather(*(s.serve_forever() for s in servers))
        return

    # 一期单实例（无鉴权，保持旧链路）
    listen_port = int(os.getenv("CDP_LISTEN_PORT", "9222"))
    target_port = int(os.getenv("CDP_TARGET_PORT", "9223"))
    server = await asyncio.start_server(
        lambda cr, cw: _handle(target_port, False, "", cr, cw),
        LISTEN_HOST, listen_port,
    )
    print(f"[cdp_proxy] listening {LISTEN_HOST}:{listen_port} -> 127.0.0.1:{target_port} (single, no auth)", flush=True)
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
