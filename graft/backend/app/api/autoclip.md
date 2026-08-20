# backend/app/api/autoclip.py · [[autoclip-pipeline-batch-slicing]] [[data-isolation-access-control]]

- _merge_default_autoclip_config · function · L32-L54 — async def _merge_default_autoclip_config(db, config: Optional[dict]) -> dict
- AutoClipRunRequest · class · L58-L60 — class AutoClipRunRequest(BaseModel)
- AutoClipRunResponse · class · L63-L66 — class AutoClipRunResponse(BaseModel)
- AutoClipProgressResponse · class · L69-L73 — class AutoClipProgressResponse(BaseModel)
- AutoClipRunResponseItem · class · L76-L90 — class AutoClipRunResponseItem(BaseModel)
- ClipUpdateRequest · class · L93-L96 — class ClipUpdateRequest(BaseModel)
- ClipResponse · class · L99-L116 — class ClipResponse(BaseModel)
- _serialize_clip · function · L119-L136 — def _serialize_clip(clip: ClipCandidate) -> dict
- _serialize_autoclip_run · function · L139-L153 — def _serialize_autoclip_run(run: AutoClipRun) -> dict
- run_autoclip · function · L157-L275 — async def run_autoclip( episode_id: str, data: AutoClipRunRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_autoclip_history · function · L279-L305 — async def get_autoclip_history( episode_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_autoclip_progress · function · L309-L367 — async def get_autoclip_progress( episode_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_autoclip_clips · function · L371-L398 — async def get_autoclip_clips( episode_id: str, min_score: float = Query(0.0, ge=0.0, le=100.0), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- update_clip · function · L402-L440 — async def update_clip( clip_id: str, data: ClipUpdateRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- regenerate_autoclip · function · L444-L484 — async def regenerate_autoclip( episode_id: str, data: AutoClipRunRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
