---
name: seedance_wm resumability & state
slug: seedance-wm-resumability-state
type: concept
sources:
  - path: engines/seedance_wm/pipeline.py
    hash: 166502eaf36b6f8dc06149f74761586023bc6941dc439464776e624954a105b1
sources_digest: 65bf64de9f5a68c708658fd541c1432b4fe3181f2151ad3709e6495d2385a95b
links:
  - to: seedance-wm-engine
    relation: part_of
    description: >-
      Implemented by pipeline.py's _State class and enforced throughout
      process_video.
generator:
  version: 1
covers:
  - symbol: ProcessResult
    kind: class
    at: 'engines/seedance_wm/pipeline.py:L41-L51'
  - symbol: _State
    kind: class
    at: 'engines/seedance_wm/pipeline.py:L54-L85'
  - symbol: __init__
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L57-L63'
  - symbol: load
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L65-L75'
  - symbol: save
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L77-L79'
  - symbol: mark_done
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L81-L82'
  - symbol: is_done
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L84-L85'
  - symbol: _video_hash
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L88-L96'
  - symbol: _cache_dir
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L99-L100'
  - symbol: _ensure_disk
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L103-L108'
  - symbol: _emit
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L111-L119'
  - symbol: process_video
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L122-L367'
  - symbol: _inpaint_progress
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L280-L283'
  - symbol: _qa_check
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L370-L384'
---
<!-- context:generated:start -->
## Summary

The pipeline persists per-stage completion status to cache/state.json keyed by a lightweight video hash (path + size + mtime), so crashed runs skip already-completed stages. A disk-space guard (_MIN_FREE_GB) aborts before running out of space, and QA validation checks output existence, decodability, and duration error under 50ms. Known error types return a failed ProcessResult rather than raising.

## Related

- part of [[seedance-wm-engine]] — Implemented by pipeline.py's _State class and enforced throughout process_video.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
