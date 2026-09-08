# backend/app/services/distributed_lock.py

- _get_client · function · L46-L51 — def _get_client() -> aioredis.Redis
- acquire_lock · function · L54-L62 — async def acquire_lock(key: str, ttl: int = 1800) -> Optional[str]
- release_lock · function · L65-L72 — async def release_lock(key: str, token: str) -> bool
