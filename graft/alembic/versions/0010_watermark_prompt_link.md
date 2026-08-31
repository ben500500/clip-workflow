# alembic/versions/0010_watermark_prompt_link.py · [[alembic-migration-chain]] [[short-drama-production-workflow]]

Alembic migration adding a prompt_record_id column to watermark_videos to link watermark-removal tasks to their source prompt records, enabling automatic copy carry-over when publishing material.

- upgrade · function · L26-L35 — Adds a nullable prompt_record_id UUID column to watermark_videos and an index on it to support task-to-prompt association lookups.
- downgrade · function · L38-L40 — Reverses the migration by dropping the prompt_record_id index and column from watermark_videos.
