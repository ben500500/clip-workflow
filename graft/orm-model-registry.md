---
name: ORM Model Registry
slug: orm-model-registry
type: system
sources:
  - path: backend/app/models/__init__.py
    hash: 100682b3206fc5e75f6bd183dbea53a12c3980147c793f61d9382eecee86f125
  - path: backend/app/models/audit.py
    hash: 107dcc44551ef231091f4ae86f68e75a037c0b9e6cd8932b78014ca02b707c7d
  - path: backend/app/models/channel.py
    hash: 7d822e6de267ee591fc80177b8324d0480dba33c8fa0a1e4b05f24e54171787b
  - path: backend/app/models/dashboard.py
    hash: 080c8d83b6633f3a9558716aec32758c74ca8e73ded679719bbbee6913c06140
  - path: backend/app/models/drama.py
    hash: d92c9c97e108ebd4aab5a799784dc073cdee2bf795c74bd08e1a88c1b4e01730
  - path: backend/app/models/material.py
    hash: a88c6f0f451a2c6fac47bf9ad2a307d26d478224ebab1d5d478b62a13e7f82d8
  - path: backend/app/models/models.py
    hash: 437161f362c80997a4b99b2ceb111edb54768c9adaf4c701ba93613ad0db3b24
  - path: backend/app/models/monitor.py
    hash: 02281c162a148f812ccbc31ff28dca2415a5002ecc9647603ef6261617a488f7
  - path: backend/app/models/publish.py
    hash: a35d874c0b7e68264d8a6eed0d068c484a19d9a617c9c4d4bc10d9f009defa1b
  - path: backend/app/models/shortdrama.py
    hash: 638627f330df49bff2aa249f95703cc9af781a7c04a731762f63c4e393922488
  - path: backend/app/models/variant.py
    hash: 27f6c33ce119bf8b2d06316d46411d4cae5b18b7b23945bb387fd8fd1a0c24c0
sources_digest: cb25755cdd85198ac320e4e012172031825f9d4d291b77e5c58ac7eaa5200af6
links:
  - to: configuration-database-bootstrap
    relation: depends_on
    description: All models inherit Base from app.database
  - to: data-isolation-rbac
    relation: implements
    description: >-
      default_data_scope_for_role and user_can_access_all_materials defined in
      user.py
generator:
  version: 1
covers:
  - symbol: AuditLog
    kind: class
    at: 'backend/app/models/audit.py:L22-L41'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L40-L41'
  - symbol: PublishAudit
    kind: class
    at: 'backend/app/models/audit.py:L44-L76'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L75-L76'
  - symbol: LoginAudit
    kind: class
    at: 'backend/app/models/audit.py:L79-L101'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L100-L101'
  - symbol: CookieAccessLog
    kind: class
    at: 'backend/app/models/audit.py:L104-L122'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/audit.py:L121-L122'
  - symbol: ChannelAccount
    kind: class
    at: 'backend/app/models/channel.py:L33-L61'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/channel.py:L60-L61'
  - symbol: ChannelOperator
    kind: class
    at: 'backend/app/models/channel.py:L64-L93'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/channel.py:L92-L93'
  - symbol: VideoMetric
    kind: class
    at: 'backend/app/models/dashboard.py:L26-L64'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/dashboard.py:L63-L64'
  - symbol: MiniProgramMetric
    kind: class
    at: 'backend/app/models/dashboard.py:L67-L81'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/dashboard.py:L80-L81'
  - symbol: AdMetric
    kind: class
    at: 'backend/app/models/dashboard.py:L84-L102'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/dashboard.py:L101-L102'
  - symbol: DramaMetric
    kind: class
    at: 'backend/app/models/dashboard.py:L105-L120'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/dashboard.py:L119-L120'
  - symbol: FunnelSnapshot
    kind: class
    at: 'backend/app/models/dashboard.py:L123-L142'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/dashboard.py:L141-L142'
  - symbol: EcosystemMetric
    kind: class
    at: 'backend/app/models/dashboard.py:L145-L160'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/dashboard.py:L159-L160'
  - symbol: gen_drama_code
    kind: function
    at: 'backend/app/models/drama.py:L33-L38'
  - symbol: Drama
    kind: class
    at: 'backend/app/models/drama.py:L41-L93'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/drama.py:L92-L93'
  - symbol: DramaStill
    kind: class
    at: 'backend/app/models/drama.py:L96-L108'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/drama.py:L107-L108'
  - symbol: DramaAccount
    kind: class
    at: 'backend/app/models/drama.py:L111-L129'
  - symbol: DramaMaterial
    kind: class
    at: 'backend/app/models/drama.py:L132-L144'
  - symbol: Project
    kind: class
    at: 'backend/app/models/material.py:L29-L45'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L44-L45'
  - symbol: Episode
    kind: class
    at: 'backend/app/models/material.py:L48-L73'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L72-L73'
  - symbol: AutoClipProject
    kind: class
    at: 'backend/app/models/material.py:L76-L91'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L90-L91'
  - symbol: AutoClipRun
    kind: class
    at: 'backend/app/models/material.py:L94-L117'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L116-L117'
  - symbol: ClipCandidate
    kind: class
    at: 'backend/app/models/material.py:L120-L143'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L142-L143'
  - symbol: DetectedInterval
    kind: class
    at: 'backend/app/models/material.py:L146-L164'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L163-L164'
  - symbol: SliceTask
    kind: class
    at: 'backend/app/models/material.py:L167-L217'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L216-L217'
  - symbol: SliceOutput
    kind: class
    at: 'backend/app/models/material.py:L220-L242'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L241-L242'
  - symbol: Publication
    kind: class
    at: 'backend/app/models/material.py:L245-L263'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L262-L263'
  - symbol: SystemConfig
    kind: class
    at: 'backend/app/models/material.py:L266-L275'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L274-L275'
  - symbol: PlatformProfile
    kind: class
    at: 'backend/app/models/material.py:L278-L292'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L291-L292'
  - symbol: ImportTemplate
    kind: class
    at: 'backend/app/models/material.py:L295-L307'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L306-L307'
  - symbol: ImportHistory
    kind: class
    at: 'backend/app/models/material.py:L310-L326'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L325-L326'
  - symbol: BatchSlice
    kind: class
    at: 'backend/app/models/material.py:L329-L359'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L358-L359'
  - symbol: BatchSliceItem
    kind: class
    at: 'backend/app/models/material.py:L362-L390'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L389-L390'
  - symbol: WorkerNode
    kind: class
    at: 'backend/app/models/monitor.py:L25-L55'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L54-L55'
  - symbol: AlertRule
    kind: class
    at: 'backend/app/models/monitor.py:L58-L80'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L79-L80'
  - symbol: AlertEvent
    kind: class
    at: 'backend/app/models/monitor.py:L83-L103'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L102-L103'
  - symbol: RiskEvent
    kind: class
    at: 'backend/app/models/monitor.py:L106-L127'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/monitor.py:L126-L127'
  - symbol: VideoAccount
    kind: class
    at: 'backend/app/models/publish.py:L26-L60'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L59-L60'
  - symbol: MiniProgram
    kind: class
    at: 'backend/app/models/publish.py:L63-L82'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L81-L82'
  - symbol: PublishBatch
    kind: class
    at: 'backend/app/models/publish.py:L85-L104'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L103-L104'
  - symbol: PublishTask
    kind: class
    at: 'backend/app/models/publish.py:L107-L155'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L154-L155'
  - symbol: PublishProfile
    kind: class
    at: 'backend/app/models/publish.py:L158-L189'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L188-L189'
  - symbol: PublishTimeSlot
    kind: class
    at: 'backend/app/models/publish.py:L192-L214'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L213-L214'
  - symbol: PublishMaterial
    kind: class
    at: 'backend/app/models/publish.py:L217-L244'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/publish.py:L243-L244'
  - symbol: ShortdramaPrompt
    kind: class
    at: 'backend/app/models/shortdrama.py:L26-L100'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/shortdrama.py:L99-L100'
  - symbol: WatermarkTask
    kind: class
    at: 'backend/app/models/shortdrama.py:L103-L131'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/shortdrama.py:L130-L131'
  - symbol: WatermarkVideo
    kind: class
    at: 'backend/app/models/shortdrama.py:L134-L161'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/shortdrama.py:L160-L161'
  - symbol: ClipVariant
    kind: class
    at: 'backend/app/models/variant.py:L39-L87'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/variant.py:L86-L87'
  - symbol: VideoFingerprint
    kind: class
    at: 'backend/app/models/variant.py:L90-L121'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/variant.py:L120-L121'
---
<!-- context:generated:start -->
## Summary

Domain-split SQLAlchemy models (user, material, publish, dashboard, audit, monitor, shortdrama, channel, variant, drama) re-exported through models.py facade to preserve legacy import paths and populate Base.metadata for alembic. Any new model must be added to its domain module AND re-exported in models.py or it's invisible to existing imports and migrations. Uses SQLAlchemy global class registry to resolve cross-module string relationships without circular imports.

## Related

- depends on [[configuration-database-bootstrap]] — All models inherit Base from app.database
- implements [[data-isolation-rbac]] — default_data_scope_for_role and user_can_access_all_materials defined in user.py
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
