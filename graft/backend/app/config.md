# backend/app/config.py · [[configuration-database-bootstrap]]

- _parse_origins · function · L15-L17 — Parses a comma-separated CORS origins string into a trimmed list, dropping empty entries.
- Settings · class · L20-L273 — Pydantic settings model declaring every environment variable for the backend (DB, Redis, MinIO, JWT, watermark, Seedance, wechat download, etc.) with defaults and required-field enforcement.
- _no_default_secret · method · L259-L264 — Rejects a missing or placeholder JWT_SECRET at startup to force a strong production secret in production environments.
- _cookie_key_differs · method · L268-L273 — Enforces that a configured COOKIE_ENCRYPT_KEY must differ from JWT_SECRET to avoid reusing the same key for both token signing and cookie encryption.
- _ensure_cookie_key · function · L276-L291 — Generates a persistent random cookie encryption key when none is configured, writing it to disk so it survives restarts and never falls back to JWT_SECRET.
