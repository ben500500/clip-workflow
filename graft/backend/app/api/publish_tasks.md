# backend/app/api/publish_tasks.py

- PublishTaskCreate · class · L30-L45 — class PublishTaskCreate(BaseModel)
- PublishTaskResponse · class · L48-L76 — class PublishTaskResponse(BaseModel)
- PublishTaskConfirmResponse · class · L79-L83 — class PublishTaskConfirmResponse(BaseModel)
- PublishBatchCreate · class · L86-L88 — class PublishBatchCreate(BaseModel)
- create_publish_task · function · L92-L124 — async def create_publish_task( data: PublishTaskCreate, db: AsyncSession = Depends(get_db), )
- create_publish_tasks_batch · function · L128-L168 — async def create_publish_tasks_batch( data: PublishBatchCreate, db: AsyncSession = Depends(get_db), )
- _check_publish_limits · function · L171-L238 — async def _check_publish_limits(db: AsyncSession, data: PublishTaskCreate)
- _create_publish_task_internal · function · L241-L287 — async def _create_publish_task_internal(db: AsyncSession, data: PublishTaskCreate) -> PublishTask
- _to_uuid_or_none · function · L245-L252 — def _to_uuid_or_none(v: Optional[str]) -> Optional[uuid.UUID]
- list_publish_tasks · function · L291-L324 — async def list_publish_tasks( platform: Optional[str] = Query(None), status: Optional[str] = Query(None), start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), )
- get_publish_task · function · L328-L343 — async def get_publish_task( task_id: str, db: AsyncSession = Depends(get_db), )
- get_publish_task_screenshot · function · L347-L371 — async def get_publish_task_screenshot( task_id: str, db: AsyncSession = Depends(get_db), )
- confirm_publish_task · function · L375-L410 — async def confirm_publish_task( task_id: str, db: AsyncSession = Depends(get_db), )
- requeue_publish_task · function · L414-L454 — async def requeue_publish_task( task_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
