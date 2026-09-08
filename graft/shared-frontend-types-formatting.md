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
    at: 'frontend/src/types/index.ts:L46-L63'
  - symbol: ClipCandidate
    kind: interface
    at: 'frontend/src/types/index.ts:L67-L84'
  - symbol: AutoClipRunRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L86-L99'
  - symbol: IntervalHistoryItem
    kind: interface
    at: 'frontend/src/types/index.ts:L101-L112'
  - symbol: AutoClipConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L114-L126'
  - symbol: DetectedInterval
    kind: interface
    at: 'frontend/src/types/index.ts:L130-L142'
  - symbol: SliceTask
    kind: interface
    at: 'frontend/src/types/index.ts:L146-L170'
  - symbol: WorkerNode
    kind: interface
    at: 'frontend/src/types/index.ts:L172-L201'
  - symbol: WorkerRunningTask
    kind: interface
    at: 'frontend/src/types/index.ts:L203-L211'
  - symbol: SliceOutput
    kind: interface
    at: 'frontend/src/types/index.ts:L213-L225'
  - symbol: DedupeConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L227-L229'
  - symbol: PublishTask
    kind: interface
    at: 'frontend/src/types/index.ts:L233-L265'
  - symbol: PublishTimeSlot
    kind: interface
    at: 'frontend/src/types/index.ts:L267-L276'
  - symbol: PublishProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L278-L302'
  - symbol: PublishBatch
    kind: interface
    at: 'frontend/src/types/index.ts:L304-L312'
  - symbol: Publication
    kind: interface
    at: 'frontend/src/types/index.ts:L314-L324'
  - symbol: VideoAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L328-L345'
  - symbol: MiniProgram
    kind: interface
    at: 'frontend/src/types/index.ts:L347-L356'
  - symbol: OperatorRouteRow
    kind: interface
    at: 'frontend/src/types/index.ts:L360-L375'
  - symbol: OperatorStat
    kind: interface
    at: 'frontend/src/types/index.ts:L377-L381'
  - symbol: PublishAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L383-L403'
  - symbol: LoginAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L405-L418'
  - symbol: RiskEventItem
    kind: interface
    at: 'frontend/src/types/index.ts:L420-L432'
  - symbol: AuditResult
    kind: interface
    at: 'frontend/src/types/index.ts:L434-L437'
  - symbol: MultiOpVerification
    kind: interface
    at: 'frontend/src/types/index.ts:L441-L453'
  - symbol: ShortDramaGeneration
    kind: interface
    at: 'frontend/src/types/index.ts:L457-L466'
  - symbol: ShortDramaAnalysisRow
    kind: interface
    at: 'frontend/src/types/index.ts:L468-L488'
  - symbol: ShortDramaSummary
    kind: interface
    at: 'frontend/src/types/index.ts:L490-L497'
  - symbol: ShortDramaTopic
    kind: interface
    at: 'frontend/src/types/index.ts:L499-L502'
  - symbol: PlatformProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L506-L516'
  - symbol: SystemConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L518-L523'
  - symbol: DashboardOverview
    kind: interface
    at: 'frontend/src/types/index.ts:L527-L536'
  - symbol: TrendPoint
    kind: interface
    at: 'frontend/src/types/index.ts:L538-L549'
  - symbol: FunnelData
    kind: interface
    at: 'frontend/src/types/index.ts:L551-L563'
  - symbol: VideoMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L565-L594'
  - symbol: MiniProgramMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L596-L606'
  - symbol: AdMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L608-L622'
  - symbol: DramaMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L624-L635'
  - symbol: EcosystemMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L637-L648'
  - symbol: ImportTemplate
    kind: interface
    at: 'frontend/src/types/index.ts:L650-L657'
  - symbol: ImportHistoryRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L659-L670'
  - symbol: PlatformDetectResult
    kind: interface
    at: 'frontend/src/types/index.ts:L672-L686'
  - symbol: FilePreviewResult
    kind: interface
    at: 'frontend/src/types/index.ts:L688-L692'
  - symbol: CrossAnalysisData
    kind: interface
    at: 'frontend/src/types/index.ts:L694-L703'
  - symbol: FunnelCompareData
    kind: interface
    at: 'frontend/src/types/index.ts:L705-L724'
  - symbol: DramaDetail
    kind: interface
    at: 'frontend/src/types/index.ts:L726-L743'
  - symbol: Role
    kind: type
    at: 'frontend/src/types/index.ts:L747-L747'
  - symbol: User
    kind: interface
    at: 'frontend/src/types/index.ts:L749-L760'
  - symbol: LoginResponse
    kind: interface
    at: 'frontend/src/types/index.ts:L762-L766'
  - symbol: RoleOption
    kind: interface
    at: 'frontend/src/types/index.ts:L768-L771'
  - symbol: AlertRule
    kind: interface
    at: 'frontend/src/types/index.ts:L787-L799'
  - symbol: AlertEvent
    kind: interface
    at: 'frontend/src/types/index.ts:L801-L813'
  - symbol: ChannelOperator
    kind: interface
    at: 'frontend/src/types/index.ts:L817-L824'
  - symbol: Theater
    kind: interface
    at: 'frontend/src/types/index.ts:L826-L834'
  - symbol: ChannelAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L836-L858'
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
  - symbol: getClipTypeLabel
    kind: function
    at: 'frontend/src/utils/format.ts:L53-L61'
  - symbol: getClipTypeColor
    kind: function
    at: 'frontend/src/utils/format.ts:L63-L70'
  - symbol: getStatusColor
    kind: function
    at: 'frontend/src/utils/format.ts:L72-L98'
  - symbol: getStatusLabel
    kind: function
    at: 'frontend/src/utils/format.ts:L100-L126'
  - symbol: truncateText
    kind: function
    at: 'frontend/src/utils/format.ts:L128-L131'
---
<!-- context:generated:start -->
## Summary

The complete TypeScript type contract for the frontend (snake_case field names matching backend, optional fields for nullable DB columns, nested stage objects for workflow tracking) plus pure formatting utilities (formatFileSize, formatDuration, formatDateTime, getStatusColor/Label, etc.). The status maps are hardcoded, so adding new workflow states requires updating both getStatusColor and getStatusLabel.

## Related

- uses [[slice-config-tooltip-watermark-styles]] — SliceTask type from types is consumed by buildSliceConfigTooltip.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
