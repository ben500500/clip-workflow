# backend/app/api/batch_slice.py

- BatchEpisodeItem · class · L42-L45 — class BatchEpisodeItem(BaseModel)
- BatchSliceRunRequest · class · L48-L59 — class BatchSliceRunRequest(BaseModel)
- BatchSliceRunResponse · class · L62-L65 — class BatchSliceRunResponse(BaseModel)
- BatchSliceItemResponse · class · L68-L86 — class BatchSliceItemResponse(BaseModel)
- BatchSliceResponse · class · L89-L104 — class BatchSliceResponse(BaseModel)
- BatchSliceOutputItem · class · L107-L114 — class BatchSliceOutputItem(BaseModel)
- BatchSliceOutputResponse · class · L117-L119 — class BatchSliceOutputResponse(BaseModel)
- _serialize_batch · function · L127-L142 — def _serialize_batch(batch: BatchSlice) -> dict
- _serialize_item · function · L145-L163 — def _serialize_item(item: BatchSliceItem) -> dict
- _load_batch_owned · function · L166-L179 — async def _load_batch_owned(db: AsyncSession, batch_id: str, current_user: User) -> BatchSlice
- run_batch_slice · function · L188-L240 — async def run_batch_slice( data: BatchSliceRunRequest, current_user: Annotated[User, Depends(get_current_user)], db: AsyncSession = Depends(get_db), )
- list_batch_slices · function · L244-L254 — async def list_batch_slices( page: int = 1, page_size: int = 20, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_batch_slice · function · L258-L265 — async def get_batch_slice( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_batch_items · function · L269-L282 — async def get_batch_items( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_batch_outputs · function · L286-L361 — async def get_batch_outputs( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- retry_batch_slice · function · L365-L395 — async def retry_batch_slice( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- cancel_batch_slice · function · L399-L420 — async def cancel_batch_slice( batch_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
