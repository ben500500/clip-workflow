# docker/remotion-worker/healthcheck.py

- _redis_ok · function · L17-L38 — def _redis_ok() -> bool
- HealthHandler · class · L41-L55 — class HealthHandler(BaseHTTPRequestHandler)
- do_GET · method · L42-L52 — def do_GET(self)
- log_message · method · L54-L55 — def log_message(self, *args): # 静默访问日志，避免刷屏
- _serve_http · function · L58-L63 — def _serve_http()
- main · function · L66-L74 — def main(): # 后台起 HTTP 服务，前台做 redis ping 校验（HEALTHCHECK 主命令）
