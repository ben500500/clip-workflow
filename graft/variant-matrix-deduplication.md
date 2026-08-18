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
    at: 'backend/app/api/variants.py:L41-L45'
  - symbol: VariantBindRequest
    kind: class
    at: 'backend/app/api/variants.py:L48-L50'
  - symbol: _get_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L53-L63'
  - symbol: _list_variant_groups
    kind: function
    at: 'backend/app/api/variants.py:L66-L101'
  - symbol: variant_matrix
    kind: function
    at: 'backend/app/api/variants.py:L105-L111'
  - symbol: variant_detail
    kind: function
    at: 'backend/app/api/variants.py:L115-L150'
  - symbol: generate_variants
    kind: function
    at: 'backend/app/api/variants.py:L154-L171'
  - symbol: verify_variant
    kind: function
    at: 'backend/app/api/variants.py:L175-L190'
  - symbol: bind_variant_account
    kind: function
    at: 'backend/app/api/variants.py:L194-L216'
  - symbol: update_thresholds
    kind: function
    at: 'backend/app/api/variants.py:L220-L239'
  - symbol: uuid_of
    kind: function
    at: 'backend/app/api/variants.py:L242-L247'
---
<!-- context:generated:start -->
## Summary

Multi-account video deduplication via variant matrix: lists variant groups with fingerprint distances and collision flags, triggers variant generation via Celery, verifies fingerprints before publication (30s synchronous wait), and binds variants to accounts with a one-account-per-variant constraint. Zero-intrusion when variant_count=1 or no variants exist; default thresholds (phash 0.20, audio 0.15, seg 0.30, combined 0.15) overridable via SystemConfig.

## Related

- uses [[publish-tasks-scheduling]] — publish_batches calls guard_account_variant_unique to prevent duplicate variant publishing.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
