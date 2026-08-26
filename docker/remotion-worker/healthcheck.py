#!/usr/bin/env python3
"""Remotion worker 健康检查 HTTP 端点。

在 docker/remotion-worker 容器内作为 HEALTHCHECK 命令运行：
GET /health 返回 200 {"status":"ok"} 视为健康；同时用 redis ping 校验
broker 连通性（与现有 celery worker 的 healthcheck 思路一致）。

仅依赖标准库 http.server，无需额外依赖。
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# redis ping 校验 broker 连通（可选，redis 客户端由 requirements 提供）
def _redis_ok() -> bool:
    try:
        import redis
        from urllib.parse import urlparse

        url = os.getenv("CELERY_BROKER_URL", "")
        if not url:
            return True  # 未配置 broker 地址则跳过连通性校验
        parsed = urlparse(url.replace("redis://", "http://"))
        r = redis.Redis(
            host=parsed.hostname or "redis",
            port=parsed.port or 6379,
            password=parsed.password,
            db=int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        ok = r.ping()
        r.close()
        return ok
    except Exception:
        return False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # 静默访问日志，避免刷屏
        pass


def _serve_http():
    try:
        server = HTTPServer(("0.0.0.0", 8081), HealthHandler)
        server.serve_forever()
    except Exception as e:
        sys.stderr.write(f"healthcheck http server failed: {e}\n")


def main():
    # 后台起 HTTP 服务，前台做 redis ping 校验（HEALTHCHECK 主命令）
    t = threading.Thread(target=_serve_http, daemon=True)
    t.start()
    if not _redis_ok():
        print("redis ping failed", file=sys.stderr)
        sys.exit(1)
    print("remotion worker health ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
