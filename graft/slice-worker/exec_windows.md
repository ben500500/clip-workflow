# slice-worker/exec_windows.go · [[slice-worker-node]] [[worker-platform-abstractions]]

Windows-specific process management helpers for the slice worker, providing Python binary resolution, process group setup, and process tree termination via taskkill.

- pythonBinary · function · L11-L13 — Returns the Windows Python executable name, which is 'python' rather than 'python3' used on other platforms.
- SetProcessGroup · function · L17-L19 — No-op on Windows since process groups don't exist; process tree termination is handled separately via taskkill.
- KillProcessTree · function · L22-L29 — Terminates a process and all its descendants on Windows by invoking taskkill with /F and /T flags using the process PID.
- itoa · function · L31-L48 — Converts an integer to its decimal string representation without using strconv, handling zero and negative values.
