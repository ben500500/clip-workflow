# backend/app/api/slice.py

- upload_badge_image · function · L98-L160 — Uploads a badge image to MinIO raw-footage bucket under badge/ prefix, validating image extension and size limits.
- upload_subtitle_file · function · L164-L222 — Uploads a subtitle file (srt/vtt) to MinIO raw-footage bucket under subtitle/ prefix for direct subtitle burning.
- get_slice_preferences · function · L226-L235 — Retrieves the current user's persisted slice configuration from their account.
- save_slice_preferences · function · L239-L255 — Persists the user's slice configuration, creating a UserPreference row if none exists.
- run_slice · function · L259-L582 — Orchestrates a video slicing run: resolves engine, builds cutlist from accepted clips or fallback modes, constructs all configs, and dispatches to worker/celery.
- list_slice_tasks · function · L586-L613 — Lists slice tasks for an episode with data isolation.
- get_slice_task · function · L617-L666 — Returns a single slice task's details with data isolation.
- get_slice_outputs · function · L670-L710 — Returns slice output files for a task with data isolation.
- get_slice_upload_url · function · L714-L751 — Issues a presigned upload URL for worker output uploads, authenticated via worker token.
- slice_task_callback · function · L755-L885 — Handles worker completion/failure callbacks, verifying worker token and updating task/output state.
- update_slice_progress · function · L889-L915 — Updates a slice task's progress percentage from worker callback.
- retry_slice_task · function · L919-L1057 — Re-dispatches a failed slice task to the worker, reusing persisted configs.
- cancel_slice_task · function · L1061-L1100 — Cancels a pending/running slice task and marks it cancelled in Redis.
- delete_slice_task · function · L1104-L1158 — Deletes a slice task and its associated outputs from storage and DB.
