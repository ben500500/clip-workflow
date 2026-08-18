# alembic/versions/0008_data_scope.py · [[alembic-migration-chain]] [[multi-operator-rbac-audit]]

Alembic migration adding data isolation columns (users.data_scope and projects.created_by) to enforce the second-phase data isolation scheme where admins/material/publisher roles see all materials while operators only see their own.

- upgrade · function · L28-L47 — Adds data_scope and created_by columns, then backfills existing users' data_scope based on role so admin/material/publisher get 'all' and everyone else defaults to 'own'.
- downgrade · function · L50-L53 — Reverses the migration by dropping the created_by index, created_by column, and data_scope column.
