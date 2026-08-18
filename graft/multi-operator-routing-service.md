---
name: Multi-Operator Routing Service
slug: multi-operator-routing-service
type: system
sources:
  - path: backend/app/services/multi_operator.py
    hash: 811139459b1b4475190b263ebc79f1d373b59d79ea53693a499b277f8f61194e
sources_digest: e2dccedbb022819284468df3e64038c2ecfaced64001991438d63aad774410bc
links:
  - to: rpa-publishing-service
    relation: uses
    description: >-
      Provides CDP connection routing and tokens that publish_service consumes
      for authenticated CDP URLs
  - to: wechat-download-pipeline
    relation: uses
    description: >-
      preview_client routes through multi_operator to get a CDP connection for
      the logged-in WeChat account
generator:
  version: 1
covers:
  - symbol: _redis
    kind: function
    at: 'backend/app/services/multi_operator.py:L91-L93'
  - symbol: multi_operator_enabled
    kind: function
    at: 'backend/app/services/multi_operator.py:L96-L103'
  - symbol: set_flag
    kind: function
    at: 'backend/app/services/multi_operator.py:L106-L111'
  - symbol: resolve_port
    kind: function
    at: 'backend/app/services/multi_operator.py:L114-L134'
  - symbol: get_route
    kind: function
    at: 'backend/app/services/multi_operator.py:L137-L143'
  - symbol: register_route
    kind: function
    at: 'backend/app/services/multi_operator.py:L146-L166'
  - symbol: alloc_port
    kind: function
    at: 'backend/app/services/multi_operator.py:L169-L181'
  - symbol: mark_heartbeat
    kind: function
    at: 'backend/app/services/multi_operator.py:L184-L192'
  - symbol: mark_expired
    kind: function
    at: 'backend/app/services/multi_operator.py:L195-L201'
  - symbol: set_ready
    kind: function
    at: 'backend/app/services/multi_operator.py:L204-L209'
  - symbol: check_route_heartbeats
    kind: function
    at: 'backend/app/services/multi_operator.py:L212-L258'
  - symbol: _seconds_until_midnight
    kind: function
    at: 'backend/app/services/multi_operator.py:L261-L264'
  - symbol: acquire_quota
    kind: function
    at: 'backend/app/services/multi_operator.py:L267-L290'
  - symbol: release_inflight
    kind: function
    at: 'backend/app/services/multi_operator.py:L293-L300'
  - symbol: get_daily_used
    kind: function
    at: 'backend/app/services/multi_operator.py:L303-L309'
  - symbol: get_profiles
    kind: function
    at: 'backend/app/services/multi_operator.py:L312-L319'
  - symbol: sync_profiles_from_db
    kind: function
    at: 'backend/app/services/multi_operator.py:L322-L369'
  - symbol: save_pending
    kind: function
    at: 'backend/app/services/multi_operator.py:L375-L381'
  - symbol: get_pending
    kind: function
    at: 'backend/app/services/multi_operator.py:L384-L390'
  - symbol: delete_pending
    kind: function
    at: 'backend/app/services/multi_operator.py:L393-L398'
  - symbol: freeze_pending
    kind: function
    at: 'backend/app/services/multi_operator.py:L401-L416'
  - symbol: issue_cdp_token
    kind: function
    at: 'backend/app/services/multi_operator.py:L422-L437'
  - symbol: verify_cdp_token
    kind: function
    at: 'backend/app/services/multi_operator.py:L440-L458'
  - symbol: _fmt_ts
    kind: function
    at: 'backend/app/services/multi_operator.py:L464-L471'
  - symbol: get_route_matrix
    kind: function
    at: 'backend/app/services/multi_operator.py:L474-L511'
  - symbol: get_verification_status
    kind: function
    at: 'backend/app/services/multi_operator.py:L514-L582'
  - symbol: get_operator_stats
    kind: function
    at: 'backend/app/services/multi_operator.py:L585-L608'
---
<!-- context:generated:start -->
## Summary

Redis-backed routing, port allocation, quota enforcement, and pending task persistence for multi-account publishing. Uses Lua scripts for atomic port pool allocation and dual-gate quota checks (per-account and per-operator). Feature-flagged (MULTI_OPERATOR_ENABLED) for zero-intrusion fallback to legacy ports; 20-second heartbeat failure window before marking routes expired; single-use CDP tokens with 60-second TTLs to prevent replay attacks.

## Related

- uses [[rpa-publishing-service]] — Provides CDP connection routing and tokens that publish_service consumes for authenticated CDP URLs
- uses [[wechat-download-pipeline]] — preview_client routes through multi_operator to get a CDP connection for the logged-in WeChat account
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
