# backend/app/services/data_import_service.py

- _validate_columns · function · L47-L58 — def _validate_columns(df: pd.DataFrame, required: list, import_type: str) -> list
- _normalize_columns · function · L61-L64 — def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame
- _parse_date · function · L67-L78 — def _parse_date(value) -> Optional[date]
- _safe_int · function · L81-L88 — def _safe_int(value, default=0) -> int
- _safe_float · function · L91-L98 — def _safe_float(value, default=0.0) -> float
- _upsert_video_metric · function · L101-L125 — async def _upsert_video_metric( db: AsyncSession, video_id: str, publish_date, account_id: Optional[uuid.UUID], values: dict, )
- _upsert_metric · function · L128-L150 — async def _upsert_metric( db: AsyncSession, model, date_field: str, record_date, account_id: Optional[uuid.UUID], values: dict, )
- import_video_metrics · function · L153-L244 — async def import_video_metrics( file, account_id: Optional[uuid.UUID], db: AsyncSession, ) -> dict
- import_mini_program_metrics · function · L247-L313 — async def import_mini_program_metrics( file, account_id: Optional[uuid.UUID], db: AsyncSession, ) -> dict
- import_ad_metrics · function · L316-L386 — async def import_ad_metrics( file, account_id: Optional[uuid.UUID], db: AsyncSession, ) -> dict
- _generate_template_sync · function · L389-L439 — def _generate_template_sync(import_type: str) -> bytes
- generate_import_template · function · L442-L454 — async def generate_import_template(import_type: str) -> bytes
