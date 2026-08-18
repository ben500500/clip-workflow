# backend/app/celery/shortdrama_tasks.py · [[celery-task-layer]]

Celery task module for short-drama video generation, providing two independent channels: Doubao RPA one-click generation and Seedance official API direct generation.

- _load_shortdrama_prompt · function · L32-L44 — Loads a ShortdramaPrompt record by id from the database, returning None for invalid UUIDs or missing records.
- _now_str · function · L47-L48 — Returns the current UTC time formatted as a compact timestamp string for use in file naming.
- _update_doubao_prompt · function · L55-L107 — Updates the Doubao task fields on a ShortdramaPrompt record, applying only the non-None keyword arguments passed in.
- _sync_doubao_video · function · L110-L191 — Downloads the finished Doubao video from its CDN link, uploads it to MinIO, and backfills the prompt record's video fields while cleaning up the old video.
- _load_doubao_config · function · L194-L203 — Loads the Doubao RPA configuration from system_config, returning an empty dict when absent or malformed.
- _check_doubao_cancelled · function · L206-L211 — Checks whether the Doubao task has been cancelled by the user, treating a missing record as cancelled.
- doubao_generate_task · function · L215-L433 — Orchestrates the one-click Doubao RPA generation flow: drives the browser to generate a video, handles login/rewrite confirmation callbacks, then downloads and syncs the finished video to MinIO while driving the doubao_status state machine.
- _progress_cb · function · L256-L262 — Reports generation progress to both the Celery state and the database prompt record.
- _qrcode_cb · function · L265-L271 — Persists the login QR code and flips status to need_login so the frontend can display the scan prompt.
- _on_login_success · function · L275-L281 — Resets status from need_login back to running and clears the QR code so the frontend login popup closes.
- _screenshot_cb · function · L284-L288 — Persists a screenshot of the Doubao conversation window for frontend display.
- _account_cb · function · L291-L297 — Persists the detected Doubao account nickname to the prompt record for frontend display.
- _rewrite_cb · function · L300-L339 — Handles Doubao's rewrite-confirmation flow: appends the rewrite to history, sets awaiting_rewrite status with a confirm token, and polls the DB until the user approves, rejects, or cancels (bounded by a configurable timeout).
- _update_seedance_prompt · function · L440-L477 — Updates the Seedance direct-connection task fields on a ShortdramaPrompt record, applying only the non-None keyword arguments passed in.
- _load_seedance_db_config · function · L480-L489 — Loads the Seedance direct-connection configuration from system_config, returning an empty dict when absent or malformed.
- _check_seedance_cancelled · function · L492-L497 — Checks whether the Seedance task has been cancelled by the user, treating a missing record as cancelled.
- _sync_generated_video · function · L500-L583 — Downloads a generated video from its URL, uploads it to MinIO, and backfills the prompt record's video fields while cleaning up the old video and tagging the generation channel.
- seedance_generate_task · function · L587-L792 — Orchestrates the Seedance official API direct-generation flow: submits a generation request, polls for completion, then downloads and syncs the finished video to MinIO while driving the seedance_status state machine.
- _progress_cb · function · L653-L659 — Reports Seedance generation progress to both the Celery state and the database prompt record.
