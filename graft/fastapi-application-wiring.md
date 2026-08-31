---
name: FastAPI Application Wiring
slug: fastapi-application-wiring
type: system
sources:
  - path: backend/app/main.py
    hash: 48e1415d633aea9f92e66063204d5263b995fd4d08dcc2d5d0bb00e831db6270
sources_digest: 85cd5467ae72ef3065799d3f6cb370d08621076b22d5c95809d8bf8be667dcc9
links:
  - to: auth-session-layer
    relation: uses
    description: Global get_current_user dependency on mounted routers
  - to: configuration-database-bootstrap
    relation: uses
    description: Lifespan calls init_db and seeds defaults
  - to: worker-node-management-engine-update
    relation: part_of
    description: Workers router mounted under /api
generator:
  version: 1
covers:
  - symbol: _create_seed_users
    kind: function
    at: 'backend/app/main.py:L38-L78'
  - symbol: _create_seed_platform_profiles
    kind: function
    at: 'backend/app/main.py:L81-L101'
  - symbol: _create_seed_alert_rules
    kind: function
    at: 'backend/app/main.py:L104-L106'
  - symbol: lifespan
    kind: function
    at: 'backend/app/main.py:L110-L124'
  - symbol: websocket_wechat_dl
    kind: function
    at: 'backend/app/main.py:L154-L191'
  - symbol: websocket_lan_source
    kind: function
    at: 'backend/app/main.py:L195-L230'
  - symbol: health_check
    kind: function
    at: 'backend/app/main.py:L263-L265'
  - symbol: health_check_detailed
    kind: function
    at: 'backend/app/main.py:L269-L272'
---
<!-- context:generated:start -->
## Summary

Entry point mounting all routers under /api with JWT auth, CORS, lifespan DB init + seed users (DEBUG-only from SEED_USERS_JSON to avoid weak prod passwords), WebSocket /ws/wechat-dl/{task_id} subscribing to Redis pub/sub. Auth router and login QR image proxy left unauthenticated (img tags can't carry JWT); Go slice-worker callback/heartbeat routes use token-based auth instead of global dependency. /api/health/detailed checks DB, Redis, MinIO, disk.

## Related

- uses [[auth-session-layer]] — Global get_current_user dependency on mounted routers
- uses [[configuration-database-bootstrap]] — Lifespan calls init_db and seeds defaults
- part of [[worker-node-management-engine-update]] — Workers router mounted under /api
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
