---
name: Publish Audit & Login QR
slug: publish-audit-login-qr
type: system
sources:
  - path: backend/app/api/publish_audit.py
    hash: afe7bdd6273b8569de3fe1763c9a3634ef146da09a8be8f76534338ff32c0d3b
  - path: backend/app/api/publish_login_qr.py
    hash: 01b7744690af4c850465ff6294fc2db7448f6555426c426faa89643253952700
sources_digest: c5a90d1ec8a6e1290832a695ed5ad11cd8cb6d37b766178c351f6b5439e4fa19
links:
  - to: publish-api-facade
    relation: part_of
    description: These routers are included by the publish facade.
generator:
  version: 1
covers:
  - symbol: _serialize_publish_audit
    kind: function
    at: 'backend/app/api/publish_audit.py:L22-L43'
  - symbol: _serialize_login_audit
    kind: function
    at: 'backend/app/api/publish_audit.py:L46-L60'
  - symbol: _serialize_risk_event
    kind: function
    at: 'backend/app/api/publish_audit.py:L63-L76'
  - symbol: get_multi_operator_matrix
    kind: function
    at: 'backend/app/api/publish_audit.py:L80-L118'
  - symbol: get_multi_operator_operators
    kind: function
    at: 'backend/app/api/publish_audit.py:L122-L128'
  - symbol: list_publish_audits
    kind: function
    at: 'backend/app/api/publish_audit.py:L132-L160'
  - symbol: trace_publish_audit
    kind: function
    at: 'backend/app/api/publish_audit.py:L164-L193'
  - symbol: get_multi_operator_verification
    kind: function
    at: 'backend/app/api/publish_audit.py:L197-L207'
  - symbol: set_multi_operator_flag
    kind: function
    at: 'backend/app/api/publish_audit.py:L211-L219'
  - symbol: LoginQrApply
    kind: class
    at: 'backend/app/api/publish_login_qr.py:L33-L35'
  - symbol: LoginScanCallback
    kind: class
    at: 'backend/app/api/publish_login_qr.py:L38-L44'
  - symbol: _probe_cdp_port
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L47-L59'
  - symbol: _resolve_profile_port
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L62-L139'
  - symbol: apply_login_qr
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L143-L197'
  - symbol: claim_login_qr
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L201-L218'
  - symbol: serve_login_qr_image
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L222-L240'
  - symbol: login_scan_callback
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L244-L267'
  - symbol: get_login_status
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L271-L282'
  - symbol: login_heartbeat
    kind: function
    at: 'backend/app/api/publish_login_qr.py:L286-L327'
---
<!-- context:generated:start -->
## Summary

Multi-operator audit/observability subdomain: port matrix dashboard, per-operator quota consumption, audit log queries (publish/login/risk), request-ID traceability, and a verification wizard with Redis-backed feature flag. Login QR flow captures the real login QR from Chromium via CDP, encrypts with Fernet, stores in MinIO, issues single-use 90-second claim tokens, and serves via a same-origin proxy to avoid browser access to internal MinIO URLs. Includes port-probing logic (_resolve_profile_port) that aligns allocated port with the actually running Chromium port to fix a P0 502 root cause from port drift.

## Related

- part of [[publish-api-facade]] — These routers are included by the publish facade.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
