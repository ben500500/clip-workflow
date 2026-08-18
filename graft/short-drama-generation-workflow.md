---
name: Short-Drama Generation Workflow
slug: short-drama-generation-workflow
type: system
sources:
  - path: frontend/src/pages/ShortDrama.tsx
    hash: ab59d2e4d45aacc0bfb7ac7f4909f2f6683f1b376b1004e0abbd0898ac38ae78
  - path: frontend/src/pages/Watermark.tsx
    hash: d2a6141474470acd093df4b0550711ab21ba683f4c4a805ed02418afaacb8e8e
sources_digest: f1a47e9c7977ab552841ca87370e45c7984909a8714f1778a2309766ab12691a
links:
  - to: frontend-api-layer
    relation: uses
    description: 'Calls shortdramaApi, watermarkApi, publishApi.'
  - to: publishing-material-generation
    relation: produces
    description: >-
      Watermark removal tasks carry prompt_record_id that PublishMaterialTab can
      auto-fill from.
generator:
  version: 1
covers:
  - symbol: ShortDrama
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L110-L1881'
  - symbol: handleGenerate
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L346-L378'
  - symbol: handleOptimize
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L381-L401'
  - symbol: handleCopy
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L403-L429'
  - symbol: clearForm
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L431-L442'
  - symbol: openTemplateEditor
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L445-L451'
  - symbol: handleSaveTemplates
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L453-L472'
  - symbol: resetTemplates
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L474-L485'
  - symbol: deleteRecord
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L487-L495'
  - symbol: handleUploadVideo
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L498-L510'
  - symbol: handleDeleteVideo
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L512-L524'
  - symbol: handleImportToWatermark
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L526-L544'
  - symbol: handleDoubaoAccountTypeChange
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L549-L557'
  - symbol: handleSwitchDoubaoAccount
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L561-L572'
  - symbol: handleDoubaoGenerate
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L575-L600'
  - symbol: handleDoubaoCancel
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L603-L618'
  - symbol: handleRewriteDecision
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L621-L655'
  - symbol: isDoubaoActive
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L658-L661'
  - symbol: isSeedanceActive
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L666-L669'
  - symbol: handleSeedanceGenerate
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L672-L703'
  - symbol: handleSeedanceCancel
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L706-L719'
  - symbol: switchDurationMode
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L722-L735'
  - symbol: saveDefaultDuration
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L738-L748'
  - symbol: handleDurationSelect
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L750-L753'
  - symbol: PromptResultBlock
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L1884-L1916'
  - symbol: PendingFile
    kind: interface
    at: 'frontend/src/pages/Watermark.tsx:L36-L46'
  - symbol: ImportedVideo
    kind: interface
    at: 'frontend/src/pages/Watermark.tsx:L49-L57'
  - symbol: pad4
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L69-L69'
  - symbol: genTaskName
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L71-L92'
  - symbol: p
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L73-L73'
  - symbol: Watermark
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L94-L1274'
  - symbol: loadDetail
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L184-L191'
  - symbol: handleSelectFiles
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L198-L239'
  - symbol: removePendingFile
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L241-L247'
  - symbol: clearPending
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L249-L256'
  - symbol: submitTask
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L259-L335'
  - symbol: toggleExpand
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L338-L353'
  - symbol: handleGoToPublish
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L358-L372'
  - symbol: retryTask
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L375-L406'
  - symbol: deleteTask
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L409-L419'
  - symbol: batchDelete
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L421-L435'
  - symbol: deleteVideo
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L437-L446'
  - symbol: downloadVideo
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L449-L456'
  - symbol: downloadBatch
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L458-L476'
  - symbol: renderVideos
    kind: function
    at: 'frontend/src/pages/Watermark.tsx:L596-L741'
---
<!-- context:generated:start -->
## Summary

ShortDrama orchestrates prompt generation and video creation via two independent channels (Doubao RPA and Seedance official API), with polling loops for both, QR-code login for Doubao, rewrite confirmation modals, and handoff to watermark removal and publishing. Persists editable prompt templates and per-user defaults (duration, Doubao account type). Watermark is the downstream removal page with four engines (remove_ai, seedance, seedance_wm, remove_mask), date-based task naming in localStorage, and preservation of prompt_record_id links from generation through removal to publishing.

## Related

- uses [[frontend-api-layer]] — Calls shortdramaApi, watermarkApi, publishApi.
- produces [[publishing-material-generation]] — Watermark removal tasks carry prompt_record_id that PublishMaterialTab can auto-fill from.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
