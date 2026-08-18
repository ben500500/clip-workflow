# backend/app/api/batch_slice.py

- BatchEpisodeItem · class · L42-L45 — Pydantic model for one episode in the batch request, carrying optional title and required video file path.
- BatchSliceRunRequest · class · L48-L59 — Request body for batch slice run: drama name, ordered episode list, unified slice config, and whether to auto-delete source videos.
- BatchSliceRunResponse · class · L62-L65 — Response model confirming batch creation with batch id, total episode count, and a status message.
- BatchSliceItemResponse · class · L68-L86 — Response model describing per-episode processing state including phase, progress, output count, and error message.
- BatchSliceResponse · class · L89-L104 — Response model summarizing a batch's overall status, counts (total/done/failed/outputs), and timestamps.
- BatchSliceOutputItem · class · L107-L114 — Response model for one slice output entry in the aggregated output list.
- BatchSliceOutputResponse · class · L117-L119 — Response model wrapping a batch id and its list of slice output items.
- _serialize_batch · function · L127-L142 — Converts a BatchSlice ORM object into a JSON-safe dict with ISO timestamps and null-safe fields.
- _serialize_item · function · L145-L163 — Converts a BatchSliceItem ORM object into a JSON-safe dict with ISO timestamps and null-safe fields.
- _load_batch_owned · function · L166-L179 — Loads a batch by id, validating UUID format and enforcing data-isolation by checking project access for the current user.
- run_batch_slice · function · L188-L240 — Validates input, creates a pending batch with its items, and dispatches the async Celery task that processes episodes in order.
- list_batch_slices · function · L244-L254 — Returns a paginated, newest-first list of batch slice history for the user.
- get_batch_slice · function · L258-L265 — Returns the overall status/progress of a single owned batch.
- get_batch_items · function · L269-L282 — Returns the per-episode processing status list for an owned batch, ordered by sequence.
- get_batch_outputs · function · L286-L361 — Aggregates all slice outputs across a batch's items, generating presigned download URLs and falling back to episode-level task scan for legacy data.
- retry_batch_slice · function · L365-L395 — Resets failed batch items to pending and re-dispatches the Celery task to retry only the failed episodes.
- cancel_batch_slice · function · L399-L420 — Cancels a batch by marking all in-progress items as cancelled and setting the batch to cancelled state, refusing if already finished.
