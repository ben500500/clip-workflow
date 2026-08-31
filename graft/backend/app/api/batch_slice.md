# backend/app/api/batch_slice.py · [[autoclip-pipeline-batch-slicing]] [[data-isolation-access-control]]

- BatchEpisodeItem · class · L43-L46 — Pydantic model for one episode in the batch request, carrying optional title and required video file path.
- BatchSliceRunRequest · class · L49-L60 — Request body for batch slice run: drama name, ordered episode list, unified slice config, and whether to auto-delete source videos.
- BatchSliceRunResponse · class · L63-L66 — Response model confirming batch creation with batch id, total episode count, and a status message.
- BatchSliceItemResponse · class · L69-L87 — Response model describing per-episode processing state including phase, progress, output count, and error message.
- BatchSliceResponse · class · L90-L105 — Response model summarizing a batch's overall status, counts (total/done/failed/outputs), and timestamps.
- BatchSliceOutputItem · class · L108-L115 — Response model for one slice output entry in the aggregated output list.
- BatchSliceOutputResponse · class · L118-L120 — Response model wrapping a batch id and its list of slice output items.
- _serialize_batch · function · L128-L143 — Converts a BatchSlice ORM object into a JSON-safe dict with ISO timestamps and null-safe fields.
- _serialize_item · function · L146-L164 — Converts a BatchSliceItem ORM object into a JSON-safe dict with ISO timestamps and null-safe fields.
- _load_batch_owned · function · L167-L180 — Loads a batch by id, validating UUID format and enforcing data-isolation by checking project access for the current user.
- run_batch_slice · function · L189-L241 — Validates input, creates a pending batch with its items, and dispatches the async Celery task that processes episodes in order.
- list_batch_slices · function · L245-L264 — Returns a paginated, newest-first list of batch slice history for the user.
- get_batch_slice · function · L268-L275 — Returns the overall status/progress of a single owned batch.
- get_batch_items · function · L279-L292 — Returns the per-episode processing status list for an owned batch, ordered by sequence.
- get_batch_outputs · function · L296-L376 — Aggregates all slice outputs across a batch's items, generating presigned download URLs and falling back to episode-level task scan for legacy data.
- retry_batch_slice · function · L380-L420 — Resets failed batch items to pending and re-dispatches the Celery task to retry only the failed episodes.
- cancel_batch_slice · function · L424-L445 — Cancels a batch by marking all in-progress items as cancelled and setting the batch to cancelled state, refusing if already finished.
