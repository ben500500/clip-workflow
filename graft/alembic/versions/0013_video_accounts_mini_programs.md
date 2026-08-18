# alembic/versions/0013_video_accounts_mini_programs.py · [[alembic-migration-chain]]

Alembic migration adding video_accounts and mini_programs tables plus publish_tasks/video_metrics/publish_materials columns for the video account matrix and short-video analysis feature.

- upgrade · function · L28-L89 — Creates the video_accounts and mini_programs tables and adds foreign-key columns linking publish_tasks, video_metrics, and publish_materials to the new account/mini-program/source entities.
- downgrade · function · L92-L102 — Reverses the migration by dropping the added columns and tables in reverse dependency order.
