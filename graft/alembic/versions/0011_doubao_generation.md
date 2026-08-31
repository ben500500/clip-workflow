# alembic/versions/0011_doubao_generation.py · [[alembic-migration-chain]] [[short-drama-production-workflow]]

Alembic migration adding Doubao (豆包) one-click generation fields to users and shortdrama_prompts tables for the short-drama production feature.

- upgrade · function · L29-L74 — Adds users.doubao_account_type (default 'free') and ten Doubao generation task columns to shortdrama_prompts to support the one-click Doubao generation workflow.
- downgrade · function · L77-L87 — Reverses the migration by dropping all Doubao generation columns from shortdrama_prompts and users.
