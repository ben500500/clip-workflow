# backend/app/services/feishu_service.py

- extract_spreadsheet_token · function · L45-L68 — def extract_spreadsheet_token(url: str) -> Optional[str]
- parse_feishu_url · function · L71-L110 — def parse_feishu_url(url: str) -> Optional[dict]
- _split_theater_names · function · L113-L121 — def _split_theater_names(value) -> List[str]
- _get_tenant_access_token · function · L126-L145 — async def _get_tenant_access_token(client: httpx.AsyncClient) -> Optional[str]
- fetch_sheet_rows · function · L148-L207 — async def fetch_sheet_rows(spreadsheet_token: str, url: Optional[str] = None) -> List[dict]
- _bitable_value_to_str · function · L210-L238 — def _bitable_value_to_str(value) -> str
- _wiki_node_to_obj · function · L241-L257 — async def _wiki_node_to_obj(client: httpx.AsyncClient, headers: dict, wiki_token: str) -> Optional[dict]
- _fetch_bitable_records · function · L260-L310 — async def _fetch_bitable_records(client: httpx.AsyncClient, headers: dict, app_token: str, table_id: Optional[str]) -> List[dict]
- fetch_feishu_rows · function · L313-L344 — async def fetch_feishu_rows(url: Optional[str] = None) -> (List[dict], Optional[str])
- sync_from_feishu · function · L349-L421 — async def sync_from_feishu(url: Optional[str] = None) -> dict
- _find_col · function · L424-L441 — def _find_col(header_row: dict, target: str) -> Optional[str]
- _sync_theaters · function · L444-L457 — async def _sync_theaters(db, drama: Drama, theater_ids: List)
