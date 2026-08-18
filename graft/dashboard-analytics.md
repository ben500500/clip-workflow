---
name: Dashboard & Analytics
slug: dashboard-analytics
type: system
sources:
  - path: backend/app/api/dashboard.py
    hash: 49d2a534cc9105116ee74539e9800cb69015546b3d091da5e31305e33abb44f4
sources_digest: b43f8e676810f75597b583f40b7ff8c6786fd46915811224c652e280606ba276
links:
  - to: system-config-platform-profiles
    relation: uses
    description: Reads SystemConfig for default dashboard config values.
generator:
  version: 1
covers:
  - symbol: VideoMetricResponse
    kind: class
    at: 'backend/app/api/dashboard.py:L34-L63'
  - symbol: VideoTagsUpdate
    kind: class
    at: 'backend/app/api/dashboard.py:L66-L67'
  - symbol: ImportResultResponse
    kind: class
    at: 'backend/app/api/dashboard.py:L70-L73'
  - symbol: DashboardConfigResponse
    kind: class
    at: 'backend/app/api/dashboard.py:L76-L77'
  - symbol: _serialize_video_metric
    kind: function
    at: 'backend/app/api/dashboard.py:L82-L112'
  - symbol: _parse_account_id
    kind: function
    at: 'backend/app/api/dashboard.py:L115-L122'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/dashboard.py:L125-L132'
  - symbol: get_overview
    kind: function
    at: 'backend/app/api/dashboard.py:L138-L146'
  - symbol: get_overview_trend
    kind: function
    at: 'backend/app/api/dashboard.py:L150-L160'
  - symbol: get_overview_funnel
    kind: function
    at: 'backend/app/api/dashboard.py:L164-L172'
  - symbol: get_top_videos
    kind: function
    at: 'backend/app/api/dashboard.py:L176-L183'
  - symbol: list_video_metrics
    kind: function
    at: 'backend/app/api/dashboard.py:L189-L239'
  - symbol: get_video_ranking
    kind: function
    at: 'backend/app/api/dashboard.py:L243-L251'
  - symbol: get_video_detail
    kind: function
    at: 'backend/app/api/dashboard.py:L255-L270'
  - symbol: update_video_tags
    kind: function
    at: 'backend/app/api/dashboard.py:L274-L308'
  - symbol: get_mini_program_metrics
    kind: function
    at: 'backend/app/api/dashboard.py:L314-L353'
  - symbol: get_ad_metrics
    kind: function
    at: 'backend/app/api/dashboard.py:L359-L402'
  - symbol: get_drama_ranking
    kind: function
    at: 'backend/app/api/dashboard.py:L408-L445'
  - symbol: get_funnel
    kind: function
    at: 'backend/app/api/dashboard.py:L451-L459'
  - symbol: get_funnel_trend
    kind: function
    at: 'backend/app/api/dashboard.py:L463-L504'
  - symbol: import_video_metrics
    kind: function
    at: 'backend/app/api/dashboard.py:L510-L518'
  - symbol: import_mini_program_metrics
    kind: function
    at: 'backend/app/api/dashboard.py:L522-L530'
  - symbol: import_ad_metrics
    kind: function
    at: 'backend/app/api/dashboard.py:L534-L542'
  - symbol: download_import_template
    kind: function
    at: 'backend/app/api/dashboard.py:L546-L559'
  - symbol: get_dashboard_config
    kind: function
    at: 'backend/app/api/dashboard.py:L565-L585'
  - symbol: update_dashboard_config
    kind: function
    at: 'backend/app/api/dashboard.py:L589-L609'
  - symbol: smart_import_upload
    kind: function
    at: 'backend/app/api/dashboard.py:L615-L623'
  - symbol: import_preview
    kind: function
    at: 'backend/app/api/dashboard.py:L627-L632'
  - symbol: import_confirm
    kind: function
    at: 'backend/app/api/dashboard.py:L636-L652'
  - symbol: list_import_templates
    kind: function
    at: 'backend/app/api/dashboard.py:L656-L660'
  - symbol: save_custom_import_template
    kind: function
    at: 'backend/app/api/dashboard.py:L664-L673'
  - symbol: list_import_history
    kind: function
    at: 'backend/app/api/dashboard.py:L677-L681'
  - symbol: get_ecosystem
    kind: function
    at: 'backend/app/api/dashboard.py:L687-L697'
  - symbol: get_cross_analysis
    kind: function
    at: 'backend/app/api/dashboard.py:L703-L711'
  - symbol: get_drama_detail
    kind: function
    at: 'backend/app/api/dashboard.py:L717-L763'
  - symbol: get_funnel_compare
    kind: function
    at: 'backend/app/api/dashboard.py:L769-L832'
  - symbol: build_filter
    kind: function
    at: 'backend/app/api/dashboard.py:L782-L786'
  - symbol: calc_change
    kind: function
    at: 'backend/app/api/dashboard.py:L808-L811'
  - symbol: _serialize_shortdrama_analysis_row
    kind: function
    at: 'backend/app/api/dashboard.py:L841-L896'
  - symbol: get_shortdrama_analysis
    kind: function
    at: 'backend/app/api/dashboard.py:L900-L970'
  - symbol: get_shortdrama_summary
    kind: function
    at: 'backend/app/api/dashboard.py:L974-L1027'
  - symbol: get_shortdrama_topics
    kind: function
    at: 'backend/app/api/dashboard.py:L1031-L1089'
---
<!-- context:generated:start -->
## Summary

Operational metrics for short drama content: overview stats, video listings with pagination/filtering, mini-program and ad metrics, drama rankings, funnel analysis, Excel-based data import, smart import with platform detection, ecosystem metrics, and cross-analysis. Delegates aggregation to dashboard_service, data_import_service, and smart_import_service. Uses a whitelist of sortable columns to prevent arbitrary attribute access, normalizes tags by writing back the first tag to content_type for backward compatibility, and supports both template-based and smart import workflows.

## Related

- uses [[system-config-platform-profiles]] — Reads SystemConfig for default dashboard config values.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
