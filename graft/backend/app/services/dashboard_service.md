# backend/app/services/dashboard_service.py

- _cache_key · function · L41-L48 — def _cache_key(name: str, **params) -> str
- _get_cached_agg · function · L51-L62 — async def _get_cached_agg(key: str)
- _set_cached_agg · function · L65-L78 — async def _set_cached_agg(key: str, data) -> None
- _get_cached_agg · function · L81-L92 — async def _get_cached_agg(key: str)
- _get_snapshot_agg · function · L95-L106 — async def _get_snapshot_agg(key: str)
- _with_cache · function · L109-L131 — async def _with_cache(name: str, db, params: dict, compute)
- get_overview · function · L134-L145 — async def get_overview( db: AsyncSession, account_id: Optional[uuid.UUID] = None, target_date: Optional[date] = None, ) -> dict
- _compute_overview · function · L148-L241 — async def _compute_overview( db: AsyncSession, account_id: Optional[uuid.UUID] = None, target_date: Optional[date] = None, ) -> dict
- get_video_ranking · function · L244-L296 — async def get_video_ranking( db: AsyncSession, account_id: Optional[uuid.UUID] = None, sort_by: str = "play_count", limit: int = 20, ) -> list
- get_funnel · function · L299-L312 — async def get_funnel( db: AsyncSession, account_id: Optional[uuid.UUID] = None, target_date: Optional[date] = None, ) -> dict
- _compute_funnel · function · L315-L415 — async def _compute_funnel( db: AsyncSession, account_id: Optional[uuid.UUID] = None, target_date: Optional[date] = None, ) -> dict
- get_trend · function · L418-L434 — async def get_trend( db: AsyncSession, account_id: Optional[uuid.UUID] = None, start_date: Optional[date] = None, end_date: Optional[date] = None, ) -> list
- _compute_trend · function · L437-L542 — async def _compute_trend( db: AsyncSession, account_id: Optional[uuid.UUID] = None, start_date: Optional[date] = None, end_date: Optional[date] = None, ) -> list
