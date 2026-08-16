# backend/wechat_download/service.py

- ImportError_ · class · L48-L49 — class ImportError_(Exception)
- create_import_task · function · L56-L78 — async def create_import_task( db: AsyncSession, *, created_by: Optional[uuid.UUID], source_url: str, source_type: str = "self_owned", project_id: Optional[uuid.UUID] = None, authorize_note: Optional[str] = None, ) -> WechatDownloadTask
- get_task · function · L81-L83 — async def get_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[WechatDownloadTask]
- create_import_tasks_batch · function · L86-L132 — async def create_import_tasks_batch( db: AsyncSession, *, created_by: Optional[uuid.UUID], source_urls: list[str], source_type: str = "self_owned", project_id: Optional[uuid.UUID] = None, authorize_note: Optional[str] = None, ) -> tuple[list[WechatDownloadTask], list[str]]
- _serialize_task · function · L135-L153 — def _serialize_task(t: WechatDownloadTask) -> dict
- _read_default_download_resolution · function · L160-L172 — async def _read_default_download_resolution(db: AsyncSession) -> str
- _apply_download_resolution · function · L175-L218 — async def _apply_download_resolution(db: AsyncSession, local_path: str) -> None
- run_download_pipeline · function · L225-L300 — async def run_download_pipeline(task_id: uuid.UUID) -> dict
- _parse_with_fallback · function · L303-L357 — async def _parse_with_fallback(db, task: WechatDownloadTask)
- _hit_parse_cache · function · L360-L389 — async def _hit_parse_cache(db: AsyncSession, source_url: str) -> Optional[ParseResult]
- _set_status · function · L392-L397 — async def _set_status(db, task, status, progress, message)
- _fail · function · L400-L404 — async def _fail(db, task, error)
- _progress_payload · function · L411-L418 — def _progress_payload(task) -> dict
- _publish_progress · function · L421-L429 — async def _publish_progress(task) -> None
- _temp_path · function · L432-L435 — def _temp_path(task_id) -> str
- _ensure_project · function · L438-L456 — async def _ensure_project(db, task) -> uuid.UUID
- _create_episode · function · L459-L474 — async def _create_episode(db, task, project_id, file_key, size, parsed) -> uuid.UUID
