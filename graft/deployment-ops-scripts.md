---
name: Deployment & Ops Scripts
slug: deployment-ops-scripts
type: system
sources:
  - path: scripts/cleanup_orphans.py
    hash: 6253490f6ff0ebc20eba9e5c10fef30d6ba802d26087d8d4d1085b0f42f10856
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
  - path: scripts/start.sh
    hash: 01e2d2f4c7ba684f76cf41f2df6fa0297c9eb8540d1b64634614148d1f9915e0
  - path: scripts/status.sh
    hash: 2ad2b1e0c9a2ff6552d5e4026d5144aa93d88a705edfe43dd71e66617dd16ead
  - path: scripts/stop.sh
    hash: f89859a999e45532881b19fa8e8e3440113fb45851dc85e64340fb93e5a4b3ee
sources_digest: 4165967e0d00818e3eb38ce82d2a32fc6cf8df1e58ca6dd9627f87a4fd86d2f1
links:
  - to: database-schema-migration-tooling
    relation: uses
    description: >-
      deploy_server.sh invokes db_sync_columns.py; healthcheck.sh queries the
      database for schema columns.
  - to: docker-compose-stack-contract
    relation: depends_on
    description: >-
      All scripts assume the docker-compose.yml service names and
      NGINX_PORT/MINIO_CONSOLE_PORT env vars; logs.sh's hardcoded 13-service
      list must stay in sync with compose definitions.
  - to: slice-worker-node
    relation: configures
    description: >-
      server-setup.sh optionally provisions the slice-worker service and
      init_admin.sh creates the admin account.
generator:
  version: 1
covers:
  - symbol: human_size
    kind: function
    at: 'scripts/cleanup_orphans.py:L49-L55'
  - symbol: media_path_size
    kind: function
    at: 'scripts/cleanup_orphans.py:L58-L75'
  - symbol: _collect_valid
    kind: function
    at: 'scripts/cleanup_orphans.py:L78-L102'
  - symbol: _scan_raw
    kind: function
    at: 'scripts/cleanup_orphans.py:L105-L113'
  - symbol: _scan_sliced
    kind: function
    at: 'scripts/cleanup_orphans.py:L116-L128'
  - symbol: _scan_media
    kind: function
    at: 'scripts/cleanup_orphans.py:L131-L158'
  - symbol: _remove_media
    kind: function
    at: 'scripts/cleanup_orphans.py:L161-L173'
  - symbol: main
    kind: function
    at: 'scripts/cleanup_orphans.py:L176-L246'
---
<!-- context:generated:start -->
## Summary

Operational shell/Python scripts for the production server: deploy_server.sh syncs code via tar-pipe and rebuilds only affected containers based on git diff, then runs db_sync_columns.py; healthcheck.sh verifies all components (containers, API endpoints, videos dir 777 permissions, fontTools/SC font in slice worker, detect_task_id column, Redis queue lengths, ollama/MiniCPM-V); init_admin.sh bootstraps the first admin by temporarily enabling DEBUG and injecting a seed user then restoring config; cleanup_orphans.py removes storage objects with no DB record (dry-run by default).

## Related

- uses [[database-schema-migration-tooling]] — deploy_server.sh invokes db_sync_columns.py; healthcheck.sh queries the database for schema columns.
- depends on [[docker-compose-stack-contract]] — All scripts assume the docker-compose.yml service names and NGINX_PORT/MINIO_CONSOLE_PORT env vars; logs.sh's hardcoded 13-service list must stay in sync with compose definitions.
- configures [[slice-worker-node]] — server-setup.sh optionally provisions the slice-worker service and init_admin.sh creates the admin account.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
