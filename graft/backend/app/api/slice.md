# backend/app/api/slice.py · [[video-slicing-pipeline]]

- upload_badge_image · function · L107-L169 — async def upload_badge_image( file: UploadFile = File(...), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- upload_subtitle_file · function · L173-L231 — async def upload_subtitle_file( file: UploadFile = File(...), current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_slice_preferences · function · L235-L244 — async def get_slice_preferences( current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- save_slice_preferences · function · L248-L264 — async def save_slice_preferences( data: UserSliceConfigRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- _resolve_slice_inputs · function · L267-L556 — async def _resolve_slice_inputs( db: AsyncSession, eid: uuid.UUID, episode: Episode, data: SliceRunRequest, source_file_key: Optional[str], source_bucket: str, episode_id: str, current_user: Optional[User] = None, ) -> tuple
- _create_slice_task_record · function · L559-L645 — async def _create_slice_task_record( db: AsyncSession, eid: uuid.UUID, episode: Episode, data: SliceRunRequest, cutlist: str, intervals_content: str, source_file_key: Optional[str], source_bucket: str, ) -> tuple
- _dispatch_slice_task · function · L648-L806 — async def _dispatch_slice_task( db: AsyncSession, engine: str, episode: Episode, slice_task: SliceTask, data: SliceRunRequest, source_file_key: Optional[str], source_bucket: str, cutlist: str, intervals_content: str, configs: dict, fallback_whole_video: bool, ) -> SliceRunResponse
- run_slice · function · L810-L850 — async def run_slice( episode_id: str, data: SliceRunRequest, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- list_slice_tasks · function · L854-L881 — async def list_slice_tasks( episode_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_slice_task · function · L885-L934 — async def get_slice_task( task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_slice_outputs · function · L938-L978 — async def get_slice_outputs( task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_slice_output · function · L982-L1012 — async def get_slice_output( output_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- get_slice_upload_url · function · L1016-L1053 — async def get_slice_upload_url( task_id: str, file_name: str, x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"), db: AsyncSession = Depends(get_db), )
- slice_task_callback · function · L1057-L1212 — async def slice_task_callback( task_id: str, data: SliceTaskCallback, x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"), db: AsyncSession = Depends(get_db), )
- update_slice_progress · function · L1216-L1242 — async def update_slice_progress( task_id: str, data: dict, x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"), db: AsyncSession = Depends(get_db), )
- retry_slice_task · function · L1246-L1428 — async def retry_slice_task( task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- cancel_slice_task · function · L1432-L1471 — async def cancel_slice_task( task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- delete_slice_task · function · L1475-L1533 — async def delete_slice_task( task_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
