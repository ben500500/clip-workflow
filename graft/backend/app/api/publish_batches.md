# backend/app/api/publish_batches.py

- PublishTaskAssignRequest · class · L29-L40 — class PublishTaskAssignRequest(BaseModel)
- PublishBatchResponse · class · L43-L52 — class PublishBatchResponse(BaseModel)
- _serialize_publish_batch · function · L55-L64 — def _serialize_publish_batch(batch: PublishBatch) -> dict
- list_publish_batches · function · L68-L78 — async def list_publish_batches( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_publish_batch · function · L82-L106 — async def get_publish_batch( batch_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_publish_batch_stats · function · L110-L155 — async def get_publish_batch_stats( batch_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- create_publish_batch · function · L159-L238 — async def create_publish_batch( data: PublishTaskAssignRequest, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
