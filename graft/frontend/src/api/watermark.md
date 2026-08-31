# frontend/src/api/watermark.ts · [[frontend-api-layer]]

API client module for watermark removal/processing operations, exposing typed endpoints for upload, run, task management, and video download.

- WatermarkVideoItem · interface · L3-L19 — Data shape describing a single processed video's status, progress, and output details within a watermark task.
- WatermarkTaskItem · interface · L21-L38 — Data shape describing a watermark batch task's engine, progress counts, and lifecycle timestamps.
- WatermarkTaskDetail · interface · L40-L42 — Task item extended with the list of videos belonging to that watermark task.
- WatermarkUploadResult · interface · L44-L49 — Data shape returned after uploading a source file, carrying the storage key and upload id for later processing.
- WatermarkRunParams · interface · L51-L71 — Typed request payload for launching a watermark removal run, enumerating engine choice and all tunable processing options.
