---
name: Interval Detection Engine
slug: interval-detection-engine
type: system
sources:
  - path: engines/detect_intervals.py
    hash: 7d009ae2cde6a54c1aa057f870160e4583a4f209d2807691a528a90dea2215f0
sources_digest: c52218e6c86974882808196d915d0bb4c832ef5d6001ed8ad4b048a458e6a272
links: []
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
---
<!-- context:generated:start -->
## Summary

CLI-based interval detection engine wrapping ffmpeg filters to identify credits (trailing black segments via blackdetect) and static/frozen frames (via freezedetect). Writes JSON results with start/end times, confidence, and labels. Handles edge cases like open-ended freeze intervals at video end (using duration as fallback) and credits detection only when the last black segment is near the video tail. Watermark/custom modes return empty results since no generic detector exists.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
