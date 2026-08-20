# backend/app/api/upload.py · [[minio-storage-upload]]

- UploadResumeRequest · class · L36-L40 — class UploadResumeRequest(BaseModel)
- UploadResumeResponse · class · L43-L49 — class UploadResumeResponse(BaseModel)
- UploadProgressResponse · class · L52-L58 — class UploadProgressResponse(BaseModel)
- UploadCompleteRequest · class · L61-L65 — class UploadCompleteRequest(BaseModel)
- MultiUploadResponse · class · L68-L72 — class MultiUploadResponse(BaseModel)
- _serialize_episode · function · L75-L88 — def _serialize_episode(episode: Episode) -> dict
- _check_project_access · function · L91-L99 — async def _check_project_access(project: Project, current_user: User)
- _store_uploaded_file · function · L102-L149 — async def _store_uploaded_file( upload_id: str, project_id: uuid.UUID, file_name: str, file_size: int, db: AsyncSession, title: Optional[str] = None, episode_no: Optional[int] = None, ) -> Episode
- create_upload · function · L153-L178 — async def create_upload(data: UploadResumeRequest)
- get_upload_info · function · L182-L197 — async def get_upload_info( upload_id: str, tus_resumable: Optional[str] = Header(None, alias="Tus-Resumable"), )
- upload_chunk · function · L201-L230 — async def upload_chunk( upload_id: str, request: Request, upload_offset: Optional[str] = Header(None, alias="Upload-Offset"), )
- complete_upload · function · L234-L268 — async def complete_upload( data: UploadCompleteRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- upload_single · function · L272-L342 — async def upload_single( file: UploadFile = File(...), project_id: str = Form(...), title: Optional[str] = Form(None), episode_no: Optional[int] = Form(None), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- upload_multi · function · L346-L509 — async def upload_multi( files: List[UploadFile] = File(...), project_name: str = Form(""), project_id: Optional[str] = Form(None), merge: str = Form("false"), title: Optional[str] = Form(None), description: Optional[str] = Form(None), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- _check_av_sync · function · L512-L551 — async def _check_av_sync(file_path: str, threshold: float = 0.5) -> dict
- _run_ffmpeg · function · L554-L567 — async def _run_ffmpeg(cmd: List[str]) -> bool
- _ffmpeg_concat · function · L570-L619 — async def _ffmpeg_concat(paths: List[str], out_path: str) -> bool
- cancel_upload · function · L623-L626 — async def cancel_upload(upload_id: str)
