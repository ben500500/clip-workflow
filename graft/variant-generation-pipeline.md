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
  - symbol: _pick_audio_mode
    kind: function
    at: 'backend/app/services/variant_service.py:L115-L123'
  - symbol: build_variant_recipes
    kind: function
    at: 'backend/app/services/variant_service.py:L126-L213'
  - symbol: _pick
    kind: function
    at: 'backend/app/services/variant_service.py:L145-L149'
  - symbol: _recipe_fingerprint_key
    kind: function
    at: 'backend/app/services/variant_service.py:L216-L218'
  - symbol: _load_output
    kind: function
    at: 'backend/app/services/variant_service.py:L221-L230'
  - symbol: _load_output_video_path
    kind: function
    at: 'backend/app/services/variant_service.py:L233-L246'
  - symbol: _save_variant_row
    kind: function
    at: 'backend/app/services/variant_service.py:L249-L269'
  - symbol: _update_variant
    kind: function
    at: 'backend/app/services/variant_service.py:L272-L278'
  - symbol: mark_output_variants_failed
    kind: function
    at: 'backend/app/services/variant_service.py:L281-L296'
  - symbol: _save_fingerprint
    kind: function
    at: 'backend/app/services/variant_service.py:L299-L315'
  - symbol: _load_group_fingerprints
    kind: function
    at: 'backend/app/services/variant_service.py:L318-L333'
  - symbol: _check_against_history
    kind: function
    at: 'backend/app/services/variant_service.py:L336-L384'
  - symbol: _build_variant_cutlist
    kind: function
    at: 'backend/app/services/variant_service.py:L387-L425'
  - symbol: _generate_variant_file
    kind: function
    at: 'backend/app/services/variant_service.py:L428-L470'
  - symbol: _probe_duration_sec
    kind: function
    at: 'backend/app/services/variant_service.py:L473-L483'
  - symbol: generate_variants_for_output
    kind: function
    at: 'backend/app/services/variant_service.py:L486-L631'
  - symbol: _regenerate_recipe
    kind: function
    at: 'backend/app/services/variant_service.py:L634-L649'
  - symbol: verify_variant_fingerprint
    kind: function
    at: 'backend/app/services/variant_service.py:L652-L694'
  - symbol: guard_account_variant_unique
    kind: function
    at: 'backend/app/services/variant_service.py:L697-L754'
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
