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
  - symbol: WorkflowStageStatus
    kind: type
    at: 'frontend/src/types/index.ts:L62-L62'
  - symbol: EpisodeWorkflowStage
    kind: interface
    at: 'frontend/src/types/index.ts:L64-L72'
  - symbol: EpisodeWorkflowItem
    kind: interface
    at: 'frontend/src/types/index.ts:L74-L88'
  - symbol: ProjectWorkflowOverall
    kind: interface
    at: 'frontend/src/types/index.ts:L90-L100'
  - symbol: ProjectWorkflowStatus
    kind: interface
    at: 'frontend/src/types/index.ts:L102-L107'
  - symbol: ClipCandidate
    kind: interface
    at: 'frontend/src/types/index.ts:L111-L127'
  - symbol: AutoClipRunRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L129-L142'
  - symbol: IntervalHistoryItem
    kind: interface
    at: 'frontend/src/types/index.ts:L144-L155'
  - symbol: AutoClipConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L157-L159'
  - symbol: DetectedInterval
    kind: interface
    at: 'frontend/src/types/index.ts:L163-L175'
  - symbol: SliceTask
    kind: interface
    at: 'frontend/src/types/index.ts:L179-L203'
  - symbol: WorkerNode
    kind: interface
    at: 'frontend/src/types/index.ts:L205-L234'
  - symbol: WorkerRunningTask
    kind: interface
    at: 'frontend/src/types/index.ts:L236-L244'
  - symbol: SliceOutput
    kind: interface
    at: 'frontend/src/types/index.ts:L246-L258'
  - symbol: DedupeConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L260-L262'
  - symbol: PublishTask
    kind: interface
    at: 'frontend/src/types/index.ts:L266-L298'
  - symbol: PublishTimeSlot
    kind: interface
    at: 'frontend/src/types/index.ts:L300-L309'
  - symbol: PublishProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L311-L335'
  - symbol: PublishBatch
    kind: interface
    at: 'frontend/src/types/index.ts:L337-L345'
  - symbol: Publication
    kind: interface
    at: 'frontend/src/types/index.ts:L347-L357'
  - symbol: VideoAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L361-L378'
  - symbol: MiniProgram
    kind: interface
    at: 'frontend/src/types/index.ts:L380-L389'
  - symbol: OperatorRouteRow
    kind: interface
    at: 'frontend/src/types/index.ts:L393-L408'
  - symbol: OperatorStat
    kind: interface
    at: 'frontend/src/types/index.ts:L410-L414'
  - symbol: PublishAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L416-L436'
  - symbol: LoginAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L438-L451'
  - symbol: RiskEventItem
    kind: interface
    at: 'frontend/src/types/index.ts:L453-L465'
  - symbol: AuditResult
    kind: interface
    at: 'frontend/src/types/index.ts:L467-L470'
  - symbol: MultiOpVerification
    kind: interface
    at: 'frontend/src/types/index.ts:L474-L486'
  - symbol: ShortDramaGeneration
    kind: interface
    at: 'frontend/src/types/index.ts:L490-L499'
  - symbol: ShortDramaAnalysisRow
    kind: interface
    at: 'frontend/src/types/index.ts:L501-L521'
  - symbol: ShortDramaSummary
    kind: interface
    at: 'frontend/src/types/index.ts:L523-L530'
  - symbol: ShortDramaTopic
    kind: interface
    at: 'frontend/src/types/index.ts:L532-L535'
  - symbol: PlatformProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L539-L549'
  - symbol: SystemConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L551-L556'
  - symbol: DashboardOverview
    kind: interface
    at: 'frontend/src/types/index.ts:L560-L569'
  - symbol: TrendPoint
    kind: interface
    at: 'frontend/src/types/index.ts:L571-L582'
  - symbol: FunnelData
    kind: interface
    at: 'frontend/src/types/index.ts:L584-L596'
  - symbol: VideoMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L598-L627'
  - symbol: MiniProgramMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L629-L639'
  - symbol: AdMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L641-L655'
  - symbol: DramaMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L657-L668'
  - symbol: EcosystemMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L670-L681'
  - symbol: ImportTemplate
    kind: interface
    at: 'frontend/src/types/index.ts:L683-L690'
  - symbol: ImportHistoryRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L692-L703'
  - symbol: PlatformDetectResult
    kind: interface
    at: 'frontend/src/types/index.ts:L705-L719'
  - symbol: FilePreviewResult
    kind: interface
    at: 'frontend/src/types/index.ts:L721-L725'
  - symbol: CrossAnalysisData
    kind: interface
    at: 'frontend/src/types/index.ts:L727-L736'
  - symbol: FunnelCompareData
    kind: interface
    at: 'frontend/src/types/index.ts:L738-L757'
  - symbol: DramaDetail
    kind: interface
    at: 'frontend/src/types/index.ts:L759-L776'
  - symbol: Role
    kind: type
    at: 'frontend/src/types/index.ts:L780-L780'
  - symbol: User
    kind: interface
    at: 'frontend/src/types/index.ts:L782-L793'
  - symbol: LoginResponse
    kind: interface
    at: 'frontend/src/types/index.ts:L795-L799'
  - symbol: RoleOption
    kind: interface
    at: 'frontend/src/types/index.ts:L801-L804'
  - symbol: AlertRule
    kind: interface
    at: 'frontend/src/types/index.ts:L820-L832'
  - symbol: AlertEvent
    kind: interface
    at: 'frontend/src/types/index.ts:L834-L846'
  - symbol: ChannelOperator
    kind: interface
    at: 'frontend/src/types/index.ts:L850-L857'
  - symbol: ChannelAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L859-L879'
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
