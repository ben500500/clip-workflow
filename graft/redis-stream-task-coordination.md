---
name: Redis Stream Task Coordination
slug: redis-stream-task-coordination
type: system
sources:
  - path: backend/app/services/redis_stream.py
    hash: 10ee017b50e40dd3f273ca06681f120e726a450097e777a6e26d1862ff53925e
sources_digest: 50d7d8e12ed5a13b58278673b7051b3c405a684e87fb152110cf5e543ef7f1bc
links:
  - to: slice-engine-orchestration
    relation: produces
    description: >-
      Publishes slice tasks that the Go workers consume and execute via the
      slice engine
  - to: video-publishing-pipeline
    relation: uses
    description: Provides the Redis-backed pending state that publish_service persists to
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
  - symbol: get_task_redis_status
    kind: function
    at: 'backend/app/services/redis_stream.py:L178-L201'
  - symbol: set_node_enabled
    kind: function
    at: 'backend/app/services/redis_stream.py:L204-L218'
  - symbol: is_node_enabled
    kind: function
    at: 'backend/app/services/redis_stream.py:L221-L230'
  - symbol: set_node_cpu_percent
    kind: function
    at: 'backend/app/services/redis_stream.py:L233-L248'
  - symbol: get_node_cpu_percent
    kind: function
    at: 'backend/app/services/redis_stream.py:L251-L263'
  - symbol: delete_worker_node
    kind: function
    at: 'backend/app/services/redis_stream.py:L266-L307'
  - symbol: get_worker_nodes_from_redis
    kind: function
    at: 'backend/app/services/redis_stream.py:L310-L436'
  - symbol: set_node_update_command
    kind: function
    at: 'backend/app/services/redis_stream.py:L439-L468'
  - symbol: get_node_update_command
    kind: function
    at: 'backend/app/services/redis_stream.py:L471-L480'
  - symbol: clear_node_update_command
    kind: function
    at: 'backend/app/services/redis_stream.py:L483-L489'
---
<!-- context:generated:start -->
## Summary

The Redis Stream service layer coordinating task distribution and worker node management between the backend API and Go worker processes. Publishes slice tasks to priority-based streams (high/normal/low) plus a dedicated subtitle stream consumed only by Linux workers with libass-enabled ffmpeg, preventing Mac workers from failing on subtitle burn-in. Maintains a lazy singleton Redis client, defines key prefixes shared with Go workers, and handles Redis errors defensively returning None/empty on failures.

## Related

- produces [[slice-engine-orchestration]] — Publishes slice tasks that the Go workers consume and execute via the slice engine
- uses [[video-publishing-pipeline]] — Provides the Redis-backed pending state that publish_service persists to
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
