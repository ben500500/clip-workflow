---
name: OpenCV Watermark Remover
slug: opencv-watermark-remover
type: system
sources:
  - path: engines/remove_mask_remover.py
    hash: 05c8b1251e9fe02e4f0dfd7a7b073016d1a85e308d67cb65451df8e0bbde9533
sources_digest: 257e2f509e192e5ad54c48f290a7f5a2ad6a4659de1d3114925b9629f9044961
links:
  - to: watermark-removal-roi-library
    relation: uses
    description: Uses remove_mask_rois for preset ROI matching
generator:
  version: 1
covers:
  - symbol: _load_sampled_frames
    kind: function
    at: 'engines/remove_mask_remover.py:L87-L103'
  - symbol: _semi_white_mask
    kind: function
    at: 'engines/remove_mask_remover.py:L106-L125'
  - symbol: _static_consistency_filter
    kind: function
    at: 'engines/remove_mask_remover.py:L128-L169'
  - symbol: _detect_text_bands
    kind: function
    at: 'engines/remove_mask_remover.py:L172-L239'
  - symbol: _detect_corner_heatmap
    kind: function
    at: 'engines/remove_mask_remover.py:L242-L318'
  - symbol: _cluster_boxes
    kind: function
    at: 'engines/remove_mask_remover.py:L321-L393'
  - symbol: _merge_bands
    kind: function
    at: 'engines/remove_mask_remover.py:L396-L439'
  - symbol: analyze_video
    kind: function
    at: 'engines/remove_mask_remover.py:L442-L508'
  - symbol: analysis_to_rois
    kind: function
    at: 'engines/remove_mask_remover.py:L511-L645'
  - symbol: _band_ok
    kind: function
    at: 'engines/remove_mask_remover.py:L530-L532'
  - symbol: _to_roi
    kind: function
    at: 'engines/remove_mask_remover.py:L534-L537'
  - symbol: _merge_y_overlap
    kind: function
    at: 'engines/remove_mask_remover.py:L539-L559'
  - symbol: _emit
    kind: function
    at: 'engines/remove_mask_remover.py:L561-L567'
  - symbol: _corner_edge_ok
    kind: function
    at: 'engines/remove_mask_remover.py:L578-L585'
  - symbol: _corner_edge_ok
    kind: function
    at: 'engines/remove_mask_remover.py:L613-L620'
  - symbol: process_crop
    kind: function
    at: 'engines/remove_mask_remover.py:L648-L762'
  - symbol: process
    kind: function
    at: 'engines/remove_mask_remover.py:L765-L872'
  - symbol: main
    kind: function
    at: 'engines/remove_mask_remover.py:L875-L1034'
---
<!-- context:generated:start -->
## Summary

Video watermark removal engine combining OpenCV inpainting with automatic watermark detection. Supports manual ROI, preset configurations ranked by removal effectiveness, and automatic detection via time-consistency heatmaps that detect semi-transparent white text bands and generate corner-specific ROIs. Uses height guards (≤110px) to distinguish text watermarks from large moving subjects, confidence thresholds (≥0.09) to filter false positives, and a fallback covering 13% of top/bottom edges when detection fails. Preserves original resolution, frame rate, and audio through ffmpeg stream copying.

## Related

- uses [[watermark-removal-roi-library]] — Uses remove_mask_rois for preset ROI matching
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
