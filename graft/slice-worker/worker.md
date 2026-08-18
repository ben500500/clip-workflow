# slice-worker/worker.go

The worker node that consumes slice tasks from Redis streams, executes them via ffmpeg engine, uploads results, and reports status/heartbeat.

- Worker · struct · L25-L48 — Core worker node struct holding config, redis client, executor, transfer, callbacks, and runtime state (running tasks, counters, engine version, capabilities).
- RunningTask · struct · L51-L57 — Data holder describing a task currently executing on this worker, including its context cancel function for cancellation support.
- NewWorker · function · L60-L68 — Constructor wiring up the worker's executor, file transfer, and callback service from config and redis client.
- SetCallbacks · method · L71-L101 — Registers user callbacks and bridges transfer/executor progress events into the unified onTaskProgress callback.
- checkEngine · method · L109-L133 — Self-checks the Python engine at startup using ast.parse (read-only, avoids py_compile cache writes on read-only mounts) to surface version incompatibility early.
- Run · method · L135-L253 — Main worker loop: registers node, starts heartbeat/claim/update goroutines, and continuously fetches and dispatches tasks respecting concurrency limits and admin disable state.
- cleanupOrphanDirs · method · L265-L299 — Cleans leftover temp directories from crashed workers, removing only non-UUID dirs or UUID dirs whose redis task is absent/terminal to avoid touching live tasks.
- waitRunningTasks · method · L302-L320 — Polls running task count during graceful shutdown, returning when all finish or the timeout deadline is reached.
- claimLoop · method · L323-L368 — Periodically claims stale PEL messages, skipping tasks with fresh leases or terminal status, and re-executes genuine orphans.
- runTask · method · L371-L540 — Executes a full slice task pipeline: dedup/idempotency checks, download source and badges, run ffmpeg engine, upload outputs, ACK, update status, and send callback.
- handleTaskError · method · L543-L612 — Routes task failures: cancels without retry, retries with backoff by re-queueing when under max retries, or marks failed when retries exhausted.
- sendFailureCallback · method · L615-L627 — Sends an HTTP failure callback to the backend if a callback URL is configured.
- watchCancellation · method · L630-L650 — Polls redis task status every 3 seconds to detect backend cancellation and trigger the task context cancel.
- leaseRenewal · method · L658-L671 — Periodically refreshes the task lease in redis so long-running tasks aren't misjudged as orphans by claimLoop.
- heartbeatLoop · method · L674-L696 — Periodically reports node liveness, current task counts, and engine version to redis to keep the node online.
- engineUpdateLoop · method · L705-L721 — Periodically checks for pushed engine updates and applies them without redeployment.
- checkEngineUpdate · method · L724-L763 — Compares remote engine version against local and downloads/applies the new engine when a newer version is available.
- emitProgress · method · L766-L775 — Forwards progress events to the registered onTaskProgress callback if present.
- matchTags · method · L778-L794 — Determines whether this worker's configured tags satisfy all required tags for a task.
- log · method · L797-L804 — Routes log messages to the registered onLog callback.
- GetRunningTasks · method · L807-L814 — Returns a snapshot of all currently running tasks from the sync.Map.
- CancelTask · method · L817-L826 — Cancels a running task by invoking its stored context cancel function, returning whether the task was found.
- GetCurrentTaskCount · method · L829-L831 — Returns the atomic count of currently executing tasks.
- getHostname · function · L834-L840 — Returns the machine hostname, falling back to 'unknown' on error.
- getFileSize · function · L843-L848 — Returns the byte size of a file, or 0 if stat fails.
- strconvParseInt · function · L851-L863 — Parses a string to int64, returning 0 on parse failure.
