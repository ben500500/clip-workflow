# backend/lan_source/service.py

- LanSourceImportError · class · L45-L46 — class LanSourceImportError(Exception)
- RetryableLanSourceError · class · L49-L53 — class RetryableLanSourceError(LanSourceImportError)
- create_import_task · function · L60-L81 — async def create_import_task( db: AsyncSession, *, created_by: Optional[uuid.UUID], drama_name: str, project_id: Optional[uuid.UUID] = None, total_episodes: Optional[int] = None, ) -> LanSourceImport
- get_import_task · function · L84-L86 — async def get_import_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[LanSourceImport]
- serialize_task · function · L89-L107 — def serialize_task(t: LanSourceImport) -> dict
- run_import_pipeline · function · L114-L216 — async def run_import_pipeline(task_id: uuid.UUID) -> dict
- load_db_config · function · L219-L233 — async def load_db_config(db: AsyncSession) -> LanSourceConfig
- _discover_episodes · function · L236-L244 — async def _discover_episodes(task: LanSourceImport, cfg: Optional[LanSourceConfig] = None) -> list[CdnEpisode]
- _download_all · function · L247-L251 — async def _download_all(url_paths: list[tuple[str, str]], cfg: Optional[LanSourceConfig] = None) -> list[bool]
- _ensure_project · function · L254-L273 — async def _ensure_project(db: AsyncSession, task: LanSourceImport, cfg: Optional[LanSourceConfig] = None) -> uuid.UUID
- _ensure_drama · function · L276-L298 — async def _ensure_drama(db: AsyncSession, task: LanSourceImport) -> uuid.UUID
- _import_episode · function · L301-L333 — async def _import_episode( db: AsyncSession, task: LanSourceImport, project_id: uuid.UUID, drama_id: uuid.UUID, ep: CdnEpisode, local_path: str, idx: int, ) -> uuid.UUID
- _set_status · function · L336-L341 — async def _set_status(db, task: LanSourceImport, status, progress, message)
- _fail · function · L344-L348 — async def _fail(db, task: LanSourceImport, error)
- _progress_payload · function · L355-L364 — def _progress_payload(task: LanSourceImport) -> dict
- _publish_progress · function · L367-L375 — async def _publish_progress(task: LanSourceImport) -> None
- _temp_dir · function · L378-L381 — def _temp_dir(task_id) -> str
- _cleanup_temp · function · L384-L391 — def _cleanup_temp(task_id) -> None
