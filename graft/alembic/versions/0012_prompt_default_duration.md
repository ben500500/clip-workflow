# alembic/versions/0012_prompt_default_duration.py · [[alembic-migration-chain]]

Alembic migration adding a per-user default prompt-generation duration (seconds) column to the users table, so a user's chosen duration (10s/15s/20s/25s/30s/custom) persists as their default.

- upgrade · function · L24-L28 — Adds the nullable integer prompt_default_duration column to the users table to persist each user's default prompt-generation duration.
- downgrade · function · L31-L32 — Removes the prompt_default_duration column from the users table to reverse the migration.
