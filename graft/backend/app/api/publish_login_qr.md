# backend/app/api/publish_login_qr.py

- LoginQrApply · class · L28-L30 — class LoginQrApply(BaseModel)
- LoginScanCallback · class · L33-L39 — class LoginScanCallback(BaseModel)
- _resolve_profile_port · function · L42-L75 — async def _resolve_profile_port(db: AsyncSession, account_id) -> tuple
- apply_login_qr · function · L79-L133 — async def apply_login_qr( body: LoginQrApply, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- claim_login_qr · function · L137-L155 — async def claim_login_qr( token: str, current_user: Annotated[User, Depends(get_current_user)] = None, )
- login_scan_callback · function · L159-L182 — async def login_scan_callback( body: LoginScanCallback, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_login_status · function · L186-L197 — async def get_login_status( account_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- login_heartbeat · function · L201-L236 — async def login_heartbeat( account_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
