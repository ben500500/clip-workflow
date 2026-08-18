# slice-worker/tray_other.go

Fallback no-op tray implementation for non-Windows/macOS platforms (Linux, containers, servers) that lack a desktop tray, keeping the code structure uniform while running in background/TUI mode.

- NoopTray · struct · L13-L15 — No-op tray controller struct that holds a reference to the TrayUI but performs no actual tray operations on unsupported platforms.
- newPlatformTrayController · function · L17-L19 — Factory returning a NoopTray instance as the platform-specific tray controller for environments without desktop tray support.
- Start · method · L21-L24 — Stores the UI reference and logs that the platform lacks tray support, falling back to background mode.
- Stop · method · L26-L26 — No-op stop method since there is no tray to shut down on unsupported platforms.
- SetOnline · method · L28-L28 — No-op setter for online status since there is no tray indicator to update.
- Notify · method · L30-L32 — Logs notification messages to the console instead of showing a tray balloon on unsupported platforms.
