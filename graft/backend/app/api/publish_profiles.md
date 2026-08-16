# backend/app/api/publish_profiles.py

- PublishProfileCreate · class · L22-L41 — class PublishProfileCreate(BaseModel)
- PublishProfileUpdate · class · L44-L63 — class PublishProfileUpdate(BaseModel)
- PublishProfileResponse · class · L66-L90 — class PublishProfileResponse(BaseModel)
- _serialize_publish_profile · function · L93-L118 — def _serialize_publish_profile(profile: PublishProfile) -> dict
- list_publish_profiles · function · L122-L136 — async def list_publish_profiles( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- create_publish_profile · function · L140-L180 — async def create_publish_profile( data: PublishProfileCreate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_publish_profile · function · L184-L220 — async def update_publish_profile( profile_id: str, data: PublishProfileUpdate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- delete_publish_profile · function · L224-L246 — async def delete_publish_profile( profile_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
