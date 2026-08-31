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
    at: 'frontend/src/pages/DramaLibrary.tsx:L52-L81'
  - symbol: handle
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L57-L69'
  - symbol: DramaLibrary
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L83-L1206'
  - symbol: doSearch
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L178-L178'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L181-L186'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L188-L204'
  - symbol: onTopicPresetChange
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L207-L212'
  - symbol: submit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L214-L242'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L244-L252'
  - symbol: runFeishuSync
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L259-L275'
  - symbol: openDetail
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L278-L297'
  - symbol: loadSliceStatus
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L300-L310'
  - symbol: loadLanConfig
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L313-L320'
  - symbol: loadDuploadConfig
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L323-L330'
  - symbol: submitDuploadPush
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L333-L344'
  - symbol: loadLanDramas
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L347-L361'
  - symbol: previewLanDrama
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L365-L389'
  - symbol: submitLanImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L392-L409'
  - symbol: pollLanTask
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L412-L436'
  - symbol: lanToSlice
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L439-L447'
  - symbol: saveLinkedEpisodes
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L450-L463'
  - symbol: setCover
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L465-L476'
  - symbol: addStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L478-L488'
  - symbol: removeStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L490-L501'
  - symbol: linkAccounts
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L503-L513'
  - symbol: resetImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L516-L523'
  - symbol: onImportFile
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L525-L542'
  - symbol: toggleNew
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L544-L548'
  - symbol: toggleUpdate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L549-L553'
  - symbol: doImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L555-L601'
  - symbol: accountNameById
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L666-L666'
---
<!-- context:generated:start -->
## Summary

Full CRUD admin page for drama records: searchable table, create/edit modal, detail drawer with cover/still image management and video-account linking, plus a multi-step Excel import wizard with diff preview (new vs updated rows) and row selection. Uses hardcoded enums for frequency/type/rating/listing status and DraggableUpload for image uploads returning file keys.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
