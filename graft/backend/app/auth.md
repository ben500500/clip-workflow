# backend/app/auth.py

- verify_password · function · L36-L38 — def verify_password(plain_password: str, hashed_password: str) -> bool
- get_password_hash · function · L41-L43 — def get_password_hash(password: str) -> str
- _create_jwt · function · L51-L56 — def _create_jwt(payload: dict, expires_delta: timedelta) -> str
- create_access_token · function · L59-L68 — def create_access_token(data: dict, jti: Optional[str] = None) -> str
- create_refresh_token · function · L71-L88 — def create_refresh_token(data: dict) -> tuple[str, str, datetime]
- _hash_token · function · L91-L93 — def _hash_token(token: str) -> str
- decode_token · function · L96-L115 — def decode_token(token: str, expected_type: Optional[str] = None) -> dict
- get_current_user · function · L123-L177 — async def get_current_user( credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)], db: Annotated[AsyncSession, Depends(get_db)], ) -> User
- require_roles · function · L180-L208 — def require_roles(*roles: UserRole)
- role_checker · function · L198-L206 — async def role_checker( current_user: User = Depends(get_current_user), ) -> User
- create_user_session · function · L211-L232 — async def create_user_session( db: AsyncSession, user: User, request: Request, access_jti: Optional[str] = None, ) -> UserSession
- get_role_menus · function · L284-L290 — def get_role_menus(role: str) -> list[str]
- _fernet_key_from_secret · function · L298-L301 — def _fernet_key_from_secret(secret: str) -> bytes
- encrypt_cookie · function · L304-L313 — def encrypt_cookie(plain_text: str) -> str
- decrypt_cookie · function · L316-L322 — def decrypt_cookie(cipher_text: str) -> str
