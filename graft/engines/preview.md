# engines/preview.py · [[preview-frame-extraction-engine]]

CLI tool that extracts evenly-spaced preview frames from a video using ffmpeg and reports progress/output to stdout.

- ffprobe_duration · function · L15-L24 — Queries ffprobe for the video's duration in seconds, returning 0.0 on any failure so callers can fall back to a default timing scheme.
- main · function · L27-L55 — Validates the source, computes evenly-spaced timestamps across the video duration, and invokes ffmpeg to extract one JPEG frame per timestamp while emitting progress and output lines.
