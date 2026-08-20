# backend/app/api/config.py · [[system-config-platform-profiles]]

- ConfigUpdateRequest · class · L17-L19 — class ConfigUpdateRequest(BaseModel)
- ConfigResponse · class · L22-L26 — class ConfigResponse(BaseModel)
- ProfileCreate · class · L29-L36 — class ProfileCreate(BaseModel)
- ProfileUpdate · class · L39-L46 — class ProfileUpdate(BaseModel)
- ProfileResponse · class · L49-L60 — class ProfileResponse(BaseModel)
- _default_profile_for · function · L296-L304 — def _default_profile_for(profile: PlatformProfile) -> dict | None
- _serialize_config · function · L307-L313 — def _serialize_config(cfg: SystemConfig) -> dict
- _serialize_profile · function · L316-L327 — def _serialize_profile(profile: PlatformProfile) -> dict
- get_all_config · function · L331-L360 — async def get_all_config(db: AsyncSession = Depends(get_db))
- update_config · function · L364-L389 — async def update_config( data: ConfigUpdateRequest, db: AsyncSession = Depends(get_db), )
- reset_config_default · function · L393-L420 — async def reset_config_default( data: ConfigUpdateRequest, db: AsyncSession = Depends(get_db), )
- list_platform_profiles · function · L424-L430 — async def list_platform_profiles(db: AsyncSession = Depends(get_db))
- create_platform_profile · function · L434-L461 — async def create_platform_profile( data: ProfileCreate, db: AsyncSession = Depends(get_db), )
- update_platform_profile · function · L465-L512 — async def update_platform_profile( profile_id: str, data: ProfileUpdate, db: AsyncSession = Depends(get_db), )
- reset_platform_profile_default · function · L516-L552 — async def reset_platform_profile_default( profile_id: str, db: AsyncSession = Depends(get_db), )
- get_platform_presets · function · L556-L568 — async def get_platform_presets()
- delete_platform_profile · function · L572-L591 — async def delete_platform_profile( profile_id: str, db: AsyncSession = Depends(get_db), )
