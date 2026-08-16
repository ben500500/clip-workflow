# backend/app/api/publications.py

- PublicationCreate · class · L19-L25 — class PublicationCreate(BaseModel)
- PublicationUpdate · class · L28-L34 — class PublicationUpdate(BaseModel)
- PublicationResponse · class · L37-L48 — class PublicationResponse(BaseModel)
- _serialize_publication · function · L51-L62 — def _serialize_publication(pub: Publication) -> dict
- _check_output_scope · function · L65-L78 — async def _check_output_scope(db: AsyncSession, output: SliceOutput, current_user: User)
- list_publications · function · L82-L108 — async def list_publications( output_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- create_publication · function · L112-L153 — async def create_publication( output_id: str, data: PublicationCreate, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
- update_publication · function · L157-L207 — async def update_publication( publication_id: str, data: PublicationUpdate, current_user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db), )
