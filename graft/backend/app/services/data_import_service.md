# backend/app/services/data_import_service.py · [[dashboard-metrics-aggregation]]

- _validate_columns · function · L47-L58 — Checks that all required columns exist in the DataFrame (case-insensitive, whitespace-trimmed) and returns a list of missing-column error messages.
- _normalize_columns · function · L61-L64 — Lowercases and strips whitespace from all DataFrame column names so downstream lookups are case-insensitive.
- _parse_date · function · L67-L78 — Converts a cell value from various formats (datetime, date, string) into a date object, returning None for missing or unparseable values.
- _safe_int · function · L81-L88 — Converts a cell value to int, returning a default for NaN or non-numeric values to avoid import crashes.
- _safe_float · function · L91-L98 — Converts a cell value to float, returning a default for NaN or non-numeric values to avoid import crashes.
- _upsert_video_metric · function · L101-L125 — Finds an existing video metric by (video_id, publish_date, optional account_id) and updates it, or inserts a new row when none exists.
- _upsert_metric · function · L128-L150 — Generic upsert for daily metric tables keyed by (date_field, optional account_id), updating an existing row or inserting a new one.
- import_video_metrics · function · L153-L244 — Reads a video metrics Excel file, validates required columns, parses each row into typed values, and upserts them per video, returning per-row errors.
- import_mini_program_metrics · function · L247-L313 — Reads a mini program metrics Excel file, validates required columns, and upserts daily metric rows keyed by date and account.
- import_ad_metrics · function · L316-L386 — Reads an ad metrics Excel file, validates required columns, and upserts daily ad metric rows keyed by date and account.
- _generate_template_sync · function · L389-L439 — Builds an Excel template with required and optional columns plus a sample row for a given import type, raising on unknown types.
- generate_import_template · function · L442-L454 — Async wrapper that offloads Excel template generation to an executor thread to avoid blocking the event loop.
