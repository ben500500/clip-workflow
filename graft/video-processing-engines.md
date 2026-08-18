---
name: Video Processing Engines
slug: video-processing-engines
type: system
sources:
  - path: engines/detect_intervals.py
    hash: 7d009ae2cde6a54c1aa057f870160e4583a4f209d2807691a528a90dea2215f0
  - path: engines/preview.py
    hash: 421381a6d72ff611e9e181c7fbff3ab7a9adc28275c349e1e86949719f7b8e14
  - path: engines/remove_mask_remover.py
    hash: 05c8b1251e9fe02e4f0dfd7a7b073016d1a85e308d67cb65451df8e0bbde9533
  - path: engines/remove_mask_rois.py
    hash: ad940041ad8d0a7124334facf4c8b893bdf5f4ca1adaea6bd9b844aed7a69e40
  - path: engines/seedance_watermark_remover.py
    hash: 2797cd45c3dc431af263421071ac52628f6a9b59229038b4e006ae253145dee6
  - path: engines/seedance_wm_runner.py
    hash: 9324e618953e01ed9dc3ab4d4e49722047f5aa14fa3b16cb351f290ce2571c28
  - path: engines/seedance_wm/__init__.py
    hash: d7f955cbc5d135f8535dcedce738e3a9d196d74c6e7c55ea317156353ae6d547
  - path: engines/seedance_wm/__main__.py
    hash: e4fbe8fa3bcad8d9626b895899c09df74e9c8fefb50510df1c1e21264e6ec95f
  - path: engines/seedance_wm/agent.py
    hash: 3f2eb825756b5e78c03d7b11640372c052906649053d03450e1f076dd397911f
  - path: engines/seedance_wm/cli.py
    hash: e13288d60c59df0839456b4479da4d1bdfa7a8102dc1be491709b789d444cf68
  - path: engines/seedance_wm/config.py
    hash: 81153d831a1dc20a203f2461b928b51db973c95fa09b3fdbe57bf8f188be26fb
  - path: engines/seedance_wm/detect.py
    hash: a7f98d8b259bcad3d31989956493c46c351725001f87e36b3cf5c69d86007a9a
  - path: engines/seedance_wm/errors.py
    hash: b8cfbba3209bb2aa3f6107c03c6cf6081a521a9e889faf01aa070f89f7f0a1b1
  - path: engines/seedance_wm/ffmpeg_io.py
    hash: b4f95fe0344e25015e1da3bff7dad668bd86a004160638b82b2ca8d56a26b9da
  - path: engines/seedance_wm/inpaint.py
    hash: 914c93e7f372a50daa4656a7b3a95c665d1e0f9bd0df078990ddeceae17ca649
sources_digest: 67ff1821dbbe96fc15681c6ac4f9be43432d8e54d7aa800bd3cd8b06a488db50
links:
  - to: slice-engine-orchestration
    relation: uses
    description: slice_service invokes these engine scripts as subprocesses with CLI flags
generator:
  version: 1
covers:
  - symbol: load_config
    kind: function
    at: 'engines/detect_intervals.py:L29-L37'
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/detect_intervals.py:L40-L49'
  - symbol: run_ffmpeg_detect
    kind: function
    at: 'engines/detect_intervals.py:L52-L57'
  - symbol: parse_blackdetect
    kind: function
    at: 'engines/detect_intervals.py:L60-L70'
  - symbol: parse_freezedetect
    kind: function
    at: 'engines/detect_intervals.py:L73-L88'
  - symbol: main
    kind: function
    at: 'engines/detect_intervals.py:L91-L145'
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/preview.py:L15-L24'
  - symbol: main
    kind: function
    at: 'engines/preview.py:L27-L55'
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
  - symbol: _load_raiw_fill
    kind: function
    at: 'engines/seedance_watermark_remover.py:L63-L79'
  - symbol: _fill
    kind: function
    at: 'engines/seedance_watermark_remover.py:L75-L76'
  - symbol: _onnx_model_ready
    kind: function
    at: 'engines/seedance_watermark_remover.py:L85-L108'
  - symbol: _get_raiw_fill
    kind: function
    at: 'engines/seedance_watermark_remover.py:L111-L115'
  - symbol: _multi_canny
    kind: function
    at: 'engines/seedance_watermark_remover.py:L122-L128'
  - symbol: _auto_detect
    kind: function
    at: 'engines/seedance_watermark_remover.py:L131-L200'
  - symbol: _build_mask
    kind: function
    at: 'engines/seedance_watermark_remover.py:L203-L239'
  - symbol: _inpaint_telea
    kind: function
    at: 'engines/seedance_watermark_remover.py:L246-L248'
  - symbol: _make_inpaint
    kind: function
    at: 'engines/seedance_watermark_remover.py:L251-L292'
  - symbol: _inpaint
    kind: function
    at: 'engines/seedance_watermark_remover.py:L284-L290'
  - symbol: remove_watermark
    kind: function
    at: 'engines/seedance_watermark_remover.py:L295-L492'
  - symbol: _masks_for_frame
    kind: function
    at: 'engines/seedance_watermark_remover.py:L426-L430'
  - symbol: main
    kind: function
    at: 'engines/seedance_watermark_remover.py:L495-L551'
  - symbol: build_agent
    kind: function
    at: 'engines/seedance_wm/agent.py:L18-L71'
  - symbol: extract_frames_tool
    kind: function
    at: 'engines/seedance_wm/agent.py:L32-L34'
  - symbol: detect_tool
    kind: function
    at: 'engines/seedance_wm/agent.py:L37-L39'
  - symbol: mask_tool
    kind: function
    at: 'engines/seedance_wm/agent.py:L42-L44'
  - symbol: inpaint_tool
    kind: function
    at: 'engines/seedance_wm/agent.py:L47-L51'
  - symbol: mux_tool
    kind: function
    at: 'engines/seedance_wm/agent.py:L54-L56'
  - symbol: _parse_bbox
    kind: function
    at: 'engines/seedance_wm/cli.py:L52-L62'
  - symbol: build_parser
    kind: function
    at: 'engines/seedance_wm/cli.py:L65-L112'
  - symbol: _apply_cli_overrides
    kind: function
    at: 'engines/seedance_wm/cli.py:L115-L140'
  - symbol: _confirm_disclaimer
    kind: function
    at: 'engines/seedance_wm/cli.py:L143-L149'
  - symbol: _print_metrics
    kind: function
    at: 'engines/seedance_wm/cli.py:L152-L165'
  - symbol: run
    kind: function
    at: 'engines/seedance_wm/cli.py:L168-L240'
  - symbol: main
    kind: function
    at: 'engines/seedance_wm/cli.py:L243-L250'
  - symbol: DetectorConfig
    kind: class
    at: 'engines/seedance_wm/config.py:L21-L26'
  - symbol: InpainterConfig
    kind: class
    at: 'engines/seedance_wm/config.py:L30-L36'
  - symbol: TemporalConfig
    kind: class
    at: 'engines/seedance_wm/config.py:L40-L43'
  - symbol: OutputConfig
    kind: class
    at: 'engines/seedance_wm/config.py:L47-L52'
  - symbol: LoggingConfig
    kind: class
    at: 'engines/seedance_wm/config.py:L56-L59'
  - symbol: CacheConfig
    kind: class
    at: 'engines/seedance_wm/config.py:L63-L66'
  - symbol: Config
    kind: class
    at: 'engines/seedance_wm/config.py:L70-L163'
  - symbol: from_yaml
    kind: method
    at: 'engines/seedance_wm/config.py:L79-L81'
  - symbol: _from_dict
    kind: method
    at: 'engines/seedance_wm/config.py:L84-L125'
  - symbol: to_yaml
    kind: method
    at: 'engines/seedance_wm/config.py:L127-L163'
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
  - symbol: check_ffmpeg
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L32-L36'
  - symbol: _parse_rational
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L39-L47'
  - symbol: VideoMeta
    kind: class
    at: 'engines/seedance_wm/ffmpeg_io.py:L51-L57'
  - symbol: probe_video
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L60-L95'
  - symbol: extract_frames
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L98-L161'
  - symbol: mux_video
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L164-L228'
  - symbol: get_available_disk_gb
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L231-L234'
  - symbol: run_cmd
    kind: function
    at: 'engines/seedance_wm/ffmpeg_io.py:L237-L238'
  - symbol: _lama_model_ready
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L29-L57'
  - symbol: resolve_device
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L60-L70'
  - symbol: _inpaint_cv2
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L73-L81'
  - symbol: _inpaint_lama
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L87-L99'
  - symbol: inpaint_frames
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L102-L185'
  - symbol: _build_inpaint_chain
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L188-L223'
  - symbol: temporal_smooth
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L226-L295'
  - symbol: _read_frame
    kind: function
    at: 'engines/seedance_wm/inpaint.py:L264-L269'
  - symbol: _parse_region
    kind: function
    at: 'engines/seedance_wm_runner.py:L44-L48'
  - symbol: build_parser
    kind: function
    at: 'engines/seedance_wm_runner.py:L51-L77'
  - symbol: _apply_backend
    kind: function
    at: 'engines/seedance_wm_runner.py:L80-L93'
  - symbol: main
    kind: function
    at: 'engines/seedance_wm_runner.py:L96-L202'
---
<!-- context:generated:start -->
## Summary

Standalone Python CLI engines invoked as subprocesses by the backend, communicating via PROGRESS:/OUTPUT: stdout lines. Includes interval detection (blackdetect/freezedetect for credits and static frames), preview frame extraction (up to 20 JPEGs), and watermark removal (OpenCV inpainting, Seedance-specific detection with LaMa/MI-GAN/ONNX backends, and an experience-based ROI library). Engines are deliberately self-contained with only stdlib + ffmpeg/OpenCV dependencies.

## Related

- uses [[slice-engine-orchestration]] — slice_service invokes these engine scripts as subprocesses with CLI flags
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
