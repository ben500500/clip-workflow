# slice-worker/tray_darwin_nocgo.go

Fallback tray implementation for macOS builds without cgo, degrading to log-only mode so CGO_ENABLED=0 builds compile.

- NoCgoMacTray · struct · L14-L16 — Struct type holding the TrayUI reference for the no-cgo macOS fallback tray.
- newPlatformTrayController · function · L18-L20 — Factory returning the no-cgo fallback tray controller for macOS builds without cgo.
- Start · method · L22-L25 — Stores the UI reference and logs that the tray cannot render without cgo, running in background mode instead.
- Stop · method · L27-L27 — No-op stop method satisfying the TrayController interface for the fallback tray.
- SetOnline · method · L29-L29 — No-op online-status setter satisfying the TrayController interface for the fallback tray.
- Notify · method · L31-L33 — Logs notifications to stdout instead of showing a macOS menu bar popup when cgo is unavailable.
