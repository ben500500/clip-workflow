---
name: RPA Multi-Operator Infrastructure
slug: rpa-multi-operator-infrastructure
type: system
sources:
  - path: rpa/bootstrap.py
    hash: fc71189ee0a8c2bc77016dc39e71ec79d7ea1176d3b58770eb645e1a0fad3937
  - path: rpa/cdp_proxy.py
    hash: d2fc8389048322e3baaf04c389c06c7c7c5e9720792afa5861dbd7f6b677a5c5
  - path: rpa/start_chromium.sh
    hash: 9947e5aebc1d96e7355e96ca472ad11b93f98e2c5d590816eec9c5164491cae0
  - path: scripts/chaos_drill.py
    hash: 31d17a15c64f37d71e65a5f2dcebac86afff3baeb92d82d7f5cb1a15ddfeccd3
sources_digest: 6f8d239324e60c9180cfc8c9a2a3aadcca50a0716b9e49f97e82753cc3074937
links:
  - to: publishing-output-hub
    relation: implements
    description: >-
      PublishManagement's QR-code login flow and multi-operator verification
      depend on this profile/token infrastructure.
  - to: short-drama-generation-workflow
    relation: implements
    description: >-
      The Doubao RPA channel in ShortDrama connects to these Chromium instances
      via CDP for QR login and video generation.
generator:
  version: 1
covers:
  - symbol: main
    kind: function
    at: 'rpa/bootstrap.py:L20-L53'
  - symbol: _verify_token
    kind: function
    at: 'rpa/cdp_proxy.py:L42-L67'
  - symbol: _pipe
    kind: function
    at: 'rpa/cdp_proxy.py:L70-L85'
  - symbol: _read_head
    kind: function
    at: 'rpa/cdp_proxy.py:L88-L101'
  - symbol: _rewrite_request_host
    kind: function
    at: 'rpa/cdp_proxy.py:L104-L114'
  - symbol: _extract_bearer
    kind: function
    at: 'rpa/cdp_proxy.py:L117-L128'
  - symbol: _rewrite_response_body
    kind: function
    at: 'rpa/cdp_proxy.py:L131-L135'
  - symbol: _http_401
    kind: function
    at: 'rpa/cdp_proxy.py:L138-L144'
  - symbol: _handle
    kind: function
    at: 'rpa/cdp_proxy.py:L147-L238'
  - symbol: main
    kind: function
    at: 'rpa/cdp_proxy.py:L241-L282'
  - symbol: _redis_get
    kind: function
    at: 'scripts/chaos_drill.py:L54-L56'
  - symbol: _get_route_states
    kind: function
    at: 'scripts/chaos_drill.py:L59-L70'
  - symbol: _get_profiles
    kind: function
    at: 'scripts/chaos_drill.py:L73-L78'
  - symbol: _run_cmd
    kind: function
    at: 'scripts/chaos_drill.py:L83-L88'
  - symbol: inject_chromium_crash
    kind: function
    at: 'scripts/chaos_drill.py:L91-L102'
  - symbol: inject_redis_restart
    kind: function
    at: 'scripts/chaos_drill.py:L105-L108'
  - symbol: inject_worker_restart
    kind: function
    at: 'scripts/chaos_drill.py:L111-L116'
  - symbol: _wait_ready
    kind: function
    at: 'scripts/chaos_drill.py:L121-L138'
  - symbol: drill_chromium
    kind: function
    at: 'scripts/chaos_drill.py:L141-L160'
  - symbol: drill_redis
    kind: function
    at: 'scripts/chaos_drill.py:L163-L197'
  - symbol: drill_worker
    kind: function
    at: 'scripts/chaos_drill.py:L200-L210'
  - symbol: main
    kind: function
    at: 'scripts/chaos_drill.py:L215-L264'
---
<!-- context:generated:start -->
## Summary

The RPA container's multi-operator browser infrastructure: bootstrap.py fetches the profile list from Redis key pub:profiles and writes /app/profiles.json with three views (raw profiles, chrom_profiles for start_chromium.sh, cdp_profiles for cdp_proxy.py), degrading gracefully to single-instance mode if Redis is unreachable. start_chromium.sh probes a hardcoded list of Chromium binary paths across Playwright image versions, launches per-profile instances with isolated user-data-dirs and ports from the routing table pool, and exits if any instance dies or the profile set changes (MD5 signature check every 10s) to trigger autorestart. cdp_proxy.py bridges external clients to Chromium's localhost-only DevTools, rewriting Host headers to bypass DNS-rebinding protection, with a multi-tenant mode requiring single-use Bearer tokens (60s TTL) validated against Redis; /json/version is exempt as a health check. chaos_drill.py validates self-healing by injecting Chromium/Redis/worker crashes, treating expired-state detection as the hard pass criterion for Chromium.

## Related

- implements [[publishing-output-hub]] — PublishManagement's QR-code login flow and multi-operator verification depend on this profile/token infrastructure.
- implements [[short-drama-generation-workflow]] — The Doubao RPA channel in ShortDrama connects to these Chromium instances via CDP for QR login and video generation.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
