# backend/app/services/batch_slice_service.py

- _get_batch · function · L55-L59 — Loads a single BatchSlice record by id from the database.
- _load_items · function · L62-L69 — Loads all BatchSliceItem rows for a batch ordered by sequence number.
- _update_item · function · L72-L77 — Persists field updates to a single batch item row.
- _update_batch · function · L80-L85 — Persists field updates to a batch row.
- _set_phase · function · L88-L99 — Updates an item's phase/status/progress both in DB and in-memory object to track workflow stage.
- _find_or_create_project · function · L102-L120 — Looks up a Project by name (oldest first) or creates a new one owned by the creator for data isolation.
- _upload_and_create_episode · function · L123-L153 — Uploads the source video file to MinIO raw-footage bucket and creates an Episode record, returning its id.
- _trigger_autoclip · function · L156-L177 — Invokes the autoclip API to kick off AI clip-point selection and returns the latest AutoClipRun id.
- _wait_autoclip · function · L180-L201 — Polls the latest AutoClipRun until it reaches a terminal completed/failed state or times out.
- _trigger_detect · function · L204-L230 — Invokes the interval detection API and returns the id of the most recent detect_* SliceTask.
- _wait_detect · function · L233-L256 — Polls the latest detect_* SliceTask until terminal state or timeout.
- _accept_all_candidates · function · L259-L271 — Auto-review: flips all pending ClipCandidates for an episode to accepted, returning the count.
- _trigger_slice · function · L274-L305 — Invokes the slice API with auto_accept_all forced on, filtering config to known fields to avoid pydantic errors, and returns the SliceTask id.
- _wait_slice · function · L308-L334 — Polls the latest SliceTask until completed/failed/cancelled or timeout, tracking output_count.
- _delete_source · function · L337-L358 — Deletes the source video from local disk and MinIO, clearing the episode's source_file_key to save space.
- run_batch · function · L361-L534 — Entry point that routes to decoupled vs serial pipeline modes and orchestrates the full per-episode upload→autoclip→review→interval→slice→delete workflow.
