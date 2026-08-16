# backend/app/api/upload.py

- UploadResumeRequest · class · L35-L39 — class UploadResumeRequest(BaseModel)
- UploadResumeResponse · class · L42-L48 — class UploadResumeResponse(BaseModel)
- UploadProgressResponse · class · L51-L57 — class UploadProgressResponse(BaseModel)
- UploadCompleteRequest · class · L60-L64 — class UploadCompleteRequest(BaseModel)
- MultiUploadResponse · class · L67-L71 — class MultiUploadResponse(BaseModel)
- _serialize_episode · function · L74-L87 — def _serialize_episode(episode: Episode) -> dict
- _check_project_access · function · L90-L98 — async def _check_project_access(project: Project, current_user: User)
- _store_uploaded_file · function · L101-L140 — async def _store_uploaded_file( upload_id: str, project_id: uuid.UUID, file_name: str, file_size: int, db: AsyncSession, title: Optional[str] = None, episode_no: Optional[int] = None, ) -> Episode
- create_upload · function · L144-L169 — async def create_upload(data: UploadResumeRequest)
- get_upload_info · function · L173-L188 — async def get_upload_info( upload_id: str, tus_resumable: Optional[str] = Header(None, alias="Tus-Resumable"), )
- upload_chunk · function · L192-L221 — async def upload_chunk( upload_id: str, request: Request, upload_offset: Optional[str] = Header(None, alias="Upload-Offset"), )
- get_upload_progress_endpoint · function · L225-L237 — async def get_upload_progress_endpoint(upload_id: str)
- complete_upload · function · L241-L275 — async def complete_upload( data: UploadCompleteRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- upload_single · function · L279-L340 — async def upload_single( file: UploadFile = File(...), project_id: str = Form(...), title: Optional[str] = Form(None), episode_no: Optional[int] = Form(None), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- upload_multi · function · L344-L459 — async def upload_multi( files: List[UploadFile] = File(...), project_name: str = Form(...), merge: str = Form("false"), description: Optional[str] = Form(None), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- _run_ffmpeg · function · L462-L475 — async def _run_ffmpeg(cmd: List[str]) -> bool
- _ffmpeg_concat · function · L478-L527 — async def _ffmpeg_concat(paths: List[str], out_path: str) -> bool
- cancel_upload · function · L531-L534 — async def cancel_upload(upload_id: str)
