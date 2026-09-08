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
  - symbol: BatchSliceConfig
    kind: interface
    at: 'frontend/src/pages/ProjectDetail.tsx:L22-L39'
  - symbol: loadSavedBatchConfig
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L61-L72'
  - symbol: saveBatchConfig
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L74-L80'
  - symbol: ProjectDetail
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L84-L1187'
  - symbol: applyBatchPreset
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L132-L144'
  - symbol: fetchData
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L173-L188'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L197-L226'
  - symbol: submitMultiUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L229-L268'
  - symbol: handleMultiFileUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L271-L308'
  - symbol: handleTabChange
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L332-L337'
  - symbol: toggleOutputRow
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L361-L363'
  - symbol: downloadOutputOne
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L366-L382'
  - symbol: downloadOutputGroup
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L385-L415'
  - symbol: togglePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L418-L458'
  - symbol: refreshPreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L460-L485'
  - symbol: renderSourcePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L487-L539'
  - symbol: readEpisodeHookKeys
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L543-L553'
  - symbol: runOneClickSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L556-L586'
  - symbol: runBatchSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L590-L609'
  - symbol: buildSliceModeOptions
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L49-L57'
  - symbol: SliceTasks
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L59-L1278'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L165-L204'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L206-L286'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L288-L296'
  - symbol: deleteTask
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L298-L310'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L313-L334'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L336-L338'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L340-L342'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L345-L350'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L351-L353'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L354-L356'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L363-L375'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L370-L371'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L376-L390'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L412-L417'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L534-L554'
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
