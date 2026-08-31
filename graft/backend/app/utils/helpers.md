# backend/app/utils/helpers.py · [[shared-backend-utilities]]

Utility module providing time formatting, cutlist/intervals generation, temp file writing, and size/date helpers for the video clipping backend.

- format_time · function · L11-L16 — Formats a seconds value into a zero-padded HH:MM:SS.mmm string for cutlist output.
- parse_time · function · L19-L26 — Parses HH:MM:SS.mmm or HH:MM:SS time strings back into total seconds, handling 2- and 3-part formats.
- sanitize_filename · function · L29-L40 — def sanitize_filename(name: str, max_len: int = 80) -> str
- build_clip_name · function · L43-L53 — def build_clip_name(episode_title: Optional[str], index: int) -> str
- generate_cutlist · function · L56-L110 — Builds cutlist text from accepted clip candidates, preferring adjusted times and numbering clips sequentially.
- generate_intervals_file · function · L113-L124 — Builds interval text lines from enabled detected intervals, emitting start and end times per line.
- write_temp_file · function · L127-L131 — Writes string content to a non-deleted temporary file and returns its path.
- write_temp_json · function · L134-L138 — Serializes a dict to JSON in a non-deleted temporary file and returns its path.
- ensure_dir · function · L141-L144 — Creates a directory if missing and returns the path.
- generate_signed_url_headers · function · L147-L149 — Placeholder returning empty headers for MinIO presigned URL requests.
- human_readable_size · function · L152-L160 — Converts a byte count into a human-readable string with appropriate unit, handling None as N/A.
- utc_iso · function · L162-L173 — Converts a naive UTC datetime to an ISO string with +00:00 timezone marker so frontend dayjs parses it in the correct local time.
