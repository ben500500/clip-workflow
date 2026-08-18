# alembic/versions/0005_shortdrama_prompts.py · [[alembic-migration-chain]]

Alembic migration adding the shortdrama_prompts table to persist Seedance prompt generation history for the short-drama production workflow.

- upgrade · function · L24-L38 — Creates the shortdrama_prompts table storing source text, generation parameters, and resulting Seedance prompt, plus an index on created_at.
- downgrade · function · L41-L43 — Reverses the migration by dropping the created_at index and the shortdrama_prompts table.
