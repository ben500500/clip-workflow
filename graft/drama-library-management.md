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
    at: 'frontend/src/pages/DramaLibrary.tsx:L65-L94'
  - symbol: handle
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L70-L82'
  - symbol: DramaLibrary
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L96-L1358'
  - symbol: doSearch
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L213-L213'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L216-L221'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L223-L240'
  - symbol: onTopicPresetChange
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L243-L248'
  - symbol: submit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L250-L279'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L281-L289'
  - symbol: loadFeishuStatus
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L299-L309'
  - symbol: runFeishuSync
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L316-L332'
  - symbol: runFeishuRosterSync
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L335-L358'
  - symbol: openDetail
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L361-L380'
  - symbol: loadSliceStatus
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L383-L393'
  - symbol: loadLanConfig
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L396-L403'
  - symbol: loadDuploadConfig
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L406-L413'
  - symbol: submitDuploadPush
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L416-L427'
  - symbol: loadLanDramas
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L430-L444'
  - symbol: previewLanDrama
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L448-L472'
  - symbol: submitLanImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L475-L492'
  - symbol: pollLanTask
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L495-L519'
  - symbol: lanToSlice
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L522-L530'
  - symbol: saveLinkedEpisodes
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L533-L546'
  - symbol: setCover
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L548-L559'
  - symbol: addStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L561-L571'
  - symbol: removeStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L573-L584'
  - symbol: linkAccounts
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L586-L596'
  - symbol: resetImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L599-L606'
  - symbol: onImportFile
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L608-L625'
  - symbol: toggleNew
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L627-L631'
  - symbol: toggleUpdate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L632-L636'
  - symbol: doImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L638-L684'
  - symbol: accountNameById
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L742-L742'
---
<!-- context:generated:start -->
## Summary

Full CRUD admin page for drama records: searchable table, create/edit modal, detail drawer with cover/still image management and video-account linking, plus a multi-step Excel import wizard with diff preview (new vs updated rows) and row selection. Uses hardcoded enums for frequency/type/rating/listing status and DraggableUpload for image uploads returning file keys.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
