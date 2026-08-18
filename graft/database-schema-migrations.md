---
name: Database Schema & Migrations
slug: database-schema-migrations
type: system
sources:
  - path: init.sql
    hash: b48db092e06361365f81bf13373aa159a4ea23720f7c5fa350ddcbd90661a3c5
  - path: migrations/fix_missing_indexes.sql
    hash: 6f012faf18a694d4a80a1cd9c8f3d4c05902527bb58ee5d561bc2c520784dbc4
  - path: scripts/db_sync_columns.py
    hash: 38f9cd038d661f97525e76e03f7364e4d7e4d6c20c60773b66b012a46f43a6a8
sources_digest: 70384877b5cbefeb996d7f51f2adcf673999c394d0e0ae35ffeaacb8c80f8d0c
links:
  - to: deployment-ops-scripts
    relation: uses
    description: >-
      deploy_server.sh runs db_sync_columns.py post-deploy to repair schema
      drift.
generator:
  version: 1
covers:
  - symbol: main
    kind: function
    at: 'scripts/db_sync_columns.py:L29-L67'
---
<!-- context:generated:start -->
## Summary

init.sql pre-creates extension tables (auth, collaboration, media, autoclip, celery, notifications, system_configs) with UUID PKs and CHECK constraints, deliberately omitting FKs to ORM-managed tables to avoid schema conflicts. A faulty CREATE INDEX referencing nonexistent users.email aborted the whole script under ON_ERROR_STOP=1, leaving 27 business indexes uncreated and causing 30-second dashboard timeouts; fix_missing_indexes.sql retroactively creates them with CREATE INDEX CONCURRENTLY IF NOT EXISTS (must run via psql -f outside a transaction block). db_sync_columns.py repairs column drift when Alembic silently skips new columns (e.g., slice_tasks.subtitle_mask_config) after a DuplicateTableError, adding columns without NOT NULL to avoid failing on historical rows.

## Related

- uses [[deployment-ops-scripts]] — deploy_server.sh runs db_sync_columns.py post-deploy to repair schema drift.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
