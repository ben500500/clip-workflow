# alembic/versions/0015_doubao_progress.py · [[alembic-migration-chain]] [[short-drama-production-workflow]]

Alembic migration adding a nullable doubao_progress integer column to shortdrama_prompts so Celery tasks can report 0-100% progress for one-click Doubao generation.

- upgrade · function · L24-L28 — Adds the nullable doubao_progress integer column to the shortdrama_prompts table.
- downgrade · function · L31-L32 — Removes the doubao_progress column to roll back the migration.
