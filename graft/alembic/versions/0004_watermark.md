# alembic/versions/0004_watermark.py · [[alembic-migration-chain]]

Alembic migration adding watermark_tasks and watermark_videos tables to support the v4 batch watermark-removal feature with async execution, progress tracking, history, and resource cleanup.

- upgrade · function · L24-L60 — Creates the watermark_tasks and watermark_videos tables with progress/count tracking columns and a task_id index for batch watermark-removal jobs.
- downgrade · function · L63-L66 — Rolls back the migration by dropping the task_id index and both watermark tables.
