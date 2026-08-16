# backend/app/utils/helpers.py

- format_time · function · L10-L15 — def format_time(seconds: float) -> str
- parse_time · function · L18-L25 — def parse_time(time_str: str) -> float
- generate_cutlist · function · L28-L42 — def generate_cutlist(clips: List[ClipCandidate]) -> str
- generate_intervals_file · function · L45-L56 — def generate_intervals_file(intervals: List[DetectedInterval]) -> str
- write_temp_file · function · L59-L63 — def write_temp_file(content: str, suffix: str = ".txt") -> str
- write_temp_json · function · L66-L70 — def write_temp_json(data: dict, suffix: str = ".json") -> str
- ensure_dir · function · L73-L76 — def ensure_dir(path: str) -> str
- generate_signed_url_headers · function · L79-L81 — def generate_signed_url_headers() -> dict
- human_readable_size · function · L84-L92 — def human_readable_size(size_bytes: Optional[int]) -> str
- utc_iso · function · L94-L105 — def utc_iso(dt) -> str
