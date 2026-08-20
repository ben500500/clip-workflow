# backend/app/database.py · [[configuration-database-bootstrap]] [[data-isolation-rbac]]

- Base · class · L34-L35 — class Base(DeclarativeBase)
- get_db · function · L38-L48 — async def get_db() -> AsyncSession
- init_db · function · L51-L62 — async def init_db()
- _enforce_idle_in_transaction_timeout · function · L65-L88 — async def _enforce_idle_in_transaction_timeout()
- _backfill_data_scope · function · L91-L112 — async def _backfill_data_scope()
- _ensure_autoclip_runs_table · function · L115-L156 — async def _ensure_autoclip_runs_table()
- _apply_compat_migrations · function · L159-L257 — async def _apply_compat_migrations()
- close_db · function · L260-L262 — async def close_db()
- _ensure_wechat_download_tables · function · L264-L276 — async def _ensure_wechat_download_tables()
