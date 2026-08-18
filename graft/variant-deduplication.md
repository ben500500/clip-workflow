---
name: Variant Deduplication
slug: variant-deduplication
type: system
sources:
  - path: backend/app/models/variant.py
    hash: 27f6c33ce119bf8b2d06316d46411d4cae5b18b7b23945bb387fd8fd1a0c24c0
  - path: backend/app/services/fingerprint_service.py
    hash: 1110fe920e9b42f0087487d8556ae749d25485c8d264333d73898512ae028f1d
sources_digest: fd1c9b42930fafe0a532f498f09c51b9807f896c3ecd8dc216c74723ec7ea68b
links:
  - to: celery-task-layer
    relation: produces
    description: >-
      generate_variants_task and verify_variant_fingerprint_task invoke
      variant_service
  - to: orm-model-registry
    relation: uses
    description: ClipVariant and VideoFingerprint models
generator:
  version: 1
covers:
  - symbol: ClipVariant
    kind: class
    at: 'backend/app/models/variant.py:L39-L87'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/variant.py:L86-L87'
  - symbol: VideoFingerprint
    kind: class
    at: 'backend/app/models/variant.py:L90-L121'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/variant.py:L120-L121'
  - symbol: _run
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L53-L60'
  - symbol: _probe_duration
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L63-L72'
  - symbol: _probe_resolution
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L75-L84'
  - symbol: _extract_sample_frames
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L90-L103'
  - symbol: _read_frame_rgb
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L106-L127'
  - symbol: _dct2
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L130-L143'
  - symbol: _phash_of_gray
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L146-L167'
  - symbol: compute_visual_fingerprint
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L170-L217'
  - symbol: compute_audio_fingerprint
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L223-L251'
  - symbol: _audio_signature
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L254-L322'
  - symbol: compute_segment_fingerprint
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L328-L370'
  - symbol: hamming_distance_hex
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L376-L389'
  - symbol: vector_distance
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L392-L403'
  - symbol: _extract_algo
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L413-L430'
  - symbol: _algo_distance
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L433-L442'
  - symbol: compare_fingerprints
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L445-L463'
  - symbol: is_collision
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L466-L488'
  - symbol: compute_full_fingerprint
    kind: function
    at: 'backend/app/services/fingerprint_service.py:L491-L505'
---
<!-- context:generated:start -->
## Summary

Multi-account dedup: ClipVariant derived from SliceOutput with unique constraint on account_id preventing same material on multiple accounts. Three fingerprint types (visual pHash, audio spectral, temporal segment) with weighted collision thresholds (phash 0.20, audio 0.15, seg 0.30, combined 0.15). Hard rule: collision failures degrade to manual handling, never publish identical content. variant_count=1 is zero-intrusion backward-compat mode. Fingerprint computation separated from persistence.

## Related

- produces [[celery-task-layer]] — generate_variants_task and verify_variant_fingerprint_task invoke variant_service
- uses [[orm-model-registry]] — ClipVariant and VideoFingerprint models
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
