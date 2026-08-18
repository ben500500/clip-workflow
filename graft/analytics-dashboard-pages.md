---
name: Analytics Dashboard Pages
slug: analytics-dashboard-pages
type: system
sources:
  - path: frontend/src/pages/ContentAnalysis.tsx
    hash: 1de0b85ca3cbe4f4cc35bc29351449a7fec1da9c34671509c2d0be2c64689ca6
  - path: frontend/src/pages/DashboardOverview.tsx
    hash: af376ad99f95595d4f7ddcf63065029be22b9d838ba736ddb4ac550f12838fb2
  - path: frontend/src/pages/DashboardSettings.tsx
    hash: 85742b74611827641b3134a00b191b8155d48f993080842ab7e3edcdf3086f55
  - path: frontend/src/pages/DataImport.tsx
    hash: e4878acff05eb6067d0cea018315968ec441b2c4947d778725e14c52c00874e5
  - path: frontend/src/pages/DramaMonetization.tsx
    hash: 16c2d8a56ebfd7748507bd8eb2a434103a2ba9877650bbb88f93b7bd8b4d7c5f
  - path: frontend/src/pages/Ecosystem.tsx
    hash: 0a4a8eef054baa8c75483c841e0da155b1b911c3c3cdd0b9c450ce46b9abdae3
sources_digest: 274358f52e134d5ff3471f22b158e333b7d15835cce5ef01a0d4728d356ad625
links:
  - to: frontend-api-client-layer
    relation: uses
    description: >-
      All pages fetch via dashboardApi; DataImport uses
      smartImportUpload/importConfirm/downloadTemplate.
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
  - symbol: SmartImportPanel
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L15-L174'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L22-L41'
  - symbol: handleConfirm
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L43-L60'
  - symbol: ImportPanelProps
    kind: interface
    at: 'frontend/src/pages/DataImport.tsx:L178-L183'
  - symbol: ImportPanel
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L185-L249'
  - symbol: ImportHistoryPanel
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L253-L278'
  - symbol: DataImport
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L282-L342'
  - symbol: DramaMonetization
    kind: function
    at: 'frontend/src/pages/DramaMonetization.tsx:L14-L147'
  - symbol: Ecosystem
    kind: function
    at: 'frontend/src/pages/Ecosystem.tsx:L14-L92'
---
<!-- context:generated:start -->
## Summary

The analytics frontend: DashboardOverview (core revenue/play stats, 30-day trend via hand-rolled bar chart, IAA funnel as progress bars, top-5 videos), ContentAnalysis (sortable video metrics table + top-10 ranking + inline tag editor), DramaMonetization (ad/mini-program/drama tabs; drama endpoint called without date params so it may return all-time data), Ecosystem (article/read/OA/WeCom metrics), DashboardSettings (metric formulas, alert thresholds, attribution, display config), and DataImport (smart import with platform auto-detection and manual one-to-one field mapping, template import, history).

## Related

- uses [[frontend-api-client-layer]] — All pages fetch via dashboardApi; DataImport uses smartImportUpload/importConfirm/downloadTemplate.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
