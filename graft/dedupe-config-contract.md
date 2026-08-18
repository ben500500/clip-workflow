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
    at: 'engines/slice.py:L180-L185'
  - symbol: _resolve_dedupe_config
    kind: function
    at: 'engines/slice.py:L188-L220'
  - symbol: build_dedupe_filter
    kind: function
    at: 'engines/slice.py:L223-L326'
  - symbol: build_dedupe_audio_filter
    kind: function
    at: 'engines/slice.py:L329-L369'
  - symbol: build_dedupe_watermark
    kind: function
    at: 'engines/slice.py:L372-L413'
  - symbol: cpu_threads_for_percent
    kind: function
    at: 'engines/slice.py:L416-L435'
  - symbol: parse_time
    kind: function
    at: 'engines/slice.py:L438-L444'
  - symbol: read_cutlist
    kind: function
    at: 'engines/slice.py:L447-L463'
  - symbol: read_intervals
    kind: function
    at: 'engines/slice.py:L466-L482'
  - symbol: subtract_intervals
    kind: function
    at: 'engines/slice.py:L485-L507'
  - symbol: ffprobe_duration
    kind: function
    at: 'engines/slice.py:L510-L519'
  - symbol: ffprobe_resolution
    kind: function
    at: 'engines/slice.py:L522-L536'
  - symbol: ffprobe_framerate
    kind: function
    at: 'engines/slice.py:L539-L565'
  - symbol: ffprobe_size
    kind: function
    at: 'engines/slice.py:L568-L584'
  - symbol: _fallback_libx264_args
    kind: function
    at: 'engines/slice.py:L587-L615'
  - symbol: run_ffmpeg
    kind: function
    at: 'engines/slice.py:L618-L642'
  - symbol: detect_best_encoder
    kind: function
    at: 'engines/slice.py:L645-L673'
  - symbol: build_encoder_args
    kind: function
    at: 'engines/slice.py:L676-L683'
  - symbol: slice_segment
    kind: function
    at: 'engines/slice.py:L686-L705'
  - symbol: concat_segments
    kind: function
    at: 'engines/slice.py:L708-L732'
  - symbol: _is_copy_segment
    kind: function
    at: 'engines/slice.py:L735-L740'
  - symbol: _concat_demuxer
    kind: function
    at: 'engines/slice.py:L743-L758'
  - symbol: safe_name
    kind: function
    at: 'engines/slice.py:L761-L765'
  - symbol: _badge_scale_and_opacity
    kind: function
    at: 'engines/slice.py:L790-L816'
  - symbol: build_badges_overlay_args
    kind: function
    at: 'engines/slice.py:L819-L883'
  - symbol: apply_badges
    kind: function
    at: 'engines/slice.py:L886-L894'
  - symbol: _fc_match_sc_font
    kind: function
    at: 'engines/slice.py:L968-L1000'
  - symbol: _extract_sc_face
    kind: function
    at: 'engines/slice.py:L1003-L1052'
  - symbol: _fontconfig_has_cjk_sc
    kind: function
    at: 'engines/slice.py:L1055-L1070'
  - symbol: _resolve_drawtext_font
    kind: function
    at: 'engines/slice.py:L1073-L1103'
  - symbol: _build_text_overlays_filter
    kind: function
    at: 'engines/slice.py:L1106-L1175'
  - symbol: apply_text_overlays
    kind: function
    at: 'engines/slice.py:L1178-L1195'
  - symbol: build_watermark_filter
    kind: function
    at: 'engines/slice.py:L1198-L1242'
  - symbol: _watermark_style_exprs
    kind: function
    at: 'engines/slice.py:L1245-L1291'
  - symbol: css_hex_to_ass
    kind: function
    at: 'engines/slice.py:L1320-L1340'
  - symbol: _css_to_drawtext
    kind: function
    at: 'engines/slice.py:L1343-L1359'
  - symbol: _parse_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1362-L1370'
  - symbol: _format_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1373-L1380'
  - symbol: read_srt
    kind: function
    at: 'engines/slice.py:L1383-L1460'
  - symbol: detect_speech_windows
    kind: function
    at: 'engines/slice.py:L1475-L1546'
  - symbol: _trim_to_speech
    kind: function
    at: 'engines/slice.py:L1549-L1565'
  - symbol: _filter_and_align_srt
    kind: function
    at: 'engines/slice.py:L1568-L1596'
  - symbol: build_clip_subtitle
    kind: function
    at: 'engines/slice.py:L1599-L1638'
  - symbol: burn_subtitle
    kind: function
    at: 'engines/slice.py:L1643-L1740'
  - symbol: _mask_text_clusters
    kind: function
    at: 'engines/slice.py:L1784-L1793'
  - symbol: _split_tall_band
    kind: function
    at: 'engines/slice.py:L1796-L1891'
  - symbol: detect_subtitle_region
    kind: function
    at: 'engines/slice.py:L1894-L2166'
  - symbol: _low_percentile
    kind: function
    at: 'engines/slice.py:L2189-L2202'
  - symbol: _bimodal_threshold
    kind: function
    at: 'engines/slice.py:L2205-L2246'
  - symbol: detect_watermark_region
    kind: function
    at: 'engines/slice.py:L2249-L2384'
  - symbol: detect_subtitle_temporal_windows
    kind: function
    at: 'engines/slice.py:L2387-L2513'
  - symbol: detect_subtitle_spatial_regions
    kind: function
    at: 'engines/slice.py:L2525-L2612'
  - symbol: detect_subtitle_dynamic_regions
    kind: function
    at: 'engines/slice.py:L2627-L2772'
  - symbol: _parse_subtitle_mask_config
    kind: function
    at: 'engines/slice.py:L2775-L2785'
  - symbol: _source_intervals_to_local_intervals
    kind: function
    at: 'engines/slice.py:L2788-L2815'
  - symbol: _scale_region
    kind: function
    at: 'engines/slice.py:L2818-L2833'
  - symbol: _mask_enable_expr
    kind: function
    at: 'engines/slice.py:L2836-L2839'
  - symbol: _source_intervals_to_local_enable
    kind: function
    at: 'engines/slice.py:L2842-L2873'
  - symbol: _spatial_windows_to_local
    kind: function
    at: 'engines/slice.py:L2876-L2917'
  - symbol: _dynamic_windows_to_local
    kind: function
    at: 'engines/slice.py:L2920-L2967'
  - symbol: build_subtitle_mask_enable
    kind: function
    at: 'engines/slice.py:L2970-L2989'
  - symbol: _subtitle_mask_area
    kind: function
    at: 'engines/slice.py:L2992-L3039'
  - symbol: _f
    kind: function
    at: 'engines/slice.py:L3003-L3010'
  - symbol: subtitle_mask_bottom_margin
    kind: function
    at: 'engines/slice.py:L3042-L3102'
  - symbol: _merge_regions
    kind: function
    at: 'engines/slice.py:L3105-L3131'
  - symbol: _scale_regions
    kind: function
    at: 'engines/slice.py:L3134-L3151'
  - symbol: build_subtitle_mask_filter
    kind: function
    at: 'engines/slice.py:L3154-L3207'
  - symbol: build_subtitle_mask_filter_multi
    kind: function
    at: 'engines/slice.py:L3210-L3293'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3229-L3232'
  - symbol: build_subtitle_mask_filter_multi_region
    kind: function
    at: 'engines/slice.py:L3296-L3380'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3316-L3323'
  - symbol: build_subtitle_mask_filter_multi_region_windows
    kind: function
    at: 'engines/slice.py:L3383-L3469'
  - symbol: _enable
    kind: function
    at: 'engines/slice.py:L3399-L3403'
  - symbol: build_subtitle_mask_filter_dynamic
    kind: function
    at: 'engines/slice.py:L3472-L3551'
  - symbol: apply_subtitle_mask
    kind: function
    at: 'engines/slice.py:L3554-L3659'
  - symbol: _video_has_audio
    kind: function
    at: 'engines/slice.py:L3662-L3673'
  - symbol: apply_cover_first_frame
    kind: function
    at: 'engines/slice.py:L3676-L3751'
  - symbol: main
    kind: function
    at: 'engines/slice.py:L3754-L4317'
  - symbol: parse_vert2horiz_config
    kind: function
    at: 'engines/slice.py:L4320-L4330'
  - symbol: apply_vert2horiz
    kind: function
    at: 'engines/slice.py:L4333-L4392'
  - symbol: DedupeManualConfigValue
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L10-L34'
  - symbol: Props
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L129-L134'
  - symbol: DedupeManualConfig
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L137-L236'
  - symbol: set
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L140-L142'
  - symbol: setWm
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L143-L147'
  - symbol: row
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L150-L158'
  - symbol: num
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L160-L160'
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
