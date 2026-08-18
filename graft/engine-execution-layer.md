---
name: Engine Execution Layer
slug: engine-execution-layer
type: system
sources:
  - path: backend/app/engines/__init__.py
    hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - path: backend/app/engines/watermark_runner.py
    hash: dee0abd33a18e6fe5d4dbf3bb662e223d03b6e7a22699d190c875c5a5e1db7ff
  - path: backend/app/services/interval_service.py
    hash: 5f79dc43d0184e187bc996af79f78856efba9a351230d85da1c0144a5ef9908f
sources_digest: 43595e0084327ac3da5c94ab7591827062defa8562b4ead6c92635ee5cc89b4e
links:
  - to: configuration-database-bootstrap
    relation: configures
    description: ENGINES_DIR and WATERMARK_* settings locate scripts
  - to: worker-node-management-engine-update
    relation: produces
    description: The engines/ directory is what push_worker_update hashes and workers pull
generator:
  version: 1
covers:
  - symbol: _run_cmd
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L33-L130'
  - symbol: read_stream
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L57-L74'
  - symbol: progress_pulse
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L76-L89'
  - symbol: watchdog
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L91-L109'
  - symbol: _script_path
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L133-L138'
  - symbol: _load_roi_experience
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L141-L158'
  - symbol: run_remove_ai_watermarks
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L161-L216'
  - symbol: run_seedance_watermark_remover
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L219-L260'
  - symbol: run_remove_mask
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L263-L325'
  - symbol: run_seedance_wm
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L328-L374'
  - symbol: run_watermark_engine
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L377-L402'
  - symbol: temp_video_path
    kind: function
    at: 'backend/app/engines/watermark_runner.py:L405-L407'
  - symbol: detect_intervals
    kind: function
    at: 'backend/app/services/interval_service.py:L13-L99'
---
<!-- context:generated:start -->
## Summary

Factory-based engine selection (local vs remote) with lazy imports to avoid heavy deps. Watermark removal runs four engines as subprocesses funneled through _run_cmd, which parses PROGRESS:<pct> lines and uses a custom watchdog timeout — deliberately avoiding asyncio.wait_for because pipe reads are uncancellable. Interval detection spawns an external Python script that communicates its result via a file path written to stdout, not JSON. Engines are not thread-safe; callers manage concurrency.

## Related

- configures [[configuration-database-bootstrap]] — ENGINES_DIR and WATERMARK_* settings locate scripts
- produces [[worker-node-management-engine-update]] — The engines/ directory is what push_worker_update hashes and workers pull
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
