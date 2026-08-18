---
name: seedance_wm engine
slug: seedance-wm-engine
type: system
sources:
  - path: engines/seedance_wm/log.py
    hash: ee98e56bf3bc442012dfb7f6bdac73be4ddc3a7bab415b616c67c0ee89224869
  - path: engines/seedance_wm/mask.py
    hash: 96da5961936e4bed860239356372efc91153a364debab215aab2c88065a6cb78
  - path: engines/seedance_wm/pipeline.py
    hash: 166502eaf36b6f8dc06149f74761586023bc6941dc439464776e624954a105b1
  - path: engines/seedance_wm/remover.py
    hash: bb067f99bae9e570af82b112d63fc7ec8c0b6c531ebff55fcf24ac015bbf54d2
  - path: engines/seedance_wm/tools.py
    hash: 668f43851164a116182b9ef5ccab346af1ef1d2bca3ff086717e154786f9df43
  - path: engines/seedance_wm/version.py
    hash: c9cb763bcf25c4dcb4575f22c86a3c1128bba56262f2cb2aabd9334b5ae8c06b
sources_digest: 4fa58511a1c7634a5e9e4070aadc56243779b5a8585e6654b5570f825fbea28a
links:
  - to: seedance-wm-logging-convention
    relation: uses
    description: >-
      All engine modules log through get_logger from log.py, enforcing the
      [HH:MM:SS.mmm] [LEVEL] [module] format.
  - to: seedance-wm-mask-generation
    relation: part_of
    description: >-
      mask.py is stage 3 of the pipeline, converting bboxes to per-frame mask
      PNGs.
  - to: seedance-wm-resumability-state
    relation: implements
    description: >-
      pipeline.py's _State class persists stage completion to cache/state.json
      keyed by video hash.
generator:
  version: 1
covers:
  - symbol: _UtcFormatter
    kind: class
    at: 'engines/seedance_wm/log.py:L27-L32'
  - symbol: formatTime
    kind: method
    at: 'engines/seedance_wm/log.py:L30-L32'
  - symbol: get_logger
    kind: function
    at: 'engines/seedance_wm/log.py:L35-L39'
  - symbol: _configure
    kind: function
    at: 'engines/seedance_wm/log.py:L42-L47'
  - symbol: set_level
    kind: function
    at: 'engines/seedance_wm/log.py:L50-L52'
  - symbol: add_file_handler
    kind: function
    at: 'engines/seedance_wm/log.py:L55-L61'
  - symbol: generate_mask_sequence
    kind: function
    at: 'engines/seedance_wm/mask.py:L19-L77'
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
  - symbol: BatchResult
    kind: class
    at: 'engines/seedance_wm/remover.py:L28-L39'
  - symbol: success_count
    kind: method
    at: 'engines/seedance_wm/remover.py:L34-L35'
  - symbol: failed
    kind: method
    at: 'engines/seedance_wm/remover.py:L38-L39'
  - symbol: Remover
    kind: class
    at: 'engines/seedance_wm/remover.py:L42-L143'
  - symbol: __init__
    kind: method
    at: 'engines/seedance_wm/remover.py:L43-L44'
  - symbol: process
    kind: method
    at: 'engines/seedance_wm/remover.py:L47-L54'
  - symbol: batch
    kind: method
    at: 'engines/seedance_wm/remover.py:L57-L128'
  - symbol: _process_one
    kind: method
    at: 'engines/seedance_wm/remover.py:L130-L143'
  - symbol: extract_frames
    kind: function
    at: 'engines/seedance_wm/tools.py:L15-L26'
  - symbol: detect_watermark
    kind: function
    at: 'engines/seedance_wm/tools.py:L29-L42'
  - symbol: generate_mask_sequence
    kind: function
    at: 'engines/seedance_wm/tools.py:L45-L51'
  - symbol: inpaint_frames
    kind: function
    at: 'engines/seedance_wm/tools.py:L54-L65'
  - symbol: temporal_smooth
    kind: function
    at: 'engines/seedance_wm/tools.py:L68-L72'
  - symbol: mux_video
    kind: function
    at: 'engines/seedance_wm/tools.py:L75-L83'
  - symbol: video_meta
    kind: function
    at: 'engines/seedance_wm/tools.py:L86-L96'
---
<!-- context:generated:start -->
## Summary

The Seedance watermark-removal engine: a five-stage pipeline (extract frames, detect watermark, generate masks, inpaint with temporal smoothing, mux output) orchestrated by pipeline.py. The Remover class is the public SDK entry point, tools.py exposes atomic functions to an Agno Agent, and the whole engine is resumable via a state file keyed by a lightweight video hash. Degradation chain: manual bbox > auto-detection > experience-based ROI fallback.

## Related

- uses [[seedance-wm-logging-convention]] — All engine modules log through get_logger from log.py, enforcing the [HH:MM:SS.mmm] [LEVEL] [module] format.
- part of [[seedance-wm-mask-generation]] — mask.py is stage 3 of the pipeline, converting bboxes to per-frame mask PNGs.
- implements [[seedance-wm-resumability-state]] — pipeline.py's _State class persists stage completion to cache/state.json keyed by video hash.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
