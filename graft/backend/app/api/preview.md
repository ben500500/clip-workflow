# backend/app/api/preview.py

- BatchDownloadRequest · class · L29-L30 — class BatchDownloadRequest(BaseModel)
- BatchDownloadItem · class · L33-L36 — class BatchDownloadItem(BaseModel)
- BatchDownloadResponse · class · L39-L40 — class BatchDownloadResponse(BaseModel)
- _check_output_scope · function · L43-L56 — async def _check_output_scope(db: AsyncSession, output: SliceOutput, current_user: User)
- preview_frames · function · L60-L111 — async def preview_frames( output_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- preview_video · function · L115-L148 — async def preview_video( output_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- download_output · function · L152-L201 — async def download_output( output_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- _cleanup_tmp · function · L204-L209 — async def _cleanup_tmp(path: str)
- batch_download · function · L213-L270 — async def batch_download( data: BatchDownloadRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
