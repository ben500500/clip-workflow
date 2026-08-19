---
name: Shared Frontend Types & Formatting
slug: shared-frontend-types-formatting
type: file
sources:
  - path: frontend/src/types/index.ts
    hash: da7127de58db22604b5dd519f3c41ec8e0c73bee43a5c23e0a3c3364a7587dd3
  - path: frontend/src/utils/format.ts
    hash: 60045635a7ad286a573ef3329b36e1bbfea883da3830b43adea2429eb41f28c8
sources_digest: c8d934aac8772e646ba619effd3306c4e002de02b5e743790b9216fb6761e34e
links:
  - to: slice-config-tooltip-watermark-styles
    relation: uses
    description: SliceTask type from types is consumed by buildSliceConfigTooltip.
generator:
  version: 1
covers:
  - symbol: ApiList
    kind: interface
    at: 'frontend/src/types/index.ts:L3-L8'
  - symbol: ApiError
    kind: interface
    at: 'frontend/src/types/index.ts:L10-L12'
  - symbol: ProjectStatus
    kind: type
    at: 'frontend/src/types/index.ts:L16-L16'
  - symbol: Project
    kind: interface
    at: 'frontend/src/types/index.ts:L18-L28'
  - symbol: ProjectFormValues
    kind: interface
    at: 'frontend/src/types/index.ts:L30-L35'
  - symbol: ProjectStats
    kind: interface
    at: 'frontend/src/types/index.ts:L37-L44'
  - symbol: Episode
    kind: interface
    at: 'frontend/src/types/index.ts:L46-L58'
  - symbol: ClipCandidate
    kind: interface
    at: 'frontend/src/types/index.ts:L62-L78'
  - symbol: AutoClipRunRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L80-L93'
  - symbol: IntervalHistoryItem
    kind: interface
    at: 'frontend/src/types/index.ts:L95-L106'
  - symbol: AutoClipConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L108-L110'
  - symbol: DetectedInterval
    kind: interface
    at: 'frontend/src/types/index.ts:L114-L126'
  - symbol: SliceTask
    kind: interface
    at: 'frontend/src/types/index.ts:L130-L154'
  - symbol: WorkerNode
    kind: interface
    at: 'frontend/src/types/index.ts:L156-L185'
  - symbol: WorkerRunningTask
    kind: interface
    at: 'frontend/src/types/index.ts:L187-L195'
  - symbol: SliceOutput
    kind: interface
    at: 'frontend/src/types/index.ts:L197-L209'
  - symbol: DedupeConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L211-L213'
  - symbol: PublishTask
    kind: interface
    at: 'frontend/src/types/index.ts:L217-L249'
  - symbol: PublishTimeSlot
    kind: interface
    at: 'frontend/src/types/index.ts:L251-L260'
  - symbol: PublishProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L262-L286'
  - symbol: PublishBatch
    kind: interface
    at: 'frontend/src/types/index.ts:L288-L296'
  - symbol: Publication
    kind: interface
    at: 'frontend/src/types/index.ts:L298-L308'
  - symbol: VideoAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L312-L329'
  - symbol: MiniProgram
    kind: interface
    at: 'frontend/src/types/index.ts:L331-L340'
  - symbol: OperatorRouteRow
    kind: interface
    at: 'frontend/src/types/index.ts:L344-L359'
  - symbol: OperatorStat
    kind: interface
    at: 'frontend/src/types/index.ts:L361-L365'
  - symbol: PublishAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L367-L387'
  - symbol: LoginAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L389-L402'
  - symbol: RiskEventItem
    kind: interface
    at: 'frontend/src/types/index.ts:L404-L416'
  - symbol: AuditResult
    kind: interface
    at: 'frontend/src/types/index.ts:L418-L421'
  - symbol: MultiOpVerification
    kind: interface
    at: 'frontend/src/types/index.ts:L425-L437'
  - symbol: ShortDramaGeneration
    kind: interface
    at: 'frontend/src/types/index.ts:L441-L450'
  - symbol: ShortDramaAnalysisRow
    kind: interface
    at: 'frontend/src/types/index.ts:L452-L472'
  - symbol: ShortDramaSummary
    kind: interface
    at: 'frontend/src/types/index.ts:L474-L481'
  - symbol: ShortDramaTopic
    kind: interface
    at: 'frontend/src/types/index.ts:L483-L486'
  - symbol: PlatformProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L490-L500'
  - symbol: SystemConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L502-L507'
  - symbol: DashboardOverview
    kind: interface
    at: 'frontend/src/types/index.ts:L511-L520'
  - symbol: TrendPoint
    kind: interface
    at: 'frontend/src/types/index.ts:L522-L533'
  - symbol: FunnelData
    kind: interface
    at: 'frontend/src/types/index.ts:L535-L547'
  - symbol: VideoMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L549-L578'
  - symbol: MiniProgramMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L580-L590'
  - symbol: AdMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L592-L606'
  - symbol: DramaMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L608-L619'
  - symbol: EcosystemMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L621-L632'
  - symbol: ImportTemplate
    kind: interface
    at: 'frontend/src/types/index.ts:L634-L641'
  - symbol: ImportHistoryRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L643-L654'
  - symbol: PlatformDetectResult
    kind: interface
    at: 'frontend/src/types/index.ts:L656-L670'
  - symbol: FilePreviewResult
    kind: interface
    at: 'frontend/src/types/index.ts:L672-L676'
  - symbol: CrossAnalysisData
    kind: interface
    at: 'frontend/src/types/index.ts:L678-L687'
  - symbol: FunnelCompareData
    kind: interface
    at: 'frontend/src/types/index.ts:L689-L708'
  - symbol: DramaDetail
    kind: interface
    at: 'frontend/src/types/index.ts:L710-L727'
  - symbol: Role
    kind: type
    at: 'frontend/src/types/index.ts:L731-L731'
  - symbol: User
    kind: interface
    at: 'frontend/src/types/index.ts:L733-L744'
  - symbol: LoginResponse
    kind: interface
    at: 'frontend/src/types/index.ts:L746-L750'
  - symbol: RoleOption
    kind: interface
    at: 'frontend/src/types/index.ts:L752-L755'
  - symbol: AlertRule
    kind: interface
    at: 'frontend/src/types/index.ts:L771-L783'
  - symbol: AlertEvent
    kind: interface
    at: 'frontend/src/types/index.ts:L785-L797'
  - symbol: ChannelOperator
    kind: interface
    at: 'frontend/src/types/index.ts:L801-L808'
  - symbol: ChannelAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L810-L830'
  - symbol: formatFileSize
    kind: function
    at: 'frontend/src/utils/format.ts:L3-L10'
  - symbol: formatDuration
    kind: function
    at: 'frontend/src/utils/format.ts:L12-L20'
  - symbol: pad
    kind: function
    at: 'frontend/src/utils/format.ts:L17-L17'
  - symbol: formatDateTime
    kind: function
    at: 'frontend/src/utils/format.ts:L22-L25'
  - symbol: formatDate
    kind: function
    at: 'frontend/src/utils/format.ts:L27-L30'
  - symbol: formatRelativeTime
    kind: function
    at: 'frontend/src/utils/format.ts:L32-L44'
  - symbol: formatPercent
    kind: function
    at: 'frontend/src/utils/format.ts:L46-L49'
  - symbol: getStatusColor
    kind: function
    at: 'frontend/src/utils/format.ts:L51-L77'
  - symbol: getStatusLabel
    kind: function
    at: 'frontend/src/utils/format.ts:L79-L105'
  - symbol: truncateText
    kind: function
    at: 'frontend/src/utils/format.ts:L107-L110'
---
<!-- context:generated:start -->
## Summary

The complete TypeScript type contract for the frontend (snake_case field names matching backend, optional fields for nullable DB columns, nested stage objects for workflow tracking) plus pure formatting utilities (formatFileSize, formatDuration, formatDateTime, getStatusColor/Label, etc.). The status maps are hardcoded, so adding new workflow states requires updating both getStatusColor and getStatusLabel.

## Related

- uses [[slice-config-tooltip-watermark-styles]] — SliceTask type from types is consumed by buildSliceConfigTooltip.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
