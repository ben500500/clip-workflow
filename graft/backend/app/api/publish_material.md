# backend/app/api/publish_material.py

- PublishMaterialGenerateRequest · class · L40-L52 — class PublishMaterialGenerateRequest(BaseModel): # 用户输入的短剧剧情梗概 / 已生成的 Seedance 提示词 / 短剧标题（必填）
- PublishMaterialGenerateResponse · class · L55-L59 — class PublishMaterialGenerateResponse(BaseModel)
- PublishMaterialRecordItem · class · L62-L72 — class PublishMaterialRecordItem(BaseModel)
- _serialize_record · function · L80-L99 — def _serialize_record(r: PublishMaterial) -> dict
- generate_publish_material · function · L111-L191 — async def generate_publish_material( data: PublishMaterialGenerateRequest, db: AsyncSession = Depends(get_db), )
- list_publish_materials · function · L195-L208 — async def list_publish_materials( limit: int = 50, db: AsyncSession = Depends(get_db), )
- get_publish_material · function · L215-L221 — async def get_publish_material( record_id: str, db: AsyncSession = Depends(get_db), )
- delete_publish_material · function · L225-L233 — async def delete_publish_material( record_id: str, db: AsyncSession = Depends(get_db), )
- _get_record_or_404 · function · L236-L247 — async def _get_record_or_404(record_id: str, db: AsyncSession) -> PublishMaterial
