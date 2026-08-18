---
name: FFmpeg Path Resolution
slug: ffmpeg-path-resolution
type: file
sources:
  - path: autoclip/app/utils/ffmpeg_utils.py
    hash: 7cdc6ebe80039338c3078e6eeb3ddacf28387a21c66afa15cea1f4b5a3d88a9f
sources_digest: 74e1e90cdb269c26fd1800eeb3ed19e7e000c61180095f83fc13093ff9230abb
links:
  - to: autoclip-pipeline-stages
    relation: uses
    description: >-
      Pipeline steps that invoke ffmpeg/ffprobe resolve paths through these
      helpers.
generator:
  version: 1
covers:
  - symbol: _resolve_from_env
    kind: function
    at: 'autoclip/app/utils/ffmpeg_utils.py:L16-L21'
  - symbol: get_ffmpeg_path
    kind: function
    at: 'autoclip/app/utils/ffmpeg_utils.py:L24-L40'
  - symbol: get_ffprobe_path
    kind: function
    at: 'autoclip/app/utils/ffmpeg_utils.py:L43-L59'
---
<!-- context:generated:start -->
## Summary

Single source of truth for ffmpeg/ffprobe executable paths: env vars first (validated to exist), then system PATH via shutil.which, then bare command name. Enables the desktop installer to bundle binaries for zero external dependencies while preserving dev compatibility.

## Related

- uses [[autoclip-pipeline-stages]] — Pipeline steps that invoke ffmpeg/ffprobe resolve paths through these helpers.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
