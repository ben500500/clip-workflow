# engines/detect_intervals.py · [[video-processing-engines]]

CLI engine that detects credits (trailing black) and static (frozen) intervals in a video via ffmpeg filters and writes the results to a JSON file.

- load_config · function · L29-L37 — Loads a JSON config file over default detection parameters, silently ignoring missing or malformed files.
- ffprobe_duration · function · L40-L49 — Queries the total duration of a video file via ffprobe, returning 0.0 on any failure.
- run_ffmpeg_detect · function · L52-L57 — Runs an ffmpeg filter graph on a video and returns the stderr output where detector messages are printed.
- parse_blackdetect · function · L60-L70 — Parses blackdetect stderr lines into (start, end) intervals, discarding segments shorter than 0.3s.
- parse_freezedetect · function · L73-L88 — Parses freezedetect stderr into frozen intervals, keeping an open-ended interval when a freeze runs to the end of the video.
- main · function · L91-L145 — Orchestrates detection by mode: emits a credits interval only for the last black segment near the video end, and static intervals only when frozen duration meets the minimum threshold.
