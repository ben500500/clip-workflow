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
    at: 'frontend/src/pages/DramaLibrary.tsx:L49-L78'
  - symbol: handle
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L54-L66'
  - symbol: DramaLibrary
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L80-L1026'
  - symbol: doSearch
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L162-L162'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L165-L170'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L172-L187'
  - symbol: onTopicPresetChange
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L190-L195'
  - symbol: submit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L197-L224'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L226-L234'
  - symbol: openDetail
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L237-L254'
  - symbol: loadSliceStatus
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L257-L267'
  - symbol: loadLanConfig
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L270-L277'
  - symbol: loadLanDramas
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L280-L290'
  - symbol: previewLanDrama
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L293-L307'
  - symbol: submitLanImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L310-L327'
  - symbol: pollLanTask
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L330-L354'
  - symbol: lanToSlice
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L357-L365'
  - symbol: saveLinkedEpisodes
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L368-L381'
  - symbol: setCover
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L383-L394'
  - symbol: addStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L396-L406'
  - symbol: removeStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L408-L419'
  - symbol: linkAccounts
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L421-L431'
  - symbol: resetImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L434-L441'
  - symbol: onImportFile
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L443-L460'
  - symbol: toggleNew
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L462-L466'
  - symbol: toggleUpdate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L467-L471'
  - symbol: doImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L473-L515'
  - symbol: accountNameById
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L569-L569'
---
<!-- context:generated:start -->
## Summary

Full CRUD admin page for drama records: searchable table, create/edit modal, detail drawer with cover/still image management and video-account linking, plus a multi-step Excel import wizard with diff preview (new vs updated rows) and row selection. Uses hardcoded enums for frequency/type/rating/listing status and DraggableUpload for image uploads returning file keys.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
