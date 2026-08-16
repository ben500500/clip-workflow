# backend/app/services/smart_import_service.py

- _normalize_headers · function · L100-L102 — def _normalize_headers(headers: list) -> list
- _read_headers_sync · function · L105-L116 — def _read_headers_sync(file_bytes: bytes) -> list
- _read_preview_sync · function · L119-L130 — def _read_preview_sync(file_bytes: bytes, nrows: int = 5) -> list
- _detect_platform · function · L133-L153 — def _detect_platform(headers: list) -> Optional[dict]
- _transform_row_sync · function · L156-L177 — def _transform_row_sync( df: pd.DataFrame, mapping: dict, target_table: str, ) -> list
- detect_platform · function · L180-L212 — async def detect_platform(file_bytes: bytes) -> dict
- preview_file · function · L215-L226 — async def preview_file(file_bytes: bytes) -> dict
- confirm_import · function · L229-L273 — async def confirm_import( file_bytes: bytes, mapping: dict, target_table: str, account_id: Optional[uuid.UUID], db: AsyncSession, ) -> dict
- BytesFileWrapper · class · L255-L258 — class BytesFileWrapper
- __init__ · method · L256-L258 — def __init__(self, data: bytes, name: str = "import.xlsx")
- get_import_templates · function · L276-L290 — async def get_import_templates(db: AsyncSession) -> list
- save_custom_template · function · L293-L317 — async def save_custom_template( name: str, platform: str, mapping: dict, unit_conversions: Optional[dict], db: AsyncSession, ) -> dict
- get_import_history · function · L320-L340 — async def get_import_history(db: AsyncSession) -> list
- get_ecosystem_metrics · function · L343-L382 — async def get_ecosystem_metrics( db: AsyncSession, account_id: Optional[uuid.UUID] = None, start_date: Optional[date] = None, end_date: Optional[date] = None, ) -> list
- get_cross_analysis · function · L385-L432 — async def get_cross_analysis( db: AsyncSession, account_id: Optional[uuid.UUID] = None, page: int = 1, page_size: int = 20, ) -> dict
