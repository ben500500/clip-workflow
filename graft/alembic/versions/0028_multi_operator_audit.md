# alembic/versions/0028_multi_operator_audit.py · [[alembic-migration-chain]] [[multi-operator-rbac-audit]]

Alembic migration adding four new audit/risk tables (publish_audits, login_audits, cookie_access_logs, risk_events) to support multi-operator observability and risk-graduation statistics for the WeChat Channels publishing flow.

- upgrade · function · L31-L135 — Creates the four audit tables with their indexes, guarded by existence checks so the migration is idempotent and backward-compatible.
- downgrade · function · L138-L144 — Drops the four audit tables created by upgrade, iterating over them and removing only those that exist.
