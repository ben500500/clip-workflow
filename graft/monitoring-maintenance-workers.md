---
name: 'Monitoring, Maintenance & Workers'
slug: monitoring-maintenance-workers
type: system
sources:
  - path: frontend/src/pages/Maintenance.tsx
    hash: afb0711b1761bbeb97ae58590a2fb408efe0469ad67fb671b1f4b74bd5456ec6
  - path: frontend/src/pages/Monitor.tsx
    hash: 3bb49845fa614feb89ee0cb6e8ce26cb6e2f1b6b18a4485f5c72fa36d9345f33
  - path: frontend/src/pages/Workers.tsx
    hash: 9a2b2a8ff2885cbef5be14a95d5c9f22e757dd9770b5c7e3d588a3dc3c6b22b6
sources_digest: 8505a40c32eb76085da3c63871c31c73821a607a2e53d5707922a709a4344394
links:
  - to: frontend-api-layer
    relation: uses
    description: 'Uses monitorApi, maintenanceApi, sliceApi for worker/engine operations.'
generator:
  version: 1
covers:
  - symbol: Maintenance
    kind: function
    at: 'frontend/src/pages/Maintenance.tsx:L13-L199'
  - symbol: fetchStatus
    kind: function
    at: 'frontend/src/pages/Maintenance.tsx:L22-L34'
  - symbol: handleArchive
    kind: function
    at: 'frontend/src/pages/Maintenance.tsx:L40-L57'
  - symbol: onOk
    kind: method
    at: 'frontend/src/pages/Maintenance.tsx:L47-L55'
  - symbol: handleCleanup
    kind: function
    at: 'frontend/src/pages/Maintenance.tsx:L59-L67'
  - symbol: handleLifecycle
    kind: function
    at: 'frontend/src/pages/Maintenance.tsx:L69-L85'
  - symbol: onOk
    kind: method
    at: 'frontend/src/pages/Maintenance.tsx:L75-L83'
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
  - symbol: WorkersPage
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L39-L555'
  - symbol: fetchWorkers
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L49-L61'
  - symbol: syncFromRedis
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L63-L74'
  - symbol: toggleWorker
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L77-L93'
  - symbol: adjustCpuPercent
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L96-L113'
  - symbol: removeWorker
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L116-L127'
  - symbol: fetchEnginesStatus
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L130-L137'
  - symbol: pushUpdate
    kind: function
    at: 'frontend/src/pages/Workers.tsx:L140-L152'
---
<!-- context:generated:start -->
## Summary

Monitor aggregates health checks, metrics, alert rules, and events with CRUD and a manual alert-check trigger, mapping internal metric keys (worker_offline, disk_usage) to Chinese labels; assumes backend provides runAlertCheck returning triggered/notified counts. Maintenance handles archiving old metrics, temp-file cleanup, and MinIO lifecycle policies (phase three), with destructive actions guarded by Modal.confirm. Workers is the distributed node dashboard: enable/disable, CPU allocation, Redis sync, engine push, 10s polling, and server engine-version comparison to flag nodes needing updates.

## Related

- uses [[frontend-api-layer]] — Uses monitorApi, maintenanceApi, sliceApi for worker/engine operations.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
