# backend/app/database.py · [[configuration-database-bootstrap]] [[data-isolation-rbac]]

- Base · class · L34-L35 — Declarative base class that all ORM models inherit from.
- get_db · function · L38-L48 — FastAPI dependency that yields an async session, committing on success and rolling back on exception.
- init_db · function · L51-L63 — Creates all tables and runs idempotent compatibility migrations, backfills, and wechat_download table creation on startup.
- _enforce_idle_in_transaction_timeout · function · L66-L89 — async def _enforce_idle_in_transaction_timeout()
- _backfill_data_scope · function · L92-L113 — Idempotently backfills users.data_scope for existing rows based on role, granting 'all' to admin/material/publisher and 'own' to operators.
- _backfill_drama_theaters · function · L116-L154 — async def _backfill_drama_theaters()
- _ensure_autoclip_runs_table · function · L157-L198 — Explicitly creates the autoclip_runs table (and its episode index) for old databases where create_all won't add it.
- _apply_compat_migrations · function · L201-L308 — Adds newly-introduced columns to existing tables for old-database upgrades, skipping columns that already exist.
- close_db · function · L311-L313 — Disposes the async engine to release pooled connections on shutdown.
- _ensure_wechat_download_tables · function · L315-L327 — Creates tables for the wechat_download package's independent Base metadata, which create_all on the main Base won't cover.
