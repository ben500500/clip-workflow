# backend/app/services/batch_decoupled_service.py · [[batch-slicing-workflow]] [[redis-streams-real-time-state]]

- _get_batch · function · L56-L61 — async def _get_batch(batch_id: str)
- _load_items · function · L64-L71 — async def _load_items(batch_id: str) -> list
- _load_item · function · L74-L79 — async def _load_item(item_id: str) -> BatchSliceItem
- _update_item · function · L82-L87 — async def _update_item(item_id, **fields)
- _update_batch · function · L90-L95 — async def _update_batch(batch_id, **fields)
- _get_operator · function · L98-L104 — async def _get_operator(batch: BatchSlice)
- _resolve_project · function · L107-L123 — async def _resolve_project(batch: BatchSlice)
- run_batch_decoupled · function · L129-L186 — async def run_batch_decoupled(batch_id: str)
- process_selection · function · L192-L246 — async def process_selection(batch_id: str, item_id: str, episode_id: str)
- dispatch_ready_slices · function · L252-L322 — async def dispatch_ready_slices()
- finalize_slices · function · L328-L400 — async def finalize_slices()
- aggregate_batches · function · L406-L470 — async def aggregate_batches()
