---
name: frontend dashboard & analytics pages
slug: frontend-dashboard-analytics-pages
type: system
sources:
  - path: frontend/src/pages/ContentAnalysis.tsx
    hash: 1de0b85ca3cbe4f4cc35bc29351449a7fec1da9c34671509c2d0be2c64689ca6
  - path: frontend/src/pages/Dashboard.tsx
    hash: 00e9ff53fdc99fbb14b9ed45e04d03b6a7f2a8eb50fb79999eb706b67a5719aa
  - path: frontend/src/pages/DashboardOverview.tsx
    hash: af376ad99f95595d4f7ddcf63065029be22b9d838ba736ddb4ac550f12838fb2
  - path: frontend/src/pages/DashboardSettings.tsx
    hash: 85742b74611827641b3134a00b191b8155d48f993080842ab7e3edcdf3086f55
sources_digest: 6399bc9a624a42c9f10061db68df36e9d2270f9ce64a6bc54c81dfb2d61f4975
links:
  - to: frontend-api-layer
    relation: uses
    description: All fetch via dashboardApi and projectApi.getStats.
generator:
  version: 1
covers:
  - symbol: ContentAnalysis
    kind: function
    at: 'frontend/src/pages/ContentAnalysis.tsx:L11-L197'
  - symbol: openTagEditor
    kind: function
    at: 'frontend/src/pages/ContentAnalysis.tsx:L26-L30'
  - symbol: addTag
    kind: function
    at: 'frontend/src/pages/ContentAnalysis.tsx:L32-L39'
  - symbol: saveTags
    kind: function
    at: 'frontend/src/pages/ContentAnalysis.tsx:L41-L51'
  - symbol: fetchVideos
    kind: function
    at: 'frontend/src/pages/ContentAnalysis.tsx:L53-L64'
  - symbol: Dashboard
    kind: function
    at: 'frontend/src/pages/Dashboard.tsx:L15-L118'
  - symbol: DashboardOverview
    kind: function
    at: 'frontend/src/pages/DashboardOverview.tsx:L16-L219'
  - symbol: DashboardConfig
    kind: interface
    at: 'frontend/src/pages/DashboardSettings.tsx:L10-L18'
  - symbol: DashboardSettings
    kind: function
    at: 'frontend/src/pages/DashboardSettings.tsx:L20-L134'
  - symbol: handleSave
    kind: function
    at: 'frontend/src/pages/DashboardSettings.tsx:L45-L55'
---
<!-- context:generated:start -->
## Summary

Analytics and monitoring pages: DashboardOverview (core revenue/play stats, 30-day trend via hand-rolled bar chart, IAA funnel as progress bars, top-5 videos, alert thresholds on eCPM/revenue-per-UV/jump/play rates), ContentAnalysis (paginated sortable video metrics table + top-10 ranking sidebar, inline tag editor), DashboardSettings (config form with nested field names for metric formulas, alert thresholds, attribution, display options), and Dashboard (project stats landing page).

## Related

- uses [[frontend-api-layer]] — All fetch via dashboardApi and projectApi.getStats.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
