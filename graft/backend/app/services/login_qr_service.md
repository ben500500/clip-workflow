# backend/app/services/login_qr_service.py

- _redis · function · L57-L58 — def _redis() -> aioredis.Redis
- issue_claim · function · L61-L77 — async def issue_claim(account_id, operator_id, qr_key: str, ttl: int = CLAIM_TTL) -> str
- verify_claim_token · function · L80-L89 — async def verify_claim_token(token: str) -> Optional[dict]
- capture_login_qr · function · L92-L146 — async def capture_login_qr(account_id, port: int, profile_dir: Optional[str] = None, host: Optional[str] = None) -> Optional[bytes]
- store_qr · function · L149-L165 — async def store_qr(account_id, png_bytes: bytes) -> Optional[str]
- encrypt_cookie_bytes · function · L168-L174 — def encrypt_cookie_bytes(data: bytes) -> bytes
- decrypt_cookie_bytes · function · L177-L183 — def decrypt_cookie_bytes(data: bytes) -> bytes
- get_qr_presigned_url · function · L186-L189 — async def get_qr_presigned_url(qr_key: str, expires: int = 300) -> Optional[str]
- set_login_state · function · L192-L206 — async def set_login_state(account_id, state: str, extra: Optional[dict] = None) -> None
- get_login_state · function · L209-L215 — async def get_login_state(account_id) -> Optional[dict]
- check_login_status_via_cdp · function · L218-L248 — async def check_login_status_via_cdp(account_id, port: int, host: Optional[str] = None) -> str
- silent_keepalive · function · L251-L267 — async def silent_keepalive(account_id, port: int, host: Optional[str] = None) -> bool
