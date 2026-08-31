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
    at: 'frontend/src/types/index.ts:L46-L60'
  - symbol: ClipCandidate
    kind: interface
    at: 'frontend/src/types/index.ts:L64-L81'
  - symbol: AutoClipRunRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L83-L96'
  - symbol: IntervalHistoryItem
    kind: interface
    at: 'frontend/src/types/index.ts:L98-L109'
  - symbol: AutoClipConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L111-L123'
  - symbol: DetectedInterval
    kind: interface
    at: 'frontend/src/types/index.ts:L127-L139'
  - symbol: SliceTask
    kind: interface
    at: 'frontend/src/types/index.ts:L143-L167'
  - symbol: WorkerNode
    kind: interface
    at: 'frontend/src/types/index.ts:L169-L198'
  - symbol: WorkerRunningTask
    kind: interface
    at: 'frontend/src/types/index.ts:L200-L208'
  - symbol: SliceOutput
    kind: interface
    at: 'frontend/src/types/index.ts:L210-L222'
  - symbol: DedupeConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L224-L226'
  - symbol: PublishTask
    kind: interface
    at: 'frontend/src/types/index.ts:L230-L262'
  - symbol: PublishTimeSlot
    kind: interface
    at: 'frontend/src/types/index.ts:L264-L273'
  - symbol: PublishProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L275-L299'
  - symbol: PublishBatch
    kind: interface
    at: 'frontend/src/types/index.ts:L301-L309'
  - symbol: Publication
    kind: interface
    at: 'frontend/src/types/index.ts:L311-L321'
  - symbol: VideoAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L325-L342'
  - symbol: MiniProgram
    kind: interface
    at: 'frontend/src/types/index.ts:L344-L353'
  - symbol: OperatorRouteRow
    kind: interface
    at: 'frontend/src/types/index.ts:L357-L372'
  - symbol: OperatorStat
    kind: interface
    at: 'frontend/src/types/index.ts:L374-L378'
  - symbol: PublishAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L380-L400'
  - symbol: LoginAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L402-L415'
  - symbol: RiskEventItem
    kind: interface
    at: 'frontend/src/types/index.ts:L417-L429'
  - symbol: AuditResult
    kind: interface
    at: 'frontend/src/types/index.ts:L431-L434'
  - symbol: MultiOpVerification
    kind: interface
    at: 'frontend/src/types/index.ts:L438-L450'
  - symbol: ShortDramaGeneration
    kind: interface
    at: 'frontend/src/types/index.ts:L454-L463'
  - symbol: ShortDramaAnalysisRow
    kind: interface
    at: 'frontend/src/types/index.ts:L465-L485'
  - symbol: ShortDramaSummary
    kind: interface
    at: 'frontend/src/types/index.ts:L487-L494'
  - symbol: ShortDramaTopic
    kind: interface
    at: 'frontend/src/types/index.ts:L496-L499'
  - symbol: PlatformProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L503-L513'
  - symbol: SystemConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L515-L520'
  - symbol: DashboardOverview
    kind: interface
    at: 'frontend/src/types/index.ts:L524-L533'
  - symbol: TrendPoint
    kind: interface
    at: 'frontend/src/types/index.ts:L535-L546'
  - symbol: FunnelData
    kind: interface
    at: 'frontend/src/types/index.ts:L548-L560'
  - symbol: VideoMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L562-L591'
  - symbol: MiniProgramMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L593-L603'
  - symbol: AdMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L605-L619'
  - symbol: DramaMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L621-L632'
  - symbol: EcosystemMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L634-L645'
  - symbol: ImportTemplate
    kind: interface
    at: 'frontend/src/types/index.ts:L647-L654'
  - symbol: ImportHistoryRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L656-L667'
  - symbol: PlatformDetectResult
    kind: interface
    at: 'frontend/src/types/index.ts:L669-L683'
  - symbol: FilePreviewResult
    kind: interface
    at: 'frontend/src/types/index.ts:L685-L689'
  - symbol: CrossAnalysisData
    kind: interface
    at: 'frontend/src/types/index.ts:L691-L700'
  - symbol: FunnelCompareData
    kind: interface
    at: 'frontend/src/types/index.ts:L702-L721'
  - symbol: DramaDetail
    kind: interface
    at: 'frontend/src/types/index.ts:L723-L740'
  - symbol: Role
    kind: type
    at: 'frontend/src/types/index.ts:L744-L744'
  - symbol: User
    kind: interface
    at: 'frontend/src/types/index.ts:L746-L757'
  - symbol: LoginResponse
    kind: interface
    at: 'frontend/src/types/index.ts:L759-L763'
  - symbol: RoleOption
    kind: interface
    at: 'frontend/src/types/index.ts:L765-L768'
  - symbol: AlertRule
    kind: interface
    at: 'frontend/src/types/index.ts:L784-L796'
  - symbol: AlertEvent
    kind: interface
    at: 'frontend/src/types/index.ts:L798-L810'
  - symbol: ChannelOperator
    kind: interface
    at: 'frontend/src/types/index.ts:L814-L821'
  - symbol: Theater
    kind: interface
    at: 'frontend/src/types/index.ts:L823-L831'
  - symbol: ChannelAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L833-L855'
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
