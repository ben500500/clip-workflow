# autoclip/app/utils/text_processor.py

- TextProcessor · class · L26-L295 — class TextProcessor
- chunk_text · method · L30-L79 — def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> List[str]
- chunk_srt_data · method · L81-L179 — def chunk_srt_data(self, srt_data: List[Dict], interval_minutes: int = 30, pause_threshold_ms: int = 1000) -> List[Dict]
- parse_srt · method · L182-L222 — def parse_srt(srt_path: Path) -> List[Dict]
- extract_text_by_time_range · method · L225-L255 — def extract_text_by_time_range(text: str, srt_data: List[Dict], start_time: str, end_time: str) -> str
- time_to_seconds · method · L258-L279 — def time_to_seconds(time_str: str) -> float
- seconds_to_time · method · L282-L295 — def seconds_to_time(seconds: float) -> str
