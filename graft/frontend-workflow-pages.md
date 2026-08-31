---
name: frontend workflow pages
slug: frontend-workflow-pages
type: system
sources:
  - path: frontend/src/pages/BatchSlice.tsx
    hash: f2a0cd97d8d1487af1465214f77bc3ec7ec1aa082e10ba9b0f548876495a73ce
  - path: frontend/src/pages/ChannelAccounts.tsx
    hash: 18c5f77524864cc6f01d508cbe11f1fc92940fe42ec9db2e11efb7188e39cec0
  - path: frontend/src/pages/ClipReview.tsx
    hash: 4a7b792b497352545dbb458fa7d426c3e7980ef7c657b70352fb078a262e4e71
sources_digest: 5166de0e230cd48f5a092969063bb49ce7bf3410b3023ddd7284fc8dc1d80680
links:
  - to: frontend-api-layer
    relation: uses
    description: >-
      Uses batchSliceApi, sliceApi, autoclipApi, projectApi, channelAccountApi,
      publishApi, authApi.
generator:
  version: 1
covers:
  - symbol: FlattenOutput
    kind: interface
    at: 'frontend/src/pages/BatchSlice.tsx:L24-L30'
  - symbol: IntervalConfig
    kind: interface
    at: 'frontend/src/pages/BatchSlice.tsx:L34-L37'
  - symbol: SliceConfigState
    kind: type
    at: 'frontend/src/pages/BatchSlice.tsx:L42-L45'
  - symbol: BatchSlicePage
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L95-L1273'
  - symbol: applySlicePreset
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L110-L126'
  - symbol: handleFileUpload
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L222-L239'
  - symbol: buildPayload
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L241-L265'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L267-L272'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L274-L279'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L281-L286'
  - symbol: handleRun
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L288-L314'
  - symbol: handleRetry
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L316-L334'
  - symbol: handleCancel
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L336-L354'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L356-L366'
  - symbol: renderOutputModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L368-L426'
  - symbol: handlePreviewOutput
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L429-L437'
  - symbol: openTrimModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L440-L449'
  - symbol: handleTrimRangeChange
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L452-L458'
  - symbol: submitTrim
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L461-L483'
  - symbol: renderPreviewModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L485-L498'
  - symbol: renderTrimModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L500-L553'
  - symbol: formatSize
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L555-L560'
  - symbol: OperatorForm
    kind: interface
    at: 'frontend/src/pages/ChannelAccounts.tsx:L38-L42'
  - symbol: ChannelAccounts
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L44-L690'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L107-L112'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L114-L130'
  - symbol: handleVideoAccountChange
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L133-L141'
  - symbol: handleSubmit
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L143-L169'
  - symbol: handleDelete
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L171-L179'
  - symbol: openTheaterCreate
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L182-L186'
  - symbol: openTheaterEdit
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L188-L192'
  - symbol: handleTheaterSubmit
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L194-L215'
  - symbol: handleTheaterDelete
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L217-L229'
  - symbol: handleTheaterFilterChange
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L231-L234'
  - symbol: openOperator
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L237-L242'
  - symbol: handleAddOperator
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L244-L268'
  - symbol: handleRemoveOperator
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L270-L280'
  - symbol: VideoPreview
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L20-L144'
  - symbol: ClipReview
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L147-L585'
  - symbol: fetchClips
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L158-L169'
  - symbol: fetchVideoUrl
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L171-L178'
  - symbol: updateStatus
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L186-L194'
  - symbol: batchUpdate
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L197-L216'
  - symbol: batchAllUpdate
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L219-L234'
  - symbol: adjust
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L237-L245'
  - symbol: adjustDebounced
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L248-L257'
  - symbol: onTitleClick
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L291-L298'
---
<!-- context:generated:start -->
## Summary

Operational pages for the Clip Workflow: BatchSlice (upload JSON manifest, run batch, poll expanded batches every 5s, trim finished outputs via sliceApi — trimming requires an episode_id, outputs without one cannot be edited), ClipReview (accept/reject/adjust auto-generated clip candidates with debounced time-range updates, treats 'adjusted' clips as valid alongside 'accepted'), and ChannelAccounts (channel ledger CRUD with auto-sync to the video account library and dual-track operator validation requiring either a system user ID or external name).

## Related

- uses [[frontend-api-layer]] — Uses batchSliceApi, sliceApi, autoclipApi, projectApi, channelAccountApi, publishApi, authApi.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
