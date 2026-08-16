# backend/app/services/dashboard_service.py

- get_overview · function · L28-L121 — async def get_overview( db: AsyncSession, account_id: Optional[uuid.UUID] = None, target_date: Optional[date] = None, ) -> dict
- get_video_ranking · function · L124-L176 — async def get_video_ranking( db: AsyncSession, account_id: Optional[uuid.UUID] = None, sort_by: str = "play_count", limit: int = 20, ) -> list
- get_funnel · function · L179-L279 — async def get_funnel( db: AsyncSession, account_id: Optional[uuid.UUID] = None, target_date: Optional[date] = None, ) -> dict
- get_trend · function · L282-L387 — async def get_trend( db: AsyncSession, account_id: Optional[uuid.UUID] = None, start_date: Optional[date] = None, end_date: Optional[date] = None, ) -> list
