---
name: Login QR Self-Service
slug: login-qr-self-service
type: system
sources:
  - path: backend/app/services/login_qr_service.py
    hash: 386d7ed87b9bf35df0214242062d2d486ecbc6bdbefc83b8b762678b4f363dd6
sources_digest: db4ab59175fbc6bbc4278b8480b2baf86cd45184a573438a0c78940809ff13f7
links:
  - to: auth-session-layer
    relation: uses
    description: Fernet key derivation from COOKIE_ENCRYPT_KEY
  - to: redis-streams-real-time-state
    relation: uses
    description: Redis connections and claim-token storage
generator:
  version: 1
covers:
  - symbol: _redis
    kind: function
    at: 'backend/app/services/login_qr_service.py:L57-L60'
  - symbol: issue_claim
    kind: function
    at: 'backend/app/services/login_qr_service.py:L63-L76'
  - symbol: verify_claim_token
    kind: function
    at: 'backend/app/services/login_qr_service.py:L79-L85'
  - symbol: capture_login_qr
    kind: function
    at: 'backend/app/services/login_qr_service.py:L88-L152'
  - symbol: store_qr
    kind: function
    at: 'backend/app/services/login_qr_service.py:L155-L171'
  - symbol: encrypt_cookie_bytes
    kind: function
    at: 'backend/app/services/login_qr_service.py:L174-L180'
  - symbol: decrypt_cookie_bytes
    kind: function
    at: 'backend/app/services/login_qr_service.py:L183-L189'
  - symbol: get_qr_presigned_url
    kind: function
    at: 'backend/app/services/login_qr_service.py:L192-L195'
  - symbol: set_login_state
    kind: function
    at: 'backend/app/services/login_qr_service.py:L198-L209'
  - symbol: get_login_state
    kind: function
    at: 'backend/app/services/login_qr_service.py:L212-L215'
  - symbol: check_login_status_via_cdp
    kind: function
    at: 'backend/app/services/login_qr_service.py:L218-L255'
  - symbol: silent_keepalive
    kind: function
    at: 'backend/app/services/login_qr_service.py:L258-L281'
---
<!-- context:generated:start -->
## Summary

Self-service WeChat Channels login: captures real QR codes from browser profiles via CDP, encrypts with Fernet, stores in MinIO, issues single-use claim tokens (90s TTL) with atomic Lua-script verification preventing replay. Login state machine (logging/ready/need_login/expired) in Redis hashes. Critical constraint: never close the reused browser page after QR capture or the login session dies before scanning. Fallback for headless Chromium QR rendering failures.

## Related

- uses [[auth-session-layer]] — Fernet key derivation from COOKIE_ENCRYPT_KEY
- uses [[redis-streams-real-time-state]] — Redis connections and claim-token storage
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
