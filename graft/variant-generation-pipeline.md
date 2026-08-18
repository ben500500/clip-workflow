---
name: Variant Generation Pipeline
slug: variant-generation-pipeline
type: system
sources:
  - path: backend/app/services/variant_service.py
    hash: cfbe73212c29c4726a8a0ca2abdeabc4c6b540824969fc6c85a19429be0c5113
sources_digest: 50bbc6ad52b1bbffdc3c03395e5b61f21ab884d07c8de286ea14c120bbe81676
links:
  - to: minio-storage-service
    relation: uses
    description: Stores generated variant files in MinIO
  - to: slice-engine-orchestration
    relation: uses
    description: Invokes run_slice_fast with dedupe mode for variant generation
  - to: video-publishing-pipeline
    relation: produces
    description: Variant files are the inputs that get published to platforms
generator:
  version: 1
covers:
  - symbol: build_variant_recipes
    kind: function
    at: 'backend/app/services/variant_service.py:L75-L120'
  - symbol: _recipe_fingerprint_key
    kind: function
    at: 'backend/app/services/variant_service.py:L123-L125'
  - symbol: _load_output
    kind: function
    at: 'backend/app/services/variant_service.py:L128-L133'
  - symbol: _load_output_video_path
    kind: function
    at: 'backend/app/services/variant_service.py:L136-L149'
  - symbol: _save_variant_row
    kind: function
    at: 'backend/app/services/variant_service.py:L152-L172'
  - symbol: _update_variant
    kind: function
    at: 'backend/app/services/variant_service.py:L175-L181'
  - symbol: _save_fingerprint
    kind: function
    at: 'backend/app/services/variant_service.py:L184-L200'
  - symbol: _load_group_fingerprints
    kind: function
    at: 'backend/app/services/variant_service.py:L203-L216'
  - symbol: _check_against_history
    kind: function
    at: 'backend/app/services/variant_service.py:L219-L253'
  - symbol: _build_variant_cutlist
    kind: function
    at: 'backend/app/services/variant_service.py:L256-L294'
  - symbol: _generate_variant_file
    kind: function
    at: 'backend/app/services/variant_service.py:L297-L339'
  - symbol: _probe_duration_sec
    kind: function
    at: 'backend/app/services/variant_service.py:L342-L352'
  - symbol: generate_variants_for_output
    kind: function
    at: 'backend/app/services/variant_service.py:L355-L480'
  - symbol: _regenerate_recipe
    kind: function
    at: 'backend/app/services/variant_service.py:L483-L489'
  - symbol: verify_variant_fingerprint
    kind: function
    at: 'backend/app/services/variant_service.py:L492-L529'
  - symbol: guard_account_variant_unique
    kind: function
    at: 'backend/app/services/variant_service.py:L532-L585'
---
<!-- context:generated:start -->
## Summary

Multi-account video deduplication variant generation workflow for the platform's Phase 1 core pipeline. Builds structural-difference recipes (speed, crop, color, noise, watermark, audio, temporal segmentation) via build_variant_recipes, then generates actual variant files through the slice engine's dedupe mode. Computes phash/audio/sequence fingerprints, performs collision detection against same-group history with automatic recipe regeneration retries, and enforces one-account-one-variant binding rules. Zero-invasion when count=1, marks collisions for manual handling rather than risking duplicate content.

## Related

- uses [[minio-storage-service]] — Stores generated variant files in MinIO
- uses [[slice-engine-orchestration]] — Invokes run_slice_fast with dedupe mode for variant generation
- produces [[video-publishing-pipeline]] — Variant files are the inputs that get published to platforms
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
