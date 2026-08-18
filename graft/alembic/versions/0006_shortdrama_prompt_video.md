# alembic/versions/0006_shortdrama_prompt_video.py · [[alembic-migration-chain]]

Alembic migration adding video attachment columns to shortdrama_prompts to support importing generated videos into the watermark-removal flow.

- upgrade · function · L23-L51 — Adds seven nullable video metadata columns (file name, key, bucket, size, status, error message, uploaded_at) to the shortdrama_prompts table.
- downgrade · function · L54-L61 — Removes the seven video attachment columns from shortdrama_prompts to reverse the migration.
