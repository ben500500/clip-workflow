---
name: Audit & Observability
slug: audit-observability
type: system
sources:
  - path: backend/app/models/audit.py
    hash: 107dcc44551ef231091f4ae86f68e75a037c0b9e6cd8932b78014ca02b707c7d
  - path: backend/app/models/monitor.py
    hash: 02281c162a148f812ccbc31ff28dca2415a5002ecc9647603ef6261617a488f7
  - path: backend/app/services/audit_service.py
    hash: 320b2740e8d62703a618a272193e96734be95f81f9ae603a9e8184d55b676e93
sources_digest: fcfcdf2a5062305b41f968ab71e5c18760672802ef997b0c77ab629e796c7807
links:
  - to: login-qr-self-service
    relation: uses
    description: Logs QR login flows and cookie decryptions
  - to: orm-model-registry
    relation: uses
    description: 'AuditLog, PublishAudit, LoginAudit, CookieAccessLog, RiskEvent models'
generator:
  version: 1
covers:
  - symbol: AuditLog
    kind: class
    at: 'backend/app/models/audit.py:L22-L41'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L40-L41'
  - symbol: PublishAudit
    kind: class
    at: 'backend/app/models/audit.py:L44-L76'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L75-L76'
  - symbol: LoginAudit
    kind: class
    at: 'backend/app/models/audit.py:L79-L101'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L100-L101'
  - symbol: CookieAccessLog
    kind: class
    at: 'backend/app/models/audit.py:L104-L122'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L121-L122'
  - symbol: WorkerNode
    kind: class
    at: 'backend/app/models/monitor.py:L25-L55'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L54-L55'
  - symbol: AlertRule
    kind: class
    at: 'backend/app/models/monitor.py:L58-L80'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L79-L80'
  - symbol: AlertEvent
    kind: class
    at: 'backend/app/models/monitor.py:L83-L103'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L102-L103'
  - symbol: RiskEvent
    kind: class
    at: 'backend/app/models/monitor.py:L106-L127'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L126-L127'
  - symbol: gen_trace_id
    kind: function
    at: 'backend/app/services/audit_service.py:L34-L36'
  - symbol: content_hash
    kind: function
    at: 'backend/app/services/audit_service.py:L39-L43'
  - symbol: _log_publish_audit
    kind: function
    at: 'backend/app/services/audit_service.py:L57-L87'
  - symbol: _log_login_audit
    kind: function
    at: 'backend/app/services/audit_service.py:L90-L104'
  - symbol: _log_cookie_access
    kind: function
    at: 'backend/app/services/audit_service.py:L107-L119'
  - symbol: _log_risk_event
    kind: function
    at: 'backend/app/services/audit_service.py:L122-L135'
  - symbol: log_publish_audit
    kind: function
    at: 'backend/app/services/audit_service.py:L141-L148'
  - symbol: log_login_audit
    kind: function
    at: 'backend/app/services/audit_service.py:L151-L157'
  - symbol: log_cookie_access
    kind: function
    at: 'backend/app/services/audit_service.py:L160-L166'
  - symbol: log_risk_event
    kind: function
    at: 'backend/app/services/audit_service.py:L169-L175'
  - symbol: list_publish_audits
    kind: function
    at: 'backend/app/services/audit_service.py:L181-L196'
  - symbol: list_login_audits
    kind: function
    at: 'backend/app/services/audit_service.py:L199-L208'
  - symbol: list_risk_events
    kind: function
    at: 'backend/app/services/audit_service.py:L211-L220'
  - symbol: trace_by_request_id
    kind: function
    at: 'backend/app/services/audit_service.py:L223-L259'
---
<!-- context:generated:start -->
## Summary

Four audit log types (PublishAudit, LoginAudit, CookieAccessLog, RiskEvent) with request_id cross-model traceability for full-chain reconstruction of publishing ops. Write failures are logged but never block business flow. Risk types constrained by RISK_TYPE_* constants; content_hash is SHA-256. CookieAccessLog logs every decryption/read of encrypted cookies.

## Related

- uses [[login-qr-self-service]] — Logs QR login flows and cookie decryptions
- uses [[orm-model-registry]] — AuditLog, PublishAudit, LoginAudit, CookieAccessLog, RiskEvent models
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
