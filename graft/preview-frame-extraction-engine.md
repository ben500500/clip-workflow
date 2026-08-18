---
name: Preview Frame Extraction Engine
slug: preview-frame-extraction-engine
type: system
sources:
  - path: engines/preview.py
    hash: 421381a6d72ff611e9e181c7fbff3ab7a9adc28275c349e1e86949719f7b8e14
sources_digest: 46f4d072cac42cccc118c70a335c5d2f54c4b4cc079bd96eac319508b9e89086
links:
  - to: slice-engine-orchestration
    relation: implements
    description: run_preview invokes this engine as a subprocess
generator:
  version: 1
covers:
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/preview.py:L15-L24'
  - symbol: main
    kind: function
    at: 'engines/preview.py:L27-L55'
---
<!-- context:generated:start -->
## Summary

Command-line utility extracting evenly spaced preview frames from a video using ffmpeg. Extracts up to 20 JPEG frames (default 6) at timestamps distributed across the video length, communicating progress via PROGRESS:<pct> and OUTPUT:<name>:<duration> lines. Clamps frame count to 20, falls back to sequential timestamps if duration probing fails, and uses -q:v 2 for high-quality JPEG output. A gotcha: prints OUTPUT:<name>:0 with hardcoded duration 0 rather than actual frame duration.

## Related

- implements [[slice-engine-orchestration]] — run_preview invokes this engine as a subprocess
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
