# backend/app/api/publish_audit.py

- _serialize_publish_audit · function · L21-L42 — def _serialize_publish_audit(a) -> dict
- _serialize_login_audit · function · L45-L59 — def _serialize_login_audit(a) -> dict
- _serialize_risk_event · function · L62-L75 — def _serialize_risk_event(a) -> dict
- get_multi_operator_matrix · function · L79-L90 — async def get_multi_operator_matrix( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_multi_operator_operators · function · L94-L100 — async def get_multi_operator_operators( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- list_publish_audits · function · L104-L132 — async def list_publish_audits( action: Optional[str] = Query(None, description="过滤动作：publish/confirm/fail/reauth"), account_id: Optional[str] = Query(None), operator_id: Optional[str] = Query(None), request_id: Optional[str] = Query(None, description="trace_id 溯源"), kind: Optional[str] = Query("publish", description="audit 类型：publish/login/risk"), limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- trace_publish_audit · function · L136-L165 — async def trace_publish_audit( request_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
