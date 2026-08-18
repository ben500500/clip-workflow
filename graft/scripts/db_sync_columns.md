# scripts/db_sync_columns.py · [[database-schema-migration-tooling]]

Post-deploy script that reconciles SQLAlchemy ORM model columns with the actual database schema by ALTER TABLE ADD COLUMN for missing columns, skipping whole missing tables for alembic to create.

- main · function · L29-L67 — Connects to the database, iterates all ORM tables, and adds any columns missing from the live schema using idempotent ALTER TABLE ADD COLUMN IF NOT EXISTS statements.
