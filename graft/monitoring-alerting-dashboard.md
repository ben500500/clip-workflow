---
name: Monitoring & Alerting Dashboard
slug: monitoring-alerting-dashboard
type: system
sources:
  - path: frontend/src/pages/Monitor.tsx
    hash: 3bb49845fa614feb89ee0cb6e8ce26cb6e2f1b6b18a4485f5c72fa36d9345f33
sources_digest: d1934891c152b1833fd5048efaebe12be841c1a004a9ff0b2163657bf4ab4ebc
links: []
generator:
  version: 1
covers:
  - symbol: HealthCheck
    kind: interface
    at: 'frontend/src/pages/Monitor.tsx:L14-L18'
  - symbol: Monitor
    kind: function
    at: 'frontend/src/pages/Monitor.tsx:L30-L336'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/Monitor.tsx:L67-L71'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/Monitor.tsx:L73-L77'
  - symbol: handleSave
    kind: function
    at: 'frontend/src/pages/Monitor.tsx:L79-L94'
  - symbol: handleDelete
    kind: function
    at: 'frontend/src/pages/Monitor.tsx:L96-L113'
  - symbol: onOk
    kind: method
    at: 'frontend/src/pages/Monitor.tsx:L103-L111'
  - symbol: handleRunCheck
    kind: function
    at: 'frontend/src/pages/Monitor.tsx:L115-L123'
---
<!-- context:generated:start -->
## Summary

Monitor page aggregates health checks, metric values, alert rules, and recent alert events with CRUD for rules and a manual alert-check trigger. Maps internal metric keys (worker_offline, disk_usage) to Chinese labels via METRIC_LABELS. Rule form includes metric, operator, threshold, level, and optional DingTalk webhook. Assumes backend provides runAlertCheck returning triggered/notified counts.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
