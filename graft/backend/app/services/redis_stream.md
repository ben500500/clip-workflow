# backend/app/services/redis_stream.py

- _get_stream · function · L48-L58 — def _get_stream(priority: str = "normal") -> str
- _parse_str_list · function · L61-L73 — def _parse_str_list(raw: str) -> list
- get_redis · function · L82-L94 — async def get_redis() -> aioredis.Redis
- reset_redis_client · function · L97-L100 — def reset_redis_client() -> None
- publish_slice_task · function · L103-L140 — async def publish_slice_task(task_data: dict, priority: str = "normal") -> Optional[str]
- store_task_callback_token · function · L143-L149 — async def store_task_callback_token(task_id: str, token: str, ttl_seconds: int = 86400) -> None
- get_task_callback_token · function · L152-L159 — async def get_task_callback_token(task_id: str) -> Optional[str]
- mark_task_cancelled · function · L162-L175 — async def mark_task_cancelled(task_id: str) -> None
- get_task_redis_status · function · L178-L201 — async def get_task_redis_status(task_id: str) -> Optional[dict]
- set_node_enabled · function · L204-L218 — async def set_node_enabled(node_id: str, enabled: bool) -> None
- is_node_enabled · function · L221-L230 — async def is_node_enabled(node_id: str) -> bool
- set_node_cpu_percent · function · L233-L248 — async def set_node_cpu_percent(node_id: str, percent: int) -> None
- get_node_cpu_percent · function · L251-L263 — async def get_node_cpu_percent(node_id: str, default: int = 50) -> int
- delete_worker_node · function · L266-L307 — async def delete_worker_node(node_id: str) -> bool
- get_worker_nodes_from_redis · function · L310-L436 — async def get_worker_nodes_from_redis(offline_after_seconds: int = 60) -> list[dict]
- set_node_update_command · function · L439-L468 — async def set_node_update_command(node_id: str, target_version: str) -> bool
- get_node_update_command · function · L471-L480 — async def get_node_update_command(node_id: str) -> Optional[dict]
- clear_node_update_command · function · L483-L489 — async def clear_node_update_command(node_id: str) -> None
