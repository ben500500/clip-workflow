---
name: Multi-Video Dedup & Fingerprinting
slug: multi-video-dedup-fingerprinting
type: concept
sources:
  - path: alembic/versions/0034_multi_video_dedup_variants.py
    hash: eadc353ba3ee7e8ddb1c6eea61347df3893f5c7be6cd579715ecdd7350893e12
sources_digest: ae6313709c66c4ef49fb532b9d363aa378d047967dd4046e9199348157a567d1
links:
  - to: alembic-migration-chain
    relation: part_of
    description: Single migration in the chain implementing the dedup data layer.
generator:
  version: 1
covers:
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0034_multi_video_dedup_variants.py:L29-L94'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0034_multi_video_dedup_variants.py:L97-L104'
---
<!-- context:generated:start -->
## Summary

Phase 0 dedup data layer: clip_variants (unique per account), video_fingerprints (phash/audio/temporal perceptual hashes covering L3/L4 blind spots), variant_group_id on slice_outputs for zero-intrusion aggregation, variant_id on publications for auditability, and variant_count on slice_tasks. Attempts pgvector extension but gracefully falls back to string-distance comparison if unavailable.

## Related

- part of [[alembic-migration-chain]] — Single migration in the chain implementing the dedup data layer.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
