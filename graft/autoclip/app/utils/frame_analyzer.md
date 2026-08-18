# autoclip/app/utils/frame_analyzer.py · [[frame-analysis]]

- _seconds_to_ffmpeg_ts · function · L55-L60 — def _seconds_to_ffmpeg_ts(sec: float) -> str
- _extract_frame · function · L63-L81 — def _extract_frame(video_path: str, timestamp: float, out_path: str) -> bool
- _normalize_description · function · L84-L97 — def _normalize_description(raw: Dict[str, Any]) -> Dict[str, Any]
- _cache_key · function · L100-L106 — def _cache_key(video_path: str, start_sec: float, end_sec: float) -> str
- _cache_dir · function · L109-L112 — def _cache_dir() -> Path
- _read_cache · function · L115-L122 — def _read_cache(key: str) -> Optional[Dict[str, Any]]
- _write_cache · function · L125-L130 — def _write_cache(key: str, desc: Dict[str, Any]) -> None
- analyze_clip_frames · function · L133-L230 — def analyze_clip_frames( video_path: str, start_time: str, end_time: str, project_id: Optional[str] = None, ) -> Optional[Dict[str, Any]]
- to_sec · function · L160-L168 — def to_sec(t: str) -> Optional[float]
- analyze_timeline_frames · function · L233-L266 — def analyze_timeline_frames( timeline_data: List[Dict], video_path: str, project_id: Optional[str] = None, enabled: Optional[bool] = None, ) -> Dict[str, Dict[str, Any]]
