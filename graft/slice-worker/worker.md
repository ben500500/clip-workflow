# slice-worker/worker.go · [[slice-worker-node]]

The worker node that consumes slice tasks from Redis streams, executes them via ffmpeg engine, uploads results, and reports status/heartbeat.

- Worker · struct · L26-L53 — Core worker node struct holding config, redis client, executor, transfer, callbacks, and runtime state (running tasks, counters, engine version, capabilities).
- RunningTask · struct · L56-L67 — Data holder describing a task currently executing on this worker, including its context cancel function for cancellation support.
- NewWorker · function · L70-L81 — Constructor wiring up the worker's executor, file transfer, and callback service from config and redis client.
- setBackendEnabled · method · L84-L86 — func (w *Worker) setBackendEnabled(enabled bool)
- getBackendEnabled · method · L89-L91 — func (w *Worker) getBackendEnabled() bool
- SetCallbacks · method · L94-L124 — Registers user callbacks and bridges transfer/executor progress events into the unified onTaskProgress callback.
- checkEngine · method · L132-L156 — Self-checks the Python engine at startup using ast.parse (read-only, avoids py_compile cache writes on read-only mounts) to surface version incompatibility early.
- Run · method · L158-L287 — Main worker loop: registers node, starts heartbeat/claim/update goroutines, and continuously fetches and dispatches tasks respecting concurrency limits and admin disable state.
- cleanupOrphanDirs · method · L300-L338 — Cleans leftover temp directories from crashed workers, removing only non-UUID dirs or UUID dirs whose redis task is absent/terminal to avoid touching live tasks.
- waitRunningTasks · method · L341-L359 — Polls running task count during graceful shutdown, returning when all finish or the timeout deadline is reached.
- claimLoop · method · L362-L385 — Periodically claims stale PEL messages, skipping tasks with fresh leases or terminal status, and re-executes genuine orphans.
- claimOnce · method · L390-L424 — func (w *Worker) claimOnce(streams []string, minIdle time.Duration, startup bool)
- logPendingOverview · method · L427-L440 — func (w *Worker) logPendingOverview(streams []string)
- stuckTaskLoop · method · L449-L484 — func (w *Worker) stuckTaskLoop(ctx context.Context)
- requeueStuckTask · method · L489-L527 — func (w *Worker) requeueStuckTask(rt *RunningTask)
- runTask · method · L530-L776 — Executes a full slice task pipeline: dedup/idempotency checks, download source and badges, run ffmpeg engine, upload outputs, ACK, update status, and send callback.
- handleTaskError · method · L779-L859 — Routes task failures: cancels without retry, retries with backoff by re-queueing when under max retries, or marks failed when retries exhausted.
- sendFailureCallback · method · L862-L874 — Sends an HTTP failure callback to the backend if a callback URL is configured.
- watchCancellation · method · L877-L897 — Polls redis task status every 3 seconds to detect backend cancellation and trigger the task context cancel.
- leaseRenewal · method · L905-L936 — Periodically refreshes the task lease in redis so long-running tasks aren't misjudged as orphans by claimLoop.
- heartbeatLoop · method · L939-L961 — Periodically reports node liveness, current task counts, and engine version to redis to keep the node online.
- engineUpdateLoop · method · L970-L986 — Periodically checks for pushed engine updates and applies them without redeployment.
- checkEngineUpdate · method · L989-L1028 — Compares remote engine version against local and downloads/applies the new engine when a newer version is available.
- emitProgress · method · L1031-L1044 — Forwards progress events to the registered onTaskProgress callback if present.
- matchTags · method · L1047-L1063 — Determines whether this worker's configured tags satisfy all required tags for a task.
- log · method · L1066-L1073 — Routes log messages to the registered onLog callback.
- GetRunningTasks · method · L1076-L1083 — Returns a snapshot of all currently running tasks from the sync.Map.
- CancelTask · method · L1086-L1095 — Cancels a running task by invoking its stored context cancel function, returning whether the task was found.
- GetCurrentTaskCount · method · L1098-L1100 — Returns the atomic count of currently executing tasks.
- getHostname · function · L1103-L1109 — Returns the machine hostname, falling back to 'unknown' on error.
- getFileSize · function · L1112-L1117 — Returns the byte size of a file, or 0 if stat fails.
- strconvParseInt · function · L1120-L1132 — Parses a string to int64, returning 0 on parse failure.
