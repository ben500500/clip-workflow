# slice-worker/instance_lock.go · [[slice-worker-node]]

- acquireInstanceLock · function · L23-L59 — Acquires a per-node lock by writing the current PID to a lock file, rejecting the call if an existing lock file holds a live PID, and returns a release closure that only removes the lock if it still belongs to this process.
- processAlive · function · L62-L72 — Determines whether a PID corresponds to a live process by sending signal 0 (existence probe) on Unix.
