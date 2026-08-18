---
name: Worker Node Management
slug: worker-node-management
type: system
sources:
  - path: frontend/src/pages/Workers.tsx
    hash: 9a2b2a8ff2885cbef5be14a95d5c9f22e757dd9770b5c7e3d588a3dc3c6b22b6
sources_digest: 2f1c51a1f3fef31f5b680e3cb021cce9d9b2aea956dbd37e0754775a954db323
links: []
generator:
  version: 1
covers:
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

Workers page monitors and controls distributed worker nodes handling video slicing: enable/disable, CPU allocation percentage, delete, Redis sync, and engine update push. Polls every 10 seconds and fetches server engine version via sliceApi.getEnginesStatus to determine which nodes need updates. Handles offline nodes, unknown versions, and progress for different task modes.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
