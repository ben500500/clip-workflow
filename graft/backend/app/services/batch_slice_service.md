# backend/app/services/batch_slice_service.py · [[batch-slicing-workflow]]

- _get_batch · function · L56-L62 — Loads a single BatchSlice record by id from the database.
- _load_items · function · L65-L75 — Loads all BatchSliceItem rows for a batch ordered by sequence number.
- _update_item · function · L78-L83 — Persists field updates to a single batch item row.
- _update_batch · function · L86-L91 — Persists field updates to a batch row.
- _set_phase · function · L94-L105 — Updates an item's phase/status/progress both in DB and in-memory object to track workflow stage.
- _find_or_create_project · function · L108-L157 — Looks up a Project by name (oldest first) or creates a new one owned by the creator for data isolation.
- _upload_and_create_episode · function · L160-L190 — Uploads the source video file to MinIO raw-footage bucket and creates an Episode record, returning its id.
- _trigger_autoclip · function · L193-L216 — Invokes the autoclip API to kick off AI clip-point selection and returns the latest AutoClipRun id.
- _wait_autoclip · function · L219-L242 — Polls the latest AutoClipRun until it reaches a terminal completed/failed state or times out.
- _trigger_detect · function · L245-L273 — Invokes the interval detection API and returns the id of the most recent detect_* SliceTask.
- _wait_detect · function · L276-L307 — Polls the latest detect_* SliceTask until terminal state or timeout.
- _accept_all_candidates · function · L310-L328 — Auto-review: flips all pending ClipCandidates for an episode to accepted, returning the count.
- _trigger_slice · function · L331-L391 — Invokes the slice API with auto_accept_all forced on, filtering config to known fields to avoid pydantic errors, and returns the SliceTask id.
- _wait_slice · function · L394-L431 — Polls the latest SliceTask until completed/failed/cancelled or timeout, tracking output_count.
- _delete_source · function · L434-L458 — Deletes the source video from local disk and MinIO, clearing the episode's source_file_key to save space.
- run_batch · function · L461-L638 — Entry point that routes to decoupled vs serial pipeline modes and orchestrates the full per-episode upload→autoclip→review→interval→slice→delete workflow.
