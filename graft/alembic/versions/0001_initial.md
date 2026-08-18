# alembic/versions/0001_initial.py · [[alembic-migration-chain]]

Alembic migration that adds the phase-2/3 schema structures (user_sessions, audit_logs, alert_rules, alert_events) on top of ORM-created business tables.

- upgrade · function · L25-L99 — Creates the four new tables (user_sessions, audit_logs, alert_rules, alert_events) with their indexes, leaving video_metrics.tags to be added idempotently by init_db().
- downgrade · function · L102-L106 — Rolls back the migration by dropping the four tables in reverse dependency order.
