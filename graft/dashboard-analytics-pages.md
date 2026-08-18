---
name: Dashboard Analytics Pages
slug: dashboard-analytics-pages
type: system
sources:
  - path: frontend/src/pages/DramaMonetization.tsx
    hash: 16c2d8a56ebfd7748507bd8eb2a434103a2ba9877650bbb88f93b7bd8b4d7c5f
  - path: frontend/src/pages/Ecosystem.tsx
    hash: 0a4a8eef054baa8c75483c841e0da155b1b911c3c3cdd0b9c450ce46b9abdae3
  - path: frontend/src/pages/FunnelAnalysis.tsx
    hash: 10c6a4a1c034af981614b3bf7490ac5e252cb8c4054c2c8a5ab0fd746e11e1ba
  - path: frontend/src/pages/ShortDramaAnalysis.tsx
    hash: 15c881c898656ef7cf9244fddd812b9fd2c91301b9facdd10acb545e542c4c95
sources_digest: 3f3a86144b9b02fbba17e70fa7c53e3ff1e7f5354efa71c9f15268c2ea6d4d18
links:
  - to: shared-frontend-types-formatting
    relation: uses
    description: >-
      Consumes FunnelData, EcosystemMetric, and dashboard metric types plus
      formatDate/formatPercent utilities.
generator:
  version: 1
covers:
  - symbol: DramaMonetization
    kind: function
    at: 'frontend/src/pages/DramaMonetization.tsx:L14-L147'
  - symbol: Ecosystem
    kind: function
    at: 'frontend/src/pages/Ecosystem.tsx:L14-L92'
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

A family of read-only analytics dashboards (monetization, funnel, ecosystem, short-drama analysis) that fetch aggregated metrics from dashboardApi over a date range (default 30 days) and render summary statistics plus tables. They share the same pattern: parallel Promise.all fetches, dayjs-based RangePicker triggering refetch, and inline client-side derivation of metrics like eCPM. A shared gotcha is that some endpoints (e.g. getDramaMetrics) ignore the selected date range.

## Related

- uses [[shared-frontend-types-formatting]] — Consumes FunnelData, EcosystemMetric, and dashboard metric types plus formatDate/formatPercent utilities.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
