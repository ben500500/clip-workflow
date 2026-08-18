---
name: RPA Route Table & Chaos Validation
slug: rpa-route-table-chaos-validation
type: concept
sources:
  - path: rpa/bootstrap.py
    hash: fc71189ee0a8c2bc77016dc39e71ec79d7ea1176d3b58770eb645e1a0fad3937
  - path: scripts/chaos_drill.py
    hash: 31d17a15c64f37d71e65a5f2dcebac86afff3baeb92d82d7f5cb1a15ddfeccd3
sources_digest: ccb86b410ba6845791228955a2e671c9b5ba01d43d16594bc4423f2bed9caf79
links:
  - to: rpa-multi-operator-container
    relation: validates
    description: >-
      Chaos drill injects failures and checks route table/profile recovery in
      the RPA container.
generator:
  version: 1
covers:
  - symbol: main
    kind: function
    at: 'rpa/bootstrap.py:L20-L53'
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

The multi-operator routing state lives in Redis keys pub:route:* and pub:profiles, maintained by the backend's sync_multi_operator_profiles beat task. The chaos drill script validates self-healing by injecting Chromium crashes, Redis restarts, and worker restarts, waiting for recovery within configurable windows (45s/60s/90s). The worker scenario cannot automatically assert zero duplicate sends (only a log-checking hint), while the Chromium scenario treats expired-state detection as the hard pass criterion and ready-state recovery as observational.

## Related

- validates [[rpa-multi-operator-container]] — Chaos drill injects failures and checks route table/profile recovery in the RPA container.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
