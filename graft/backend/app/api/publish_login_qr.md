# backend/app/api/publish_login_qr.py

- LoginQrApply · class · L33-L35 — class LoginQrApply(BaseModel)
- LoginScanCallback · class · L38-L44 — class LoginScanCallback(BaseModel)
- _probe_cdp_port · function · L47-L59 — async def _probe_cdp_port(host: str, port: int, timeout: float = 2.0) -> bool
- _resolve_profile_port · function · L62-L139 — async def _resolve_profile_port(db: AsyncSession, account_id) -> tuple
- apply_login_qr · function · L143-L197 — async def apply_login_qr( body: LoginQrApply, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- claim_login_qr · function · L201-L218 — async def claim_login_qr( token: str, current_user: Annotated[User, Depends(get_current_user)] = None, )
- serve_login_qr_image · function · L222-L240 — async def serve_login_qr_image(qr_key: str)
- login_scan_callback · function · L244-L267 — async def login_scan_callback( body: LoginScanCallback, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_login_status · function · L271-L282 — async def get_login_status( account_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- login_heartbeat · function · L286-L327 — async def login_heartbeat( account_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
