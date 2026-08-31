# engines/seedance_wm/ffmpeg_io.py · [[video-processing-engines]]

FFmpeg I/O layer encapsulating probe, frame extraction, and final video muxing for the two pipeline stages that touch raw video.

- check_ffmpeg · function · L32-L36 — Guards every FFmpeg operation by failing fast with a friendly install hint when the ffmpeg binary is absent.
- _parse_rational · function · L39-L47 — Converts FFmpeg's rational frame-rate strings (e.g. '30000/1001') into a float, defaulting to 0.0 on malformed input.
- VideoMeta · class · L51-L57 — Plain data holder carrying probed video metadata (fps, dimensions, duration, audio presence) for downstream stages.
- probe_video · function · L60-L95 — Validates an input file and extracts its video metadata, raising typed errors for missing/empty/unsupported files and undecodable streams.
- extract_frames · function · L98-L161 — Decodes a video into a PNG frame sequence at a target fps and optionally separates the audio track, returning a result dict for later muxing.
- mux_video · function · L164-L228 — Re-encodes a frame sequence (with optional original audio) into a final playable video, falling back to raw frames when no cleaned frames exist.
- get_available_disk_gb · function · L231-L234 — Reports free disk space on the volume containing the given path so callers can preflight storage before extraction.
- run_cmd · function · L237-L238 — Thin wrapper running a shell command and capturing its output for simple subprocess invocations.
