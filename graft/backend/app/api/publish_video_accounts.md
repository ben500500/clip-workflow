# backend/app/api/publish_video_accounts.py

- VideoAccountCreate · class · L22-L33 — class VideoAccountCreate(BaseModel)
- VideoAccountUpdate · class · L36-L46 — class VideoAccountUpdate(BaseModel)
- VideoAccountResponse · class · L49-L65 — class VideoAccountResponse(BaseModel)
- VideoAccountBatchImport · class · L68-L71 — class VideoAccountBatchImport(BaseModel)
- _serialize_video_account · function · L74-L90 — def _serialize_video_account(acc: VideoAccount) -> dict
- list_video_accounts · function · L94-L117 — async def list_video_accounts( platform: Optional[str] = Query(None), group_name: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- create_video_account · function · L121-L144 — async def create_video_account( data: VideoAccountCreate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- batch_import_video_accounts · function · L148-L190 — async def batch_import_video_accounts( data: VideoAccountBatchImport, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_video_account · function · L194-L223 — async def update_video_account( account_id: str, data: VideoAccountUpdate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- delete_video_account · function · L227-L249 — async def delete_video_account( account_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
