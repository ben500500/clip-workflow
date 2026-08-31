---
name: Variant Matrix & Deduplication
slug: variant-matrix-deduplication
type: system
sources:
  - path: backend/app/api/variants.py
    hash: 0a7e3ea55d85cbf9fc6b82875a4eda677a41f9df4d4c65509a771d0265daed50
sources_digest: 3898c7f3b4f18bcfa21af10856467d8f549eaaee72c6f591409d78b4c7cff142
links:
  - to: publish-tasks-scheduling
    relation: uses
    description: >-
      publish_batches calls guard_account_variant_unique to prevent duplicate
      variant publishing.
generator:
  version: 1
covers:
  - symbol: VariantGenerateRequest
    kind: class
    at: 'backend/app/api/variants.py:L50-L54'
  - symbol: VariantBindRequest
    kind: class
    at: 'backend/app/api/variants.py:L57-L59'
  - symbol: _get_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L62-L74'
  - symbol: _list_variant_groups
    kind: function
    at: 'backend/app/api/variants.py:L77-L142'
  - symbol: variant_matrix
    kind: function
    at: 'backend/app/api/variants.py:L146-L152'
  - symbol: variant_detail
    kind: function
    at: 'backend/app/api/variants.py:L156-L193'
  - symbol: generate_variants
    kind: function
    at: 'backend/app/api/variants.py:L197-L216'
  - symbol: verify_variant
    kind: function
    at: 'backend/app/api/variants.py:L220-L235'
  - symbol: bind_variant_account
    kind: function
    at: 'backend/app/api/variants.py:L239-L261'
  - symbol: update_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L265-L284'
  - symbol: uuid_of
    kind: function
    at: 'backend/app/api/variants.py:L287-L292'
  - symbol: VariantGenerateBatchRequest
    kind: class
    at: 'backend/app/api/variants.py:L294-L298'
  - symbol: SliceOutputListRequest
    kind: class
    at: 'backend/app/api/variants.py:L301-L304'
  - symbol: generate_variants_batch
    kind: function
    at: 'backend/app/api/variants.py:L308-L354'
  - symbol: _check_output_access
    kind: function
    at: 'backend/app/api/variants.py:L357-L374'
  - symbol: _load_variant_or_404
    kind: function
    at: 'backend/app/api/variants.py:L377-L384'
  - symbol: _guard_variant_access
    kind: function
    at: 'backend/app/api/variants.py:L387-L396'
  - symbol: _delete_minio_file
    kind: function
    at: 'backend/app/api/variants.py:L399-L408'
  - symbol: cleanup_stuck_variants
    kind: function
    at: 'backend/app/api/variants.py:L412-L442'
  - symbol: delete_variant
    kind: function
    at: 'backend/app/api/variants.py:L446-L462'
  - symbol: delete_variant_group
    kind: function
    at: 'backend/app/api/variants.py:L466-L496'
  - symbol: download_variant_group_zip
    kind: function
    at: 'backend/app/api/variants.py:L500-L555'
  - symbol: download_variant
    kind: function
    at: 'backend/app/api/variants.py:L559-L577'
  - symbol: list_slice_outputs
    kind: function
    at: 'backend/app/api/variants.py:L581-L740'
---
<!-- context:generated:start -->
## Summary

Multi-account video deduplication via variant matrix: lists variant groups with fingerprint distances and collision flags, triggers variant generation via Celery, verifies fingerprints before publication (30s synchronous wait), and binds variants to accounts with a one-account-per-variant constraint. Zero-intrusion when variant_count=1 or no variants exist; default thresholds (phash 0.20, audio 0.15, seg 0.30, combined 0.15) overridable via SystemConfig.

## Related

- uses [[publish-tasks-scheduling]] — publish_batches calls guard_account_variant_unique to prevent duplicate variant publishing.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
