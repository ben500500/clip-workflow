# backend/app/services/batch_slice_service.py · [[batch-slicing-workflow]]

- _get_batch · function · L56-L62 — async def _get_batch(batch_id: str)
- _load_items · function · L65-L75 — async def _load_items(batch_id: str) -> list[BatchSliceItem]
- _update_item · function · L78-L83 — async def _update_item(item_id, **fields)
- _update_batch · function · L86-L91 — async def _update_batch(batch_id, **fields)
- _set_phase · function · L94-L105 — async def _set_phase(item, phase: str, status: str = None, progress: float = None)
- _find_or_create_project · function · L108-L157 — async def _find_or_create_project(name: str, created_by: str) -> Project
- _upload_and_create_episode · function · L160-L190 — async def _upload_and_create_episode(item: BatchSliceItem, project_id) -> str
- _trigger_autoclip · function · L193-L216 — async def _trigger_autoclip(episode_id: str, item: BatchSliceItem, user: User, config: dict) -> str
- _wait_autoclip · function · L219-L242 — async def _wait_autoclip(episode_id: str, timeout: float = AUTOCLIP_TIMEOUT)
- _trigger_detect · function · L245-L273 — async def _trigger_detect(episode_id: str, item: BatchSliceItem, user: User, detect_config: dict) -> str
- _wait_detect · function · L276-L307 — async def _wait_detect(episode_id: str, task_id: Optional[str] = None, timeout: float = DETECT_TIMEOUT)
- _accept_all_candidates · function · L310-L324 — async def _accept_all_candidates(episode_id: str) -> int
- _trigger_slice · function · L327-L371 — async def _trigger_slice(episode_id: str, item: BatchSliceItem, user: User, slice_config: dict) -> str
- _wait_slice · function · L374-L411 — async def _wait_slice(episode_id: str, task_id: Optional[str] = None, timeout: float = SLICE_TIMEOUT) -> tuple[bool, str, int]
- _delete_source · function · L414-L438 — async def _delete_source(item: BatchSliceItem)
- run_batch · function · L441-L618 — async def run_batch(batch_id: str)
