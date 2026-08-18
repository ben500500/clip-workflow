---
name: FFmpeg Utilities
slug: ffmpeg-utilities
type: system
sources:
  - path: autoclip/app/utils/ffmpeg_utils.py
    hash: 7cdc6ebe80039338c3078e6eeb3ddacf28387a21c66afa15cea1f4b5a3d88a9f
sources_digest: 74e1e90cdb269c26fd1800eeb3ed19e7e000c61180095f83fc13093ff9230abb
links:
  - to: frame-analysis
    relation: uses
    description: frame_analyzer uses ffmpeg subprocess calls for frame extraction.
  - to: speech-recognition
    relation: uses
    description: >-
      speech_recognizer depends on ffmpeg_utils for binary paths during audio
      extraction.
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

Single source of truth for ffmpeg/ffprobe binary paths across the backend. Resolves via env vars (AUTOCLIP_FFMPEG_PATH, FFMPEG_PATH, etc.), then system PATH via shutil.which, then bare command name. Validates env-var paths point to existing files. Enables the desktop installer to bundle binaries for zero external dependencies while preserving dev-environment compatibility.

## Related

- uses [[frame-analysis]] — frame_analyzer uses ffmpeg subprocess calls for frame extraction.
- uses [[speech-recognition]] — speech_recognizer depends on ffmpeg_utils for binary paths during audio extraction.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
