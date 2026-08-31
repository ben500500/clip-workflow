---
name: slice engine
slug: slice-engine
type: system
sources:
  - path: engines/slice.py
    hash: 23e69efab7790d2613658e66961be2aa13c91cce58b448fc2d4c17d038906b8a
sources_digest: 1b5fed13b23b1c2bc716ea1536d2d8ccc321787b85db714d6acc30a99866a6e2
links:
  - to: dedupe-config-contract
    relation: implements
    description: >-
      slice.py's _resolve_dedupe_config and DEDUPE_PRESETS define the manual
      dedupe parameter contract mirrored by the frontend DedupeManualConfig
      component.
  - to: vert2horiz-crop
    relation: uses
    description: >-
      Optionally imports vert2horiz_crop for vertical-to-horizontal conversion
      during slicing.
generator:
  version: 1
covers:
  - symbol: _even
    kind: function
    at: 'engines/slice.py:L213-L218'
  - symbol: _ffmpeg_has_drawtext
    kind: function
    at: 'engines/slice.py:L229-L246'
  - symbol: drawtext_available
    kind: function
    at: 'engines/slice.py:L249-L251'
  - symbol: _resolve_dedupe_config
    kind: function
    at: 'engines/slice.py:L254-L286'
  - symbol: build_dedupe_filter
    kind: function
    at: 'engines/slice.py:L289-L430'
  - symbol: build_dedupe_audio_filter
    kind: function
    at: 'engines/slice.py:L433-L477'
  - symbol: build_dedupe_watermark
    kind: function
    at: 'engines/slice.py:L480-L521'
  - symbol: cpu_threads_for_percent
    kind: function
    at: 'engines/slice.py:L524-L543'
  - symbol: parse_time
    kind: function
    at: 'engines/slice.py:L546-L552'
  - symbol: read_cutlist
    kind: function
    at: 'engines/slice.py:L555-L571'
  - symbol: read_intervals
    kind: function
    at: 'engines/slice.py:L574-L590'
  - symbol: subtract_intervals
    kind: function
    at: 'engines/slice.py:L593-L615'
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/slice.py:L618-L627'
  - symbol: ffprobe_resolution
    kind: function
    at: 'engines/slice.py:L630-L644'
  - symbol: ffprobe_framerate
    kind: function
    at: 'engines/slice.py:L647-L673'
  - symbol: ffprobe_size
    kind: function
    at: 'engines/slice.py:L676-L692'
  - symbol: _fallback_libx264_args
    kind: function
    at: 'engines/slice.py:L695-L730'
  - symbol: run_ffmpeg
    kind: function
    at: 'engines/slice.py:L733-L766'
  - symbol: _encoder_runtime_ok
    kind: function
    at: 'engines/slice.py:L769-L787'
  - symbol: detect_best_encoder
    kind: function
    at: 'engines/slice.py:L790-L832'
  - symbol: build_encoder_args
    kind: function
    at: 'engines/slice.py:L835-L842'
  - symbol: slice_segment
    kind: function
    at: 'engines/slice.py:L845-L864'
  - symbol: concat_segments
    kind: function
    at: 'engines/slice.py:L867-L901'
  - symbol: _is_copy_segment
    kind: function
    at: 'engines/slice.py:L904-L909'
  - symbol: _concat_demuxer
    kind: function
    at: 'engines/slice.py:L912-L927'
  - symbol: safe_name
    kind: function
    at: 'engines/slice.py:L930-L934'
  - symbol: _badge_scale_and_opacity
    kind: function
    at: 'engines/slice.py:L959-L985'
  - symbol: build_badges_overlay_args
    kind: function
    at: 'engines/slice.py:L988-L1052'
  - symbol: apply_badges
    kind: function
    at: 'engines/slice.py:L1055-L1063'
  - symbol: _fc_match_sc_font
    kind: function
    at: 'engines/slice.py:L1137-L1169'
  - symbol: _extract_sc_face
    kind: function
    at: 'engines/slice.py:L1172-L1221'
  - symbol: _fontconfig_has_cjk_sc
    kind: function
    at: 'engines/slice.py:L1224-L1239'
  - symbol: _resolve_drawtext_font
    kind: function
    at: 'engines/slice.py:L1242-L1272'
  - symbol: _build_text_overlays_filter
    kind: function
    at: 'engines/slice.py:L1275-L1344'
  - symbol: apply_text_overlays
    kind: function
    at: 'engines/slice.py:L1347-L1364'
  - symbol: build_watermark_filter
    kind: function
    at: 'engines/slice.py:L1367-L1411'
  - symbol: _watermark_style_exprs
    kind: function
    at: 'engines/slice.py:L1414-L1460'
  - symbol: css_hex_to_ass
    kind: function
    at: 'engines/slice.py:L1489-L1509'
  - symbol: _css_to_drawtext
    kind: function
    at: 'engines/slice.py:L1512-L1528'
  - symbol: _parse_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1531-L1539'
  - symbol: _format_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1542-L1549'
  - symbol: read_srt
    kind: function
    at: 'engines/slice.py:L1552-L1629'
  - symbol: detect_speech_windows
    kind: function
    at: 'engines/slice.py:L1644-L1715'
  - symbol: _trim_to_speech
    kind: function
    at: 'engines/slice.py:L1718-L1734'
  - symbol: _filter_and_align_srt
    kind: function
    at: 'engines/slice.py:L1737-L1765'
  - symbol: build_clip_subtitle
    kind: function
    at: 'engines/slice.py:L1768-L1811'
  - symbol: burn_subtitle
    kind: function
    at: 'engines/slice.py:L1816-L1913'
  - symbol: _mask_text_clusters
    kind: function
    at: 'engines/slice.py:L1957-L1966'
  - symbol: _split_tall_band
    kind: function
    at: 'engines/slice.py:L1969-L2064'
  - symbol: detect_subtitle_region
    kind: function
    at: 'engines/slice.py:L2067-L2339'
  - symbol: _low_percentile
    kind: function
    at: 'engines/slice.py:L2362-L2375'
  - symbol: _bimodal_threshold
    kind: function
    at: 'engines/slice.py:L2378-L2419'
  - symbol: detect_watermark_region
    kind: function
    at: 'engines/slice.py:L2422-L2557'
  - symbol: detect_subtitle_temporal_windows
    kind: function
    at: 'engines/slice.py:L2560-L2686'
  - symbol: detect_subtitle_spatial_regions
    kind: function
    at: 'engines/slice.py:L2698-L2785'
  - symbol: detect_subtitle_dynamic_regions
    kind: function
    at: 'engines/slice.py:L2800-L2945'
  - symbol: _parse_subtitle_mask_config
    kind: function
    at: 'engines/slice.py:L2948-L2958'
  - symbol: _source_intervals_to_local_intervals
    kind: function
    at: 'engines/slice.py:L2961-L2988'
  - symbol: _scale_region
    kind: function
    at: 'engines/slice.py:L2991-L3006'
  - symbol: _mask_enable_expr
    kind: function
    at: 'engines/slice.py:L3009-L3012'
  - symbol: _source_intervals_to_local_enable
    kind: function
    at: 'engines/slice.py:L3015-L3046'
  - symbol: _spatial_windows_to_local
    kind: function
    at: 'engines/slice.py:L3049-L3090'
  - symbol: _dynamic_windows_to_local
    kind: function
    at: 'engines/slice.py:L3093-L3140'
  - symbol: build_subtitle_mask_enable
    kind: function
    at: 'engines/slice.py:L3143-L3162'
  - symbol: _subtitle_mask_area
    kind: function
    at: 'engines/slice.py:L3165-L3212'
  - symbol: _f
    kind: function
    at: 'engines/slice.py:L3176-L3183'
  - symbol: subtitle_mask_bottom_margin
    kind: function
    at: 'engines/slice.py:L3215-L3275'
  - symbol: _merge_regions
    kind: function
    at: 'engines/slice.py:L3278-L3304'
  - symbol: _scale_regions
    kind: function
    at: 'engines/slice.py:L3307-L3324'
  - symbol: build_subtitle_mask_filter
    kind: function
    at: 'engines/slice.py:L3327-L3380'
  - symbol: build_subtitle_mask_filter_multi
    kind: function
    at: 'engines/slice.py:L3383-L3466'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3402-L3405'
  - symbol: build_subtitle_mask_filter_multi_region
    kind: function
    at: 'engines/slice.py:L3469-L3553'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3489-L3496'
  - symbol: build_subtitle_mask_filter_multi_region_windows
    kind: function
    at: 'engines/slice.py:L3556-L3642'
  - symbol: _enable
    kind: function
    at: 'engines/slice.py:L3572-L3576'
  - symbol: build_subtitle_mask_filter_dynamic
    kind: function
    at: 'engines/slice.py:L3645-L3724'
  - symbol: apply_subtitle_mask
    kind: function
    at: 'engines/slice.py:L3727-L3832'
  - symbol: _video_has_audio
    kind: function
    at: 'engines/slice.py:L3835-L3846'
  - symbol: apply_cover_first_frame
    kind: function
    at: 'engines/slice.py:L3849-L3941'
  - symbol: _fps_value
    kind: function
    at: 'engines/slice.py:L3958-L3966'
  - symbol: build_output_tier_filter
    kind: function
    at: 'engines/slice.py:L3969-L4002'
  - symbol: main
    kind: function
    at: 'engines/slice.py:L4005-L4764'
  - symbol: parse_vert2horiz_config
    kind: function
    at: 'engines/slice.py:L4767-L4777'
  - symbol: apply_vert2horiz
    kind: function
    at: 'engines/slice.py:L4780-L4839'
---
<!-- context:generated:start -->
## Summary

The ffmpeg-based slicing engine for the Clip Workflow: cuts source videos into segments per a cutlist, optionally applies deduplication filters, and concatenates results. Builds four-layer dedupe filter chains (spatial, temporal, color, texture) plus audio fingerprint and watermark dedupe. Auto-falls back from hardware encoders to libx264 on runtime failure, uses stream-copy mode for fast slicing when no filters apply, and limits CPU threads via cpu_threads_for_percent. Requires Python 3.10+ (PEP 604 unions).

## Related

- implements [[dedupe-config-contract]] — slice.py's _resolve_dedupe_config and DEDUPE_PRESETS define the manual dedupe parameter contract mirrored by the frontend DedupeManualConfig component.
- uses [[vert2horiz-crop]] — Optionally imports vert2horiz_crop for vertical-to-horizontal conversion during slicing.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
