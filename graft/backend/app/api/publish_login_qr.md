# backend/app/api/publish_login_qr.py · [[publish-audit-login-qr]]

- LoginQrApply · class · L33-L35 — Request body for admin to request a login QR scan, carrying only the target account id.
- LoginScanCallback · class · L38-L44 — Request body for the operator's WeChat scan result callback, carrying account id, operator/scanner identity, and the scan result (success/failed/expired).
- _probe_cdp_port · function · L47-L59 — Probes whether a host:port actually serves Chromium's CDP /json/version endpoint, used to detect port drift between the pool-assigned port and the live listening port.
- _resolve_profile_port · function · L62-L139 — Resolves the account's Chromium debug port by preferring the multi-operator route table, falling back to PublishProfile config, then probing candidate ports to converge on the actually-listening port and avoid 9223/9224 drift.
- apply_login_qr · function · L143-L197 — Admin endpoint that captures the real login QR via CDP, encrypts it into MinIO, issues a single-use 90s TTL claim token, and sets the account login state to 'logging'.
- claim_login_qr · function · L201-L218 — Operator endpoint that verifies a single-use TTL claim token and returns a same-origin image proxy URL so the browser can load the QR without hitting internal MinIO presigned links.
- serve_login_qr_image · function · L222-L240 — Same-origin endpoint that downloads the Fernet-encrypted QR from MinIO, decrypts it, and returns the PNG so the frontend <img> can load it without JWT or internal MinIO access.
- login_scan_callback · function · L244-L267 — Callback endpoint that transitions the account login state to 'ready' on success or 'need_login' on failure after the operator confirms the WeChat scan.
- get_login_status · function · L271-L282 — Queries the account's current login-state machine value (logging/ready/need_login/expired), returning 'unknown' when no state exists.
- login_heartbeat · function · L286-L327 — 30-minute heartbeat that checks login validity via CDP and only downgrades to need_login (with risk alert) when a previously-ready session expires, while ignoring the login-page QR during an in-progress scan to avoid spurious alerts.
