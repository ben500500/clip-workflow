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
    at: 'frontend/src/pages/DramaLibrary.tsx:L47-L76'
  - symbol: handle
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L52-L64'
  - symbol: DramaLibrary
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L78-L794'
  - symbol: doSearch
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L140-L140'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L143-L148'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L150-L164'
  - symbol: submit
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L166-L192'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L194-L202'
  - symbol: openDetail
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L205-L219'
  - symbol: loadSliceStatus
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L222-L232'
  - symbol: saveLinkedEpisodes
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L235-L248'
  - symbol: setCover
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L250-L261'
  - symbol: addStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L263-L273'
  - symbol: removeStill
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L275-L286'
  - symbol: linkAccounts
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L288-L298'
  - symbol: resetImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L301-L308'
  - symbol: onImportFile
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L310-L327'
  - symbol: toggleNew
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L329-L333'
  - symbol: toggleUpdate
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L334-L338'
  - symbol: doImport
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L340-L382'
  - symbol: accountNameById
    kind: function
    at: 'frontend/src/pages/DramaLibrary.tsx:L436-L436'
---
<!-- context:generated:start -->
## Summary

Full CRUD admin page for drama records: searchable table, create/edit modal, detail drawer with cover/still image management and video-account linking, plus a multi-step Excel import wizard with diff preview (new vs updated rows) and row selection. Uses hardcoded enums for frequency/type/rating/listing status and DraggableUpload for image uploads returning file keys.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
