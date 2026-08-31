# alembic/versions/0030_publish_task_dead_letter.py · [[alembic-migration-chain]] [[publishing-video-account-matrix]]

Alembic migration adding retry_count, dead_letter, and dead_letter_reason columns to publish_tasks so failed publishes can be retried and dead-lettered instead of silently lost.

- upgrade · function · L28-L40 — Adds the three new publish_tasks columns (retry_count, dead_letter, dead_letter_reason) with backward-compatible defaults so existing rows remain valid.
- downgrade · function · L43-L46 — Rolls back the migration by dropping the three added columns in reverse order.
