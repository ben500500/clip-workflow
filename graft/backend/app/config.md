# backend/app/config.py · [[configuration-database-bootstrap]]

- _parse_origins · function · L15-L17 — def _parse_origins(raw: str) -> list[str]
- Settings · class · L20-L223 — class Settings(BaseSettings): # Database # 必填：必须通过 .env / 环境变量注入，缺失时启动即报错 # 示例：postgresql+asyncpg://user:password@host:5432/dbname
- _no_default_secret · method · L209-L214 — def _no_default_secret(cls, v: str) -> str
- _cookie_key_differs · method · L218-L223 — def _cookie_key_differs(cls, v: str, info) -> str: # 若配置了 COOKIE_ENCRYPT_KEY，则不能与 JWT_SECRET 相同
- _ensure_cookie_key · function · L226-L241 — def _ensure_cookie_key() -> str
