# slice-worker/exec_unix.go · [[slice-worker-node]] [[worker-platform-abstractions]]

- pythonBinary · function · L15-L20 — Resolves the Python executable name, honoring the SLICE_PYTHON env override to allow forcing a Python 3.10+ interpreter when the system default is too old.
- SetProcessGroup · function · L23-L25 — Configures a child command to run in its own process group so the whole tree can be killed together.
- KillProcessTree · function · L28-L38 — Force-kills an entire process group (including ffmpeg children) by sending SIGKILL to the negative pgid, falling back to killing just the process if group lookup fails.
