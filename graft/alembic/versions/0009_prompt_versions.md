# alembic/versions/0009_prompt_versions.py · [[alembic-migration-chain]]

Alembic migration adding prompt_long and prompt_short columns to shortdrama_prompts to support three-version prompts (long/short fixed templates plus AI-generated Seedance prompt).

- upgrade · function · L25-L33 — Adds the nullable prompt_long and prompt_short text columns to the shortdrama_prompts table.
- downgrade · function · L36-L38 — Removes the prompt_short and prompt_long columns to reverse the migration.
