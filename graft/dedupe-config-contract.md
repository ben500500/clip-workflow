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
    at: 'engines/slice.py:L769-L790'
  - symbol: detect_best_encoder
    kind: function
    at: 'engines/slice.py:L793-L835'
  - symbol: build_encoder_args
    kind: function
    at: 'engines/slice.py:L838-L845'
  - symbol: slice_segment
    kind: function
    at: 'engines/slice.py:L848-L867'
  - symbol: concat_segments
    kind: function
    at: 'engines/slice.py:L870-L904'
  - symbol: _is_copy_segment
    kind: function
    at: 'engines/slice.py:L907-L912'
  - symbol: _concat_demuxer
    kind: function
    at: 'engines/slice.py:L915-L930'
  - symbol: safe_name
    kind: function
    at: 'engines/slice.py:L933-L937'
  - symbol: _badge_scale_and_opacity
    kind: function
    at: 'engines/slice.py:L962-L988'
  - symbol: build_badges_overlay_args
    kind: function
    at: 'engines/slice.py:L991-L1055'
  - symbol: apply_badges
    kind: function
    at: 'engines/slice.py:L1058-L1066'
  - symbol: _fc_match_sc_font
    kind: function
    at: 'engines/slice.py:L1140-L1172'
  - symbol: _extract_sc_face
    kind: function
    at: 'engines/slice.py:L1175-L1224'
  - symbol: _fontconfig_has_cjk_sc
    kind: function
    at: 'engines/slice.py:L1227-L1242'
  - symbol: _resolve_drawtext_font
    kind: function
    at: 'engines/slice.py:L1245-L1275'
  - symbol: _build_text_overlays_filter
    kind: function
    at: 'engines/slice.py:L1278-L1347'
  - symbol: apply_text_overlays
    kind: function
    at: 'engines/slice.py:L1350-L1367'
  - symbol: build_watermark_filter
    kind: function
    at: 'engines/slice.py:L1370-L1414'
  - symbol: _watermark_style_exprs
    kind: function
    at: 'engines/slice.py:L1417-L1463'
  - symbol: css_hex_to_ass
    kind: function
    at: 'engines/slice.py:L1493-L1513'
  - symbol: _css_to_drawtext
    kind: function
    at: 'engines/slice.py:L1516-L1532'
  - symbol: _parse_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1535-L1543'
  - symbol: _format_srt_timestamp
    kind: function
    at: 'engines/slice.py:L1546-L1553'
  - symbol: read_srt
    kind: function
    at: 'engines/slice.py:L1556-L1633'
  - symbol: detect_speech_windows
    kind: function
    at: 'engines/slice.py:L1648-L1719'
  - symbol: _trim_to_speech
    kind: function
    at: 'engines/slice.py:L1722-L1738'
  - symbol: _filter_and_align_srt
    kind: function
    at: 'engines/slice.py:L1741-L1769'
  - symbol: build_clip_subtitle
    kind: function
    at: 'engines/slice.py:L1772-L1815'
  - symbol: burn_subtitle
    kind: function
    at: 'engines/slice.py:L1820-L1926'
  - symbol: _mask_text_clusters
    kind: function
    at: 'engines/slice.py:L1970-L1979'
  - symbol: _split_tall_band
    kind: function
    at: 'engines/slice.py:L1982-L2077'
  - symbol: detect_subtitle_region
    kind: function
    at: 'engines/slice.py:L2080-L2352'
  - symbol: _low_percentile
    kind: function
    at: 'engines/slice.py:L2375-L2388'
  - symbol: _bimodal_threshold
    kind: function
    at: 'engines/slice.py:L2391-L2432'
  - symbol: detect_watermark_region
    kind: function
    at: 'engines/slice.py:L2435-L2570'
  - symbol: detect_subtitle_temporal_windows
    kind: function
    at: 'engines/slice.py:L2573-L2699'
  - symbol: detect_subtitle_spatial_regions
    kind: function
    at: 'engines/slice.py:L2711-L2798'
  - symbol: detect_subtitle_dynamic_regions
    kind: function
    at: 'engines/slice.py:L2813-L2958'
  - symbol: _parse_subtitle_mask_config
    kind: function
    at: 'engines/slice.py:L2961-L2971'
  - symbol: _source_intervals_to_local_intervals
    kind: function
    at: 'engines/slice.py:L2974-L3001'
  - symbol: _scale_region
    kind: function
    at: 'engines/slice.py:L3004-L3019'
  - symbol: _mask_enable_expr
    kind: function
    at: 'engines/slice.py:L3022-L3025'
  - symbol: _source_intervals_to_local_enable
    kind: function
    at: 'engines/slice.py:L3028-L3059'
  - symbol: _spatial_windows_to_local
    kind: function
    at: 'engines/slice.py:L3062-L3103'
  - symbol: _dynamic_windows_to_local
    kind: function
    at: 'engines/slice.py:L3106-L3153'
  - symbol: build_subtitle_mask_enable
    kind: function
    at: 'engines/slice.py:L3156-L3175'
  - symbol: _subtitle_mask_area
    kind: function
    at: 'engines/slice.py:L3178-L3225'
  - symbol: _f
    kind: function
    at: 'engines/slice.py:L3189-L3196'
  - symbol: subtitle_mask_bottom_margin
    kind: function
    at: 'engines/slice.py:L3228-L3288'
  - symbol: _merge_regions
    kind: function
    at: 'engines/slice.py:L3291-L3317'
  - symbol: _scale_regions
    kind: function
    at: 'engines/slice.py:L3320-L3337'
  - symbol: build_subtitle_mask_filter
    kind: function
    at: 'engines/slice.py:L3340-L3393'
  - symbol: build_subtitle_mask_filter_multi
    kind: function
    at: 'engines/slice.py:L3396-L3479'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3415-L3418'
  - symbol: build_subtitle_mask_filter_multi_region
    kind: function
    at: 'engines/slice.py:L3482-L3566'
  - symbol: _clip
    kind: function
    at: 'engines/slice.py:L3502-L3509'
  - symbol: build_subtitle_mask_filter_multi_region_windows
    kind: function
    at: 'engines/slice.py:L3569-L3655'
  - symbol: _enable
    kind: function
    at: 'engines/slice.py:L3585-L3589'
  - symbol: build_subtitle_mask_filter_dynamic
    kind: function
    at: 'engines/slice.py:L3658-L3737'
  - symbol: apply_subtitle_mask
    kind: function
    at: 'engines/slice.py:L3740-L3845'
  - symbol: _video_has_audio
    kind: function
    at: 'engines/slice.py:L3848-L3859'
  - symbol: apply_cover_first_frame
    kind: function
    at: 'engines/slice.py:L3862-L3954'
  - symbol: _fps_value
    kind: function
    at: 'engines/slice.py:L3971-L3979'
  - symbol: build_output_tier_filter
    kind: function
    at: 'engines/slice.py:L3982-L4015'
  - symbol: main
    kind: function
    at: 'engines/slice.py:L4018-L4788'
  - symbol: parse_vert2horiz_config
    kind: function
    at: 'engines/slice.py:L4791-L4801'
  - symbol: apply_vert2horiz
    kind: function
    at: 'engines/slice.py:L4804-L4863'
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
