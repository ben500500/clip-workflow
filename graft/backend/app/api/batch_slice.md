# backend/app/api/batch_slice.py · [[autoclip-pipeline-batch-slicing]] [[data-isolation-access-control]]

- BatchEpisodeItem · class · L43-L46 — class BatchEpisodeItem(BaseModel)
- BatchSliceRunRequest · class · L49-L60 — class BatchSliceRunRequest(BaseModel)
- BatchSliceRunResponse · class · L63-L66 — class BatchSliceRunResponse(BaseModel)
- BatchSliceItemResponse · class · L69-L87 — class BatchSliceItemResponse(BaseModel)
- BatchSliceResponse · class · L90-L105 — class BatchSliceResponse(BaseModel)
- BatchSliceOutputItem · class · L108-L115 — class BatchSliceOutputItem(BaseModel)
- BatchSliceOutputResponse · class · L118-L120 — class BatchSliceOutputResponse(BaseModel)
- _serialize_batch · function · L128-L143 — def _serialize_batch(batch: BatchSlice) -> dict
- _serialize_item · function · L146-L164 — def _serialize_item(item: BatchSliceItem) -> dict
- _load_batch_owned · function · L167-L180 — async def _load_batch_owned(db: AsyncSession, batch_id: str, current_user: User) -> BatchSlice
- run_batch_slice · function · L189-L241 — async def run_batch_slice( data: BatchSliceRunRequest, current_user: Annotated[User, Depends(get_current_user)], db: AsyncSession = Depends(get_db), )
- list_batch_slices · function · L245-L264 — async def list_batch_slices( page: int = 1, page_size: int = 20, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_batch_slice · function · L268-L275 — async def get_batch_slice( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_batch_items · function · L279-L292 — async def get_batch_items( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_batch_outputs · function · L296-L376 — async def get_batch_outputs( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- retry_batch_slice · function · L380-L420 — async def retry_batch_slice( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- cancel_batch_slice · function · L424-L445 — async def cancel_batch_slice( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
