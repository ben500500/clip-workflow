---
name: Clip Workflow Pages
slug: clip-workflow-pages
type: system
sources:
  - path: frontend/src/pages/BatchSlice.tsx
    hash: dc98ccea38a0d0c5800ac23b90c721efc1cb2de626a31a570532df1966d7ce28
  - path: frontend/src/pages/ChannelAccounts.tsx
    hash: 18c5f77524864cc6f01d508cbe11f1fc92940fe42ec9db2e11efb7188e39cec0
  - path: frontend/src/pages/ClipReview.tsx
    hash: 4a7b792b497352545dbb458fa7d426c3e7980ef7c657b70352fb078a262e4e71
  - path: frontend/src/pages/Dashboard.tsx
    hash: 00e9ff53fdc99fbb14b9ed45e04d03b6a7f2a8eb50fb79999eb706b67a5719aa
sources_digest: 219608c83c9d48440712eb3e151bd7aaa07c8920e1c11788b297bd4c187052a2
links:
  - to: frontend-api-client-layer
    relation: uses
    description: >-
      BatchSlice uses batchSliceApi and sliceApi; ClipReview uses autoclipApi
      and projectApi; ChannelAccounts uses channelAccountApi/publishApi/authApi.
  - to: slicing-engine
    relation: uses
    description: >-
      BatchSlice's trim feature re-encodes a clip by calling sliceApi.run with
      cut_start/cut_end on the original episode, reusing the re-cut capability.
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
  - symbol: BatchSlicePage
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L176-L1294'
  - symbol: handleFileUpload
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L274-L291'
  - symbol: buildPayload
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L293-L333'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L335-L340'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L342-L347'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L349-L354'
  - symbol: handleRun
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L356-L382'
  - symbol: handleRetry
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L384-L402'
  - symbol: handleCancel
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L404-L422'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L424-L434'
  - symbol: renderOutputModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L436-L495'
  - symbol: handlePreviewOutput
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L498-L506'
  - symbol: openTrimModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L509-L518'
  - symbol: handleTrimRangeChange
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L521-L527'
  - symbol: submitTrim
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L530-L552'
  - symbol: renderPreviewModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L554-L567'
  - symbol: renderTrimModal
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L569-L622'
  - symbol: formatSize
    kind: function
    at: 'frontend/src/pages/BatchSlice.tsx:L624-L629'
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
  - symbol: Dashboard
    kind: function
    at: 'frontend/src/pages/Dashboard.tsx:L15-L118'
---
<!-- context:generated:start -->
## Summary

The operational frontend for the Clip Workflow: Dashboard (project stats landing), BatchSlice (JSON manifest upload, shared pipeline config, per-item polling every 5s only for expanded batches, retry/cancel, trim modal re-encoding via sliceApi.run with cut_start/cut_end), ClipReview (accept/reject/adjust autoclip candidates with debounced updates and a VideoPreview scrubber), and ChannelAccounts (WeChat Channels ledger with auto-sync to the video account library and dual-track operator validation requiring either a system user ID or external name).

## Related

- uses [[frontend-api-client-layer]] — BatchSlice uses batchSliceApi and sliceApi; ClipReview uses autoclipApi and projectApi; ChannelAccounts uses channelAccountApi/publishApi/authApi.
- uses [[slicing-engine]] — BatchSlice's trim feature re-encodes a clip by calling sliceApi.run with cut_start/cut_end on the original episode, reusing the re-cut capability.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
