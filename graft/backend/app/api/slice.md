# backend/app/api/slice.py · [[video-slicing-pipeline]]

- upload_badge_image · function · L104-L166 — Uploads a badge image to MinIO raw-footage bucket under badge/ prefix, validating image extension and size limits.
- upload_subtitle_file · function · L170-L228 — Uploads a subtitle file (srt/vtt) to MinIO raw-footage bucket under subtitle/ prefix for direct subtitle burning.
- get_slice_preferences · function · L232-L241 — Retrieves the current user's persisted slice configuration from their account.
- save_slice_preferences · function · L245-L261 — Persists the user's slice configuration, creating a UserPreference row if none exists.
- run_slice · function · L265-L662 — Orchestrates a video slicing run: resolves engine, builds cutlist from accepted clips or fallback modes, constructs all configs, and dispatches to worker/celery.
- list_slice_tasks · function · L666-L693 — Lists slice tasks for an episode with data isolation.
- get_slice_task · function · L697-L746 — Returns a single slice task's details with data isolation.
- get_slice_outputs · function · L750-L790 — Returns slice output files for a task with data isolation.
- get_slice_upload_url · function · L794-L831 — Issues a presigned upload URL for worker output uploads, authenticated via worker token.
- slice_task_callback · function · L835-L965 — Handles worker completion/failure callbacks, verifying worker token and updating task/output state.
- update_slice_progress · function · L969-L995 — Updates a slice task's progress percentage from worker callback.
- retry_slice_task · function · L999-L1140 — Re-dispatches a failed slice task to the worker, reusing persisted configs.
- cancel_slice_task · function · L1144-L1183 — Cancels a pending/running slice task and marks it cancelled in Redis.
- delete_slice_task · function · L1187-L1245 — Deletes a slice task and its associated outputs from storage and DB.
