# slice-worker/tui.go · [[worker-platform-abstractions]]

BubbleTea terminal UI for the slice worker, rendering task progress, logs, and node status in a live dashboard.

- TaskStatus · struct · L73-L84 — Data holder describing the live state of a single slice task (phase, percent, speed, status) for TUI display.
- LogEntry · struct · L87-L91 — Data holder for a single timestamped log line shown in the TUI log panel.
- TUIModel · struct · L94-L116 — State container for the TUI holding config, worker, task map, logs, and aggregate statistics.
- NewTUIModel · function · L119-L128 — Constructs the TUI model with initialized task map, log cap, start time, and connecting status.
- Init · method · L133-L138 — Starts the periodic tick command that drives the TUI's refresh loop.
- Update · method · L141-L212 — Central message dispatcher that mutates TUI state in response to key presses, window resizes, and worker task/log/status events.
- View · method · L215-L243 — Composes the full terminal frame from header, status bar, split task/log panels, and footer.
- renderHeader · method · L247-L258 — Renders the title bar with uptime and version, right-padding to fill the terminal width.
- renderStatusBar · method · L260-L274 — Renders a single-line status bar summarizing node config, concurrency, and aggregate completion stats.
- renderTaskList · method · L276-L307 — Renders the left panel listing up to the 10 most recent tasks, or an idle placeholder when none exist.
- renderTaskItem · method · L309-L380 — Renders one task row with status icon, truncated ID, progress bar, phase detail, and elapsed time.
- renderProgressBar · method · L382-L391 — Renders a filled/empty block progress bar with a percentage label.
- renderLogPanel · method · L393-L438 — Renders the right panel showing the most recent log lines, color-coded by level and truncated to width.
- renderFooter · method · L440-L447 — Renders the bottom help line right-aligned to the terminal width.
- addLog · method · L451-L462 — Appends a formatted log entry and trims the log buffer to the configured maximum.
- getActiveTasks · method · L464-L472 — Filters the task map to only those currently in running status.
- formatDuration · function · L474-L482 — Formats a duration as compact human-readable seconds, minutes, or hours.
- TickMsg · type · L486-L486 — Message type carrying the periodic tick timestamp that triggers TUI refresh.
- TaskStartMsg · struct · L488-L492 — Message notifying the TUI that a new task has begun, carrying its identity and mode.
- TaskProgressMsg · struct · L494-L499 — Message carrying a task's phase, percent, and detail for live progress updates.
- TaskCompleteMsg · struct · L501-L504 — Message notifying the TUI that a task finished, carrying its output file count.
- TaskErrorMsg · struct · L506-L509 — Message notifying the TUI that a task failed, carrying the error text.
- LogMsg · struct · L511-L514 — Message carrying an arbitrary log level and message to be appended to the TUI log panel.
- StatusMsg · struct · L516-L518 — Message updating the displayed node connection status string.
- tickCmd · method · L522-L526 — Schedules a 200ms tick that re-emits TickMsg to drive periodic TUI redraws.
