---
name: Watermark Removal Degradation Chain
slug: watermark-removal-degradation-chain
type: concept
sources:
  - path: engines/remove_mask_remover.py
    hash: 05c8b1251e9fe02e4f0dfd7a7b073016d1a85e308d67cb65451df8e0bbde9533
  - path: engines/remove_mask_rois.py
    hash: ad940041ad8d0a7124334facf4c8b893bdf5f4ca1adaea6bd9b844aed7a69e40
  - path: engines/seedance_wm/detect.py
    hash: a7f98d8b259bcad3d31989956493c46c351725001f87e36b3cf5c69d86007a9a
  - path: engines/seedance_wm/errors.py
    hash: b8cfbba3209bb2aa3f6107c03c6cf6081a521a9e889faf01aa070f89f7f0a1b1
  - path: engines/seedance_wm/inpaint.py
    hash: 914c93e7f372a50daa4656a7b3a95c665d1e0f9bd0df078990ddeceae17ca649
sources_digest: 8ad28f25b36241abc53a4bc4af57ab12559ba708ca83b6ca971b74d0ffaafc91
links:
  - to: video-processing-engines
    relation: part_of
    description: The degradation chain is implemented across the watermark removal engines
  - to: video-processing-engines
    relation: implements
    description: >-
      Engines honor the degradation-chain contract for detector/inpainter
      fallback
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
  - symbol: _norm_source_name
    kind: function
    at: 'engines/remove_mask_rois.py:L108-L110'
  - symbol: match_rois
    kind: function
    at: 'engines/remove_mask_rois.py:L113-L132'
  - symbol: resolve_rois
    kind: function
    at: 'engines/remove_mask_rois.py:L135-L147'
  - symbol: build_mask
    kind: function
    at: 'engines/remove_mask_rois.py:L150-L162'
  - symbol: rois_to_bboxes
    kind: function
    at: 'engines/remove_mask_rois.py:L165-L180'
  - symbol: probe_video_size
    kind: function
    at: 'engines/remove_mask_rois.py:L183-L195'
  - symbol: _roi_image
    kind: function
    at: 'engines/seedance_wm/detect.py:L36-L40'
  - symbol: detect_watermark_seedance
    kind: function
    at: 'engines/seedance_wm/detect.py:L43-L116'
  - symbol: _detect_yolov8
    kind: function
    at: 'engines/seedance_wm/detect.py:L119-L150'
  - symbol: _detect_paddleocr
    kind: function
    at: 'engines/seedance_wm/detect.py:L153-L196'
  - symbol: detect_watermark
    kind: function
    at: 'engines/seedance_wm/detect.py:L199-L261'
  - symbol: WatermarkRemoverError
    kind: class
    at: 'engines/seedance_wm/errors.py:L30-L37'
  - symbol: __init__
    kind: method
    at: 'engines/seedance_wm/errors.py:L35-L37'
  - symbol: InvalidArgsError
    kind: class
    at: 'engines/seedance_wm/errors.py:L40-L41'
  - symbol: VideoReadError
    kind: class
    at: 'engines/seedance_wm/errors.py:L44-L45'
  - symbol: DetectFailError
    kind: class
    at: 'engines/seedance_wm/errors.py:L48-L49'
  - symbol: FfmpegMissingError
    kind: class
    at: 'engines/seedance_wm/errors.py:L52-L53'
  - symbol: InpaintError
    kind: class
    at: 'engines/seedance_wm/errors.py:L56-L57'
  - symbol: MuxError
    kind: class
    at: 'engines/seedance_wm/errors.py:L60-L61'
  - symbol: OutOfDiskError
    kind: class
    at: 'engines/seedance_wm/errors.py:L64-L65'
  - symbol: GpuOomError
    kind: class
    at: 'engines/seedance_wm/errors.py:L68-L71'
  - symbol: LicenseError
    kind: class
    at: 'engines/seedance_wm/errors.py:L74-L75'
  - symbol: _lama_model_ready
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L29-L57'
  - symbol: resolve_device
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L60-L70'
  - symbol: _inpaint_cv2
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L73-L81'
  - symbol: _inpaint_cv2_roi
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L84-L98'
  - symbol: _inpaint_lama
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L104-L116'
  - symbol: inpaint_frames
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L119-L209'
  - symbol: _build_inpaint_chain
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L212-L247'
  - symbol: temporal_smooth
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L250-L319'
  - symbol: _read_frame
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L288-L293'
---
<!-- context:generated:start -->
## Summary

Cross-cutting design across the watermark engines: detection degrades matchTemplate → YOLOv8-seg → PaddleOCR, and inpainting degrades LaMa → OpenCV TELEA/NS, with automatic GPU-to-CPU fallback. Pre-flight checks (_lama_model_ready) verify ONNX models are fully downloaded before use to avoid offline network hangs; GpuOomError is non-fatal since the system auto-degrades. The remove_mask_rois experience library provides hardcoded ROI tables (small/large scopes) as a fallback when no manual region is specified, with per-video calibration to avoid covering moving subjects.

## Related

- part of [[video-processing-engines]] — The degradation chain is implemented across the watermark removal engines
- implements [[video-processing-engines]] — Engines honor the degradation-chain contract for detector/inpainter fallback
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
