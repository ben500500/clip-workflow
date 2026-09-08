---
name: Shared Backend Utilities
slug: shared-backend-utilities
type: system
sources:
  - path: backend/app/utils/__init__.py
    hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - path: backend/app/utils/helpers.py
    hash: b7c222f4dacb42e4bafc09fd8ed6e32ea82b96d6d7aaf1762a16141256c7c054
sources_digest: 2ecc2fd91746ed8a30b94d327051d7b27cc6d7c1758957ec3a48278653547ca5
links:
  - to: wechat-download-pipeline
    relation: uses
    description: helpers used across services for temp files and filename generation
generator:
  version: 1
covers:
  - symbol: format_time
    kind: function
    at: 'backend/app/utils/helpers.py:L14-L19'
  - symbol: parse_time
    kind: function
    at: 'backend/app/utils/helpers.py:L22-L29'
  - symbol: sanitize_filename
    kind: function
    at: 'backend/app/utils/helpers.py:L32-L43'
  - symbol: build_clip_name
    kind: function
    at: 'backend/app/utils/helpers.py:L46-L56'
  - symbol: generate_cutlist
    kind: function
    at: 'backend/app/utils/helpers.py:L59-L157'
  - symbol: generate_intervals_file
    kind: function
    at: 'backend/app/utils/helpers.py:L160-L171'
  - symbol: write_temp_file
    kind: function
    at: 'backend/app/utils/helpers.py:L174-L178'
  - symbol: write_temp_json
    kind: function
    at: 'backend/app/utils/helpers.py:L181-L185'
  - symbol: ensure_dir
    kind: function
    at: 'backend/app/utils/helpers.py:L188-L191'
  - symbol: generate_signed_url_headers
    kind: function
    at: 'backend/app/utils/helpers.py:L194-L196'
  - symbol: human_readable_size
    kind: function
    at: 'backend/app/utils/helpers.py:L199-L207'
  - symbol: utc_iso
    kind: function
    at: 'backend/app/utils/helpers.py:L209-L220'
---
<!-- context:generated:start -->
## Summary

Aggregated helper functions: time formatting (seconds ↔ HH:MM:SS.mmm), filename sanitization, clip list generation, temp file management, and response/validation/ID helpers. Uses Beijing time (UTC+8) for clip naming dates while handling the DB's timestamp-without-timezone convention; utc_iso appends a UTC marker to naive datetimes to prevent frontend timezone misinterpretation. The utils/__init__.py facade centralizes re-exports to avoid circular imports.

## Related

- uses [[wechat-download-pipeline]] — helpers used across services for temp files and filename generation
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
