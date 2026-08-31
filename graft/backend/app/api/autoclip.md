# backend/app/api/autoclip.py · [[autoclip-pipeline-batch-slicing]] [[data-isolation-access-control]]

- _merge_default_autoclip_config · function · L32-L90 — Merges system-level default_autoclip_config settings (model name, score threshold) as a base layer so system settings take effect, with request-provided config overriding them.
- AutoClipRunRequest · class · L94-L96 — Request body for triggering an AutoClip run, carrying optional config overrides and an optional video path.
- AutoClipRunResponse · class · L99-L102 — Response payload confirming a dispatched AutoClip run with its Celery task id and project id.
- AutoClipProgressResponse · class · L105-L109 — Response payload reporting AutoClip pipeline status, progress fraction, and optional error message.
- AutoClipRunResponseItem · class · L112-L126 — Response item describing one historical AutoClip run record for the workbench history view.
- ClipUpdateRequest · class · L129-L132 — Request body for updating a clip candidate's status or adjusted start/end times.
- ClipResponse · class · L135-L154 — Response payload serializing a clip candidate's metadata, timing, score, and status for the frontend.
- _serialize_clip · function · L157-L175 — Converts a ClipCandidate ORM object into a plain dict with stringified ids and ISO timestamps for API responses.
- _serialize_autoclip_run · function · L178-L192 — Converts an AutoClipRun ORM object into a plain dict with normalized status/progress defaults and ISO timestamps.
- run_autoclip · function · L196-L314 — Validates episode access and inputs, creates a remote AutoClip project, persists project/run history, and dispatches the Celery task for the 6-step clip-selection pipeline.
- get_autoclip_history · function · L318-L344 — Returns up to 50 most recent AutoClip run records for an episode, enforcing data isolation.
- get_autoclip_progress · function · L348-L406 — Reports AutoClip pipeline progress, preferring live service status and falling back to local DB pipeline_status mapping.
- get_autoclip_clips · function · L410-L437 — Returns clip candidates for an episode, optionally filtered by a minimum score threshold and ordered by clip index.
- update_clip · function · L441-L479 — Updates a clip candidate's status (validated against allowed values) and adjusted start/end times under data isolation.
- regenerate_autoclip · function · L483-L523 — Re-runs the AutoClip pipeline with updated parameters, creating the new project first and only deleting old pending clips after successful dispatch to avoid data loss.
- delete_autoclip_history · function · L526-L563 — async def delete_autoclip_history( episode_id: str, run_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
