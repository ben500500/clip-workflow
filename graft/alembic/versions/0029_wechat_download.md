# alembic/versions/0029_wechat_download.py · [[alembic-migration-chain]] [[wechat-download-drama-management]]

Alembic migration adding three wechat_download tables (tasks, source auths, parse records) plus an episodes.source_url column to support WeChat video material import/download, designed to be independently strippable.

- upgrade · function · L31-L92 — Creates the wechat_download_tasks, wechat_source_auths, and wechat_parse_records tables with indexes, and adds the episodes.source_url glue column for source traceability.
- downgrade · function · L95-L104 — Rolls back the migration by dropping the episodes.source_url column, all indexes, and the three wechat_download tables in reverse dependency order.
