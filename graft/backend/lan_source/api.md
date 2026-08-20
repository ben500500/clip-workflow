# backend/lan_source/api.py

- _load_config · function · L46-L56 — async def _load_config(db: AsyncSession)
- lan_source_config · function · L60-L65 — async def lan_source_config( current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- lan_source_dramas · function · L69-L90 — async def lan_source_dramas( current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- lan_source_preview · function · L94-L117 — async def lan_source_preview( drama_name: str = Query(..., description="剧目名"), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- ImportRequest · class · L120-L124 — class ImportRequest(BaseModel)
- ImportResponse · class · L127-L131 — class ImportResponse(BaseModel)
- lan_source_import · function · L135-L170 — async def lan_source_import( data: ImportRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- list_tasks · function · L174-L186 — async def list_tasks( status: Optional[str] = Query(None, description="按状态过滤"), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db), )
- task_detail · function · L190-L195 — async def task_detail(task_id: uuid.UUID, db: AsyncSession = Depends(get_db))
- ToSliceRequest · class · L202-L208 — class ToSliceRequest(BaseModel)
- ToSliceResponse · class · L211-L215 — class ToSliceResponse(BaseModel)
- to_slice · function · L219-L281 — async def to_slice( task_id: uuid.UUID, data: ToSliceRequest, db: AsyncSession = Depends(get_db), )
