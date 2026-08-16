# backend/app/api/intervals.py

- DetectRequest · class · L22-L25 — class DetectRequest(BaseModel)
- DetectResponse · class · L28-L30 — class DetectResponse(BaseModel)
- DetectProgressResponse · class · L33-L39 — class DetectProgressResponse(BaseModel)
- IntervalCreate · class · L42-L50 — class IntervalCreate(BaseModel)
- IntervalUpdate · class · L53-L60 — class IntervalUpdate(BaseModel)
- IntervalResponse · class · L63-L76 — class IntervalResponse(BaseModel)
- IntervalHistoryItem · class · L79-L91 — class IntervalHistoryItem(BaseModel)
- _serialize_interval · function · L94-L107 — def _serialize_interval(interval: DetectedInterval) -> dict
- detect_intervals · function · L111-L186 — async def detect_intervals( episode_id: str, data: DetectRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_detect_progress · function · L190-L281 — async def get_detect_progress( episode_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- list_intervals · function · L285-L310 — async def list_intervals( episode_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_interval_history · function · L314-L376 — async def get_interval_history( episode_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- create_interval · function · L380-L413 — async def create_interval( data: IntervalCreate, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- update_interval · function · L417-L460 — async def update_interval( interval_id: str, data: IntervalUpdate, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- delete_interval · function · L464-L490 — async def delete_interval( interval_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- toggle_interval · function · L494-L522 — async def toggle_interval( interval_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
