# backend/app/api/publish_material.py

- PublishMaterialGenerateRequest · class · L42-L54 — class PublishMaterialGenerateRequest(BaseModel): # 用户输入的短剧剧情梗概 / 已生成的 Seedance 提示词 / 短剧标题（必填）
- PublishMaterialGenerateFromOutputRequest · class · L57-L66 — class PublishMaterialGenerateFromOutputRequest(BaseModel): # 切片成品 output_id（从 SliceOutput 自动组装剧情梗概 story）
- PublishMaterialGenerateResponse · class · L69-L73 — class PublishMaterialGenerateResponse(BaseModel)
- PublishMaterialRecordItem · class · L76-L86 — class PublishMaterialRecordItem(BaseModel)
- _serialize_record · function · L94-L113 — def _serialize_record(r: PublishMaterial) -> dict
- generate_publish_material · function · L125-L205 — async def generate_publish_material( data: PublishMaterialGenerateRequest, db: AsyncSession = Depends(get_db), )
- _build_story_from_output · function · L208-L291 — async def _build_story_from_output( db: AsyncSession, output_id: str, current_user: User ) -> dict
- generate_publish_material_from_output · function · L298-L373 — async def generate_publish_material_from_output( data: PublishMaterialGenerateFromOutputRequest, current_user: Annotated[User, Depends(get_current_user)], db: AsyncSession = Depends(get_db), )
- list_publish_materials · function · L377-L390 — async def list_publish_materials( limit: int = 50, db: AsyncSession = Depends(get_db), )
- get_publish_material · function · L397-L403 — async def get_publish_material( record_id: str, db: AsyncSession = Depends(get_db), )
- delete_publish_material · function · L407-L415 — async def delete_publish_material( record_id: str, db: AsyncSession = Depends(get_db), )
- _get_record_or_404 · function · L418-L429 — async def _get_record_or_404(record_id: str, db: AsyncSession) -> PublishMaterial
