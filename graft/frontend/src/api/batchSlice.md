# frontend/src/api/batchSlice.ts · [[frontend-api-client-layer]]

Defines the API client and TypeScript types for the batch-slice backend endpoints, covering run, list, get, outputs, retry, and cancel operations.

- BatchEpisodeItem · interface · L4-L7 — Represents a single episode to be sliced in a batch run, identified by its path with an optional title.
- BatchSliceRunRequest · interface · L9-L14 — Payload for launching a batch slice run, specifying the drama, episodes, optional slice config, and whether to auto-delete source files.
- BatchSliceRunResponse · interface · L16-L20 — Response returned when a batch slice run is started, carrying the batch id, total episode count, and a message.
- BatchSliceItem · interface · L22-L39 — Describes the per-episode status and progress of a batch slice job, including task ids, phase, output count, and error details.
- BatchSlice · interface · L41-L55 — Summarizes the overall state of a batch slice job, tracking totals for done, failed, and output counts along with timing.
- BatchSliceOutputItem · interface · L57-L64 — Represents one item's slice output within a batch, linking its sequence, title, task ids, status, and output data.
- BatchSliceOutputResponse · interface · L66-L69 — Wraps the list of output items for a completed batch slice job.
