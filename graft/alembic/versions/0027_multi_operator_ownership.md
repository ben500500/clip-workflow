# alembic/versions/0027_multi_operator_ownership.py · [[alembic-migration-chain]] [[multi-operator-rbac-audit]] [[publishing-video-account-matrix]]

Alembic migration adding multi-operator ownership fields (created_by/operator_id) to video_accounts, publish_profiles, and publish_tasks, plus the new publish_batches table, to support RBAC own/all data isolation and batch-level publish allocation.

- upgrade · function · L31-L122 — Adds ownership and graduation columns to existing tables and creates the publish_batches table with indexes and a batch foreign key, all idempotently with DEFAULT NULL to avoid table locks.
- downgrade · function · L125-L151 — Reverses the migration by dropping the batch foreign key, batch_id/operator_id columns, the publish_batches table, and all ownership/graduation columns from the affected tables.
