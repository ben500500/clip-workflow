# backend/app/services/audit_service.py

- gen_trace_id · function · L34-L36 — def gen_trace_id() -> str
- content_hash · function · L39-L43 — def content_hash(text: Optional[str]) -> Optional[str]
- _log_publish_audit · function · L46-L76 — async def _log_publish_audit(db: AsyncSession, *, task_id=None, account_id=None, operator_id=None, actor_id=None, profile_id=None, content_hash=None, cover_variant=None, copy_template=None, source_ip=None, egress_ip=None, ua_seed=None, port=None, action="publish", result=None, risk_flag=False, risk_note=None, request_id=None) -> None
- _log_login_audit · function · L79-L93 — async def _log_login_audit(db: AsyncSession, *, account_id=None, operator_id=None, actor_id=None, qr_key=None, claim_token=None, ttl_seconds=90, action="claim", scanner_name=None, source_ip=None, result=None, request_id=None) -> None
- _log_cookie_access · function · L96-L108 — async def _log_cookie_access(db: AsyncSession, *, profile_id=None, account_id=None, actor_id=None, operator_id=None, purpose="publish", ip_address=None, request_id=None) -> None
- _log_risk_event · function · L111-L124 — async def _log_risk_event(db: AsyncSession, *, account_id=None, operator_id=None, actor_id=None, risk_type="publish_limited", level="warning", message=None, disposition=None, source_ip=None, request_id=None) -> None
- log_publish_audit · function · L130-L137 — async def log_publish_audit(**kwargs) -> str
- log_login_audit · function · L140-L146 — async def log_login_audit(**kwargs) -> str
- log_cookie_access · function · L149-L155 — async def log_cookie_access(**kwargs) -> str
- log_risk_event · function · L158-L164 — async def log_risk_event(**kwargs) -> str
- list_publish_audits · function · L170-L185 — async def list_publish_audits(db: AsyncSession, *, action: Optional[str] = None, account_id: Optional[str] = None, operator_id: Optional[str] = None, request_id: Optional[str] = None, limit: int = 100) -> list
- list_login_audits · function · L188-L197 — async def list_login_audits(db: AsyncSession, *, account_id: Optional[str] = None, operator_id: Optional[str] = None, limit: int = 100) -> list
- list_risk_events · function · L200-L209 — async def list_risk_events(db: AsyncSession, *, account_id: Optional[str] = None, operator_id: Optional[str] = None, limit: int = 100) -> list
- trace_by_request_id · function · L212-L248 — async def trace_by_request_id(db: AsyncSession, request_id: str) -> dict
