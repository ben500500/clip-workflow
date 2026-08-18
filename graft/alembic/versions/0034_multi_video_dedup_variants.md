# alembic/versions/0034_multi_video_dedup_variants.py · [[alembic-migration-chain]]

Alembic migration adding the multi-video dedup data layer: new clip_variants and video_fingerprints tables plus variant columns on existing tables, with a rollback-capable downgrade.

- upgrade · function · L29-L94 — Creates the clip_variants and video_fingerprints tables and extends slice_outputs, publications, and slice_tasks with variant columns to support per-account dedup variants.
- downgrade · function · L97-L104 — Rolls back the migration by dropping the new variant columns and tables in reverse dependency order.
