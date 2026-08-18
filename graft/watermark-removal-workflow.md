---
name: Watermark Removal Workflow
slug: watermark-removal-workflow
type: system
sources:
  - path: frontend/src/pages/Watermark.tsx
    hash: d2a6141474470acd093df4b0550711ab21ba683f4c4a805ed02418afaacb8e8e
sources_digest: 417dec2ddb736f9e791385a3516281eb049d86e4a5179d7fe8e4f7c7a9a4380b
links:
  - to: short-drama-production-workflow
    relation: uses
    description: Accepts imported videos from the short-film generation flow via props.
generator:
  version: 1
covers:
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

Watermark page uploads videos, configures one of four removal engines (remove_ai, seedance, seedance_wm, remove_mask) each with its own options, submits batch tasks, and polls progress. Generates task names with a date-based sequence in localStorage, preserves prompt_record_id links from prompt generation through to publishing, and uses blob URLs for local previews that are revoked after upload/submission.

## Related

- uses [[short-drama-production-workflow]] — Accepts imported videos from the short-film generation flow via props.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
