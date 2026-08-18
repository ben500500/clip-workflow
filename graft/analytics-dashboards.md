---
name: Analytics Dashboards
slug: analytics-dashboards
type: system
sources:
  - path: frontend/src/pages/FunnelAnalysis.tsx
    hash: 10c6a4a1c034af981614b3bf7490ac5e252cb8c4054c2c8a5ab0fd746e11e1ba
  - path: frontend/src/pages/ShortDramaAnalysis.tsx
    hash: 15c881c898656ef7cf9244fddd812b9fd2c91301b9facdd10acb545e542c4c95
sources_digest: b156ae6f67cf5e12b5f1a1cc3aa4e383d53a1efb4a1f65f340a96e3b2c8d1d67
links:
  - to: frontend-api-layer
    relation: uses
    description: Both call dashboardApi for trend/summary/analysis/topics data.
generator:
  version: 1
covers:
  - symbol: FunnelAnalysis
    kind: function
    at: 'frontend/src/pages/FunnelAnalysis.tsx:L12-L180'
  - symbol: renderChange
    kind: function
    at: 'frontend/src/pages/FunnelAnalysis.tsx:L51-L55'
  - symbol: TagCell
    kind: function
    at: 'frontend/src/pages/ShortDramaAnalysis.tsx:L30-L49'
  - symbol: ShortDramaAnalysis
    kind: function
    at: 'frontend/src/pages/ShortDramaAnalysis.tsx:L51-L286'
  - symbol: fetchData
    kind: function
    at: 'frontend/src/pages/ShortDramaAnalysis.tsx:L65-L87'
---
<!-- context:generated:start -->
## Summary

FunnelAnalysis renders the conversion funnel (play→jump→mini-program UV→drama play→ad exposure→revenue) with week-over-week comparison, computing the latest funnel step from the last trend entry. ShortDramaAnalysis is the per-video performance dashboard across WeChat Channels/Douyin/Kuaishou with a 30-day default range, fixed 20-row page size, and jump_click_count shown only for WeChat Channels. Both call dashboardApi in parallel and memoize columns for performance.

## Related

- uses [[frontend-api-layer]] — Both call dashboardApi for trend/summary/analysis/topics data.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
