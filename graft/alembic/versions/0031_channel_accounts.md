# alembic/versions/0031_channel_accounts.py · [[alembic-migration-chain]] [[multi-operator-rbac-audit]] [[publishing-video-account-matrix]]

Alembic migration adding channel_accounts ledger and channel_operators sub-tables to decouple video-account business/cooperation info from the publish channel, with a CHECK constraint requiring operator identity.

- upgrade · function · L28-L70 — Creates the channel_accounts ledger table with cooperation-mode JSON and soft video_account link, plus the channel_operators sub-table enforcing that each operator has either a user FK or a hand-filled name.
- downgrade · function · L73-L75 — Rolls back the migration by dropping the two newly created tables in reverse dependency order.
