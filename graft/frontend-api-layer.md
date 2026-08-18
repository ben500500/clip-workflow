---
name: Frontend API Layer
slug: frontend-api-layer
type: system
sources:
  - path: frontend/src/types/index.ts
    hash: 4e4e97941b1a9c684221522deca24dfa3f8f0bf6c4ee87af50a0d517bffb8496
  - path: frontend/src/utils/format.ts
    hash: 60045635a7ad286a573ef3329b36e1bbfea883da3830b43adea2429eb41f28c8
  - path: frontend/vite.config.ts
    hash: 3d17d684c6130bf76421b56eea915d0b1c99c599711dba2002a1c31c3377dd18
sources_digest: c5109f951fa406e36457853857d9982d066e1a328727442082b4ba0304e53776
links:
  - to: episode-production-pipeline-pages
    relation: implements
    description: >-
      All pages consume these types and formatters; status maps must stay in
      sync with backend workflow states.
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
    at: 'frontend/src/types/index.ts:L262-L285'
  - symbol: PublishBatch
    kind: interface
    at: 'frontend/src/types/index.ts:L287-L295'
  - symbol: Publication
    kind: interface
    at: 'frontend/src/types/index.ts:L297-L307'
  - symbol: VideoAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L311-L328'
  - symbol: MiniProgram
    kind: interface
    at: 'frontend/src/types/index.ts:L330-L339'
  - symbol: OperatorRouteRow
    kind: interface
    at: 'frontend/src/types/index.ts:L343-L358'
  - symbol: OperatorStat
    kind: interface
    at: 'frontend/src/types/index.ts:L360-L364'
  - symbol: PublishAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L366-L386'
  - symbol: LoginAuditItem
    kind: interface
    at: 'frontend/src/types/index.ts:L388-L401'
  - symbol: RiskEventItem
    kind: interface
    at: 'frontend/src/types/index.ts:L403-L415'
  - symbol: AuditResult
    kind: interface
    at: 'frontend/src/types/index.ts:L417-L420'
  - symbol: MultiOpVerification
    kind: interface
    at: 'frontend/src/types/index.ts:L424-L436'
  - symbol: ShortDramaGeneration
    kind: interface
    at: 'frontend/src/types/index.ts:L440-L449'
  - symbol: ShortDramaAnalysisRow
    kind: interface
    at: 'frontend/src/types/index.ts:L451-L471'
  - symbol: ShortDramaSummary
    kind: interface
    at: 'frontend/src/types/index.ts:L473-L480'
  - symbol: ShortDramaTopic
    kind: interface
    at: 'frontend/src/types/index.ts:L482-L485'
  - symbol: PlatformProfile
    kind: interface
    at: 'frontend/src/types/index.ts:L489-L499'
  - symbol: SystemConfig
    kind: interface
    at: 'frontend/src/types/index.ts:L501-L506'
  - symbol: DashboardOverview
    kind: interface
    at: 'frontend/src/types/index.ts:L510-L519'
  - symbol: TrendPoint
    kind: interface
    at: 'frontend/src/types/index.ts:L521-L532'
  - symbol: FunnelData
    kind: interface
    at: 'frontend/src/types/index.ts:L534-L546'
  - symbol: VideoMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L548-L577'
  - symbol: MiniProgramMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L579-L589'
  - symbol: AdMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L591-L605'
  - symbol: DramaMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L607-L618'
  - symbol: EcosystemMetric
    kind: interface
    at: 'frontend/src/types/index.ts:L620-L631'
  - symbol: ImportTemplate
    kind: interface
    at: 'frontend/src/types/index.ts:L633-L640'
  - symbol: ImportHistoryRecord
    kind: interface
    at: 'frontend/src/types/index.ts:L642-L653'
  - symbol: PlatformDetectResult
    kind: interface
    at: 'frontend/src/types/index.ts:L655-L669'
  - symbol: FilePreviewResult
    kind: interface
    at: 'frontend/src/types/index.ts:L671-L675'
  - symbol: CrossAnalysisData
    kind: interface
    at: 'frontend/src/types/index.ts:L677-L686'
  - symbol: FunnelCompareData
    kind: interface
    at: 'frontend/src/types/index.ts:L688-L707'
  - symbol: DramaDetail
    kind: interface
    at: 'frontend/src/types/index.ts:L709-L726'
  - symbol: Role
    kind: type
    at: 'frontend/src/types/index.ts:L730-L730'
  - symbol: User
    kind: interface
    at: 'frontend/src/types/index.ts:L732-L743'
  - symbol: LoginResponse
    kind: interface
    at: 'frontend/src/types/index.ts:L745-L749'
  - symbol: RoleOption
    kind: interface
    at: 'frontend/src/types/index.ts:L751-L754'
  - symbol: AlertRule
    kind: interface
    at: 'frontend/src/types/index.ts:L770-L782'
  - symbol: AlertEvent
    kind: interface
    at: 'frontend/src/types/index.ts:L784-L796'
  - symbol: ChannelOperator
    kind: interface
    at: 'frontend/src/types/index.ts:L800-L807'
  - symbol: ChannelAccount
    kind: interface
    at: 'frontend/src/types/index.ts:L809-L829'
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

The typed contract layer: types/index.ts mirrors backend API responses with snake_case fields, nullable columns, and ApiList<T> pagination wrappers; utils/format.ts provides pure formatters (base-1024 file sizes, durations omitting hours under one hour, hardcoded status→color/label maps that must be updated when new workflow states are added). Vite config proxies /api to localhost:8080 with changeOrigin.

## Related

- implements [[episode-production-pipeline-pages]] — All pages consume these types and formatters; status maps must stay in sync with backend workflow states.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
