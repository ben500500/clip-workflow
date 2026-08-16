# backend/app/services/batch_decoupled_service.py

- _get_batch · function · L50-L55 — async def _get_batch(batch_id: str)
- _load_items · function · L58-L65 — async def _load_items(batch_id: str) -> list
- _load_item · function · L68-L73 — async def _load_item(item_id: str) -> BatchSliceItem
- _update_item · function · L76-L81 — async def _update_item(item_id, **fields)
- _update_batch · function · L84-L89 — async def _update_batch(batch_id, **fields)
- _get_operator · function · L92-L98 — async def _get_operator(batch: BatchSlice)
- _resolve_project · function · L101-L117 — async def _resolve_project(batch: BatchSlice)
- run_batch_decoupled · function · L123-L180 — async def run_batch_decoupled(batch_id: str)
- process_selection · function · L186-L240 — async def process_selection(batch_id: str, item_id: str, episode_id: str)
- dispatch_ready_slices · function · L246-L315 — async def dispatch_ready_slices()
- aggregate_batches · function · L321-L385 — async def aggregate_batches()
