---
name: Slice Tasks & Output Management
slug: slice-tasks-output-management
type: system
sources:
  - path: frontend/src/pages/OutputPreview.tsx
    hash: 64411e8d99fa34027d64c2724c46d21739cf795b4f4b1fb0361ef365cf489e27
  - path: frontend/src/pages/SliceTasks.tsx
    hash: ec69d10d256335a970e04f662b670fad9a8c2b36a6196b9f0826c3349325e059
sources_digest: a4f40ea46cc573160a852c4cef67ab8dae7744a4983c14cbe3d8e52ff0aeb884
links:
  - to: slice-config-tooltip-watermark-styles
    relation: uses
    description: >-
      Uses buildSliceConfigTooltip and WATERMARK_STYLE_LABEL to render
      mode-column tooltips.
  - to: slice-configuration-presets
    relation: uses
    description: >-
      Reads dedupe presets and manual overrides shared via localStorage
      slice_presets_v1.
generator:
  version: 1
covers:
  - symbol: isRealSliceTask
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L32-L32'
  - symbol: RecutVideoPreview
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L35-L143'
  - symbol: OutputPreview
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L145-L1057'
  - symbol: loadTask
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L223-L240'
  - symbol: downloadSelected
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L275-L309'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L314-L334'
  - symbol: openPublishModal
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L337-L372'
  - symbol: submitPublish
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L374-L442'
  - symbol: onMaterialChange
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L445-L455'
  - symbol: onCaptionVersionChange
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L458-L467'
  - symbol: onGenerateMaterialFromOutput
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L470-L509'
  - symbol: onGenerateMaterialFromDrama
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L512-L567'
  - symbol: openRecutModal
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L569-L588'
  - symbol: submitRecut
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L595-L622'
  - symbol: SliceTasks
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L68-L1237'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L169-L192'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L194-L270'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L272-L280'
  - symbol: deleteTask
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L282-L294'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L297-L318'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L320-L322'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L324-L326'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L329-L334'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L335-L337'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L338-L340'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L347-L359'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L354-L355'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L360-L374'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L396-L401'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L518-L538'
---
<!-- context:generated:start -->
## Summary

SliceTasks page configures and launches slice jobs (mode, dedupe presets, watermark, badges, vert2horiz, ASR subtitles, source subtitle masking) with 5-second polling and progress that only counts running tasks to avoid stale 100%. Downloads go through authenticated API calls for presigned URLs rather than direct browser navigation. Smart defaults auto-enable subtitles and preset text overlays when vert2horiz is activated.

## Related

- uses [[slice-config-tooltip-watermark-styles]] — Uses buildSliceConfigTooltip and WATERMARK_STYLE_LABEL to render mode-column tooltips.
- uses [[slice-configuration-presets]] — Reads dedupe presets and manual overrides shared via localStorage slice_presets_v1.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
