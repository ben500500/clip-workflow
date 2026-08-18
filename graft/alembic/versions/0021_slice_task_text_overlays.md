# alembic/versions/0021_slice_task_text_overlays.py · [[alembic-migration-chain]]

Alembic migration adding a JSON column to persist fixed-text overlay configuration on slice tasks so overlays survive retries.

- upgrade · function · L24-L27 — Adds the text_overlays_config JSON column to the slice_tasks table if it doesn't already exist.
- downgrade · function · L30-L31 — Removes the text_overlays_config column from slice_tasks to reverse the migration.
