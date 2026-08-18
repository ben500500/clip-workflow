# slice-worker/callback.go · [[slice-worker-node]]

- TaskCallback · struct · L12-L22 — Data structure carrying task completion status, outputs, and error details to the orchestrator.
- OutputFileInfo · struct · L25-L30 — Data structure describing a single output file produced by a task.
- CallbackService · struct · L33-L37 — HTTP client wrapper holding node identity and auth token for sending task callbacks.
- NewCallbackService · function · L40-L47 — Constructs a callback service with a 30-second HTTP timeout and the worker's node ID.
- SetToken · method · L50-L52 — Injects the callback authentication token supplied via the task payload.
- SendCallback · method · L55-L88 — Serializes task completion data and POSTs it to the orchestrator's callback URL, attaching the worker token and rejecting non-2xx responses.
