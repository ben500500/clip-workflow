# backend/app/models/audit.py

- AuditLog · class · L22-L41 — General audit log table capturing operator, action, target object, and before/after JSON values for security compliance and ops traceability, viewable only by superadmin/admin.
- __repr__ · method · L40-L41 — Human-readable string representation of an AuditLog row for debugging.
- PublishAudit · class · L44-L76 — Multi-operator publish audit table recording full publish context (actor, account, content, IPs, result, risk flag) chained by request_id across review→confirm→publish→risk-receipt flow.
- __repr__ · method · L75-L76 — Human-readable string representation of a PublishAudit row for debugging.
- LoginAudit · class · L79-L101 — Login-state self-service QR scan audit table recording QR claimer, scanner, TTL, and result for operator login-state governance and security tracing.
- __repr__ · method · L100-L101 — Human-readable string representation of a LoginAudit row for debugging.
- CookieAccessLog · class · L104-L122 — Cookie access audit table recording each decryption/read of an encrypted cookie (who, when, purpose) to prevent unauthorized cookie reads.
- __repr__ · method · L121-L122 — Human-readable string representation of a CookieAccessLog row for debugging.
