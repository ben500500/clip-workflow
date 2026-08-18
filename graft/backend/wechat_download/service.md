# backend/wechat_download/service.py · [[wechat-download-pipeline]]

- ImportError_ · class · L48-L49 — class ImportError_(Exception)
- RetryableImportError · class · L52-L57 — class RetryableImportError(ImportError_)
- create_import_task · function · L64-L86 — async def create_import_task( db: AsyncSession, *, created_by: Optional[uuid.UUID], source_url: str, source_type: str = "self_owned", project_id: Optional[uuid.UUID] = None, authorize_note: Optional[str] = None, ) -> WechatDownloadTask
- get_task · function · L89-L91 — async def get_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[WechatDownloadTask]
- create_import_tasks_batch · function · L94-L140 — async def create_import_tasks_batch( db: AsyncSession, *, created_by: Optional[uuid.UUID], source_urls: list[str], source_type: str = "self_owned", project_id: Optional[uuid.UUID] = None, authorize_note: Optional[str] = None, ) -> tuple[list[WechatDownloadTask], list[str]]
- _serialize_task · function · L143-L161 — def _serialize_task(t: WechatDownloadTask) -> dict
- _read_default_download_resolution · function · L168-L180 — async def _read_default_download_resolution(db: AsyncSession) -> str
- _apply_download_resolution · function · L183-L226 — async def _apply_download_resolution(db: AsyncSession, local_path: str) -> None
- run_download_pipeline · function · L233-L320 — async def run_download_pipeline(task_id: uuid.UUID) -> dict
- _parse_with_fallback · function · L323-L377 — async def _parse_with_fallback(db, task: WechatDownloadTask)
- _hit_parse_cache · function · L380-L409 — async def _hit_parse_cache(db: AsyncSession, source_url: str) -> Optional[ParseResult]
- _set_status · function · L412-L417 — async def _set_status(db, task, status, progress, message)
- _fail · function · L420-L424 — async def _fail(db, task, error)
- _progress_payload · function · L431-L438 — def _progress_payload(task) -> dict
- _publish_progress · function · L441-L449 — async def _publish_progress(task) -> None
- _temp_path · function · L452-L455 — def _temp_path(task_id) -> str
- _ensure_project · function · L458-L476 — async def _ensure_project(db, task) -> uuid.UUID
- _create_episode · function · L479-L494 — async def _create_episode(db, task, project_id, file_key, size, parsed) -> uuid.UUID
