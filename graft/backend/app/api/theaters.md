# backend/app/api/theaters.py

- TheaterCreate · class · L29-L32 — class TheaterCreate(BaseModel)
- TheaterUpdate · class · L35-L38 — class TheaterUpdate(BaseModel)
- TheaterResponse · class · L41-L50 — class TheaterResponse(BaseModel)
- _serialize_theater · function · L55-L64 — def _serialize_theater(t: Theater) -> dict
- _parse_uuid · function · L67-L73 — def _parse_uuid(value: Optional[str], field: str)
- _apply_rbac_filter · function · L76-L79 — def _apply_rbac_filter(current_user: User)
- list_theaters · function · L85-L103 — async def list_theaters( keyword: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_theater · function · L107-L118 — async def get_theater( theater_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- create_theater · function · L122-L144 — async def create_theater( data: TheaterCreate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_theater · function · L148-L182 — async def update_theater( theater_id: str, data: TheaterUpdate, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- delete_theater · function · L186-L200 — async def delete_theater( theater_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- _check_access · function · L203-L207 — def _check_access(t: Theater, current_user: Optional[User])
