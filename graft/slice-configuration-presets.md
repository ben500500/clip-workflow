---
name: Slice Configuration Presets
slug: slice-configuration-presets
type: concept
sources:
  - path: frontend/src/pages/EpisodeDetail.tsx
    hash: f2fca04ec36f037da6e9cc8de3c8f9b9de673d4c68dd47a6602e97091192ff32
  - path: frontend/src/pages/ProjectDetail.tsx
    hash: 1bbb9d15160553afd40326da2f779f08d7a9fa78c820244d2fed5a200d77cf4f
  - path: frontend/src/pages/SliceTasks.tsx
    hash: ec69d10d256335a970e04f662b670fad9a8c2b36a6196b9f0826c3349325e059
sources_digest: f8f94675dc0f57346f5a091fb17bdfcba566be7a42157917a13316e2e935d2d0
links:
  - to: episode-slicing-control-panel
    relation: part_of
    description: EpisodeDetail persists and reads these presets.
  - to: project-episode-management
    relation: part_of
    description: ProjectDetail shares batch slicing presets via the same localStorage key.
  - to: slice-tasks-output-management
    relation: part_of
    description: SliceTasks reads dedupe presets and manual overrides from the same store.
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
  - symbol: BatchSliceConfig
    kind: interface
    at: 'frontend/src/pages/ProjectDetail.tsx:L21-L35'
  - symbol: loadSavedBatchConfig
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L56-L67'
  - symbol: saveBatchConfig
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L69-L75'
  - symbol: ProjectDetail
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L79-L1044'
  - symbol: applyBatchPreset
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L126-L137'
  - symbol: fetchData
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L164-L179'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L188-L217'
  - symbol: submitMultiUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L220-L251'
  - symbol: handleMultiFileUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L254-L291'
  - symbol: handleTabChange
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L312-L317'
  - symbol: togglePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L320-L360'
  - symbol: refreshPreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L362-L387'
  - symbol: renderSourcePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L389-L441'
  - symbol: handleCoverUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L444-L464'
  - symbol: runOneClickSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L467-L487'
  - symbol: runBatchSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L490-L515'
  - symbol: buildSliceModeOptions
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L49-L57'
  - symbol: SliceTasks
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L59-L1246'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L162-L201'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L203-L279'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L281-L289'
  - symbol: deleteTask
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L291-L303'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L306-L327'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L329-L331'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L333-L335'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L338-L343'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L344-L346'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L347-L349'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L356-L368'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L363-L364'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L369-L383'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L405-L410'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L527-L547'
---
<!-- context:generated:start -->
## Summary

Named dedupe/manual configuration presets shared across EpisodeDetail, ProjectDetail, and SliceTasks via the localStorage key slice_presets_v1. Presets persist user configurations for dedupe recipes and manual fine-tuning (DedupeManualConfig) so batch slicing across episodes reuses the same settings. This is the cross-page mechanism for consistent slicing behavior.

## Related

- part of [[episode-slicing-control-panel]] — EpisodeDetail persists and reads these presets.
- part of [[project-episode-management]] — ProjectDetail shares batch slicing presets via the same localStorage key.
- part of [[slice-tasks-output-management]] — SliceTasks reads dedupe presets and manual overrides from the same store.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
