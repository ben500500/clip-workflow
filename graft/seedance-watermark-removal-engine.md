---
name: Seedance Watermark Removal Engine
slug: seedance-watermark-removal-engine
type: system
sources:
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
  - path: engines/seedance_wm/log.py
    hash: ee98e56bf3bc442012dfb7f6bdac73be4ddc3a7bab415b616c67c0ee89224869
  - path: engines/seedance_wm/mask.py
    hash: 96da5961936e4bed860239356372efc91153a364debab215aab2c88065a6cb78
  - path: engines/seedance_wm/pipeline.py
    hash: 166502eaf36b6f8dc06149f74761586023bc6941dc439464776e624954a105b1
  - path: engines/seedance_wm/remover.py
    hash: bb067f99bae9e570af82b112d63fc7ec8c0b6c531ebff55fcf24ac015bbf54d2
  - path: engines/seedance_wm/tools.py
    hash: 668f43851164a116182b9ef5ccab346af1ef1d2bca3ff086717e154786f9df43
  - path: engines/seedance_wm/version.py
    hash: c9cb763bcf25c4dcb4575f22c86a3c1128bba56262f2cb2aabd9334b5ae8c06b
sources_digest: 5b7b1ea9b1d4c90799e64f86136aeba02bdf70bcbd61b62b51a8ea4aa105060c
links:
  - to: detection-mask-inpaint-pipeline
    relation: uses
    description: >-
      tools.py lazily imports detect, mask, and inpaint modules;
      detect_watermark supports a fallback chain of detection methods, inpaint
      defaults to lama with fp16.
  - to: ffmpeg-i-o-layer
    relation: uses
    description: >-
      remover.py and tools.py delegate frame extraction, muxing, and metadata
      probing to seedance_wm.ffmpeg_io; SUPPORTED_EXTENSIONS drives batch file
      discovery.
  - to: slice-engine-orchestration
    relation: implements
    description: >-
      The runner CLI is compatible with the clip-workflow watermark_runner
      progress convention (PROGRESS:<pct> lines)
  - to: watermark-removal-roi-library
    relation: uses
    description: >-
      Falls back to experience-based ROI lists from remove_mask_rois when
      auto-detection fails
generator:
  version: 1
covers:
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
  - symbol: _UtcFormatter
    kind: class
    at: 'engines/seedance_wm/log.py:L27-L32'
  - symbol: formatTime
    kind: method
    at: 'engines/seedance_wm/log.py:L30-L32'
  - symbol: get_logger
    kind: function
    at: 'engines/seedance_wm/log.py:L35-L39'
  - symbol: _configure
    kind: function
    at: 'engines/seedance_wm/log.py:L42-L47'
  - symbol: set_level
    kind: function
    at: 'engines/seedance_wm/log.py:L50-L52'
  - symbol: add_file_handler
    kind: function
    at: 'engines/seedance_wm/log.py:L55-L61'
  - symbol: generate_mask_sequence
    kind: function
    at: 'engines/seedance_wm/mask.py:L19-L77'
  - symbol: ProcessResult
    kind: class
    at: 'engines/seedance_wm/pipeline.py:L41-L51'
  - symbol: _State
    kind: class
    at: 'engines/seedance_wm/pipeline.py:L54-L85'
  - symbol: __init__
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L57-L63'
  - symbol: load
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L65-L75'
  - symbol: save
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L77-L79'
  - symbol: mark_done
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L81-L82'
  - symbol: is_done
    kind: method
    at: 'engines/seedance_wm/pipeline.py:L84-L85'
  - symbol: _video_hash
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L88-L96'
  - symbol: _cache_dir
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L99-L100'
  - symbol: _ensure_disk
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L103-L108'
  - symbol: _emit
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L111-L119'
  - symbol: process_video
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L122-L367'
  - symbol: _inpaint_progress
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L280-L283'
  - symbol: _qa_check
    kind: function
    at: 'engines/seedance_wm/pipeline.py:L370-L384'
  - symbol: BatchResult
    kind: class
    at: 'engines/seedance_wm/remover.py:L28-L39'
  - symbol: success_count
    kind: method
    at: 'engines/seedance_wm/remover.py:L34-L35'
  - symbol: failed
    kind: method
    at: 'engines/seedance_wm/remover.py:L38-L39'
  - symbol: Remover
    kind: class
    at: 'engines/seedance_wm/remover.py:L42-L143'
  - symbol: __init__
    kind: method
    at: 'engines/seedance_wm/remover.py:L43-L44'
  - symbol: process
    kind: method
    at: 'engines/seedance_wm/remover.py:L47-L54'
  - symbol: batch
    kind: method
    at: 'engines/seedance_wm/remover.py:L57-L128'
  - symbol: _process_one
    kind: method
    at: 'engines/seedance_wm/remover.py:L130-L143'
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

A five-stage local watermark removal pipeline (frame extraction, detection, mask generation, inpainting, muxing) targeting Seedance 2.0 'AI生成' watermarks and static corner logos. Detection uses a degradation chain (matchTemplate primary, YOLOv8-seg and PaddleOCR fallbacks) with temporal stability scoring; inpainting prefers LaMa-ONNX with OpenCV TELEA/NS CPU fallbacks and GPU-to-CPU auto-degradation. Supports resumable execution via state.json keyed by video hash, a disk-space guard, QA validation (output decodability, duration error <50ms), and a three-tier ROI priority (manual bbox > auto-detection > experience-based ROI lists). Optional Agno agent orchestration layer with strict pipeline ordering enforced via prompts.

## Related

- uses [[detection-mask-inpaint-pipeline]] — tools.py lazily imports detect, mask, and inpaint modules; detect_watermark supports a fallback chain of detection methods, inpaint defaults to lama with fp16.
- uses [[ffmpeg-i-o-layer]] — remover.py and tools.py delegate frame extraction, muxing, and metadata probing to seedance_wm.ffmpeg_io; SUPPORTED_EXTENSIONS drives batch file discovery.
- implements [[slice-engine-orchestration]] — The runner CLI is compatible with the clip-workflow watermark_runner progress convention (PROGRESS:<pct> lines)
- uses [[watermark-removal-roi-library]] — Falls back to experience-based ROI lists from remove_mask_rois when auto-detection fails
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
