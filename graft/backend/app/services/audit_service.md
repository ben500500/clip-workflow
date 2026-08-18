# backend/app/services/audit_service.py

- gen_trace_id · function · L34-L36 — Generates a unique request_id (trace_id) to correlate all audit events across a single publish flow.
- content_hash · function · L39-L43 — Produces a truncated sha256 hash of publish content so it can be traced without storing plaintext.
- _log_publish_audit · function · L46-L76 — Persists a publish audit record capturing actor/operator/account/content hash/IPs and risk flags, with trace_id fallback generation.
- _log_login_audit · function · L79-L93 — Persists a login self-service QR scan audit record with claim token and TTL details.
- _log_cookie_access · function · L96-L108 — Persists a cookie access log recording who read a cookie and for what purpose, to prevent unauthorized reads.
- _log_risk_event · function · L111-L124 — Persists a risk event record with risk type, level, and disposition to drive graduation threshold statistics.
- log_publish_audit · function · L130-L137 — Public write entry that self-creates a session (for celery workers) and returns the request_id for downstream correlation.
- log_login_audit · function · L140-L146 — Public write entry that self-creates a session and returns the request_id for login audit events.
- log_cookie_access · function · L149-L155 — Public write entry that self-creates a session and returns the request_id for cookie access audit events.
- log_risk_event · function · L158-L164 — Public write entry that self-creates a session and returns the request_id for risk event audit records.
- list_publish_audits · function · L170-L185 — Queries publish audit records with optional filters on action/account/operator/request_id, capped at 500 rows.
- list_login_audits · function · L188-L197 — Queries login audit records filtered by account or operator, capped at 500 rows.
- list_risk_events · function · L200-L209 — Queries risk event records filtered by account or operator, capped at 500 rows.
- trace_by_request_id · function · L212-L248 — Reconstructs the full audit trail for a request_id by joining publish, login, cookie, and risk records to restore operator/actor/IP/hash context.
