---
name: Redis Streams & Real-time State
slug: redis-streams-real-time-state
type: concept
sources:
  - path: backend/app/api/workers.py
    hash: 0e4103875c0c286fc84bdb116b182af5513d9127d3cb26e85f6d3fc06afe0ec6
  - path: backend/app/services/batch_decoupled_service.py
    hash: 05649e2ec4b11377e6b4db183671fd5a63dddcd77ec78779ec0a66dd22accf96
  - path: backend/app/services/dashboard_service.py
    hash: ff9135570eb6a597a9f1e17ac89539f39edfb8757d6a4f06206a66cd32c8c684
  - path: backend/app/services/login_qr_service.py
    hash: 386d7ed87b9bf35df0214242062d2d486ecbc6bdbefc83b8b762678b4f363dd6
sources_digest: 66671268142f2d791aa4dd63371b63fb033cbc17ff64949e8bd3fe969b4f99e2
links:
  - to: batch-slicing-workflow
    relation: uses
    description: Redis Streams carry slice tasks to Go workers
  - to: worker-node-management-engine-update
    relation: uses
    description: get_worker_nodes_from_redis merges live state with DB
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
  - symbol: _get_batch
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L56-L64'
  - symbol: _load_items
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L67-L77'
  - symbol: _load_item
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L80-L88'
  - symbol: _update_item
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L91-L96'
  - symbol: _update_batch
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L99-L104'
  - symbol: _get_operator
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L107-L116'
  - symbol: _resolve_project
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L119-L137'
  - symbol: run_batch_decoupled
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L143-L200'
  - symbol: process_selection
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L206-L260'
  - symbol: dispatch_ready_slices
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L266-L342'
  - symbol: finalize_slices
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L348-L424'
  - symbol: aggregate_batches
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L430-L498'
  - symbol: _cache_key
    kind: function
    at: 'backend/app/services/dashboard_service.py:L41-L48'
  - symbol: _get_cached_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L51-L62'
  - symbol: _set_cached_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L65-L78'
  - symbol: _get_cached_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L81-L92'
  - symbol: _get_snapshot_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L95-L106'
  - symbol: _with_cache
    kind: function
    at: 'backend/app/services/dashboard_service.py:L109-L131'
  - symbol: get_overview
    kind: function
    at: 'backend/app/services/dashboard_service.py:L134-L145'
  - symbol: _compute_overview
    kind: function
    at: 'backend/app/services/dashboard_service.py:L148-L241'
  - symbol: get_video_ranking
    kind: function
    at: 'backend/app/services/dashboard_service.py:L244-L296'
  - symbol: get_funnel
    kind: function
    at: 'backend/app/services/dashboard_service.py:L299-L312'
  - symbol: _compute_funnel
    kind: function
    at: 'backend/app/services/dashboard_service.py:L315-L415'
  - symbol: get_trend
    kind: function
    at: 'backend/app/services/dashboard_service.py:L418-L434'
  - symbol: _compute_trend
    kind: function
    at: 'backend/app/services/dashboard_service.py:L437-L542'
  - symbol: _redis
    kind: function
    at: 'backend/app/services/login_qr_service.py:L57-L60'
  - symbol: issue_claim
    kind: function
    at: 'backend/app/services/login_qr_service.py:L63-L76'
  - symbol: verify_claim_token
    kind: function
    at: 'backend/app/services/login_qr_service.py:L79-L85'
  - symbol: capture_login_qr
    kind: function
    at: 'backend/app/services/login_qr_service.py:L88-L152'
  - symbol: store_qr
    kind: function
    at: 'backend/app/services/login_qr_service.py:L155-L171'
  - symbol: encrypt_cookie_bytes
    kind: function
    at: 'backend/app/services/login_qr_service.py:L174-L180'
  - symbol: decrypt_cookie_bytes
    kind: function
    at: 'backend/app/services/login_qr_service.py:L183-L189'
  - symbol: get_qr_presigned_url
    kind: function
    at: 'backend/app/services/login_qr_service.py:L192-L195'
  - symbol: set_login_state
    kind: function
    at: 'backend/app/services/login_qr_service.py:L198-L209'
  - symbol: get_login_state
    kind: function
    at: 'backend/app/services/login_qr_service.py:L212-L215'
  - symbol: check_login_status_via_cdp
    kind: function
    at: 'backend/app/services/login_qr_service.py:L218-L255'
  - symbol: silent_keepalive
    kind: function
    at: 'backend/app/services/login_qr_service.py:L258-L281'
---
<!-- context:generated:start -->
## Summary

Redis is the source of truth for runtime state across the system: worker heartbeats, login QR state machines, dashboard metric caching (30s TTL with hourly snapshot fallback), and Go worker task dispatch via Redis Streams. Nodes can appear only in Redis (new registrations) or only in DB (marked offline); the API merges both views.

## Related

- uses [[batch-slicing-workflow]] — Redis Streams carry slice tasks to Go workers
- uses [[worker-node-management-engine-update]] — get_worker_nodes_from_redis merges live state with DB
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
