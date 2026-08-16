# backend/app/api/config.py

- ConfigUpdateRequest · class · L17-L19 — class ConfigUpdateRequest(BaseModel)
- ConfigResponse · class · L22-L26 — class ConfigResponse(BaseModel)
- ProfileCreate · class · L29-L36 — class ProfileCreate(BaseModel)
- ProfileUpdate · class · L39-L46 — class ProfileUpdate(BaseModel)
- ProfileResponse · class · L49-L60 — class ProfileResponse(BaseModel)
- _default_profile_for · function · L274-L282 — def _default_profile_for(profile: PlatformProfile) -> dict | None
- _serialize_config · function · L285-L291 — def _serialize_config(cfg: SystemConfig) -> dict
- _serialize_profile · function · L294-L305 — def _serialize_profile(profile: PlatformProfile) -> dict
- get_all_config · function · L309-L338 — async def get_all_config(db: AsyncSession = Depends(get_db))
- update_config · function · L342-L367 — async def update_config( data: ConfigUpdateRequest, db: AsyncSession = Depends(get_db), )
- reset_config_default · function · L371-L398 — async def reset_config_default( data: ConfigUpdateRequest, db: AsyncSession = Depends(get_db), )
- list_platform_profiles · function · L402-L408 — async def list_platform_profiles(db: AsyncSession = Depends(get_db))
- create_platform_profile · function · L412-L439 — async def create_platform_profile( data: ProfileCreate, db: AsyncSession = Depends(get_db), )
- update_platform_profile · function · L443-L490 — async def update_platform_profile( profile_id: str, data: ProfileUpdate, db: AsyncSession = Depends(get_db), )
- reset_platform_profile_default · function · L494-L530 — async def reset_platform_profile_default( profile_id: str, db: AsyncSession = Depends(get_db), )
- get_platform_presets · function · L534-L546 — async def get_platform_presets()
- delete_platform_profile · function · L550-L569 — async def delete_platform_profile( profile_id: str, db: AsyncSession = Depends(get_db), )
