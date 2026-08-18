# frontend/src/utils/format.ts · [[frontend-api-layer]]

Central formatting utilities module providing consistent display formatting for file sizes, durations, dates, percentages, and status values across the frontend.

- formatFileSize · function · L3-L10 — Converts a byte count into a human-readable size string with the appropriate binary unit (B/KB/MB/GB/TB).
- formatDuration · function · L12-L20 — Formats a seconds value into HH:MM:SS or MM:SS clock-style display, omitting hours when zero.
- pad · function · L17-L17 — Zero-pads a number to two digits for consistent clock-style display.
- formatDateTime · function · L22-L25 — Formats an ISO date string into a full 'YYYY-MM-DD HH:mm:ss' display string.
- formatDate · function · L27-L30 — Formats an ISO date string into a 'YYYY-MM-DD' display string.
- formatRelativeTime · function · L32-L44 — Renders a date as a human-friendly relative time in Chinese (刚刚/分钟前/小时前/天前), falling back to absolute date for older entries.
- formatPercent · function · L46-L49 — Formats a numeric value as a percentage string with configurable decimal places.
- getStatusColor · function · L51-L77 — Maps a workflow status key to a hex color for UI badges, defaulting to gray for unknown statuses.
- getStatusLabel · function · L79-L105 — Maps a workflow status key to its Chinese display label, falling back to the raw key for unknown statuses.
- truncateText · function · L107-L110 — Truncates long text to a maximum length with an ellipsis suffix, returning '-' for empty input.
