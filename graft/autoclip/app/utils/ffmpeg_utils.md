# autoclip/app/utils/ffmpeg_utils.py · [[ffmpeg-path-resolution]]

Module that resolves ffmpeg/ffprobe executable paths with a priority order (env vars, then system PATH, then fallback command name) to support zero-dependency desktop packaging.

- _resolve_from_env · function · L16-L21 — Returns the first environment variable value that points to an existing file, or None if none match.
- get_ffmpeg_path · function · L24-L40 — Resolves the ffmpeg executable path by checking env vars, then system PATH, falling back to the bare command name.
- get_ffprobe_path · function · L43-L59 — Resolves the ffprobe executable path by checking env vars, then system PATH, falling back to the bare command name.
