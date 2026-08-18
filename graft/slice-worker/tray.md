# slice-worker/tray.go

System tray (menu bar) implementation for the slice worker node, with platform-specific backends for Windows/macOS and a no-tray log mode for Linux/containers.

- TrayController · interface · L19-L29 — Platform-agnostic interface that each OS backend implements to start/stop the tray, update online status icon, and show notifications.
- TrayUI · struct · L32-L52 — Holds tray UI state (node status, CPU allocation) and callbacks for toggling the node, adjusting CPU, and quitting, shared across platforms.
- NewTrayUI · function · L55-L62 — Constructs a TrayUI with default offline/disabled-off, enabled-on, and 50% CPU allocation state.
- SetStatus · method · L65-L79 — Updates node status fields and, only when something actually changed, refreshes the online icon (online only if both online and enabled) and the menu.
- SetCPUPercent · method · L82-L93 — Clamps the CPU allocation to the 1-100% range and refreshes the menu only when the value actually changes.
