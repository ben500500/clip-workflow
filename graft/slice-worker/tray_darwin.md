# slice-worker/tray_darwin.go · [[worker-platform-abstractions]]

- MacOSTray · struct · L20-L29 — State holder for the macOS tray, tracking systray menu items and CPU submenu entries to drive the worker UI.
- newPlatformTrayController · function · L32-L34 — Platform factory returning the macOS tray controller implementation.
- iconBytes · method · L36-L43 — Reads the embedded template icon PNG bytes for the menu bar, returning nil on failure.
- Start · method · L51-L58 — Blocks the main goroutine in the AppKit event loop (required by systray on macOS) and builds the menu on ready.
- onReady · method · L60-L123 — Builds the tray menu (status, CPU submenu, toggle, quit) and runs the event loop dispatching clicks to UI callbacks.
- setCPU · method · L126-L130 — Drives the backend CPU allocation change by invoking the delta callback with the target minus current percent.
- refresh · method · L132-L160 — Synchronizes tray menu titles, CPU submenu checkmarks, and toggle label with the current UI state.
- SetOnline · method · L162-L166 — Refreshes the tray display under mutex when online status changes.
- Notify · method · L168-L170 — Logs a tray notification message to the log output.
- Stop · method · L172-L174 — Quits the systray event loop to shut down the tray.
