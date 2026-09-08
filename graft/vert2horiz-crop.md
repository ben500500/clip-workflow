---
name: vert2horiz crop
slug: vert2horiz-crop
type: file
sources:
  - path: engines/vert2horiz_crop.py
    hash: 42ce32301bb5a33ea2c1bf5f45045f1385589bc8507208da1d66b278d651c231
sources_digest: 77a42b2dc98ce7169e841ad80d2a5d1ba529432c504ba45b3474f73de9573a30
links:
  - to: slice-engine
    relation: part_of
    description: Optional dependency of slice.py for vertical-to-horizontal conversion.
generator:
  version: 1
covers:
  - symbol: get_video_info
    kind: function
    at: 'engines/vert2horiz_crop.py:L87-L99'
  - symbol: FaceDetector
    kind: class
    at: 'engines/vert2horiz_crop.py:L102-L171'
  - symbol: __init__
    kind: method
    at: 'engines/vert2horiz_crop.py:L109-L113'
  - symbol: _ensure_yunet
    kind: method
    at: 'engines/vert2horiz_crop.py:L115-L129'
  - symbol: _ensure_haar
    kind: method
    at: 'engines/vert2horiz_crop.py:L131-L139'
  - symbol: detect
    kind: method
    at: 'engines/vert2horiz_crop.py:L141-L171'
  - symbol: sample_avg_face
    kind: function
    at: 'engines/vert2horiz_crop.py:L174-L208'
  - symbol: pick_main_face
    kind: function
    at: 'engines/vert2horiz_crop.py:L211-L232'
  - symbol: score
    kind: function
    at: 'engines/vert2horiz_crop.py:L224-L229'
  - symbol: compute_crop_y_keep_face
    kind: function
    at: 'engines/vert2horiz_crop.py:L235-L254'
  - symbol: generate_fixed_crop_params
    kind: function
    at: 'engines/vert2horiz_crop.py:L257-L295'
  - symbol: analyze_faces
    kind: function
    at: 'engines/vert2horiz_crop.py:L298-L367'
  - symbol: smooth_face_boxes
    kind: function
    at: 'engines/vert2horiz_crop.py:L370-L386'
  - symbol: savgol_smooth
    kind: function
    at: 'engines/vert2horiz_crop.py:L389-L425'
  - symbol: debounce_crop_y
    kind: function
    at: 'engines/vert2horiz_crop.py:L428-L448'
  - symbol: keep_window_when_face_in_frame
    kind: function
    at: 'engines/vert2horiz_crop.py:L451-L494'
  - symbol: generate_dynamic_crop_params
    kind: function
    at: 'engines/vert2horiz_crop.py:L497-L553'
  - symbol: apply_fixed_crop
    kind: function
    at: 'engines/vert2horiz_crop.py:L556-L581'
  - symbol: apply_dynamic_crop
    kind: function
    at: 'engines/vert2horiz_crop.py:L584-L659'
  - symbol: main
    kind: function
    at: 'engines/vert2horiz_crop.py:L662-L760'
---
<!-- context:generated:start -->
## Summary

Converts vertical (9:16) videos to horizontal (16:9) via face-aware cropping. Fast fixed-crop mode uses median face position (median, not mean, to resist outliers); dynamic mode applies a three-stage anti-jitter pipeline (Savitzky-Golay smoothing, minimum-step deadzone debouncing, face-comfort-zone hold). YuNet detector with Haar cascade fallback; no external ML frameworks. HEAD_MARGIN_RATIO 0.35 preserves forehead/hair.

## Related

- part of [[slice-engine]] — Optional dependency of slice.py for vertical-to-horizontal conversion.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
