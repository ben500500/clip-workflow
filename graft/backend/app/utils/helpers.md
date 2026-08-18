# backend/app/utils/helpers.py · [[backend-utility-layer]]

Utility module providing time formatting, cutlist/intervals generation, temp file writing, and size/date helpers for the video clipping backend.

- format_time · function · L10-L15 — Formats a seconds value into a zero-padded HH:MM:SS.mmm string for cutlist output.
- parse_time · function · L18-L25 — Parses HH:MM:SS.mmm or HH:MM:SS time strings back into total seconds, handling 2- and 3-part formats.
- generate_cutlist · function · L28-L42 — Builds cutlist text from accepted clip candidates, preferring adjusted times and numbering clips sequentially.
- generate_intervals_file · function · L45-L56 — Builds interval text lines from enabled detected intervals, emitting start and end times per line.
- write_temp_file · function · L59-L63 — Writes string content to a non-deleted temporary file and returns its path.
- write_temp_json · function · L66-L70 — Serializes a dict to JSON in a non-deleted temporary file and returns its path.
- ensure_dir · function · L73-L76 — Creates a directory if missing and returns the path.
- generate_signed_url_headers · function · L79-L81 — Placeholder returning empty headers for MinIO presigned URL requests.
- human_readable_size · function · L84-L92 — Converts a byte count into a human-readable string with appropriate unit, handling None as N/A.
- utc_iso · function · L94-L105 — Converts a naive UTC datetime to an ISO string with +00:00 timezone marker so frontend dayjs parses it in the correct local time.
