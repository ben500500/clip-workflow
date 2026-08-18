---
name: Face-Aware Crop
slug: face-aware-crop
type: file
sources:
  - path: engines/vert2horiz_crop.py
    hash: 42ce32301bb5a33ea2c1bf5f45045f1385589bc8507208da1d66b278d651c231
sources_digest: 77a42b2dc98ce7169e841ad80d2a5d1ba529432c504ba45b3474f73de9573a30
links:
  - to: slicing-engine
    relation: uses
    description: >-
      slice.py optionally imports vert2horiz_crop for vertical-to-horizontal
      conversion.
generator:
  version: 1
covers:
  - symbol: get_video_info
    kind: function
    at: 'engines/vert2horiz_crop.py:L81-L93'
  - symbol: FaceDetector
    kind: class
    at: 'engines/vert2horiz_crop.py:L96-L165'
  - symbol: __init__
    kind: method
    at: 'engines/vert2horiz_crop.py:L103-L107'
  - symbol: _ensure_yunet
    kind: method
    at: 'engines/vert2horiz_crop.py:L109-L123'
  - symbol: _ensure_haar
    kind: method
    at: 'engines/vert2horiz_crop.py:L125-L133'
  - symbol: detect
    kind: method
    at: 'engines/vert2horiz_crop.py:L135-L165'
  - symbol: sample_avg_face
    kind: function
    at: 'engines/vert2horiz_crop.py:L168-L202'
  - symbol: pick_main_face
    kind: function
    at: 'engines/vert2horiz_crop.py:L205-L226'
  - symbol: score
    kind: function
    at: 'engines/vert2horiz_crop.py:L218-L223'
  - symbol: compute_crop_y_keep_face
    kind: function
    at: 'engines/vert2horiz_crop.py:L229-L248'
  - symbol: generate_fixed_crop_params
    kind: function
    at: 'engines/vert2horiz_crop.py:L251-L289'
  - symbol: analyze_faces
    kind: function
    at: 'engines/vert2horiz_crop.py:L292-L361'
  - symbol: smooth_face_boxes
    kind: function
    at: 'engines/vert2horiz_crop.py:L364-L380'
  - symbol: savgol_smooth
    kind: function
    at: 'engines/vert2horiz_crop.py:L383-L419'
  - symbol: debounce_crop_y
    kind: function
    at: 'engines/vert2horiz_crop.py:L422-L442'
  - symbol: keep_window_when_face_in_frame
    kind: function
    at: 'engines/vert2horiz_crop.py:L445-L488'
  - symbol: generate_dynamic_crop_params
    kind: function
    at: 'engines/vert2horiz_crop.py:L491-L547'
  - symbol: apply_fixed_crop
    kind: function
    at: 'engines/vert2horiz_crop.py:L550-L575'
  - symbol: apply_dynamic_crop
    kind: function
    at: 'engines/vert2horiz_crop.py:L578-L637'
  - symbol: main
    kind: function
    at: 'engines/vert2horiz_crop.py:L640-L738'
---
<!-- context:generated:start -->
## Summary

Converts vertical (9:16) to horizontal (16:9) video using face-aware cropping. Fast fixed-crop mode samples frames for median face position (median over mean to resist outliers); dynamic mode tracks faces per-frame through a three-stage anti-jitter pipeline (Savitzky-Golay smoothing, minimum-step deadzone debouncing, face-comfort-zone hold). HEAD_MARGIN_RATIO 0.35 preserves forehead/hair; min_step/face_margin trade stability against responsiveness. OpenCV YuNet with Haar cascade fallback, no external ML frameworks.

## Related

- uses [[slicing-engine]] — slice.py optionally imports vert2horiz_crop for vertical-to-horizontal conversion.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
