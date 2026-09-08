# backend/app/celery/remotion_tasks.py

- run_remotion_mix_task · function · L26-L60 — def run_remotion_mix_task(self, slice_task_id: str, lock_token: str = None)
- _run_remotion_mix_flow · function · L63-L111 — async def _run_remotion_mix_flow(slice_task_id: str) -> dict
- _mark_remotion_failed · function · L114-L125 — async def _mark_remotion_failed(slice_task_id: str, error: str) -> None
- remotion_stale_recovery_task · function · L129-L149 — def remotion_stale_recovery_task(self)
- _recover_stale_remotion · function · L152-L174 — async def _recover_stale_remotion(timeout_seconds: int) -> int
