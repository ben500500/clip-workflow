# backend/app/api/publish_audit.py

- _serialize_publish_audit · function · L22-L43 — def _serialize_publish_audit(a) -> dict
- _serialize_login_audit · function · L46-L60 — def _serialize_login_audit(a) -> dict
- _serialize_risk_event · function · L63-L76 — def _serialize_risk_event(a) -> dict
- get_multi_operator_matrix · function · L80-L118 — async def get_multi_operator_matrix( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_multi_operator_operators · function · L122-L128 — async def get_multi_operator_operators( db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- list_publish_audits · function · L132-L160 — async def list_publish_audits( action: Optional[str] = Query(None, description="过滤动作：publish/confirm/fail/reauth"), account_id: Optional[str] = Query(None), operator_id: Optional[str] = Query(None), request_id: Optional[str] = Query(None, description="trace_id 溯源"), kind: Optional[str] = Query("publish", description="audit 类型：publish/login/risk"), limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- trace_publish_audit · function · L164-L193 — async def trace_publish_audit( request_id: str, db: AsyncSession = Depends(get_db), current_user: Annotated[User, Depends(get_current_user)] = None, )
- get_multi_operator_verification · function · L197-L207 — async def get_multi_operator_verification( current_user: Annotated[User, Depends(get_current_user)] = None, )
- set_multi_operator_flag · function · L211-L219 — async def set_multi_operator_flag( enabled: bool = Body(..., embed=True, description="灰度开关 MULTI_OPERATOR_ENABLED"), current_user: Annotated[User, Depends(get_current_user)] = None, )
