# backend/app/services/batch_slice_service.py

- _get_batch · function · L55-L59 — async def _get_batch(batch_id: str)
- _load_items · function · L62-L69 — async def _load_items(batch_id: str) -> list[BatchSliceItem]
- _update_item · function · L72-L77 — async def _update_item(item_id, **fields)
- _update_batch · function · L80-L85 — async def _update_batch(batch_id, **fields)
- _set_phase · function · L88-L99 — async def _set_phase(item, phase: str, status: str = None, progress: float = None)
- _find_or_create_project · function · L102-L120 — async def _find_or_create_project(name: str, created_by: str) -> Project
- _upload_and_create_episode · function · L123-L153 — async def _upload_and_create_episode(item: BatchSliceItem, project_id) -> str
- _trigger_autoclip · function · L156-L177 — async def _trigger_autoclip(episode_id: str, item: BatchSliceItem, user: User, config: dict) -> str
- _wait_autoclip · function · L180-L201 — async def _wait_autoclip(episode_id: str, timeout: float = AUTOCLIP_TIMEOUT)
- _trigger_detect · function · L204-L230 — async def _trigger_detect(episode_id: str, item: BatchSliceItem, user: User, detect_config: dict) -> str
- _wait_detect · function · L233-L256 — async def _wait_detect(episode_id: str, timeout: float = DETECT_TIMEOUT)
- _accept_all_candidates · function · L259-L271 — async def _accept_all_candidates(episode_id: str) -> int
- _trigger_slice · function · L274-L305 — async def _trigger_slice(episode_id: str, item: BatchSliceItem, user: User, slice_config: dict) -> str
- _wait_slice · function · L308-L334 — async def _wait_slice(episode_id: str, timeout: float = SLICE_TIMEOUT) -> tuple[bool, str, int]
- _delete_source · function · L337-L358 — async def _delete_source(item: BatchSliceItem)
- run_batch · function · L361-L534 — async def run_batch(batch_id: str)
