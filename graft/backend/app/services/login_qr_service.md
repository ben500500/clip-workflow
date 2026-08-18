# backend/app/services/login_qr_service.py · [[login-qr-self-service]] [[redis-streams-real-time-state]]

- _redis · function · L57-L60 — async def _redis() -> aioredis.Redis
- issue_claim · function · L63-L76 — async def issue_claim(account_id, operator_id, qr_key: str, ttl: int = CLAIM_TTL) -> str
- verify_claim_token · function · L79-L85 — async def verify_claim_token(token: str) -> Optional[dict]
- capture_login_qr · function · L88-L152 — async def capture_login_qr(account_id, port: int, profile_dir: Optional[str] = None, host: Optional[str] = None) -> Optional[bytes]
- store_qr · function · L155-L171 — async def store_qr(account_id, png_bytes: bytes) -> Optional[str]
- encrypt_cookie_bytes · function · L174-L180 — def encrypt_cookie_bytes(data: bytes) -> bytes
- decrypt_cookie_bytes · function · L183-L189 — def decrypt_cookie_bytes(data: bytes) -> bytes
- get_qr_presigned_url · function · L192-L195 — async def get_qr_presigned_url(qr_key: str, expires: int = 300) -> Optional[str]
- set_login_state · function · L198-L209 — async def set_login_state(account_id, state: str, extra: Optional[dict] = None) -> None
- get_login_state · function · L212-L215 — async def get_login_state(account_id) -> Optional[dict]
- check_login_status_via_cdp · function · L218-L255 — async def check_login_status_via_cdp(account_id, port: int, host: Optional[str] = None) -> str
- silent_keepalive · function · L258-L281 — async def silent_keepalive(account_id, port: int, host: Optional[str] = None) -> bool
