---
name: Deployment & Ops Scripts
slug: deployment-ops-scripts
type: system
sources:
  - path: scripts/deploy_server.sh
    hash: 3b80f76642b435437346aabe0738baf8bbb3789c076d8d8cf5ce0be951d8a9d9
  - path: scripts/healthcheck.sh
    hash: 0abc45283bf40525c9ade41842f4e8b55a766e4dc51fe564149d937d9684df2c
  - path: scripts/init_admin.sh
    hash: f832237c09e415c6dda01fb6e54d068f7c52a0680e1ed028f46a633887a2f614
  - path: scripts/init.sh
    hash: ee2b68250450e9f588a8837570cb7c8fc7d18e721817531874944b49fd990b91
  - path: scripts/logs.sh
    hash: d92bcf93e032d2422640ce07279b292fbfd13864447cf1ecbf8446d71f6e5920
  - path: scripts/restart.sh
    hash: 78e9977a5689ceb7a1feec3f8bbf0f64435883156deb8b8bfd7fbbb16df2e156
  - path: scripts/server-setup.sh
    hash: ec7a55b6eba273e5862a08bdabd7453a1c2fa223885b150d603cb9dc52901ce4
sources_digest: e42b5e7e3d867ab4b8a581e92cf62a149e8681fe6477114e215c1325d26b95bc
links:
  - to: database-schema-migrations
    relation: uses
    description: >-
      deploy_server.sh invokes db_sync_columns.py; healthcheck.sh queries the DB
      for detect_task_id column.
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

The operational shell-script layer: deploy_server.sh syncs code via tar-pipe (whole-directory to avoid breaking Go compilation), rebuilds only affected containers based on git diff, and runs db_sync_columns.py post-deploy. init.sh bootstraps a fresh checkout (directory tree, engine scan, .env from .env.example, Docker checks). init_admin.sh temporarily flips DEBUG on to seed the first admin since production registration requires an existing admin, then restores config and removes plaintext credentials. server-setup.sh is the one-shot Alibaba Cloud provisioner (--skip-rpa default). restart.sh, logs.sh, healthcheck.sh are operational conveniences; healthcheck.sh hardcodes container names and requires the videos dir to be 777 for batch deletion.

## Related

- uses [[database-schema-migrations]] — deploy_server.sh invokes db_sync_columns.py; healthcheck.sh queries the DB for detect_task_id column.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
