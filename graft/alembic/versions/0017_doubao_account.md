# alembic/versions/0017_doubao_account.py · [[alembic-migration-chain]]

Alembic migration adding a nullable doubao_account column to shortdrama_prompts to store the currently logged-in Doubao account nickname for frontend display.

- upgrade · function · L23-L27 — Adds the nullable doubao_account string column to the shortdrama_prompts table.
- downgrade · function · L30-L31 — Removes the doubao_account column from shortdrama_prompts to reverse the migration.
