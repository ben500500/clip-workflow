# alembic/versions/0020_slice_task_subtitle.py · [[alembic-migration-chain]] [[slice-task-config-persistence]]

Alembic migration adding a subtitle_config JSON column to slice_tasks to persist per-task subtitle settings across retries.

- upgrade · function · L24-L27 — Adds the subtitle_config JSON column to slice_tasks if it does not already exist.
- downgrade · function · L30-L31 — Removes the subtitle_config column from slice_tasks to reverse the migration.
