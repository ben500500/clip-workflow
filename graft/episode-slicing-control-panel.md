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
  - symbol: resolveSubtitleMaskPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L56-L64'
  - symbol: buildSliceModeOptions
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L68-L76'
  - symbol: EpisodeDetail
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L110-L3008'
  - symbol: handleCoverUpload
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L131-L148'
  - symbol: fetchEpisode
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L278-L291'
  - symbol: fetchHistories
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L298-L315'
  - symbol: fetchAutoclipHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L318-L326'
  - symbol: fetchIntervalHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L329-L337'
  - symbol: fetchSliceHistory
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L340-L350'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L353-L358'
  - symbol: collectCurrentPresetConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L370-L414'
  - symbol: applyPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L417-L461'
  - symbol: handleSelectPreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L476-L482'
  - symbol: collectPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L485-L490'
  - symbol: applyPersistConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L493-L502'
  - symbol: handleSavePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L505-L520'
  - symbol: handleDeletePreset
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L523-L534'
  - symbol: getCurrentStep
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L600-L611'
  - symbol: resumeAutoclipPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L614-L654'
  - symbol: resumeDetectPolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L657-L701'
  - symbol: resumeSlicePolling
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L704-L765'
  - symbol: runAutoClip
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L776-L822'
  - symbol: runDetect
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L825-L880'
  - symbol: pollLatestSliceProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L883-L930'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L933-L954'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L956-L958'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L960-L962'
  - symbol: uploadSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L965-L980'
  - symbol: removeSubtitleFile
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L982-L985'
  - symbol: resolveAutoclipConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L988-L1009'
  - symbol: oneClickSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1012-L1100'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1103-L1108'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1109-L1111'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1112-L1114'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1120-L1132'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1127-L1128'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1133-L1146'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1149-L1188'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1191-L1296'
  - symbol: workflowGuide
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1308-L1367'
  - symbol: renderProgress
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1370-L1388'
  - symbol: renderHistoryTitle
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1391-L1398'
  - symbol: renderAutoclipParamsLabel
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1401-L1410'
  - symbol: renderAutoclipParams
    kind: function
    at: 'frontend/src/pages/EpisodeDetail.tsx:L1413-L1433'
---
<!-- context:generated:start -->
## Summary

The EpisodeDetail page orchestrates the full per-episode production pipeline: AI autoclip selection, interval detection, and video slicing, with three slicing modes (fast/dedupe/scrub). It persists named config presets in localStorage, polls task progress via timers, and supports one-click slice (bypasses review) and quick-convert (skips AI analysis) paths. Concurrent pipeline stages each have separate progress trackers.

## Related

- uses [[slice-configuration-presets]] — Persists named dedupe/manual config presets to localStorage.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
