#!/usr/bin/env python3
"""CDP 反向代理：0.0.0.0:9222 -> 127.0.0.1:9223

背景：
- Chromium 127+ 强制远程调试只监听 127.0.0.1（忽略 --remote-debugging-address）
- DevTools HTTP 服务有 DNS-rebinding 防护：Host 头非 localhost/127.0.0.1 时返回 500
- /json/version 等响应里的 webSocketDebuggerUrl 会按请求 Host 头生成（如 ws://localhost/devtools/...）

本代理：
- 请求方向：把首个 HTTP 请求的 Host 头改写为 localhost（绕过 Host 校验）
- 响应方向：把 JSON body 里的 localhost 替换回客户端原始 Host（如 rpa_worker:9222），
  使 playwright 拿到的 ws URL 能通过本代理回连；WebSocket 升级后双向透传。
"""

import asyncio
import re

LISTEN_HOST, LISTEN_PORT = "0.0.0.0", 9222
TARGET_HOST, TARGET_PORT = "127.0.0.1", 9223
BUF = 65536
LOCALHOST_RE = re.compile(rb"localhost(?=[:/]|$)")
MAX_HEAD = 64 * 1024


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
        # 上限或意外结束：兜底按块读
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


def _rewrite_response_body(body: bytes, orig_host: bytes) -> bytes:
    """把响应 body 中的 localhost 替换回原始 Host（ws URL 回连用）。"""
    if not orig_host:
        return body
    return LOCALHOST_RE.sub(orig_host, body)


async def _handle(client_reader, client_writer):
    try:
        server_reader, server_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except Exception:
        client_writer.close()
        return

    try:
        # 读取请求头（首个请求），提取原始 Host
        req_head = await _read_head(client_reader)
        if not req_head:
            client_writer.close()
            server_writer.close()
            return
        orig_host = None
        for line in req_head.decode("latin1").split("\r\n"):
            if line.lower().startswith("host:"):
                orig_host = line.split(":", 1)[1].strip().encode("latin1")
                break
        server_writer.write(_rewrite_request_host(req_head))
        await server_writer.drain()

        # 读取响应头
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
            # WebSocket 升级：头已发，后续直接双向透传
            client_writer.write(resp_head)
            await client_writer.drain()
            await asyncio.gather(
                _pipe(client_reader, server_writer),
                _pipe(server_reader, client_writer),
                return_exceptions=True,
            )
        else:
            # 普通响应：先读 body 并改写，修正 Content-Length 后连同响应头一次性发出。
            # 注意：改写（localhost -> rpa_worker:9222）会改变 body 长度，
            # 若不更新 Content-Length，keep-alive 客户端会把多余字节当作
            # 下一个 HTTP 响应解析（Playwright Node 客户端 Parse Error）。
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
            # 剩余（如有，如 keep-alive 下一请求）透传
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
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT)
    print(f"[cdp_proxy] listening {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}", flush=True)
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
