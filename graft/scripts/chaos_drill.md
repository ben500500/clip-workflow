# scripts/chaos_drill.py

- _redis_get · function · L54-L56 — async def _redis_get(redis_url: str = "redis://127.0.0.1:6379")
- _get_route_states · function · L59-L70 — async def _get_route_states(r)
- _get_profiles · function · L73-L78 — async def _get_profiles(r)
- _run_cmd · function · L83-L88 — def _run_cmd(cmd: list, timeout: int = 30) -> tuple
- inject_chromium_crash · function · L91-L102 — def inject_chromium_crash(account_id: str) -> tuple
- inject_redis_restart · function · L105-L108 — def inject_redis_restart(container: str = "redis") -> tuple
- inject_worker_restart · function · L111-L116 — def inject_worker_restart(worker: str) -> tuple
- _wait_ready · function · L121-L138 — async def _wait_ready(r, expect_ready: bool, window: int) -> bool
- drill_chromium · function · L141-L160 — async def drill_chromium(account_id: str, observe: int, redis_url: str) -> tuple
- drill_redis · function · L163-L197 — async def drill_redis(observe: int, redis_url: str) -> tuple
- drill_worker · function · L200-L210 — async def drill_worker(worker: str, observe: int, redis_url: str) -> tuple
- main · function · L215-L264 — async def main() -> int
