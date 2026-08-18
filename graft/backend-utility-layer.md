---
name: Backend Utility Layer
slug: backend-utility-layer
type: system
sources:
  - path: backend/app/utils/__init__.py
    hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - path: backend/app/utils/helpers.py
    hash: f76510424c6850e469490e35c4db355699c8a08f8917783b2ca8b891cd82206e
sources_digest: e7aa0c09814cd5997323c154b2335de732cedd04c2d979fc664609b0bbd3016d
links: []
generator:
  version: 1
covers:
  - symbol: format_time
    kind: function
    at: 'backend/app/utils/helpers.py:L10-L15'
  - symbol: parse_time
    kind: function
    at: 'backend/app/utils/helpers.py:L18-L25'
  - symbol: generate_cutlist
    kind: function
    at: 'backend/app/utils/helpers.py:L28-L42'
  - symbol: generate_intervals_file
    kind: function
    at: 'backend/app/utils/helpers.py:L45-L56'
  - symbol: write_temp_file
    kind: function
    at: 'backend/app/utils/helpers.py:L59-L63'
  - symbol: write_temp_json
    kind: function
    at: 'backend/app/utils/helpers.py:L66-L70'
  - symbol: ensure_dir
    kind: function
    at: 'backend/app/utils/helpers.py:L73-L76'
  - symbol: generate_signed_url_headers
    kind: function
    at: 'backend/app/utils/helpers.py:L79-L81'
  - symbol: human_readable_size
    kind: function
    at: 'backend/app/utils/helpers.py:L84-L92'
  - symbol: utc_iso
    kind: function
    at: 'backend/app/utils/helpers.py:L94-L105'
---
<!-- context:generated:start -->
## Summary

Centralized utility functions for the backend: format_response for standardizing API output, validate_input for schema-based validation, generate_id for unique identifiers, time conversion between seconds and HH:MM:SS.mmm, cutlist/interval text generation, temp file management, and utc_iso for serializing naive UTC datetimes with explicit +00:00 offset (preventing frontend timezone misinterpretation). Centralizing helpers here avoids circular imports but requires careful import ordering.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
