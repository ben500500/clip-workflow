---
name: Variant Generation Pipeline
slug: variant-generation-pipeline
type: system
sources:
  - path: backend/app/services/variant_service.py
    hash: aa4586ca686771ac2c29849458ef498668ae413eb10524e2ab87ecde4eb7c6ea
sources_digest: 39cbe5e4a46ea0797ee648c7e8c46716283e389a7c0ee18b2b8956ee9ce1c6d2
links:
  - to: object-storage-service-minio
    relation: uses
    description: Downloads base videos from MinIO and persists ClipVariant results
  - to: rpa-publishing-service
    relation: uses
    description: verify_variant_fingerprint provides pre-publish safety checks
  - to: slice-engine-orchestration
    relation: uses
    description: Applies variant recipes through the slice engine's dedupe mode
generator:
  version: 1
covers:
  - symbol: build_variant_recipes
    kind: function
    at: 'backend/app/services/variant_service.py:L76-L128'
  - symbol: _recipe_fingerprint_key
    kind: function
    at: 'backend/app/services/variant_service.py:L131-L133'
  - symbol: _load_output
    kind: function
    at: 'backend/app/services/variant_service.py:L136-L141'
  - symbol: _load_output_video_path
    kind: function
    at: 'backend/app/services/variant_service.py:L144-L157'
  - symbol: _save_variant_row
    kind: function
    at: 'backend/app/services/variant_service.py:L160-L180'
  - symbol: _update_variant
    kind: function
    at: 'backend/app/services/variant_service.py:L183-L189'
  - symbol: _save_fingerprint
    kind: function
    at: 'backend/app/services/variant_service.py:L192-L208'
  - symbol: _load_group_fingerprints
    kind: function
    at: 'backend/app/services/variant_service.py:L211-L224'
  - symbol: _check_against_history
    kind: function
    at: 'backend/app/services/variant_service.py:L227-L261'
  - symbol: _build_variant_cutlist
    kind: function
    at: 'backend/app/services/variant_service.py:L264-L302'
  - symbol: _generate_variant_file
    kind: function
    at: 'backend/app/services/variant_service.py:L305-L347'
  - symbol: _probe_duration_sec
    kind: function
    at: 'backend/app/services/variant_service.py:L350-L360'
  - symbol: generate_variants_for_output
    kind: function
    at: 'backend/app/services/variant_service.py:L363-L488'
  - symbol: _regenerate_recipe
    kind: function
    at: 'backend/app/services/variant_service.py:L491-L497'
  - symbol: verify_variant_fingerprint
    kind: function
    at: 'backend/app/services/variant_service.py:L500-L537'
  - symbol: guard_account_variant_unique
    kind: function
    at: 'backend/app/services/variant_service.py:L540-L593'
---
<!-- context:generated:start -->
## Summary

Multi-account video deduplication variant generation for the '圆桌定稿 Phase 1' pipeline. Builds structural-difference recipes (speed, crop, color, noise, watermark, audio fingerprint) to evade platform L3/L4 detection blind spots. Collision detection against same-group history with automatic recipe regeneration up to MAX_RETRY; enforces one-account-one-variant rule and hard cap MAX_VARIANTS=20. Audio differentiation always applied (never None) to avoid zero-distance collisions; count=1 returns base output unchanged (zero-intrusion guarantee).

## Related

- uses [[object-storage-service-minio]] — Downloads base videos from MinIO and persists ClipVariant results
- uses [[rpa-publishing-service]] — verify_variant_fingerprint provides pre-publish safety checks
- uses [[slice-engine-orchestration]] — Applies variant recipes through the slice engine's dedupe mode
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
