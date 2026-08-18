---
name: Slice Engine Orchestration
slug: slice-engine-orchestration
type: system
sources:
  - path: backend/app/services/slice_service.py
    hash: 6df06295f325caa64d9caa6a3cb3c5b605cc8809c820757c1496b8d6c73b7ca5
sources_digest: c6a664b97c4f1c102817248263c9e485cdf6020afe345845f3221b7cd435859f
links:
  - to: redis-stream-task-coordination
    relation: depends_on
    description: >-
      Slice tasks published to Redis streams are consumed by workers that invoke
      this service
  - to: variant-generation-pipeline
    relation: uses
    description: >-
      Variant service invokes run_slice_fast with dedupe mode to generate
      deduplicated variants
generator:
  version: 1
covers:
  - symbol: _run_cmd
    kind: function
    at: 'backend/app/services/slice_service.py:L14-L63'
  - symbol: read_stream
    kind: function
    at: 'backend/app/services/slice_service.py:L28-L41'
  - symbol: _engine_path
    kind: function
    at: 'backend/app/services/slice_service.py:L66-L67'
  - symbol: _require_engine
    kind: function
    at: 'backend/app/services/slice_service.py:L70-L75'
  - symbol: run_slice
    kind: function
    at: 'backend/app/services/slice_service.py:L78-L162'
  - symbol: run_slice_scrub
    kind: function
    at: 'backend/app/services/slice_service.py:L165-L216'
  - symbol: run_slice_fast
    kind: function
    at: 'backend/app/services/slice_service.py:L219-L272'
  - symbol: run_preview
    kind: function
    at: 'backend/app/services/slice_service.py:L275-L289'
---
<!-- context:generated:start -->
## Summary

Service layer that orchestrates video processing by spawning external Python engine scripts as subprocesses. Exposes run_slice, run_slice_scrub, run_slice_fast, and run_preview which build CLI invocations for slice.py and preview.py engines. Manages subprocess execution with timeout enforcement (SIGTERM then SIGKILL), streaming stdout/stderr line-by-line, and parsing PROGRESS: lines to drive progress callbacks. Serializes a large set of optional config parameters (watermarks, badges, subtitles, dedupe, masks, encoder) to JSON passed as CLI flags.

## Related

- depends on [[redis-stream-task-coordination]] — Slice tasks published to Redis streams are consumed by workers that invoke this service
- uses [[variant-generation-pipeline]] — Variant service invokes run_slice_fast with dedupe mode to generate deduplicated variants
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
