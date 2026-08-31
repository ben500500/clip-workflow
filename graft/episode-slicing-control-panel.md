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
    at: 'frontend/src/pages/EpisodeDetail.tsx:L211-L3671'
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
    at: 'frontend/src/pages/EpisodeDetail.tsx:L489-L509'
  - symbol: fetchHistories
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L516-L533'
  - symbol: fetchAutoclipHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L536-L544'
  - symbol: handleDeleteAutoclipHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L547-L557'
  - symbol: fetchIntervalHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L560-L568'
  - symbol: fetchSliceHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L571-L581'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L584-L589'
  - symbol: collectCurrentPresetConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L601-L659'
  - symbol: applyPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L662-L720'
  - symbol: handleSelectPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L735-L741'
  - symbol: collectPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L744-L758'
  - symbol: applyPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L761-L779'
  - symbol: handleSavePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L782-L797'
  - symbol: handleDeletePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L800-L811'
  - symbol: getCurrentStep
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L880-L891'
  - symbol: resumeAutoclipPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L894-L934'
  - symbol: resumeDetectPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L937-L981'
  - symbol: resumeSlicePolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L984-L1045'
  - symbol: runAutoClip
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1056-L1105'
  - symbol: runDetect
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1108-L1163'
  - symbol: pollLatestSliceProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1166-L1213'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1216-L1237'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1239-L1241'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1243-L1245'
  - symbol: uploadSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1248-L1263'
  - symbol: removeSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1265-L1268'
  - symbol: resolveAutoclipConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1271-L1298'
  - symbol: oneClickSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1301-L1405'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1408-L1413'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1414-L1416'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1417-L1419'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1425-L1437'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1432-L1433'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1438-L1451'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1454-L1493'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1496-L1613'
  - symbol: workflowGuide
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1625-L1684'
  - symbol: renderProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1687-L1705'
  - symbol: renderHistoryTitle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1708-L1715'
  - symbol: renderAutoclipParamsLabel
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1718-L1727'
  - symbol: renderAutoclipParams
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1730-L1750'
---
<!-- context:generated:start -->
## Summary

The EpisodeDetail page orchestrates the full per-episode production pipeline: AI autoclip selection, interval detection, and video slicing, with three slicing modes (fast/dedupe/scrub). It persists named config presets in localStorage, polls task progress via timers, and supports one-click slice (bypasses review) and quick-convert (skips AI analysis) paths. Concurrent pipeline stages each have separate progress trackers.

## Related

- uses [[slice-configuration-presets]] — Persists named dedupe/manual config presets to localStorage.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
