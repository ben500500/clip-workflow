# backend/app/api/publish_tasks.py

- PublishTaskCreate · class · L30-L51 — class PublishTaskCreate(BaseModel)
- PublishTaskResponse · class · L54-L86 — class PublishTaskResponse(BaseModel)
- PublishTaskConfirmResponse · class · L89-L93 — class PublishTaskConfirmResponse(BaseModel)
- PublishBatchCreate · class · L96-L98 — class PublishBatchCreate(BaseModel)
- PublishTaskScheduleUpdate · class · L101-L111 — class PublishTaskScheduleUpdate(BaseModel)
- create_publish_task · function · L115-L153 — async def create_publish_task( data: PublishTaskCreate, db: AsyncSession = Depends(get_db), )
- create_publish_tasks_batch · function · L157-L204 — async def create_publish_tasks_batch( data: PublishBatchCreate, db: AsyncSession = Depends(get_db), )
- _resolve_schedule · function · L207-L250 — async def _resolve_schedule( db: AsyncSession, data: PublishTaskCreate ) -> tuple[Optional[datetime], Optional[str]]
- _check_publish_limits · function · L253-L320 — async def _check_publish_limits(db: AsyncSession, data: PublishTaskCreate)
- _create_publish_task_internal · function · L323-L391 — async def _create_publish_task_internal( db: AsyncSession, data: PublishTaskCreate, scheduled_at: Optional[datetime] = None, time_slot_label: Optional[str] = None, ) -> PublishTask
- _to_uuid_or_none · function · L336-L343 — def _to_uuid_or_none(v: Optional[str]) -> Optional[uuid.UUID]
- list_publish_tasks · function · L395-L428 — async def list_publish_tasks( platform: Optional[str] = Query(None), status: Optional[str] = Query(None), start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), )
- get_publish_task · function · L432-L447 — async def get_publish_task( task_id: str, db: AsyncSession = Depends(get_db), )
- get_publish_task_screenshot · function · L451-L475 — async def get_publish_task_screenshot( task_id: str, db: AsyncSession = Depends(get_db), )
- confirm_publish_task · function · L479-L514 — async def confirm_publish_task( task_id: str, db: AsyncSession = Depends(get_db), )
- reschedule_publish_task · function · L518-L577 — async def reschedule_publish_task( task_id: str, data: PublishTaskScheduleUpdate, db: AsyncSession = Depends(get_db), )
- requeue_publish_task · function · L581-L621 — async def requeue_publish_task( task_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
