# alembic/versions/0025_slice_task_subtitle_align_mask.py · [[alembic-migration-chain]] [[slice-task-config-persistence]]

Alembic migration adding a subtitle_align_mask boolean column to slice_tasks to persist the ASR subtitle alignment-to-source-mask toggle (default True, retained on retry).

- upgrade · function · L24-L27 — Adds the subtitle_align_mask column to slice_tasks with a NOT NULL default of TRUE so existing rows get the enabled default.
- downgrade · function · L30-L31 — Removes the subtitle_align_mask column from slice_tasks to reverse the migration.
