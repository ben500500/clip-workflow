# backend/app/services/autoclip_service.py

- create_autoclip_project · function · L11-L27 — async def create_autoclip_project(name: str, config: dict) -> Optional[str]
- upload_video · function · L30-L50 — async def upload_video(autoclip_project_id: str, video_path: str, file_name: str) -> bool
- trigger_pipeline · function · L53-L84 — async def trigger_pipeline( autoclip_project_id: str, steps: Optional[list[int]] = None, config: Optional[dict] = None, ) -> bool
- get_pipeline_progress · function · L87-L101 — async def get_pipeline_progress(autoclip_project_id: str) -> Optional[dict]
- get_clips · function · L104-L137 — async def get_clips( autoclip_project_id: str, min_score: float = 60.0, max_clips: int = 30, min_duration: float = 0.0, max_duration: float = 0.0, ) -> list[dict[str, Any]]
- check_autoclip_health · function · L140-L159 — async def check_autoclip_health() -> bool
- delete_autoclip_project · function · L162-L174 — async def delete_autoclip_project(autoclip_project_id: str) -> bool
- generate_subtitle · function · L176-L206 — async def generate_subtitle( video_url: str, start_time: Optional[float] = None, end_time: Optional[float] = None, timeout: float = 1800.0, asr_method: Optional[str] = None, ) -> Optional[dict]
