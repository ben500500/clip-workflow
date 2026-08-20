---
name: Worker Node Management & Engine Update
slug: worker-node-management-engine-update
type: system
sources:
  - path: backend/app/api/workers.py
    hash: 0e4103875c0c286fc84bdb116b182af5513d9127d3cb26e85f6d3fc06afe0ec6
sources_digest: c82459be5b33dff05207d07ec6f6b4311e2b0b3c7d5075e88af63e2043ebf5dc
links:
  - to: engine-execution-layer
    relation: uses
    description: >-
      push_worker_update hashes the engines/ directory contents that the engine
      runners execute
  - to: redis-streams-real-time-state
    relation: uses
    description: get_worker_nodes_from_redis merges live heartbeat data with DB records
generator:
  version: 1
covers:
  - symbol: WorkerNodeResponse
    kind: class
    at: 'backend/app/api/workers.py:L47-L77'
  - symbol: WorkerHeartbeatRequest
    kind: class
    at: 'backend/app/api/workers.py:L80-L97'
  - symbol: _serialize_node
    kind: function
    at: 'backend/app/api/workers.py:L100-L124'
  - symbol: worker_heartbeat
    kind: function
    at: 'backend/app/api/workers.py:L128-L185'
  - symbol: list_workers
    kind: function
    at: 'backend/app/api/workers.py:L189-L286'
  - symbol: get_worker
    kind: function
    at: 'backend/app/api/workers.py:L290-L302'
  - symbol: enable_worker_node
    kind: function
    at: 'backend/app/api/workers.py:L306-L322'
  - symbol: disable_worker_node
    kind: function
    at: 'backend/app/api/workers.py:L326-L342'
  - symbol: _NodeEnabledPatch
    kind: class
    at: 'backend/app/api/workers.py:L345-L347'
  - symbol: set_worker_enabled
    kind: function
    at: 'backend/app/api/workers.py:L351-L376'
  - symbol: delete_worker
    kind: function
    at: 'backend/app/api/workers.py:L380-L408'
  - symbol: SetNodeCpuPercentRequest
    kind: class
    at: 'backend/app/api/workers.py:L411-L413'
  - symbol: set_worker_cpu_percent
    kind: function
    at: 'backend/app/api/workers.py:L417-L446'
  - symbol: sync_workers_from_redis
    kind: function
    at: 'backend/app/api/workers.py:L450-L530'
  - symbol: _resolve_engines_dir
    kind: function
    at: 'backend/app/api/workers.py:L555-L560'
  - symbol: _iter_engine_files
    kind: function
    at: 'backend/app/api/workers.py:L563-L575'
  - symbol: _compute_engine_version
    kind: function
    at: 'backend/app/api/workers.py:L578-L593'
  - symbol: _build_engine_archive
    kind: function
    at: 'backend/app/api/workers.py:L596-L604'
  - symbol: get_engines_status
    kind: function
    at: 'backend/app/api/workers.py:L608-L625'
  - symbol: get_engines_package
    kind: function
    at: 'backend/app/api/workers.py:L629-L649'
  - symbol: push_worker_update
    kind: function
    at: 'backend/app/api/workers.py:L653-L687'
---
<!-- context:generated:start -->
## Summary

Bridges SQLAlchemy WorkerNode persistence with Redis-backed live state, exposing admin and internal heartbeat routers. Redis is the source of truth for runtime state (enabled, cpu_percent, encoder caps) while PostgreSQL persists registration; engine updates are pushed as SHA256 version hashes of engines/ dir with workers pulling tar.gz on heartbeat. Normalizes timestamps to naive UTC to avoid asyncpg offset-aware errors.

## Related

- uses [[engine-execution-layer]] — push_worker_update hashes the engines/ directory contents that the engine runners execute
- uses [[redis-streams-real-time-state]] — get_worker_nodes_from_redis merges live heartbeat data with DB records
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
