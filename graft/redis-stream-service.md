---
name: Redis Stream Service
slug: redis-stream-service
type: system
sources:
  - path: backend/app/services/redis_stream.py
    hash: 584398d379bfbb9315a93fff0be4cd64c8fc4e0a6b8595a44c8d8e74d5ef4b68
sources_digest: cf2bdc09a639ed2fbfe3618783bafd8dea0784642ca90668a5324edb0e0fd395
links:
  - to: monitoring-alerting-service
    relation: uses
    description: >-
      monitor_service reads Redis streams for queue_backlog and worker_offline
      metrics
  - to: slice-engine-orchestration
    relation: uses
    description: Publishes slice tasks that slice_service's engine subprocesses execute
generator:
  version: 1
covers:
  - symbol: _get_stream
    kind: function
    at: 'backend/app/services/redis_stream.py:L48-L58'
  - symbol: _parse_str_list
    kind: function
    at: 'backend/app/services/redis_stream.py:L61-L73'
  - symbol: get_redis
    kind: function
    at: 'backend/app/services/redis_stream.py:L82-L94'
  - symbol: reset_redis_client
    kind: function
    at: 'backend/app/services/redis_stream.py:L97-L100'
  - symbol: publish_slice_task
    kind: function
    at: 'backend/app/services/redis_stream.py:L103-L140'
  - symbol: store_task_callback_token
    kind: function
    at: 'backend/app/services/redis_stream.py:L143-L149'
  - symbol: get_task_callback_token
    kind: function
    at: 'backend/app/services/redis_stream.py:L152-L159'
  - symbol: mark_task_cancelled
    kind: function
    at: 'backend/app/services/redis_stream.py:L162-L175'
  - symbol: remove_slice_task_from_streams
    kind: function
    at: 'backend/app/services/redis_stream.py:L178-L229'
  - symbol: get_task_redis_status
    kind: function
    at: 'backend/app/services/redis_stream.py:L232-L255'
  - symbol: set_node_enabled
    kind: function
    at: 'backend/app/services/redis_stream.py:L258-L272'
  - symbol: is_node_enabled
    kind: function
    at: 'backend/app/services/redis_stream.py:L275-L284'
  - symbol: set_node_cpu_percent
    kind: function
    at: 'backend/app/services/redis_stream.py:L287-L302'
  - symbol: get_node_cpu_percent
    kind: function
    at: 'backend/app/services/redis_stream.py:L305-L317'
  - symbol: delete_worker_node
    kind: function
    at: 'backend/app/services/redis_stream.py:L320-L361'
  - symbol: get_worker_nodes_from_redis
    kind: function
    at: 'backend/app/services/redis_stream.py:L364-L490'
  - symbol: set_node_update_command
    kind: function
    at: 'backend/app/services/redis_stream.py:L493-L522'
  - symbol: get_node_update_command
    kind: function
    at: 'backend/app/services/redis_stream.py:L525-L534'
  - symbol: clear_node_update_command
    kind: function
    at: 'backend/app/services/redis_stream.py:L537-L543'
---
<!-- context:generated:start -->
## Summary

Task distribution to worker nodes via four priority streams (high, normal, low, plus a dedicated subtitle stream consumed only by Linux workers with libass). Maintains consumer groups, task status in Redis hashes with TTLs to prevent residue, and a 10,000-message stream cap. JSON payload contract with Go workers includes node capabilities and heartbeat data for offline detection.

## Related

- uses [[monitoring-alerting-service]] — monitor_service reads Redis streams for queue_backlog and worker_offline metrics
- uses [[slice-engine-orchestration]] — Publishes slice tasks that slice_service's engine subprocesses execute
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
