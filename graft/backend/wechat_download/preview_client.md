# backend/wechat_download/preview_client.py · [[provider-fallback-chain]] [[wechat-download-pipeline]]

- PreviewClient · class · L37-L168 — class PreviewClient
- __init__ · method · L40-L43 — def __init__(self) -> None
- _connect · method · L45-L55 — async def _connect(self, cdp_url: str, token: Optional[str] = None): # C3：统一走 playwright_manager 进程级单例（get_shared 永久 pin，进程内共享一个驱动）
- _pick_account_cdp · method · L57-L80 — async def _pick_account_cdp(self, db) -> Optional[dict]
- parse · method · L82-L157 — async def parse(self, share_url: str, db=None) -> ParseResult
- close · method · L159-L168 — async def close(self) -> None: # C3：close 实际未被外部调用（get_preview_client 为进程级单例、驱动经 # playwright_manager 管理）；此处改为显式回收共享驱动，避免直接 stop 残留句柄。
- PreviewUnavailableError · class · L171-L172 — class PreviewUnavailableError(Exception)
- get_preview_client · function · L178-L182 — def get_preview_client() -> PreviewClient
