---
name: Slice Engine Orchestration
slug: slice-engine-orchestration
type: system
sources:
  - path: backend/app/services/slice_service.py
    hash: 6aca808cab05a6dd638ab6d3cf4bc7ffa6caddbdb64c64de07bc0138f31c4d87
sources_digest: 01520d35a78fc408bead5d3530e3ba27f4353b7e367b3c47571354c704a61394
links:
  - to: redis-stream-service
    relation: uses
    description: Consumes slice tasks published to streams
  - to: variant-generation-pipeline
    relation: uses
    description: >-
      variant_service invokes slice engine's dedupe mode to apply variant
      recipes
  - to: video-processing-engines
    relation: uses
    description: Invokes the Python engine scripts as subprocesses
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
    at: 'backend/app/services/slice_service.py:L78-L165'
  - symbol: run_slice_scrub
    kind: function
    at: 'backend/app/services/slice_service.py:L168-L221'
  - symbol: run_slice_fast
    kind: function
    at: 'backend/app/services/slice_service.py:L224-L279'
---
<!-- context:generated:start -->
## Summary

Service layer orchestrating external video-processing engine subprocesses (slice.py, preview.py in settings.ENGINES_DIR). Builds CLI invocations with JSON-serialized config (watermarks, badges, subtitles, dedupe, masks, encoders), manages subprocess execution with graceful SIGTERM-to-SIGKILL timeout escalation, and parses PROGRESS: lines to drive progress callbacks. Explicit engine file existence checks with Chinese-language errors.

## Related

- uses [[redis-stream-service]] — Consumes slice tasks published to streams
- uses [[variant-generation-pipeline]] — variant_service invokes slice engine's dedupe mode to apply variant recipes
- uses [[video-processing-engines]] — Invokes the Python engine scripts as subprocesses
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
