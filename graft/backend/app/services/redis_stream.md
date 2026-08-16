# backend/app/services/redis_stream.py

- _get_stream · function · L48-L58 — def _get_stream(priority: str = "normal") -> str
- _parse_str_list · function · L61-L73 — def _parse_str_list(raw: str) -> list
- get_redis · function · L76-L81 — async def get_redis() -> aioredis.Redis
- publish_slice_task · function · L84-L125 — async def publish_slice_task(task_data: dict, priority: str = "normal") -> Optional[str]
- store_task_callback_token · function · L128-L138 — async def store_task_callback_token(task_id: str, token: str, ttl_seconds: int = 86400) -> None
- get_task_callback_token · function · L141-L152 — async def get_task_callback_token(task_id: str) -> Optional[str]
- mark_task_cancelled · function · L155-L172 — async def mark_task_cancelled(task_id: str) -> None
- get_task_redis_status · function · L175-L202 — async def get_task_redis_status(task_id: str) -> Optional[dict]
- set_node_enabled · function · L205-L223 — async def set_node_enabled(node_id: str, enabled: bool) -> None
- is_node_enabled · function · L226-L239 — async def is_node_enabled(node_id: str) -> bool
- set_node_cpu_percent · function · L242-L261 — async def set_node_cpu_percent(node_id: str, percent: int) -> None
- get_node_cpu_percent · function · L264-L280 — async def get_node_cpu_percent(node_id: str, default: int = 50) -> int
- delete_worker_node · function · L283-L328 — async def delete_worker_node(node_id: str) -> bool
- get_worker_nodes_from_redis · function · L331-L461 — async def get_worker_nodes_from_redis(offline_after_seconds: int = 60) -> list[dict]
- set_node_update_command · function · L464-L497 — async def set_node_update_command(node_id: str, target_version: str) -> bool
- get_node_update_command · function · L500-L513 — async def get_node_update_command(node_id: str) -> Optional[dict]
- clear_node_update_command · function · L516-L526 — async def clear_node_update_command(node_id: str) -> None
