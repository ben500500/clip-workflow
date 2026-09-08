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
    at: 'backend/app/api/variants.py:L197-L227'
  - symbol: verify_variant
    kind: function
    at: 'backend/app/api/variants.py:L231-L246'
  - symbol: bind_variant_account
    kind: function
    at: 'backend/app/api/variants.py:L250-L272'
  - symbol: update_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L276-L295'
  - symbol: uuid_of
    kind: function
    at: 'backend/app/api/variants.py:L298-L303'
  - symbol: VariantGenerateBatchRequest
    kind: class
    at: 'backend/app/api/variants.py:L305-L309'
  - symbol: SliceOutputListRequest
    kind: class
    at: 'backend/app/api/variants.py:L312-L315'
  - symbol: generate_variants_batch
    kind: function
    at: 'backend/app/api/variants.py:L319-L376'
  - symbol: _check_output_access
    kind: function
    at: 'backend/app/api/variants.py:L379-L396'
  - symbol: _load_variant_or_404
    kind: function
    at: 'backend/app/api/variants.py:L399-L406'
  - symbol: _guard_variant_access
    kind: function
    at: 'backend/app/api/variants.py:L409-L418'
  - symbol: _delete_minio_file
    kind: function
    at: 'backend/app/api/variants.py:L421-L430'
  - symbol: cleanup_stuck_variants
    kind: function
    at: 'backend/app/api/variants.py:L434-L464'
  - symbol: delete_variant
    kind: function
    at: 'backend/app/api/variants.py:L468-L484'
  - symbol: delete_variant_group
    kind: function
    at: 'backend/app/api/variants.py:L488-L518'
  - symbol: download_variant_group_zip
    kind: function
    at: 'backend/app/api/variants.py:L522-L577'
  - symbol: download_variant
    kind: function
    at: 'backend/app/api/variants.py:L581-L599'
  - symbol: list_slice_outputs
    kind: function
    at: 'backend/app/api/variants.py:L603-L762'
---
<!-- context:generated:start -->
## Summary

Multi-account video deduplication via variant matrix: lists variant groups with fingerprint distances and collision flags, triggers variant generation via Celery, verifies fingerprints before publication (30s synchronous wait), and binds variants to accounts with a one-account-per-variant constraint. Zero-intrusion when variant_count=1 or no variants exist; default thresholds (phash 0.20, audio 0.15, seg 0.30, combined 0.15) overridable via SystemConfig.

## Related

- uses [[publish-tasks-scheduling]] — publish_batches calls guard_account_variant_unique to prevent duplicate variant publishing.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
