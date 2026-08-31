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
    at: 'frontend/src/pages/ProjectDetail.tsx:L84-L1164'
  - symbol: applyBatchPreset
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L130-L142'
  - symbol: fetchData
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L171-L186'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L195-L224'
  - symbol: submitMultiUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L227-L258'
  - symbol: handleMultiFileUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L261-L298'
  - symbol: handleTabChange
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L322-L327'
  - symbol: toggleOutputRow
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L351-L353'
  - symbol: downloadOutputOne
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L356-L372'
  - symbol: downloadOutputGroup
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L375-L405'
  - symbol: togglePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L408-L448'
  - symbol: refreshPreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L450-L475'
  - symbol: renderSourcePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L477-L529'
  - symbol: readEpisodeHookKeys
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L533-L543'
  - symbol: runOneClickSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L546-L576'
  - symbol: runBatchSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L579-L606'
  - symbol: buildSliceModeOptions
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L49-L57'
  - symbol: SliceTasks
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L59-L1259'
  - symbol: buildDedupeConfig
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L163-L202'
  - symbol: runSlice
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L204-L282'
  - symbol: showOutputs
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L284-L292'
  - symbol: deleteTask
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L294-L306'
  - symbol: uploadBadgeFile
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L309-L330'
  - symbol: updateBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L332-L334'
  - symbol: removeBadge
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L336-L338'
  - symbol: addTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L341-L346'
  - symbol: updateTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L347-L349'
  - symbol: removeTextOverlay
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L350-L352'
  - symbol: applyDefaultTextOverlays
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L359-L371'
  - symbol: exists
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L366-L367'
  - symbol: handleVert2horizToggle
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L372-L386'
  - symbol: formatTaskDuration
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L408-L413'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/SliceTasks.tsx:L530-L550'
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
