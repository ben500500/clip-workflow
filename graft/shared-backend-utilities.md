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
    at: 'backend/app/utils/helpers.py:L11-L16'
  - symbol: parse_time
    kind: function
    at: 'backend/app/utils/helpers.py:L19-L26'
  - symbol: sanitize_filename
    kind: function
    at: 'backend/app/utils/helpers.py:L29-L40'
  - symbol: build_clip_name
    kind: function
    at: 'backend/app/utils/helpers.py:L43-L53'
  - symbol: generate_cutlist
    kind: function
    at: 'backend/app/utils/helpers.py:L56-L70'
  - symbol: generate_intervals_file
    kind: function
    at: 'backend/app/utils/helpers.py:L73-L84'
  - symbol: write_temp_file
    kind: function
    at: 'backend/app/utils/helpers.py:L87-L91'
  - symbol: write_temp_json
    kind: function
    at: 'backend/app/utils/helpers.py:L94-L98'
  - symbol: ensure_dir
    kind: function
    at: 'backend/app/utils/helpers.py:L101-L104'
  - symbol: generate_signed_url_headers
    kind: function
    at: 'backend/app/utils/helpers.py:L107-L109'
  - symbol: human_readable_size
    kind: function
    at: 'backend/app/utils/helpers.py:L112-L120'
  - symbol: utc_iso
    kind: function
    at: 'backend/app/utils/helpers.py:L122-L133'
---
<!-- context:generated:start -->
## Summary

Aggregated helper functions: time formatting (seconds ↔ HH:MM:SS.mmm), filename sanitization, clip list generation, temp file management, and response/validation/ID helpers. Uses Beijing time (UTC+8) for clip naming dates while handling the DB's timestamp-without-timezone convention; utc_iso appends a UTC marker to naive datetimes to prevent frontend timezone misinterpretation. The utils/__init__.py facade centralizes re-exports to avoid circular imports.

## Related

- uses [[wechat-download-pipeline]] — helpers used across services for temp files and filename generation
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
