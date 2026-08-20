# backend/app/services/batch_decoupled_service.py · [[batch-slicing-workflow]] [[redis-streams-real-time-state]]

- _get_batch · function · L56-L64 — async def _get_batch(batch_id: str)
- _load_items · function · L67-L77 — async def _load_items(batch_id: str) -> list
- _load_item · function · L80-L88 — async def _load_item(item_id: str) -> BatchSliceItem
- _update_item · function · L91-L96 — async def _update_item(item_id, **fields)
- _update_batch · function · L99-L104 — async def _update_batch(batch_id, **fields)
- _get_operator · function · L107-L116 — async def _get_operator(batch: BatchSlice)
- _resolve_project · function · L119-L137 — async def _resolve_project(batch: BatchSlice)
- run_batch_decoupled · function · L143-L200 — async def run_batch_decoupled(batch_id: str)
- process_selection · function · L206-L260 — async def process_selection(batch_id: str, item_id: str, episode_id: str)
- dispatch_ready_slices · function · L266-L342 — async def dispatch_ready_slices()
- finalize_slices · function · L348-L424 — async def finalize_slices()
- aggregate_batches · function · L430-L498 — async def aggregate_batches()
