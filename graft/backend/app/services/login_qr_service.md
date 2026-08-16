# backend/app/services/login_qr_service.py

- _redis · function · L57-L60 — async def _redis() -> aioredis.Redis
- issue_claim · function · L63-L76 — async def issue_claim(account_id, operator_id, qr_key: str, ttl: int = CLAIM_TTL) -> str
- verify_claim_token · function · L79-L85 — async def verify_claim_token(token: str) -> Optional[dict]
- capture_login_qr · function · L88-L142 — async def capture_login_qr(account_id, port: int, profile_dir: Optional[str] = None, host: Optional[str] = None) -> Optional[bytes]
- store_qr · function · L145-L161 — async def store_qr(account_id, png_bytes: bytes) -> Optional[str]
- encrypt_cookie_bytes · function · L164-L170 — def encrypt_cookie_bytes(data: bytes) -> bytes
- decrypt_cookie_bytes · function · L173-L179 — def decrypt_cookie_bytes(data: bytes) -> bytes
- get_qr_presigned_url · function · L182-L185 — async def get_qr_presigned_url(qr_key: str, expires: int = 300) -> Optional[str]
- set_login_state · function · L188-L199 — async def set_login_state(account_id, state: str, extra: Optional[dict] = None) -> None
- get_login_state · function · L202-L205 — async def get_login_state(account_id) -> Optional[dict]
- check_login_status_via_cdp · function · L208-L238 — async def check_login_status_via_cdp(account_id, port: int, host: Optional[str] = None) -> str
- silent_keepalive · function · L241-L257 — async def silent_keepalive(account_id, port: int, host: Optional[str] = None) -> bool
