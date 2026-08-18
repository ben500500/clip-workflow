# backend/app/api/publish_mini_programs.py · [[channel-accounts-mini-programs]]

- MiniProgramCreate · class · L20-L26 — class MiniProgramCreate(BaseModel)
- MiniProgramUpdate · class · L29-L35 — class MiniProgramUpdate(BaseModel)
- MiniProgramResponse · class · L38-L48 — class MiniProgramResponse(BaseModel)
- _serialize_mini_program · function · L51-L61 — def _serialize_mini_program(mp: MiniProgram) -> dict
- list_mini_programs · function · L65-L76 — async def list_mini_programs( enabled_only: bool = Query(True), db: AsyncSession = Depends(get_db), )
- create_mini_program · function · L80-L96 — async def create_mini_program( data: MiniProgramCreate, db: AsyncSession = Depends(get_db), )
- update_mini_program · function · L100-L121 — async def update_mini_program( mp_id: str, data: MiniProgramUpdate, db: AsyncSession = Depends(get_db), )
- delete_mini_program · function · L125-L142 — async def delete_mini_program( mp_id: str, db: AsyncSession = Depends(get_db), )
