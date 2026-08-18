# backend/wechat_download/preview_client.py · [[wechat-download-pipeline]]

- PreviewClient · class · L37-L164 — class PreviewClient
- __init__ · method · L40-L43 — def __init__(self) -> None
- _connect · method · L45-L54 — async def _connect(self, cdp_url: str, token: Optional[str] = None)
- _pick_account_cdp · method · L56-L79 — async def _pick_account_cdp(self, db) -> Optional[dict]
- parse · method · L81-L156 — async def parse(self, share_url: str, db=None) -> ParseResult
- close · method · L158-L164 — async def close(self) -> None
- PreviewUnavailableError · class · L167-L168 — class PreviewUnavailableError(Exception)
- get_preview_client · function · L174-L178 — def get_preview_client() -> PreviewClient
