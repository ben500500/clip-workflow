# slice-worker/main.go · [[slice-worker-node]]

Entry point for the Slice Worker distributed slicing execution node, wiring config loading, Redis connection, single-instance locking, and selecting between tray, daemon, or TUI run modes.

- main · function · L15-L79 — Bootstraps the worker process: parses flags, loads config, acquires a single-instance lock keyed by node-id, connects Redis, and dispatches to the appropriate run mode based on platform and flags.
- runDaemon · function · L82-L121 — Runs the worker in headless background mode, printing startup info and wiring plain-text log callbacks before invoking worker.Run.
- runTUI · function · L124-L197 — Runs the worker under a Bubble Tea terminal UI, bridging worker callbacks into TUI messages via a program channel and running the worker asynchronously.
