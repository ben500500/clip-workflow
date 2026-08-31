# backend/wechat_download/api.py · [[wechat-download-pipeline]]

- ImportRequest · class · L48-L53 — Request schema for a single WeChat video share-link import, carrying the source URL plus optional audit and project fields.
- ImportResponse · class · L56-L61 — Response schema confirming a created download task with its id, status, and source metadata.
- wechat_dl_providers · function · L65-L85 — Returns the configured download parsing providers with their live quota balances, merging real-time balance data into each provider's static info.
- import_wechat_video · function · L89-L120 — Creates a download task from a single WeChat share link and dispatches it to the wechat_dl Celery queue for processing.
- list_tasks · function · L124-L157 — Lists download tasks, supporting either paginated listing by creation time or batch status lookup by a comma-separated id list (validated as UUIDs).
- task_detail · function · L161-L166 — Fetches and serializes a single download task by id, returning 404 if it does not exist.
- ImportToProjectRequest · class · L173-L181 — Request schema choosing whether to import a downloaded episode into a new slicing project or an existing one.
- ImportToProjectResponse · class · L184-L187 — Response schema returning the target project and episode ids after a one-click import into a slicing project.
- import_task_to_project · function · L191-L253 — Re-points a completed download's Episode into a new or existing slicing project by reassigning project_id (no file move), enforcing ownership for existing projects.
- BatchImportRequest · class · L260-L265 — Request schema for batch-importing up to 100 WeChat share links at once.
- BatchImportResponse · class · L268-L273 — Response schema reporting how many batch tasks were created, skipped, and the skip reasons.
- import_wechat_video_batch · function · L277-L310 — Creates download tasks for multiple WeChat share links and dispatches each to the wechat_dl Celery queue, reporting created and skipped counts.
- ToSliceRequest · class · L318-L324 — Request schema for pushing a completed download into slicing, with mode and dedupe/subtitle-alignment options.
- ToSliceResponse · class · L327-L331 — Response schema returning the created slice task id and episode id after pushing a download into slicing.
- to_slice · function · L335-L405 — Pushes a completed download's episode into the slicing pipeline by creating a SliceTask and dispatching it to the video_processing queue, closing the download→slice→publish loop.
