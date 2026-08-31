# backend/dupload/api.py

- _load_config · function · L35-L45 — async def _load_config(db: AsyncSession) -> DuploadConfig
- dupload_config · function · L49-L54 — async def dupload_config( current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
- DuploadTriggerRequest · class · L57-L61 — class DuploadTriggerRequest(BaseModel)
- DuploadHostResult · class · L64-L70 — class DuploadHostResult(BaseModel)
- DuploadTriggerResponse · class · L73-L83 — class DuploadTriggerResponse(BaseModel)
- dupload_trigger · function · L87-L163 — async def dupload_trigger( data: DuploadTriggerRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), )
