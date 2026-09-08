---
name: Episode Slicing Control Panel
slug: episode-slicing-control-panel
type: system
sources:
  - path: frontend/src/pages/EpisodeDetail.tsx
    hash: f2fca04ec36f037da6e9cc8de3c8f9b9de673d4c68dd47a6602e97091192ff32
sources_digest: 4c798052444a8d2ad09df537754ac5bad4442dc3c56c018f5b695c58b8fd8890
links:
  - to: slice-configuration-presets
    relation: uses
    description: Persists named dedupe/manual config presets to localStorage.
generator:
  version: 1
covers:
  - symbol: FileHoverPreview
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L32-L127'
  - symbol: ensureUrls
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L50-L72'
  - symbol: resolveSubtitleMaskPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L157-L165'
  - symbol: buildSliceModeOptions
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L169-L177'
  - symbol: EpisodeDetail
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L211-L3689'
  - symbol: handleCoverUpload
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L234-L255'
  - symbol: handleHookFolderUpload
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L300-L325'
  - symbol: collectHookFolderFiles
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L331-L341'
  - symbol: fetchEpisode
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L492-L512'
  - symbol: fetchHistories
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L519-L536'
  - symbol: fetchAutoclipHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L539-L547'
  - symbol: handleDeleteAutoclipHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L550-L560'
  - symbol: fetchIntervalHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L563-L571'
  - symbol: fetchSliceHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L574-L584'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L587-L592'
  - symbol: collectCurrentPresetConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L604-L663'
  - symbol: applyPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L666-L725'
  - symbol: handleSelectPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L740-L746'
  - symbol: collectPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L749-L763'
  - symbol: applyPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L766-L784'
  - symbol: handleSavePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L787-L802'
  - symbol: handleDeletePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L805-L816'
  - symbol: getCurrentStep
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L890-L901'
  - symbol: resumeAutoclipPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L904-L944'
  - symbol: resumeDetectPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L947-L991'
  - symbol: resumeSlicePolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L994-L1055'
  - symbol: runAutoClip
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1066-L1115'
  - symbol: runDetect
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1118-L1173'
  - symbol: pollLatestSliceProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1176-L1223'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1226-L1247'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1249-L1251'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1253-L1255'
  - symbol: uploadSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1258-L1273'
  - symbol: removeSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1275-L1278'
  - symbol: resolveAutoclipConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1281-L1308'
  - symbol: oneClickSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1311-L1417'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1420-L1425'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1426-L1428'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1429-L1431'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1437-L1449'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1444-L1445'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1450-L1463'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1466-L1505'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1508-L1627'
  - symbol: workflowGuide
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1639-L1698'
  - symbol: renderProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1701-L1719'
  - symbol: renderHistoryTitle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1722-L1729'
  - symbol: renderAutoclipParamsLabel
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1732-L1741'
  - symbol: renderAutoclipParams
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1744-L1764'
---
<!-- context:generated:start -->
## Summary

The EpisodeDetail page orchestrates the full per-episode production pipeline: AI autoclip selection, interval detection, and video slicing, with three slicing modes (fast/dedupe/scrub). It persists named config presets in localStorage, polls task progress via timers, and supports one-click slice (bypasses review) and quick-convert (skips AI analysis) paths. Concurrent pipeline stages each have separate progress trackers.

## Related

- uses [[slice-configuration-presets]] — Persists named dedupe/manual config presets to localStorage.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
