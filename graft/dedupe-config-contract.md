---
name: dedupe config contract
slug: dedupe-config-contract
type: concept
sources:
  - path: engines/slice.py
    hash: 23e69efab7790d2613658e66961be2aa13c91cce58b448fc2d4c17d038906b8a
  - path: frontend/src/components/DedupeManualConfig.tsx
    hash: a5edec8a5255d61a0739cbfb23fadfc028d091c2fb3238f2d038de62b69e0ab6
sources_digest: cd0ea576bed0a060d172708f153985c85c524e80cc375053fa88d630eb99036b
links:
  - to: frontend-api-layer
    relation: configures
    description: >-
      DedupeManualConfig.tsx produces the manual config value sent via
      sliceApi.run.
  - to: slice-engine
    relation: part_of
    description: slice.py's _resolve_dedupe_config consumes this structure.
generator:
  version: 1
covers:
  - symbol: _even
    kind: function
    at: 'engines/slice.py:L205-L210'
  - symbol: _resolve_dedupe_config
    kind: function
    at: 'engines/slice.py:L213-L245'
  - symbol: build_dedupe_filter
    kind: function
    at: 'engines/slice.py:L248-L374'
  - symbol: build_dedupe_audio_filter
    kind: function
    at: 'engines/slice.py:L377-L421'
  - symbol: build_dedupe_watermark
    kind: function
    at: 'engines/slice.py:L424-L465'
  - symbol: cpu_threads_for_percent
    kind: function
    at: 'engines/slice.py:L468-L487'
  - symbol: parse_time
    kind: function
    at: 'engines/slice.py:L490-L496'
  - symbol: read_cutlist
    kind: function
    at: 'engines/slice.py:L499-L515'
  - symbol: read_intervals
    kind: function
    at: 'engines/slice.py:L518-L534'
  - symbol: subtract_intervals
    kind: function
    at: 'engines/slice.py:L537-L559'
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/slice.py:L562-L571'
  - symbol: ffprobe_resolution
    kind: function
    at: 'engines/slice.py:L574-L588'
  - symbol: ffprobe_framerate
    kind: function
    at: 'engines/slice.py:L591-L617'
  - symbol: ffprobe_size
    kind: function
    at: 'engines/slice.py:L620-L636'
  - symbol: _fallback_libx264_args
    kind: function
    at: 'engines/slice.py:L639-L667'
  - symbol: run_ffmpeg
    kind: function
    at: 'engines/slice.py:L670-L694'
  - symbol: detect_best_encoder
    kind: function
    at: 'engines/slice.py:L697-L725'
  - symbol: build_encoder_args
    kind: function
    at: 'engines/slice.py:L728-L735'
  - symbol: slice_segment
    kind: function
    at: 'engines/slice.py:L738-L757'
  - symbol: concat_segments
    kind: function
    at: 'engines/slice.py:L760-L784'
  - symbol: _is_copy_segment
    kind: function
    at: 'engines/slice.py:L787-L792'
  - symbol: _concat_demuxer
    kind: function
    at: 'engines/slice.py:L795-L810'
  - symbol: safe_name
    kind: function
    at: 'engines/slice.py:L813-L817'
  - symbol: _badge_scale_and_opacity
    kind: function
    at: 'engines/slice.py:L842-L868'
  - symbol: build_badges_overlay_args
    kind: function
    at: 'engines/slice.py:L871-L935'
  - symbol: apply_badges
    kind: function
    at: 'engines/slice.py:L938-L946'
  - symbol: _fc_match_sc_font
    kind: function
    at: 'engines/slice.py:L1020-L1052'
  - symbol: _extract_sc_face
    kind: function
    at: 'engines/slice.py:L1055-L1104'
  - symbol: _fontconfig_has_cjk_sc
    kind: function
    at: 'engines/slice.py:L1107-L1122'
  - symbol: _resolve_drawtext_font
    kind: function
    at: 'engines/slice.py:L1125-L1155'
  - symbol: _build_text_overlays_filter
    kind: function
    at: 'engines/slice.py:L1158-L1227'
  - symbol: apply_text_overlays
    kind: function
    at: 'engines/slice.py:L1230-L1247'
  - symbol: build_watermark_filter
    kind: function
    at: 'engines/slice.py:L1250-L1294'
  - symbol: _watermark_style_exprs
    kind: function
    at: 'engines/slice.py:L1297-L1343'
  - symbol: css_hex_to_ass
    kind: function
    at: 'engines/slice.py:L1372-L1392'
  - symbol: _css_to_drawtext
    kind: function
    at: 'engines/slice.py:L1395-L1411'
  - symbol: _parse_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1414-L1422'
  - symbol: _format_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1425-L1432'
  - symbol: read_srt
    kind: function
    at: 'engines/slice.py:L1435-L1512'
  - symbol: detect_speech_windows
    kind: function
    at: 'engines/slice.py:L1527-L1598'
  - symbol: _trim_to_speech
    kind: function
    at: 'engines/slice.py:L1601-L1617'
  - symbol: _filter_and_align_srt
    kind: function
    at: 'engines/slice.py:L1620-L1648'
  - symbol: build_clip_subtitle
    kind: function
    at: 'engines/slice.py:L1651-L1690'
  - symbol: burn_subtitle
    kind: function
    at: 'engines/slice.py:L1695-L1792'
  - symbol: _mask_text_clusters
    kind: function
    at: 'engines/slice.py:L1836-L1845'
  - symbol: _split_tall_band
    kind: function
    at: 'engines/slice.py:L1848-L1943'
  - symbol: detect_subtitle_region
    kind: function
    at: 'engines/slice.py:L1946-L2218'
  - symbol: _low_percentile
    kind: function
    at: 'engines/slice.py:L2241-L2254'
  - symbol: _bimodal_threshold
    kind: function
    at: 'engines/slice.py:L2257-L2298'
  - symbol: detect_watermark_region
    kind: function
    at: 'engines/slice.py:L2301-L2436'
  - symbol: detect_subtitle_temporal_windows
    kind: function
    at: 'engines/slice.py:L2439-L2565'
  - symbol: detect_subtitle_spatial_regions
    kind: function
    at: 'engines/slice.py:L2577-L2664'
  - symbol: detect_subtitle_dynamic_regions
    kind: function
    at: 'engines/slice.py:L2679-L2824'
  - symbol: _parse_subtitle_mask_config
    kind: function
    at: 'engines/slice.py:L2827-L2837'
  - symbol: _source_intervals_to_local_intervals
    kind: function
    at: 'engines/slice.py:L2840-L2867'
  - symbol: _scale_region
    kind: function
    at: 'engines/slice.py:L2870-L2885'
  - symbol: _mask_enable_expr
    kind: function
    at: 'engines/slice.py:L2888-L2891'
  - symbol: _source_intervals_to_local_enable
    kind: function
    at: 'engines/slice.py:L2894-L2925'
  - symbol: _spatial_windows_to_local
    kind: function
    at: 'engines/slice.py:L2928-L2969'
  - symbol: _dynamic_windows_to_local
    kind: function
    at: 'engines/slice.py:L2972-L3019'
  - symbol: build_subtitle_mask_enable
    kind: function
    at: 'engines/slice.py:L3022-L3041'
  - symbol: _subtitle_mask_area
    kind: function
    at: 'engines/slice.py:L3044-L3091'
  - symbol: _f
    kind: function
    at: 'engines/slice.py:L3055-L3062'
  - symbol: subtitle_mask_bottom_margin
    kind: function
    at: 'engines/slice.py:L3094-L3154'
  - symbol: _merge_regions
    kind: function
    at: 'engines/slice.py:L3157-L3183'
  - symbol: _scale_regions
    kind: function
    at: 'engines/slice.py:L3186-L3203'
  - symbol: build_subtitle_mask_filter
    kind: function
    at: 'engines/slice.py:L3206-L3259'
  - symbol: build_subtitle_mask_filter_multi
    kind: function
    at: 'engines/slice.py:L3262-L3345'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3281-L3284'
  - symbol: build_subtitle_mask_filter_multi_region
    kind: function
    at: 'engines/slice.py:L3348-L3432'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3368-L3375'
  - symbol: build_subtitle_mask_filter_multi_region_windows
    kind: function
    at: 'engines/slice.py:L3435-L3521'
  - symbol: _enable
    kind: function
    at: 'engines/slice.py:L3451-L3455'
  - symbol: build_subtitle_mask_filter_dynamic
    kind: function
    at: 'engines/slice.py:L3524-L3603'
  - symbol: apply_subtitle_mask
    kind: function
    at: 'engines/slice.py:L3606-L3711'
  - symbol: _video_has_audio
    kind: function
    at: 'engines/slice.py:L3714-L3725'
  - symbol: apply_cover_first_frame
    kind: function
    at: 'engines/slice.py:L3728-L3814'
  - symbol: main
    kind: function
    at: 'engines/slice.py:L3817-L4381'
  - symbol: parse_vert2horiz_config
    kind: function
    at: 'engines/slice.py:L4384-L4394'
  - symbol: apply_vert2horiz
    kind: function
    at: 'engines/slice.py:L4397-L4456'
  - symbol: DedupeManualConfigValue
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L12-L51'
  - symbol: Props
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L53-L58'
  - symbol: DedupeManualConfig
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L66-L218'
  - symbol: set
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L70-L72'
  - symbol: setDict
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L73-L77'
  - symbol: row
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L79-L87'
  - symbol: renderControl
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L90-L138'
  - symbol: num
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L95-L95'
  - symbol: renderDictGroup
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L141-L179'
---
<!-- context:generated:start -->
## Summary

The manual dedupe parameter structure (spatial crop/hflip, temporal speed, color saturation/gamma/contrast/brightness, texture noise/vignette/roll_band/jitter/sharpen, watermark) is a shared contract between the backend slice engine and the frontend. DEDUPE_PRESETS (light/standard/heavy/std_crop_desat/std_retro_scan) are mirrored in both engines/slice.py and frontend DedupeManualConfig.tsx. hflip mirroring is disabled across all presets to preserve visual quality while still reducing duplicate-detection risk.

## Related

- configures [[frontend-api-layer]] — DedupeManualConfig.tsx produces the manual config value sent via sliceApi.run.
- part of [[slice-engine]] — slice.py's _resolve_dedupe_config consumes this structure.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
