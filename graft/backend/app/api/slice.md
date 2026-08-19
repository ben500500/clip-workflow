# backend/app/api/slice.py · [[video-slicing-pipeline]]

- upload_badge_image · function · L105-L167 — Uploads a badge image to MinIO raw-footage bucket under badge/ prefix, validating image extension and size limits.
- upload_subtitle_file · function · L171-L229 — Uploads a subtitle file (srt/vtt) to MinIO raw-footage bucket under subtitle/ prefix for direct subtitle burning.
- get_slice_preferences · function · L233-L242 — Retrieves the current user's persisted slice configuration from their account.
- save_slice_preferences · function · L246-L262 — Persists the user's slice configuration, creating a UserPreference row if none exists.
- _resolve_slice_inputs · function · L265-L535 — async def _resolve_slice_inputs( db: AsyncSession, eid: uuid.UUID, episode: Episode, data: SliceRunRequest, source_file_key: Optional[str], source_bucket: str, episode_id: str, current_user: Optional[User] = None, ) -> tuple
- _create_slice_task_record · function · L538-L624 — async def _create_slice_task_record( db: AsyncSession, eid: uuid.UUID, episode: Episode, data: SliceRunRequest, cutlist: str, intervals_content: str, source_file_key: Optional[str], source_bucket: str, ) -> tuple
- _dispatch_slice_task · function · L627-L739 — async def _dispatch_slice_task( db: AsyncSession, engine: str, episode: Episode, slice_task: SliceTask, data: SliceRunRequest, source_file_key: Optional[str], source_bucket: str, cutlist: str, intervals_content: str, configs: dict, fallback_whole_video: bool, ) -> SliceRunResponse
- run_slice · function · L743-L783 — Orchestrates a video slicing run: resolves engine, builds cutlist from accepted clips or fallback modes, constructs all configs, and dispatches to worker/celery.
- list_slice_tasks · function · L787-L814 — Lists slice tasks for an episode with data isolation.
- get_slice_task · function · L818-L867 — Returns a single slice task's details with data isolation.
- get_slice_outputs · function · L871-L911 — Returns slice output files for a task with data isolation.
- get_slice_upload_url · function · L915-L952 — Issues a presigned upload URL for worker output uploads, authenticated via worker token.
- slice_task_callback · function · L956-L1086 — Handles worker completion/failure callbacks, verifying worker token and updating task/output state.
- update_slice_progress · function · L1090-L1116 — Updates a slice task's progress percentage from worker callback.
- retry_slice_task · function · L1120-L1261 — Re-dispatches a failed slice task to the worker, reusing persisted configs.
- cancel_slice_task · function · L1265-L1304 — Cancels a pending/running slice task and marks it cancelled in Redis.
- delete_slice_task · function · L1308-L1366 — Deletes a slice task and its associated outputs from storage and DB.
