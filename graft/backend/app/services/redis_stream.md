# backend/app/services/redis_stream.py · [[redis-stream-task-coordination]]

- _get_stream · function · L48-L58 — Maps a priority label to its Redis Stream name, routing subtitle tasks to a dedicated stream only consumed by nodes with subtitle-burning capability.
- _parse_str_list · function · L61-L73 — Tolerantly parses JSON-array strings (like node encoder capabilities) written by Go workers into Python lists, falling back to empty list on malformed input.
- get_redis · function · L82-L94 — Lazily creates and returns a shared Redis client singleton that reuses a connection pool to avoid per-call connection setup overhead.
- reset_redis_client · function · L97-L100 — Clears the shared Redis client reference for testing or application shutdown.
- publish_slice_task · function · L103-L140 — Publishes a slice task into the priority-selected Redis Stream, ensuring the consumer group exists and capping stream length to prevent unbounded growth.
- store_task_callback_token · function · L143-L149 — Persists a task callback/upload auth token in Redis with a TTL matching the task timeout to avoid long-term residue.
- get_task_callback_token · function · L152-L159 — Reads a stored task callback token from Redis.
- mark_task_cancelled · function · L162-L175 — Writes a cancellation marker into a task's Redis hash so workers force-kill the job, with a TTL fallback for tasks cancelled while still queued.
- get_task_redis_status · function · L178-L201 — Reads a worker-reported task status hash from Redis and normalizes it into a typed dict with progress, node, and error fields.
- set_node_enabled · function · L204-L218 — Persists a node's enabled/disabled flag as a Redis string with a 7-day TTL so workers check it before claiming new tasks.
- is_node_enabled · function · L221-L230 — Queries whether a node is enabled, defaulting to enabled when no control key exists.
- set_node_cpu_percent · function · L233-L248 — Clamps and stores a node's CPU allocation percentage (1-100) in Redis with a 7-day TTL for runtime dynamic adjustment without restart.
- get_node_cpu_percent · function · L251-L263 — Reads a node's CPU allocation percentage from Redis, clamping to 1-100 and falling back to a default on missing or invalid values.
- delete_worker_node · function · L266-L307 — Removes all Redis traces of a worker node (info hash, online set, tag sets, control keys, and its running task hashes) in a single pipeline to avoid dangling state.
- get_worker_nodes_from_redis · function · L310-L436 — Aggregates all worker nodes from Redis into UI-ready dicts, determining online/offline status from heartbeat TTL and attaching running-task progress, enabled state, CPU percent, and encoder capabilities.
- set_node_update_command · function · L439-L468 — Writes an engine update directive (target version + timestamp) to a node's Redis key with a 1-day TTL so workers self-update their engines without redeployment.
- get_node_update_command · function · L471-L480 — Reads a node's current engine update directive for UI display of push status and target version.
- clear_node_update_command · function · L483-L489 — Deletes a node's engine update directive after the worker successfully applies the update to prevent repeated pulls.
