---
name: FFmpeg I/O Layer
slug: ffmpeg-i-o-layer
type: system
sources:
  - path: engines/seedance_wm/remover.py
    hash: bb067f99bae9e570af82b112d63fc7ec8c0b6c531ebff55fcf24ac015bbf54d2
  - path: engines/seedance_wm/tools.py
    hash: 668f43851164a116182b9ef5ccab346af1ef1d2bca3ff086717e154786f9df43
  - path: engines/slice.py
    hash: 55b468c581be224e69f0ad25332a5d06b18c84547dd0f466c6f968d51957dba5
sources_digest: 7de1b1d57bd900bc18010250cb1dd22f56cd6b2372abc7c53c00ff8c9486df78
links:
  - to: seedance-watermark-removal-engine
    relation: part_of
    description: >-
      Provides ffmpeg_io primitives (probe_video, extract_frames, mux_video)
      consumed by remover.py and tools.py.
  - to: slicing-engine
    relation: part_of
    description: >-
      slice.py's run_ffmpeg, ffprobe_duration/resolution/framerate, and concat
      logic all live here.
generator:
  version: 1
covers:
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
  - symbol: _even
    kind: function
    at: 'engines/slice.py:L174-L179'
  - symbol: _resolve_dedupe_config
    kind: function
    at: 'engines/slice.py:L182-L214'
  - symbol: build_dedupe_filter
    kind: function
    at: 'engines/slice.py:L217-L317'
  - symbol: build_dedupe_audio_filter
    kind: function
    at: 'engines/slice.py:L320-L345'
  - symbol: build_dedupe_watermark
    kind: function
    at: 'engines/slice.py:L348-L389'
  - symbol: cpu_threads_for_percent
    kind: function
    at: 'engines/slice.py:L392-L411'
  - symbol: parse_time
    kind: function
    at: 'engines/slice.py:L414-L420'
  - symbol: read_cutlist
    kind: function
    at: 'engines/slice.py:L423-L439'
  - symbol: read_intervals
    kind: function
    at: 'engines/slice.py:L442-L458'
  - symbol: subtract_intervals
    kind: function
    at: 'engines/slice.py:L461-L483'
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/slice.py:L486-L495'
  - symbol: ffprobe_resolution
    kind: function
    at: 'engines/slice.py:L498-L512'
  - symbol: ffprobe_framerate
    kind: function
    at: 'engines/slice.py:L515-L541'
  - symbol: ffprobe_size
    kind: function
    at: 'engines/slice.py:L544-L560'
  - symbol: _fallback_libx264_args
    kind: function
    at: 'engines/slice.py:L563-L591'
  - symbol: run_ffmpeg
    kind: function
    at: 'engines/slice.py:L594-L612'
  - symbol: detect_best_encoder
    kind: function
    at: 'engines/slice.py:L615-L643'
  - symbol: build_encoder_args
    kind: function
    at: 'engines/slice.py:L646-L653'
  - symbol: slice_segment
    kind: function
    at: 'engines/slice.py:L656-L675'
  - symbol: concat_segments
    kind: function
    at: 'engines/slice.py:L678-L702'
  - symbol: _is_copy_segment
    kind: function
    at: 'engines/slice.py:L705-L710'
  - symbol: _concat_demuxer
    kind: function
    at: 'engines/slice.py:L713-L728'
  - symbol: safe_name
    kind: function
    at: 'engines/slice.py:L731-L735'
  - symbol: _badge_scale_and_opacity
    kind: function
    at: 'engines/slice.py:L760-L786'
  - symbol: build_badges_overlay_args
    kind: function
    at: 'engines/slice.py:L789-L853'
  - symbol: apply_badges
    kind: function
    at: 'engines/slice.py:L856-L864'
  - symbol: _fc_match_sc_font
    kind: function
    at: 'engines/slice.py:L938-L970'
  - symbol: _extract_sc_face
    kind: function
    at: 'engines/slice.py:L973-L1022'
  - symbol: _fontconfig_has_cjk_sc
    kind: function
    at: 'engines/slice.py:L1025-L1040'
  - symbol: _resolve_drawtext_font
    kind: function
    at: 'engines/slice.py:L1043-L1073'
  - symbol: _build_text_overlays_filter
    kind: function
    at: 'engines/slice.py:L1076-L1145'
  - symbol: apply_text_overlays
    kind: function
    at: 'engines/slice.py:L1148-L1165'
  - symbol: build_watermark_filter
    kind: function
    at: 'engines/slice.py:L1168-L1212'
  - symbol: _watermark_style_exprs
    kind: function
    at: 'engines/slice.py:L1215-L1261'
  - symbol: css_hex_to_ass
    kind: function
    at: 'engines/slice.py:L1290-L1310'
  - symbol: _css_to_drawtext
    kind: function
    at: 'engines/slice.py:L1313-L1329'
  - symbol: _parse_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1332-L1340'
  - symbol: _format_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1343-L1350'
  - symbol: read_srt
    kind: function
    at: 'engines/slice.py:L1353-L1430'
  - symbol: detect_speech_windows
    kind: function
    at: 'engines/slice.py:L1445-L1516'
  - symbol: _trim_to_speech
    kind: function
    at: 'engines/slice.py:L1519-L1535'
  - symbol: _filter_and_align_srt
    kind: function
    at: 'engines/slice.py:L1538-L1566'
  - symbol: build_clip_subtitle
    kind: function
    at: 'engines/slice.py:L1569-L1608'
  - symbol: burn_subtitle
    kind: function
    at: 'engines/slice.py:L1613-L1710'
  - symbol: _mask_text_clusters
    kind: function
    at: 'engines/slice.py:L1754-L1763'
  - symbol: _split_tall_band
    kind: function
    at: 'engines/slice.py:L1766-L1861'
  - symbol: detect_subtitle_region
    kind: function
    at: 'engines/slice.py:L1864-L2136'
  - symbol: _low_percentile
    kind: function
    at: 'engines/slice.py:L2159-L2172'
  - symbol: _bimodal_threshold
    kind: function
    at: 'engines/slice.py:L2175-L2216'
  - symbol: detect_watermark_region
    kind: function
    at: 'engines/slice.py:L2219-L2354'
  - symbol: detect_subtitle_temporal_windows
    kind: function
    at: 'engines/slice.py:L2357-L2483'
  - symbol: detect_subtitle_spatial_regions
    kind: function
    at: 'engines/slice.py:L2495-L2582'
  - symbol: detect_subtitle_dynamic_regions
    kind: function
    at: 'engines/slice.py:L2597-L2742'
  - symbol: _parse_subtitle_mask_config
    kind: function
    at: 'engines/slice.py:L2745-L2755'
  - symbol: _source_intervals_to_local_intervals
    kind: function
    at: 'engines/slice.py:L2758-L2785'
  - symbol: _scale_region
    kind: function
    at: 'engines/slice.py:L2788-L2803'
  - symbol: _mask_enable_expr
    kind: function
    at: 'engines/slice.py:L2806-L2809'
  - symbol: _source_intervals_to_local_enable
    kind: function
    at: 'engines/slice.py:L2812-L2843'
  - symbol: _spatial_windows_to_local
    kind: function
    at: 'engines/slice.py:L2846-L2887'
  - symbol: _dynamic_windows_to_local
    kind: function
    at: 'engines/slice.py:L2890-L2937'
  - symbol: build_subtitle_mask_enable
    kind: function
    at: 'engines/slice.py:L2940-L2959'
  - symbol: _subtitle_mask_area
    kind: function
    at: 'engines/slice.py:L2962-L3009'
  - symbol: _f
    kind: function
    at: 'engines/slice.py:L2973-L2980'
  - symbol: subtitle_mask_bottom_margin
    kind: function
    at: 'engines/slice.py:L3012-L3072'
  - symbol: _merge_regions
    kind: function
    at: 'engines/slice.py:L3075-L3101'
  - symbol: _scale_regions
    kind: function
    at: 'engines/slice.py:L3104-L3121'
  - symbol: build_subtitle_mask_filter
    kind: function
    at: 'engines/slice.py:L3124-L3177'
  - symbol: build_subtitle_mask_filter_multi
    kind: function
    at: 'engines/slice.py:L3180-L3263'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3199-L3202'
  - symbol: build_subtitle_mask_filter_multi_region
    kind: function
    at: 'engines/slice.py:L3266-L3350'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3286-L3293'
  - symbol: build_subtitle_mask_filter_multi_region_windows
    kind: function
    at: 'engines/slice.py:L3353-L3439'
  - symbol: _enable
    kind: function
    at: 'engines/slice.py:L3369-L3373'
  - symbol: build_subtitle_mask_filter_dynamic
    kind: function
    at: 'engines/slice.py:L3442-L3521'
  - symbol: apply_subtitle_mask
    kind: function
    at: 'engines/slice.py:L3524-L3629'
  - symbol: main
    kind: function
    at: 'engines/slice.py:L3632-L4183'
  - symbol: parse_vert2horiz_config
    kind: function
    at: 'engines/slice.py:L4186-L4196'
  - symbol: apply_vert2horiz
    kind: function
    at: 'engines/slice.py:L4199-L4258'
---
<!-- context:generated:start -->
## Summary

The shared ffmpeg/ffprobe wrapper used by the Seedance engine and the slicing engine: probing metadata, frame extraction, muxing, and subprocess execution with hardware-encoder fallback to software libx264. Enforces Python 3.10+ for PEP 604 unions and caps CPU threads to avoid saturating the machine.

## Related

- part of [[seedance-watermark-removal-engine]] — Provides ffmpeg_io primitives (probe_video, extract_frames, mux_video) consumed by remover.py and tools.py.
- part of [[slicing-engine]] — slice.py's run_ffmpeg, ffprobe_duration/resolution/framerate, and concat logic all live here.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
