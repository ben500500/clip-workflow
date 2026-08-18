---
name: Smart Import Service
slug: smart-import-service
type: system
sources:
  - path: backend/app/services/smart_import_service.py
    hash: 514ba1a36839a7700c9cf7d1d9a74b21e45ca0542bee07284b67fd2506577527
sources_digest: 6938bb78d75a0c40cf1b8f8af7a47218a53b608339f7586089d4c47ff578a7f7
links: []
generator:
  version: 1
covers:
  - symbol: _normalize_headers
    kind: function
    at: 'backend/app/services/smart_import_service.py:L100-L102'
  - symbol: _read_headers_sync
    kind: function
    at: 'backend/app/services/smart_import_service.py:L105-L116'
  - symbol: _read_preview_sync
    kind: function
    at: 'backend/app/services/smart_import_service.py:L119-L130'
  - symbol: _detect_platform
    kind: function
    at: 'backend/app/services/smart_import_service.py:L133-L153'
  - symbol: _transform_row_sync
    kind: function
    at: 'backend/app/services/smart_import_service.py:L156-L177'
  - symbol: detect_platform
    kind: function
    at: 'backend/app/services/smart_import_service.py:L180-L212'
  - symbol: preview_file
    kind: function
    at: 'backend/app/services/smart_import_service.py:L215-L226'
  - symbol: confirm_import
    kind: function
    at: 'backend/app/services/smart_import_service.py:L229-L273'
  - symbol: BytesFileWrapper
    kind: class
    at: 'backend/app/services/smart_import_service.py:L255-L258'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/smart_import_service.py:L256-L258'
  - symbol: get_import_templates
    kind: function
    at: 'backend/app/services/smart_import_service.py:L276-L290'
  - symbol: save_custom_template
    kind: function
    at: 'backend/app/services/smart_import_service.py:L293-L317'
  - symbol: get_import_history
    kind: function
    at: 'backend/app/services/smart_import_service.py:L320-L340'
  - symbol: get_ecosystem_metrics
    kind: function
    at: 'backend/app/services/smart_import_service.py:L343-L382'
  - symbol: get_cross_analysis
    kind: function
    at: 'backend/app/services/smart_import_service.py:L385-L432'
---
<!-- context:generated:start -->
## Summary

Auto-detects and imports platform export data (WeChat Channels, Mini Program, Ad Platform, Douyin, Kuaishou) via scoring-based platform fingerprint matching that weights required headers more heavily. Normalizes headers for encoding variations, converts ad revenue cents to yuan, and provides ecosystem metrics and cross-analysis aggregation.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
