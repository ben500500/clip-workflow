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
    at: 'frontend/src/pages/BatchSlice.tsx:L22-L28'
  - symbol: AutoClipConfig
    kind: interface
    at: 'frontend/src/pages/BatchSlice.tsx:L32-L39'
  - symbol: IntervalConfig
    kind: interface
    at: 'frontend/src/pages/BatchSlice.tsx:L41-L44'
  - symbol: SliceConfigState
    kind: interface
    at: 'frontend/src/pages/BatchSlice.tsx:L46-L83'
  - symbol: SlicePresetOption
    kind: interface
    at: 'frontend/src/pages/BatchSlice.tsx:L139-L177'
  - symbol: BatchSlicePage
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L218-L1412'
  - symbol: applySlicePreset
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L240-L281'
  - symbol: handleFileUpload
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L377-L394'
  - symbol: buildPayload
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L396-L436'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L438-L443'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L445-L450'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L452-L457'
  - symbol: handleRun
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L459-L485'
  - symbol: handleRetry
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L487-L505'
  - symbol: handleCancel
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L507-L525'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L527-L537'
  - symbol: renderOutputModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L539-L598'
  - symbol: handlePreviewOutput
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L601-L609'
  - symbol: openTrimModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L612-L621'
  - symbol: handleTrimRangeChange
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L624-L630'
  - symbol: submitTrim
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L633-L655'
  - symbol: renderPreviewModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L657-L670'
  - symbol: renderTrimModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L672-L725'
  - symbol: formatSize
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L727-L732'
  - symbol: OperatorForm
    kind: interface
    at: 'frontend/src/pages/ChannelAccounts.tsx:L37-L41'
  - symbol: ChannelAccounts
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L43-L531'
  - symbol: openCreate
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L85-L90'
  - symbol: openEdit
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L92-L107'
  - symbol: handleVideoAccountChange
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L110-L118'
  - symbol: handleSubmit
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L120-L146'
  - symbol: handleDelete
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L148-L156'
  - symbol: openOperator
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L159-L164'
  - symbol: handleAddOperator
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L166-L190'
  - symbol: handleRemoveOperator
    kind: function
    at: 'frontend/src/pages/ChannelAccounts.tsx:L192-L202'
  - symbol: VideoPreview
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L20-L144'
  - symbol: ClipReview
    kind: function
    at: 'frontend/src/pages/ClipReview.tsx:L147-L553'
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
    at: 'frontend/src/pages/ClipReview.tsx:L289-L296'
---
<!-- context:generated:start -->
## Summary

Operational pages for the Clip Workflow: BatchSlice (upload JSON manifest, run batch, poll expanded batches every 5s, trim finished outputs via sliceApi — trimming requires an episode_id, outputs without one cannot be edited), ClipReview (accept/reject/adjust auto-generated clip candidates with debounced time-range updates, treats 'adjusted' clips as valid alongside 'accepted'), and ChannelAccounts (channel ledger CRUD with auto-sync to the video account library and dual-track operator validation requiring either a system user ID or external name).

## Related

- uses [[frontend-api-layer]] — Uses batchSliceApi, sliceApi, autoclipApi, projectApi, channelAccountApi, publishApi, authApi.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
