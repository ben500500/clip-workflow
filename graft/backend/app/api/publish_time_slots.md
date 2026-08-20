# backend/app/api/publish_time_slots.py · [[publish-tasks-scheduling]]

- PublishTimeSlotCreate · class · L38-L42 — class PublishTimeSlotCreate(BaseModel)
- PublishTimeSlotUpdate · class · L45-L49 — class PublishTimeSlotUpdate(BaseModel)
- PublishTimeSlotResponse · class · L52-L62 — class PublishTimeSlotResponse(BaseModel)
- _serialize_slot · function · L65-L75 — def _serialize_slot(slot: PublishTimeSlot) -> dict
- _validate_time_range · function · L78-L89 — def _validate_time_range(start_time: str, end_time: str) -> None
- list_publish_time_slots · function · L93-L103 — async def list_publish_time_slots( enabled_only: bool = Query(False), db: AsyncSession = Depends(get_db), )
- create_publish_time_slot · function · L107-L126 — async def create_publish_time_slot( data: PublishTimeSlotCreate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_publish_time_slot · function · L130-L158 — async def update_publish_time_slot( slot_id: str, data: PublishTimeSlotUpdate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- delete_publish_time_slot · function · L162-L179 — async def delete_publish_time_slot( slot_id: str, db: AsyncSession = Depends(get_db), )
- resolve_scheduled_at · function · L182-L227 — def resolve_scheduled_at(slot: PublishTimeSlot | None, scheduled_at: datetime | None = None) -> datetime | None
- _random_in_window · function · L207-L216 — def _random_in_window(day_local: datetime) -> datetime
