# backend/app/api/remotion.py

- RemotionStatusResponse · class · L30-L37 — class RemotionStatusResponse(BaseModel)
- RemotionRenderResponse · class · L40-L46 — class RemotionRenderResponse(BaseModel)
- _load_remotion_task · function · L49-L70 — async def _load_remotion_task( slice_task_id: str, current_user: Annotated[User, Depends(get_current_user)], db: AsyncSession, ) -> SliceTask
- get_remotion_status · function · L74-L87 — async def get_remotion_status( slice_task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- trigger_remotion_render · function · L91-L136 — async def trigger_remotion_render( slice_task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
