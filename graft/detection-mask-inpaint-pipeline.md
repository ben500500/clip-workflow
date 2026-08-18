---
name: Detection/Mask/Inpaint Pipeline
slug: detection-mask-inpaint-pipeline
type: system
sources:
  - path: engines/seedance_wm/tools.py
    hash: 668f43851164a116182b9ef5ccab346af1ef1d2bca3ff086717e154786f9df43
sources_digest: 3f1830d5a81d01ee80f6e43db9ecb250578a2be7627790d55b6e0346f92dba36
links:
  - to: seedance-watermark-removal-engine
    relation: part_of
    description: Lazily imported by tools.py at call time to reduce startup cost.
generator:
  version: 1
covers:
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

The watermark-detection, mask-generation, and inpainting modules behind the Seedance engine's tools. detect_watermark supports a fallback chain of detection methods; inpaint defaults to the lama model with fp16 acceleration; temporal_smooth mutates frames in place (a caller must not reuse the input after calling it).

## Related

- part of [[seedance-watermark-removal-engine]] — Lazily imported by tools.py at call time to reduce startup cost.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
