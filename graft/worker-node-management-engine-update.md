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
    at: 'backend/app/api/workers.py:L128-L177'
  - symbol: list_workers
    kind: function
    at: 'backend/app/api/workers.py:L181-L278'
  - symbol: get_worker
    kind: function
    at: 'backend/app/api/workers.py:L282-L294'
  - symbol: enable_worker_node
    kind: function
    at: 'backend/app/api/workers.py:L298-L314'
  - symbol: disable_worker_node
    kind: function
    at: 'backend/app/api/workers.py:L318-L334'
  - symbol: delete_worker
    kind: function
    at: 'backend/app/api/workers.py:L338-L366'
  - symbol: SetNodeCpuPercentRequest
    kind: class
    at: 'backend/app/api/workers.py:L369-L371'
  - symbol: set_worker_cpu_percent
    kind: function
    at: 'backend/app/api/workers.py:L375-L404'
  - symbol: sync_workers_from_redis
    kind: function
    at: 'backend/app/api/workers.py:L408-L488'
  - symbol: _resolve_engines_dir
    kind: function
    at: 'backend/app/api/workers.py:L513-L518'
  - symbol: _iter_engine_files
    kind: function
    at: 'backend/app/api/workers.py:L521-L533'
  - symbol: _compute_engine_version
    kind: function
    at: 'backend/app/api/workers.py:L536-L551'
  - symbol: _build_engine_archive
    kind: function
    at: 'backend/app/api/workers.py:L554-L562'
  - symbol: get_engines_status
    kind: function
    at: 'backend/app/api/workers.py:L566-L583'
  - symbol: get_engines_package
    kind: function
    at: 'backend/app/api/workers.py:L587-L607'
  - symbol: push_worker_update
    kind: function
    at: 'backend/app/api/workers.py:L611-L645'
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
