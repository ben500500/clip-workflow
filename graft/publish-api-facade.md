---
name: Publish API Facade
slug: publish-api-facade
type: system
sources:
  - path: backend/app/api/publish_common.py
    hash: 4868406e56b4d4c9be6f8eeef632e20fc13e6ad84d7db1134d835e4a824ff871
  - path: backend/app/api/publish.py
    hash: b3b9db449f27d51c276f5b2add098a045e84775d2530eee89eda00988fce3e21
sources_digest: 46058f6a7a7771f5f891859f455cfe5779e9cb63a6a2d6f3e8059e3d06a8104f
links:
  - to: backend-app-factory-auth
    relation: uses
    description: Sub-routers depend on get_current_user and require_roles from app.auth.
  - to: publish-tasks-scheduling
    relation: part_of
    description: >-
      Facade includes publish_tasks, publish_profiles, publish_video_accounts,
      publish_mini_programs, publish_batches, publish_time_slots, publish_audit,
      publish_login_qr routers.
generator:
  version: 1
covers:
  - symbol: _serialize_publish_task
    kind: function
    at: 'backend/app/api/publish_common.py:L19-L50'
  - symbol: _require_admin
    kind: function
    at: 'backend/app/api/publish_common.py:L53-L56'
---
<!-- context:generated:start -->
## Summary

Compositional facade router aggregating all publish subdomains (tasks, profiles, video-accounts, mini-programs, batches, time-slots, audit, login-QR) into one router mounted under /api. No business logic lives here; it preserves the original URL structure after the monolithic publish.py (~1666 lines) was split. Any new publish subdomain must be manually added to this facade.

## Related

- uses [[backend-app-factory-auth]] — Sub-routers depend on get_current_user and require_roles from app.auth.
- part of [[publish-tasks-scheduling]] — Facade includes publish_tasks, publish_profiles, publish_video_accounts, publish_mini_programs, publish_batches, publish_time_slots, publish_audit, publish_login_qr routers.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
