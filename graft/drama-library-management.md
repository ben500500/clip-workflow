---
name: Drama Library Management
slug: drama-library-management
type: system
sources:
  - path: frontend/src/pages/DramaLibrary.tsx
    hash: 56a3afcc829328654367def87c3362eb9d30f8133d27f39158d4303ba19cf777
sources_digest: a1336a4b576ca25463e33c98c970f4bbd717776dab0daa5ff502ba78fce108e4
links: []
generator:
  version: 1
covers:
  - symbol: DraggableUpload
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L38-L67'
  - symbol: handle
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L43-L55'
  - symbol: DramaLibrary
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L69-L677'
  - symbol: doSearch
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L127-L127'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L130-L135'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L137-L151'
  - symbol: submit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L153-L179'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L181-L189'
  - symbol: openDetail
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L192-L204'
  - symbol: setCover
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L206-L217'
  - symbol: addStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L219-L229'
  - symbol: removeStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L231-L242'
  - symbol: linkAccounts
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L244-L254'
  - symbol: resetImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L257-L264'
  - symbol: onImportFile
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L266-L283'
  - symbol: toggleNew
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L285-L289'
  - symbol: toggleUpdate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L290-L294'
  - symbol: doImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L296-L338'
  - symbol: accountNameById
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L392-L392'
---
<!-- context:generated:start -->
## Summary

Full CRUD admin page for drama records: searchable table, create/edit modal, detail drawer with cover/still image management and video-account linking, plus a multi-step Excel import wizard with diff preview (new vs updated rows) and row selection. Uses hardcoded enums for frequency/type/rating/listing status and DraggableUpload for image uploads returning file keys.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
