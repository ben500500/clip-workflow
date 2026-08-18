---
name: Celery Task Queue
slug: celery-task-queue
type: file
sources:
  - path: autoclip/app/celery_app.py
    hash: 327c7f58746649147016e97778b9a3c9cab81dc3a61900fb64c5f73210e8dab9
sources_digest: e6c6e40268f1bb76c731893de2effaa09526ba57f7b58c5c8e71dcdfcb9cd0ce
links:
  - to: alembic-migration-chain
    relation: uses
    description: >-
      Migrations 0002, 0004, 0015, 0016, 0029 add tables/columns (autoclip_runs,
      watermark_tasks, doubao_progress, doubao_screenshot,
      wechat_download_tasks) that Celery tasks write to.
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

Central Celery app configured with Redis broker/result backend from env vars, JSON serialization, Asia/Shanghai timezone. Serves as the dispatch point for async tasks like autoclip runs, Doubao generation progress callbacks, and watermark removal.

## Related

- uses [[alembic-migration-chain]] — Migrations 0002, 0004, 0015, 0016, 0029 add tables/columns (autoclip_runs, watermark_tasks, doubao_progress, doubao_screenshot, wechat_download_tasks) that Celery tasks write to.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
