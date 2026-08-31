# alembic/versions/0036_drama_management.py · [[alembic-migration-chain]] [[wechat-download-drama-management]]

Alembic migration adding four new tables (dramas, drama_stills, drama_accounts, drama_materials) to support drama management for the video account auto-publish feature (ISSUE #130).

- upgrade · function · L32-L104 — Creates the four drama-management tables with their indexes, guarding each creation behind an existence check so the migration is idempotent.
- downgrade · function · L107-L111 — Rolls back the migration by dropping the four drama tables in reverse dependency order.
