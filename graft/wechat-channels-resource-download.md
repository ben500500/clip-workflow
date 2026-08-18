---
name: WeChat Channels Resource Download
slug: wechat-channels-resource-download
type: system
sources:
  - path: frontend/src/pages/ResourceDownload.tsx
    hash: 2ed21b7206ae05a055bddb66a2c4f5dda28b3fdfb7a3eae8acfbe3ac7f0886e1
sources_digest: cad804860b56b77aa0641e782ed33e01e55ab187d41eebe5dfc1173f17dda0fa
links: []
generator:
  version: 1
covers:
  - symbol: ImportPanel
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L32-L179'
  - symbol: handleResolutionChange
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L50-L57'
  - symbol: handleImport
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L59-L97'
  - symbol: TaskListPanel
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L182-L514'
  - symbol: handleToSlice
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L211-L222'
  - symbol: canImport
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L252-L252'
  - symbol: openPreview
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L254-L266'
  - symbol: openImport
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L268-L281'
  - symbol: handleImportConfirm
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L283-L308'
  - symbol: metaDuration
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L310-L317'
  - symbol: ProvidersPanel
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L517-L625'
  - symbol: renderBalance
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L531-L553'
  - symbol: ResourceDownload
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L628-L654'
---
<!-- context:generated:start -->
## Summary

ResourceDownload page manages WeChat Channels video downloads in three tabs: link import (single/batch URL to create tasks, with a global default resolution persisted via configApi), task monitoring with live WebSocket progress (/ws/wechat-dl/{taskId}), and provider status. Offers two completion paths: import into a slicing project or direct queueing into the slicing pipeline. WebSocket cleanup on task ID change is a noted gotcha.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
