# backend/app/api/watermark.py

- gen_task_name · function · L46-L65 — async def gen_task_name() -> str
- _fallback_seq · function · L71-L74 — def _fallback_seq() -> int
- WatermarkRunRequest · class · L90-L114 — class WatermarkRunRequest(BaseModel)
- WatermarkVideoItem · class · L117-L131 — class WatermarkVideoItem(BaseModel)
- WatermarkTaskItem · class · L134-L150 — class WatermarkTaskItem(BaseModel)
- WatermarkTaskDetail · class · L153-L154 — class WatermarkTaskDetail(WatermarkTaskItem)
- WatermarkDeleteRequest · class · L157-L158 — class WatermarkDeleteRequest(BaseModel)
- _serialize_video · function · L166-L186 — def _serialize_video(video: WatermarkVideo, output_url: Optional[str] = None, source_url: Optional[str] = None) -> dict
- _serialize_task · function · L189-L215 — def _serialize_task(task: WatermarkTask, fallback_prompt_record_id: Optional[str] = None) -> dict
- upload_watermark_video · function · L224-L275 — async def upload_watermark_video( file: UploadFile = File(...), db: AsyncSession = Depends(get_db), )
- run_watermark_task · function · L279-L428 — async def run_watermark_task( data: WatermarkRunRequest, db: AsyncSession = Depends(get_db), )
- list_watermark_tasks · function · L432-L460 — async def list_watermark_tasks( db: AsyncSession = Depends(get_db), )
- get_watermark_task · function · L464-L511 — async def get_watermark_task( task_id: str, db: AsyncSession = Depends(get_db), )
- delete_watermark_task · function · L515-L556 — async def delete_watermark_task( task_id: str, db: AsyncSession = Depends(get_db), )
- batch_delete_watermark_tasks · function · L560-L608 — async def batch_delete_watermark_tasks( data: WatermarkDeleteRequest, db: AsyncSession = Depends(get_db), )
- delete_watermark_video · function · L612-L641 — async def delete_watermark_video( video_id: str, db: AsyncSession = Depends(get_db), )
- download_watermark_video · function · L645-L671 — async def download_watermark_video( video_id: str, db: AsyncSession = Depends(get_db), )
- batch_download_watermark_videos · function · L675-L711 — async def batch_download_watermark_videos( data: dict, db: AsyncSession = Depends(get_db), )
