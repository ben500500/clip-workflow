# backend/lan_source/api.py

- _load_config · function · L46-L56 — async def _load_config(db: AsyncSession)
- lan_source_config · function · L60-L65 — async def lan_source_config( current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- lan_source_dramas · function · L69-L90 — async def lan_source_dramas( current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- lan_source_preview · function · L94-L119 — async def lan_source_preview( drama_name: str = Query(..., description="剧目名"), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- ImportRequest · class · L122-L126 — class ImportRequest(BaseModel)
- ImportResponse · class · L129-L133 — class ImportResponse(BaseModel)
- lan_source_import · function · L137-L172 — async def lan_source_import( data: ImportRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- list_tasks · function · L176-L188 — async def list_tasks( status: Optional[str] = Query(None, description="按状态过滤"), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db), )
- task_detail · function · L192-L197 — async def task_detail(task_id: uuid.UUID, db: AsyncSession = Depends(get_db))
- ToSliceRequest · class · L204-L210 — class ToSliceRequest(BaseModel)
- ToSliceResponse · class · L213-L217 — class ToSliceResponse(BaseModel)
- to_slice · function · L221-L283 — async def to_slice( task_id: uuid.UUID, data: ToSliceRequest, db: AsyncSession = Depends(get_db), )
