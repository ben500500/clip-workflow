# backend/app/api/publish_profiles.py · [[publish-profiles-video-accounts]]

- PublishProfileCreate · class · L22-L43 — class PublishProfileCreate(BaseModel)
- PublishProfileUpdate · class · L46-L66 — class PublishProfileUpdate(BaseModel)
- PublishProfileResponse · class · L69-L94 — class PublishProfileResponse(BaseModel)
- _serialize_publish_profile · function · L97-L123 — def _serialize_publish_profile(profile: PublishProfile) -> dict
- list_publish_profiles · function · L127-L141 — async def list_publish_profiles( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- create_publish_profile · function · L145-L186 — async def create_publish_profile( data: PublishProfileCreate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_publish_profile · function · L190-L226 — async def update_publish_profile( profile_id: str, data: PublishProfileUpdate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- delete_publish_profile · function · L230-L252 — async def delete_publish_profile( profile_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
