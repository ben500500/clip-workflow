# alembic/versions/0016_doubao_screenshot.py · [[alembic-migration-chain]] [[short-drama-production-workflow]]

Alembic migration adding a doubao_screenshot text column to shortdrama_prompts to store the current Doubao/Seedance conversation window screenshot data URL during running state.

- upgrade · function · L23-L27 — Adds the nullable doubao_screenshot Text column to the shortdrama_prompts table.
- downgrade · function · L30-L31 — Removes the doubao_screenshot column from shortdrama_prompts to reverse the migration.
