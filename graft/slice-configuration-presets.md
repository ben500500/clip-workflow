---
name: Slice Configuration & Presets
slug: slice-configuration-presets
type: concept
sources:
  - path: frontend/src/pages/EpisodeDetail.tsx
    hash: 1f5a1b7cf052264085fde1ecada8ffe186504ac5f5435031bd9eedbb6353b8b8
  - path: frontend/src/pages/Settings.tsx
    hash: 4c3ded0e3397b0b5c499a95fa07f150239e42cae1349cf5d1c266238a5c38a0f
  - path: frontend/src/pages/SliceTasks.tsx
    hash: 410d7389db1036c077d6edd69d428a2b8a88280aaefb577c00e30964069d1d92
  - path: frontend/src/utils/sliceConfigTooltip.ts
    hash: 843fcf3added57163116806cef61f0dbe9076b946c30ce2a8bfe96df0107f102
  - path: frontend/src/utils/watermarkStyles.ts
    hash: dd5d77449a6513e938a2133545b42048bd2a4cd994c43c10aba38ac67090b0d7
sources_digest: 50d3324dafe6fa415396604fc2c0fb60529a19e4fd6cde1b478b8548b18c3f3b
links:
  - to: episode-production-pipeline-pages
    relation: implements
    description: >-
      The config shape is built by these pages and consumed by sliceApi;
      watermarkStyles must match backend build_watermark_filter.
  - to: frontend-api-layer
    relation: uses
    description: Configs are serialized into slice task requests.
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
  - symbol: Settings
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L12-L393'
  - symbol: fetchAll
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L26-L34'
  - symbol: saveConfig
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L40-L50'
  - symbol: handleConfigEdit
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L52-L59'
  - symbol: handleConfigSave
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L61-L79'
  - symbol: saveProfile
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L81-L105'
  - symbol: handleConfigReset
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L108-L116'
  - symbol: handleProfileReset
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L119-L127'
  - symbol: applyPreset
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L130-L135'
  - symbol: handleAsrChange
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L138-L149'
  - symbol: renderConfigValue
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L151-L181'
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
  - symbol: buildSliceConfigTooltip
    kind: function
    at: 'frontend/src/utils/sliceConfigTooltip.ts:L6-L91'
  - symbol: WatermarkStyle
    kind: type
    at: 'frontend/src/utils/watermarkStyles.ts:L12-L12'
---
<!-- context:generated:start -->
## Summary

The slice configuration object is the shared contract across EpisodeDetail, SliceTasks, and Settings: a set of optional feature configs (dedupe_config, vert2horiz_config, subtitle_config, watermark_config, badges_config, text_overlays_config, subtitle_mask_config, watermark_mask_config) that map to backend slice.py filters. EpisodeDetail persists named presets in localStorage key slice_presets_v1 with backward-compatible fallback for older presets lacking subtitle_mask_preset. sliceConfigTooltip renders these configs into a human-readable Chinese tooltip, and watermarkStyles defines the six animation styles (scroll, float, wave, bounce, breath, blink) that must align with backend build_watermark_filter.

## Related

- implements [[episode-production-pipeline-pages]] — The config shape is built by these pages and consumed by sliceApi; watermarkStyles must match backend build_watermark_filter.
- uses [[frontend-api-layer]] — Configs are serialized into slice task requests.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
