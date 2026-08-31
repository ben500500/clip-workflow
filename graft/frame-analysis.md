---
name: Frame Analysis
slug: frame-analysis
type: system
sources:
  - path: autoclip/app/utils/frame_analyzer.py
    hash: 2b36f898e33e7147caf0f360649d978ead6c74193c960ffd0eea68a89a4dadcc
sources_digest: ad34c021d4c98d91ba978b67a3012ce528b45fdf97080b048dd4aff7f66024ad
links:
  - to: ffmpeg-utilities
    relation: uses
    description: Uses ffmpeg subprocess calls for frame extraction.
  - to: llm-manager-client-compatibility
    relation: uses
    description: Uses get_ollama_client from core.ollama_client for local model calls.
generator:
  version: 1
covers:
  - symbol: _seconds_to_ffmpeg_ts
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L55-L60'
  - symbol: _extract_frame
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L63-L81'
  - symbol: _normalize_description
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L84-L97'
  - symbol: _cache_key
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L100-L106'
  - symbol: _cache_dir
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L109-L112'
  - symbol: _read_cache
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L115-L122'
  - symbol: _write_cache
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L125-L130'
  - symbol: analyze_clip_frames
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L133-L256'
  - symbol: to_sec
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L168-L176'
  - symbol: analyze_timeline_frames
    kind: function
    at: 'autoclip/app/utils/frame_analyzer.py:L259-L304'
---
<!-- context:generated:start -->
## Summary

Visual scene understanding for AI clip selection: extracts frames from candidate segments and sends them to a local Ollama MiniCPM-V instance for structured descriptions (scene, action, emotion, OCR, quality, highlight score). Gated by FRAME_ANALYSIS_ENABLED (default off), degrades silently to None/empty dicts when Ollama is unavailable. Results cached per video hash+timestamp range under METADATA_DIR/frame_cache; multi-frame analyses merge by highest-highlight frame while concatenating OCR text.

## Related

- uses [[ffmpeg-utilities]] — Uses ffmpeg subprocess calls for frame extraction.
- uses [[llm-manager-client-compatibility]] — Uses get_ollama_client from core.ollama_client for local model calls.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
