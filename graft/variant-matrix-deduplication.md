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
    at: 'backend/app/api/variants.py:L49-L53'
  - symbol: VariantBindRequest
    kind: class
    at: 'backend/app/api/variants.py:L56-L58'
  - symbol: _get_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L61-L73'
  - symbol: _list_variant_groups
    kind: function
    at: 'backend/app/api/variants.py:L76-L113'
  - symbol: variant_matrix
    kind: function
    at: 'backend/app/api/variants.py:L117-L123'
  - symbol: variant_detail
    kind: function
    at: 'backend/app/api/variants.py:L127-L164'
  - symbol: generate_variants
    kind: function
    at: 'backend/app/api/variants.py:L168-L187'
  - symbol: verify_variant
    kind: function
    at: 'backend/app/api/variants.py:L191-L206'
  - symbol: bind_variant_account
    kind: function
    at: 'backend/app/api/variants.py:L210-L232'
  - symbol: update_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L236-L255'
  - symbol: uuid_of
    kind: function
    at: 'backend/app/api/variants.py:L258-L263'
  - symbol: VariantGenerateBatchRequest
    kind: class
    at: 'backend/app/api/variants.py:L265-L269'
  - symbol: SliceOutputListRequest
    kind: class
    at: 'backend/app/api/variants.py:L272-L275'
  - symbol: generate_variants_batch
    kind: function
    at: 'backend/app/api/variants.py:L279-L325'
  - symbol: _check_output_access
    kind: function
    at: 'backend/app/api/variants.py:L328-L345'
  - symbol: _load_variant_or_404
    kind: function
    at: 'backend/app/api/variants.py:L348-L355'
  - symbol: _guard_variant_access
    kind: function
    at: 'backend/app/api/variants.py:L358-L367'
  - symbol: _delete_minio_file
    kind: function
    at: 'backend/app/api/variants.py:L370-L379'
  - symbol: cleanup_stuck_variants
    kind: function
    at: 'backend/app/api/variants.py:L383-L413'
  - symbol: delete_variant
    kind: function
    at: 'backend/app/api/variants.py:L417-L433'
  - symbol: delete_variant_group
    kind: function
    at: 'backend/app/api/variants.py:L437-L467'
  - symbol: download_variant
    kind: function
    at: 'backend/app/api/variants.py:L471-L489'
  - symbol: list_slice_outputs
    kind: function
    at: 'backend/app/api/variants.py:L493-L652'
---
<!-- context:generated:start -->
## Summary

Multi-account video deduplication via variant matrix: lists variant groups with fingerprint distances and collision flags, triggers variant generation via Celery, verifies fingerprints before publication (30s synchronous wait), and binds variants to accounts with a one-account-per-variant constraint. Zero-intrusion when variant_count=1 or no variants exist; default thresholds (phash 0.20, audio 0.15, seg 0.30, combined 0.15) overridable via SystemConfig.

## Related

- uses [[publish-tasks-scheduling]] — publish_batches calls guard_account_variant_unique to prevent duplicate variant publishing.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
