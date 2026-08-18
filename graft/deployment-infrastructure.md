---
name: Deployment & Infrastructure
slug: deployment-infrastructure
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
  - to: video-processing-engines
    relation: configures
    description: >-
      sync-engines-to-worker.sh copies engine files into the slice-worker build
      context
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

One-click deployment scripts and Docker Compose orchestration. deploy.sh runs the full lifecycle (prereq checks, optional GPU overlay, .env creation, engine sync into worker build context, parallel build, health checks polling Nginx/API/Postgres/Redis/MinIO) with tolerance for missing components. deploy_remote_worker.sh provisions remote Slice Worker nodes in Docker or bare-metal mode, auto-detecting architecture and retrieving Redis password via SSH to the server's .env. init.sql pre-creates extension tables while deliberately avoiding ORM-managed business tables to prevent schema conflicts.

## Related

- configures [[video-processing-engines]] — sync-engines-to-worker.sh copies engine files into the slice-worker build context
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
