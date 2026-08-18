---
name: Deployment & Operations
slug: deployment-operations
type: system
sources:
  - path: deploy_remote_worker.sh
    hash: dfe8a086e1054b2df6b0ffef53a0f04d7c1523cc9fafd165bd797b86598fb706
  - path: deploy.sh
    hash: a0d335ee8a45a766f452621d57dec45cb605c168df49f6aef7e7014bcdf6e5ef
  - path: deploy/cmd.sh
    hash: 6a95daf21a9a2d141a0777786fbf3bfb83f99000523228ebe79ac44843381584
  - path: deploy/init.sql
    hash: ba9afcece93aced5d97a9891524e7097f1f7bde62ff9cf29f522c891d0a05fd6
sources_digest: 1d3ae6f02bf577af4d950f37d926e25caca9b11ed76d92b52129aa5b9d4bed02
links:
  - to: redis-stream-task-coordination
    relation: configures
    description: >-
      deploy_remote_worker.sh configures Redis URL, backend URL, concurrency
      limits, and CPU percentage for worker nodes
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

Deployment scripts and infrastructure for the Clip Workflow platform. deploy.sh orchestrates the full lifecycle (prereq checks, .env creation, image builds, service startup, health checks) with tolerance for missing components. deploy_remote_worker.sh automates one-click deployment of remote Slice Worker nodes in Docker or bare-metal modes, handling node ID generation, network validation, and Redis password retrieval. deploy/init.sql pre-creates extension tables (users, OAuth, collaboration, media assets, clip tasks, AutoClip, Celery tracking, notifications, configs) deliberately avoiding business tables the ORM manages, with UUID PKs, JSONB columns, and check constraints.

## Related

- configures [[redis-stream-task-coordination]] — deploy_remote_worker.sh configures Redis URL, backend URL, concurrency limits, and CPU percentage for worker nodes
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
