---
name: Storage Cleanup & Orphan Reclamation
slug: storage-cleanup-orphan-reclamation
type: system
sources:
  - path: scripts/cleanup_orphans.py
    hash: 6253490f6ff0ebc20eba9e5c10fef30d6ba802d26087d8d4d1085b0f42f10856
  - path: scripts/qr_render_spike.py
    hash: 1ac4ad6ef2c1b75e981d23c0fd8add47d01eeae962cf58e7a9f686524f9849d0
sources_digest: 13083178b7e594c0a5c24c8931e56bc2ea490e974ec91686c649bd50129891ac
links:
  - to: rpa-multi-operator-infrastructure
    relation: uses
    description: >-
      qr_render_spike.py connects to the same CDP Chromium instances (default
      port 9223) to validate QR extraction.
generator:
  version: 1
covers:
  - symbol: human_size
    kind: function
    at: 'scripts/cleanup_orphans.py:L49-L55'
  - symbol: media_path_size
    kind: function
    at: 'scripts/cleanup_orphans.py:L58-L75'
  - symbol: _collect_valid
    kind: function
    at: 'scripts/cleanup_orphans.py:L78-L102'
  - symbol: _scan_raw
    kind: function
    at: 'scripts/cleanup_orphans.py:L105-L113'
  - symbol: _scan_sliced
    kind: function
    at: 'scripts/cleanup_orphans.py:L116-L128'
  - symbol: _scan_media
    kind: function
    at: 'scripts/cleanup_orphans.py:L131-L158'
  - symbol: _remove_media
    kind: function
    at: 'scripts/cleanup_orphans.py:L161-L173'
  - symbol: main
    kind: function
    at: 'scripts/cleanup_orphans.py:L176-L246'
  - symbol: run_spike
    kind: function
    at: 'scripts/qr_render_spike.py:L27-L95'
  - symbol: main
    kind: function
    at: 'scripts/qr_render_spike.py:L98-L110'
---
<!-- context:generated:start -->
## Summary

cleanup_orphans.py scans MinIO raw-footage and sliced buckets plus the local /app/media volume for data with no DB record, defaulting to dry-run with a detailed report and requiring explicit --delete. It conservatively skips non-slices/ prefixes in the sliced bucket to avoid deleting unknown structures, and has a permission-error guard instructing users to rebuild the autoclip image if the 0777 fix isn't applied. qr_render_spike.py validates the CDP-extract-QR pipeline for WeChat login, centralizing QR selectors for versioning and treating small screenshots as selector misses.

## Related

- uses [[rpa-multi-operator-infrastructure]] — qr_render_spike.py connects to the same CDP Chromium instances (default port 9223) to validate QR extraction.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
