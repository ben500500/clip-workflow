# alembic/versions/0035_slice_task_cover_image.py · [[alembic-migration-chain]] [[slice-task-config-persistence]]

Alembic migration adding a nullable cover_image_key column to slice_tasks so slice configs can overlay a static cover image as the video's first frame.

- upgrade · function · L26-L27 — Adds the nullable cover_image_key column to the slice_tasks table to persist the cover image MinIO key.
- downgrade · function · L30-L31 — Rolls back the migration by dropping the cover_image_key column from slice_tasks.
