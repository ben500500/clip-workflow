# backend/app/utils/helpers.py · [[shared-backend-utilities]]

- format_time · function · L11-L16 — def format_time(seconds: float) -> str
- parse_time · function · L19-L26 — def parse_time(time_str: str) -> float
- sanitize_filename · function · L29-L40 — def sanitize_filename(name: str, max_len: int = 80) -> str
- build_clip_name · function · L43-L53 — def build_clip_name(episode_title: Optional[str], index: int) -> str
- generate_cutlist · function · L56-L70 — def generate_cutlist(clips: List[ClipCandidate], episode_title: Optional[str] = None) -> str
- generate_intervals_file · function · L73-L84 — def generate_intervals_file(intervals: List[DetectedInterval]) -> str
- write_temp_file · function · L87-L91 — def write_temp_file(content: str, suffix: str = ".txt") -> str
- write_temp_json · function · L94-L98 — def write_temp_json(data: dict, suffix: str = ".json") -> str
- ensure_dir · function · L101-L104 — def ensure_dir(path: str) -> str
- generate_signed_url_headers · function · L107-L109 — def generate_signed_url_headers() -> dict
- human_readable_size · function · L112-L120 — def human_readable_size(size_bytes: Optional[int]) -> str
- utc_iso · function · L122-L133 — def utc_iso(dt) -> str
