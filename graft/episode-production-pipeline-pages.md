---
name: Episode Production Pipeline Pages
slug: episode-production-pipeline-pages
type: system
sources:
  - path: frontend/src/pages/EpisodeDetail.tsx
    hash: 1f5a1b7cf052264085fde1ecada8ffe186504ac5f5435031bd9eedbb6353b8b8
  - path: frontend/src/pages/IntervalDetection.tsx
    hash: 79884e669eac86dd85750ef8e5c9bac5c8db09fc4aeed49ff97c9488c8219159
  - path: frontend/src/pages/SliceTasks.tsx
    hash: 410d7389db1036c077d6edd69d428a2b8a88280aaefb577c00e30964069d1d92
sources_digest: a6a11e1909bce68c3f9f9534e80a0c5a1a5175cd1407783b79146304969dd4f9
links:
  - to: frontend-api-layer
    relation: uses
    description: >-
      Calls projectApi, autoclipApi, intervalApi, sliceApi, previewApi for all
      backend interactions.
  - to: publishing-output-hub
    relation: produces
    description: >-
      Slice tasks launched here generate outputs that OutputPreview lists,
      previews, and publishes.
  - to: slice-configuration-presets
    relation: uses
    description: >-
      Both EpisodeDetail and SliceTasks build and submit the same slice config
      object consumed by sliceApi; EpisodeDetail's preset system
      serializes/restores these configs.
generator:
  version: 1
covers:
  - symbol: resolveSubtitleMaskPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L54-L62'
  - symbol: SlicePreset
    kind: interface
    at: 'frontend/src/pages/EpisodeDetail.tsx:L113-L163'
  - symbol: EpisodeDetail
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L216-L2950'
  - symbol: fetchEpisode
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L355-L368'
  - symbol: fetchHistories
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L375-L392'
  - symbol: fetchAutoclipHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L395-L403'
  - symbol: fetchIntervalHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L406-L414'
  - symbol: fetchSliceHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L417-L427'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L430-L435'
  - symbol: persistPresets
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L460-L468'
  - symbol: collectCurrentPresetConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L471-L513'
  - symbol: applyPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L516-L558'
  - symbol: handleSelectPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L573-L579'
  - symbol: collectPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L582-L587'
  - symbol: applyPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L590-L599'
  - symbol: handleSavePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L602-L617'
  - symbol: handleDeletePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L620-L631'
  - symbol: getCurrentStep
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L697-L708'
  - symbol: resumeAutoclipPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L711-L751'
  - symbol: resumeDetectPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L754-L798'
  - symbol: resumeSlicePolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L801-L862'
  - symbol: runAutoClip
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L873-L919'
  - symbol: runDetect
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L922-L977'
  - symbol: pollLatestSliceProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L980-L1027'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1030-L1051'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1053-L1055'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1057-L1059'
  - symbol: uploadSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1062-L1077'
  - symbol: removeSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1079-L1082'
  - symbol: oneClickSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1085-L1207'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1210-L1215'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1216-L1218'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1219-L1221'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1227-L1239'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1234-L1235'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1240-L1253'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1256-L1279'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1282-L1382'
  - symbol: workflowGuide
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1394-L1453'
  - symbol: renderProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1456-L1474'
  - symbol: renderHistoryTitle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1477-L1484'
  - symbol: IntervalDetection
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L14-L187'
  - symbol: fetchIntervals
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L23-L33'
  - symbol: toggle
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L63-L70'
  - symbol: remove
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L72-L80'
  - symbol: createManual
    kind: function
    at: 'frontend/src/pages/IntervalDetection.tsx:L82-L93'
  - symbol: SliceTasks
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L66-L1235'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L167-L190'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L192-L268'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L270-L278'
  - symbol: deleteTask
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L280-L292'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L295-L316'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L318-L320'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L322-L324'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L327-L332'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L333-L335'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L336-L338'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L345-L357'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L352-L353'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L358-L372'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L394-L399'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L516-L536'
---
<!-- context:generated:start -->
## Summary

The core short-video production control surfaces: EpisodeDetail orchestrates the full autoclip→interval→slice pipeline with polling and a localStorage-persisted slice preset system (slice_presets_v1, with backward-compatible fallback for older presets lacking subtitle_mask_preset); SliceTasks is a parallel slice-launch panel with a 5s polling loop and presigned-URL download flow; IntervalDetection manages detected intervals with a 3s progress poll and the invariant that watermark intervals have no auto-detector and must be added manually. All three share the same slice-config state shape (vert2horiz, ASR subtitle burn, source subtitle mask, watermark removal, badges, text overlays) and filter internal detect_* tasks from history.

## Related

- uses [[frontend-api-layer]] — Calls projectApi, autoclipApi, intervalApi, sliceApi, previewApi for all backend interactions.
- produces [[publishing-output-hub]] — Slice tasks launched here generate outputs that OutputPreview lists, previews, and publishes.
- uses [[slice-configuration-presets]] — Both EpisodeDetail and SliceTasks build and submit the same slice config object consumed by sliceApi; EpisodeDetail's preset system serializes/restores these configs.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
