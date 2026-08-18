---
name: Dashboard & Metrics Aggregation
slug: dashboard-metrics-aggregation
type: system
sources:
  - path: backend/app/models/dashboard.py
    hash: 080c8d83b6633f3a9558716aec32758c74ca8e73ded679719bbbee6913c06140
  - path: backend/app/services/dashboard_service.py
    hash: ff9135570eb6a597a9f1e17ac89539f39edfb8757d6a4f06206a66cd32c8c684
  - path: backend/app/services/data_import_service.py
    hash: d83e2360cb77e31c25f6f71d1917a48d6db23a2bca9b68e1c7d1ae05dce12723
  - path: backend/app/services/maintenance_service.py
    hash: 1871ad3c858243fee2a89cb9ff92b4388c1bb2b8994401b859bc6fedc928e9d2
sources_digest: 889bf3716aa48a094202386544fcd8ac461715caaca2136532ff8c69f04fbb17
links:
  - to: orm-model-registry
    relation: uses
    description: Metric models and archive targets
  - to: redis-streams-real-time-state
    relation: uses
    description: Cache layer for aggregated metrics
generator:
  version: 1
covers:
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
  - symbol: _cache_key
    kind: function
    at: 'backend/app/services/dashboard_service.py:L41-L48'
  - symbol: _get_cached_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L51-L62'
  - symbol: _set_cached_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L65-L78'
  - symbol: _get_cached_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L81-L92'
  - symbol: _get_snapshot_agg
    kind: function
    at: 'backend/app/services/dashboard_service.py:L95-L106'
  - symbol: _with_cache
    kind: function
    at: 'backend/app/services/dashboard_service.py:L109-L131'
  - symbol: get_overview
    kind: function
    at: 'backend/app/services/dashboard_service.py:L134-L145'
  - symbol: _compute_overview
    kind: function
    at: 'backend/app/services/dashboard_service.py:L148-L241'
  - symbol: get_video_ranking
    kind: function
    at: 'backend/app/services/dashboard_service.py:L244-L296'
  - symbol: get_funnel
    kind: function
    at: 'backend/app/services/dashboard_service.py:L299-L312'
  - symbol: _compute_funnel
    kind: function
    at: 'backend/app/services/dashboard_service.py:L315-L415'
  - symbol: get_trend
    kind: function
    at: 'backend/app/services/dashboard_service.py:L418-L434'
  - symbol: _compute_trend
    kind: function
    at: 'backend/app/services/dashboard_service.py:L437-L542'
  - symbol: _validate_columns
    kind: function
    at: 'backend/app/services/data_import_service.py:L47-L58'
  - symbol: _normalize_columns
    kind: function
    at: 'backend/app/services/data_import_service.py:L61-L64'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/services/data_import_service.py:L67-L78'
  - symbol: _safe_int
    kind: function
    at: 'backend/app/services/data_import_service.py:L81-L88'
  - symbol: _safe_float
    kind: function
    at: 'backend/app/services/data_import_service.py:L91-L98'
  - symbol: _upsert_video_metric
    kind: function
    at: 'backend/app/services/data_import_service.py:L101-L125'
  - symbol: _upsert_metric
    kind: function
    at: 'backend/app/services/data_import_service.py:L128-L150'
  - symbol: import_video_metrics
    kind: function
    at: 'backend/app/services/data_import_service.py:L153-L244'
  - symbol: import_mini_program_metrics
    kind: function
    at: 'backend/app/services/data_import_service.py:L247-L313'
  - symbol: import_ad_metrics
    kind: function
    at: 'backend/app/services/data_import_service.py:L316-L386'
  - symbol: _generate_template_sync
    kind: function
    at: 'backend/app/services/data_import_service.py:L389-L439'
  - symbol: generate_import_template
    kind: function
    at: 'backend/app/services/data_import_service.py:L442-L454'
  - symbol: archive_old_metrics
    kind: function
    at: 'backend/app/services/maintenance_service.py:L32-L64'
  - symbol: cleanup_temp_files
    kind: function
    at: 'backend/app/services/maintenance_service.py:L67-L101'
  - symbol: apply_minio_lifecycle
    kind: function
    at: 'backend/app/services/maintenance_service.py:L104-L157'
---
<!-- context:generated:start -->
## Summary

Aggregates overview/ranking/funnel/trend from denormalized data-warehouse-style metric models (VideoMetric, AdMetric, MiniProgramMetric, DramaMetric, FunnelSnapshot) with Redis caching (30s TTL) and hourly snapshot fallback for DB failure. Validates sort columns to prevent injection; computes funnel from raw metrics when no snapshot exists. Excel bulk import via pandas (offloaded to executor to avoid blocking event loop) upserts keyed by (video_id, publish_date) or (date, account_id).

## Related

- uses [[orm-model-registry]] — Metric models and archive targets
- uses [[redis-streams-real-time-state]] — Cache layer for aggregated metrics
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
