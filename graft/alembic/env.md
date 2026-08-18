# alembic/env.py · [[alembic-migration-chain]]

Alembic migration environment that injects the app's async DATABASE_URL and runs migrations against the ORM metadata.

- run_migrations_offline · function · L36-L47 — Runs migrations in offline mode by emitting SQL with literal binds instead of connecting to a database.
- do_run_migrations · function · L50-L54 — Configures the migration context on a live connection and executes pending migrations within a transaction.
- run_async_migrations · function · L57-L68 — Builds an async engine from config and runs migrations synchronously on the connection via run_sync.
- run_migrations_online · function · L71-L73 — Entry point that drives the async migration loop from the synchronous online-mode path.
