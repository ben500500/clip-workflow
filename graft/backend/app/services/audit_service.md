# backend/app/services/audit_service.py · [[audit-observability]]

- gen_trace_id · function · L34-L36 — def gen_trace_id() -> str
- content_hash · function · L39-L43 — def content_hash(text: Optional[str]) -> Optional[str]
- _log_publish_audit · function · L57-L87 — async def _log_publish_audit(db: AsyncSession, *, task_id=None, account_id=None, operator_id=None, actor_id=None, profile_id=None, content_hash=None, cover_variant=None, copy_template=None, source_ip=None, egress_ip=None, ua_seed=None, port=None, action="publish", result=None, risk_flag=False, risk_note=None, request_id=None) -> None
- _log_login_audit · function · L90-L104 — async def _log_login_audit(db: AsyncSession, *, account_id=None, operator_id=None, actor_id=None, qr_key=None, claim_token=None, ttl_seconds=90, action="claim", scanner_name=None, source_ip=None, result=None, request_id=None) -> None
- _log_cookie_access · function · L107-L119 — async def _log_cookie_access(db: AsyncSession, *, profile_id=None, account_id=None, actor_id=None, operator_id=None, purpose="publish", ip_address=None, request_id=None) -> None
- _log_risk_event · function · L122-L135 — async def _log_risk_event(db: AsyncSession, *, account_id=None, operator_id=None, actor_id=None, risk_type="publish_limited", level="warning", message=None, disposition=None, source_ip=None, request_id=None) -> None
- log_publish_audit · function · L141-L148 — async def log_publish_audit(**kwargs) -> str
- log_login_audit · function · L151-L157 — async def log_login_audit(**kwargs) -> str
- log_cookie_access · function · L160-L166 — async def log_cookie_access(**kwargs) -> str
- log_risk_event · function · L169-L175 — async def log_risk_event(**kwargs) -> str
- list_publish_audits · function · L181-L196 — async def list_publish_audits(db: AsyncSession, *, action: Optional[str] = None, account_id: Optional[str] = None, operator_id: Optional[str] = None, request_id: Optional[str] = None, limit: int = 100) -> list
- list_login_audits · function · L199-L208 — async def list_login_audits(db: AsyncSession, *, account_id: Optional[str] = None, operator_id: Optional[str] = None, limit: int = 100) -> list
- list_risk_events · function · L211-L220 — async def list_risk_events(db: AsyncSession, *, account_id: Optional[str] = None, operator_id: Optional[str] = None, limit: int = 100) -> list
- trace_by_request_id · function · L223-L259 — async def trace_by_request_id(db: AsyncSession, request_id: str) -> dict
