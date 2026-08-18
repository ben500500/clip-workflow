---
name: Slicing Engine
slug: slicing-engine
type: system
sources:
  - path: engines/slice.py
    hash: 55b468c581be224e69f0ad25332a5d06b18c84547dd0f466c6f968d51957dba5
sources_digest: f8e930be916522ce780e8335e160702f857e2608ec8720057f4ebeb5190cc647
links:
  - to: face-aware-crop
    relation: uses
    description: >-
      Optionally imports vert2horiz_crop for vertical-to-horizontal conversion
      during slicing.
  - to: ffmpeg-i-o-layer
    relation: part_of
    description: run_ffmpeg and ffprobe helpers are the execution core of slicing.
  - to: subtitle-mask-regression
    relation: validates
    description: >-
      test_subtitle_mask_regression.py exercises
      detect_subtitle_dynamic_regions, _dynamic_windows_to_local, and
      build_subtitle_mask_filter_dynamic from slice.py.
generator:
  version: 1
covers:
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

The ffmpeg-based slicing engine for the Clip Workflow: cuts source videos per cutlist, optionally applies a four-layer (spatial/temporal/color/texture) dedupe filter chain to evade platform content matching, and assembles output via concat demuxer or filter_complex. Handles frame-rate resampling after speed changes to prevent A/V desync, badge overlay watermarking, and vertical-to-horizontal conversion. DEDUPE_PRESETS offers five tunable presets (light/standard/heavy/std_retro_scan/std_crop_desat).

## Related

- uses [[face-aware-crop]] — Optionally imports vert2horiz_crop for vertical-to-horizontal conversion during slicing.
- part of [[ffmpeg-i-o-layer]] — run_ffmpeg and ffprobe helpers are the execution core of slicing.
- validates [[subtitle-mask-regression]] — test_subtitle_mask_regression.py exercises detect_subtitle_dynamic_regions, _dynamic_windows_to_local, and build_subtitle_mask_filter_dynamic from slice.py.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
