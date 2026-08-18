---
name: Maintenance Operations
slug: maintenance-operations
type: system
sources:
  - path: frontend/src/pages/Maintenance.tsx
    hash: afb0711b1761bbeb97ae58590a2fb408efe0469ad67fb671b1f4b74bd5456ec6
sources_digest: cd236b8ef0a9e1cb51c217e0a15a7343293ec126ac78b96fda232c08e8a1d5ef
links: []
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
---
<!-- context:generated:start -->
## Summary

Maintenance page handles operational tasks: archiving old dashboard metrics, cleaning temporary files, and applying MinIO storage lifecycle policies. Destructive actions (archive, lifecycle) are guarded by Modal.confirm while cleanup runs directly. Reflects a three-phase rollout with MinIO lifecycle as phase three, and exposes user-adjustable parameters (archive days, cleanup hours).
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
