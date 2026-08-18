# backend/app/services/smart_import_service.py · [[smart-import-service]]

- _normalize_headers · function · L100-L102 — Cleans header names by stripping whitespace and removing non-breaking spaces and BOM characters so they match fingerprints reliably.
- _read_headers_sync · function · L105-L116 — Reads column headers from an uploaded Excel or CSV file, falling back to CSV if Excel parsing fails.
- _read_preview_sync · function · L119-L130 — Reads a small preview of rows from an Excel or CSV file for display in the UI.
- _detect_platform · function · L133-L153 — Matches file headers against known platform fingerprints, scoring required headers double, to identify the source platform.
- _transform_row_sync · function · L156-L177 — Converts each DataFrame row into an import-ready dict by applying the target-field-to-source-column mapping, treating blank strings as zero.
- detect_platform · function · L180-L212 — Asynchronously detects the platform from file bytes and returns headers, preview rows, and a suggested column mapping.
- preview_file · function · L215-L226 — Returns file headers and first rows for UI preview without any platform detection.
- confirm_import · function · L229-L273 — Reads the full file, transforms rows per user mapping, and routes to the correct platform-specific importer based on target table.
- BytesFileWrapper · class · L255-L258 — Minimal file-like wrapper exposing bytes as a named file so existing importers can consume the uploaded data.
- __init__ · method · L256-L258 — Stores the raw bytes in a BytesIO buffer and assigns a filename for the wrapped import file.
- get_import_templates · function · L276-L290 — Fetches saved import templates ordered by creation time for reuse in the UI.
- save_custom_template · function · L293-L317 — Persists a user-defined import template with its column mapping and unit conversions.
- get_import_history · function · L320-L340 — Returns the 50 most recent import history records for display.
- get_ecosystem_metrics · function · L343-L382 — Queries ecosystem metrics (公众号/企微) filtered by account and date range, ordered by date descending.
- get_cross_analysis · function · L385-L432 — Aggregates video metrics by content_type to compare play, finish rate, jump rate, and revenue across dimensions.
