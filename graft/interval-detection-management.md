---
name: Interval Detection Management
slug: interval-detection-management
type: system
sources:
  - path: frontend/src/pages/IntervalDetection.tsx
    hash: 79884e669eac86dd85750ef8e5c9bac5c8db09fc4aeed49ff97c9488c8219159
sources_digest: 34ccef51af30115334677614cd4bdb853de822e7e58ee6c109b82bc66c68aa72
links: []
generator:
  version: 1
covers:
  - symbol: IntervalDetection
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L14-L187'
  - symbol: fetchIntervals
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L23-L33'
  - symbol: toggle
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L63-L70'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L72-L80'
  - symbol: createManual
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L82-L93'
---
<!-- context:generated:start -->
## Summary

IntervalDetection page manages detected intervals within an episode: table with CRUD, live detection progress polling every 3 seconds, and a manual creation modal supporting four interval types (credits, static, watermark, custom). Watermark intervals have no auto-detector and must be added manually. Auto-refreshes the list when detection completes.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
