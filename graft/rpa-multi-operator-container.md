---
name: RPA Multi-Operator Container
slug: rpa-multi-operator-container
type: system
sources:
  - path: rpa/bootstrap.py
    hash: fc71189ee0a8c2bc77016dc39e71ec79d7ea1176d3b58770eb645e1a0fad3937
  - path: rpa/cdp_proxy.py
    hash: d2fc8389048322e3baaf04c389c06c7c7c5e9720792afa5861dbd7f6b677a5c5
  - path: rpa/start_chromium.sh
    hash: 9947e5aebc1d96e7355e96ca472ad11b93f98e2c5d590816eec9c5164491cae0
sources_digest: 8d182e536b2cff303966bda391e29cdcccc5890ffeebb34496f589adf92d96da
links:
  - to: rpa-route-table-chaos-validation
    relation: depends_on
    description: >-
      The Redis pub:profiles key is populated by the backend's
      sync_multi_operator_profiles beat task; chaos drill validates route table
      recovery.
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
---
<!-- context:generated:start -->
## Summary

The RPA container runs Chromium instances for the Doubao generation/publishing pipeline, with bootstrap.py fetching the multi-operator profile list from Redis (pub:profiles) into /app/profiles.json, start_chromium.sh launching per-profile Chromium instances with isolated user-data-dirs and unique debug ports, and cdp_proxy.py bridging external clients to Chromium's localhost-only DevTools protocol with Bearer-token auth (single-use, 60s TTL). Gracefully degrades to single-instance mode when Redis is unavailable. Chromium 127+ only listens on 127.0.0.1 for debugging, which is intentional for security.

## Related

- depends on [[rpa-route-table-chaos-validation]] — The Redis pub:profiles key is populated by the backend's sync_multi_operator_profiles beat task; chaos drill validates route table recovery.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
