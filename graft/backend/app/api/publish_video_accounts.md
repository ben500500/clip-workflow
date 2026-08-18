# backend/app/api/publish_video_accounts.py · [[data-isolation-access-control]] [[publish-profiles-video-accounts]]

- VideoAccountCreate · class · L22-L34 — class VideoAccountCreate(BaseModel)
- VideoAccountUpdate · class · L37-L48 — class VideoAccountUpdate(BaseModel)
- VideoAccountResponse · class · L51-L68 — class VideoAccountResponse(BaseModel)
- VideoAccountBatchImport · class · L71-L74 — class VideoAccountBatchImport(BaseModel)
- _serialize_video_account · function · L77-L94 — def _serialize_video_account(acc: VideoAccount) -> dict
- list_video_accounts · function · L98-L121 — async def list_video_accounts( platform: Optional[str] = Query(None), group_name: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- create_video_account · function · L125-L149 — async def create_video_account( data: VideoAccountCreate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- batch_import_video_accounts · function · L153-L196 — async def batch_import_video_accounts( data: VideoAccountBatchImport, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- VideoAccountBatchAssignProfile · class · L199-L202 — class VideoAccountBatchAssignProfile(BaseModel)
- batch_assign_video_account_profile · function · L206-L238 — async def batch_assign_video_account_profile( data: VideoAccountBatchAssignProfile, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_video_account · function · L242-L271 — async def update_video_account( account_id: str, data: VideoAccountUpdate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- delete_video_account · function · L275-L297 — async def delete_video_account( account_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
