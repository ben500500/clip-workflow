# autoclip/app/pipeline/step2_timeline.py · [[autoclip-pipeline]]

- TimelineExtractor · class · L18-L421 — Orchestrates timeline extraction by loading the timeline prompt, applying custom duration rules, processing SRT chunks through the LLM, and assembling/sorting validated timeline results.
- __init__ · method · L21-L42 — Initializes the extractor with LLM client, text processor, prompt file, custom duration config, and output directory paths.
- _apply_duration_config · method · L44-L110 — Injects user-supplied min/max duration rules into the timeline prompt by replacing default duration sections and stripping hardcoded 90-second checks.
- extract_timeline · method · L112-L291 — Groups outlines by chunk, calls the LLM per chunk with retry/parse-fallback, persists per-chunk JSON results, then merges and globally sorts all timeline items with stable IDs.
- _parse_and_validate_response · method · L293-L372 — Parses the LLM's JSON response, validates structure and time formats, and clamps each topic's start/end times to the chunk's boundaries.
- _validate_time_format · method · L374-L379 — Checks that a time string matches the HH:MM:SS,mmm SRT format via regex.
- _convert_time_format · method · L381-L387 — Converts SRT comma-millisecond time format to FFmpeg dot-millisecond format.
- _save_debug_response · method · L389-L399 — Writes raw LLM responses or error details to a debug_responses directory for troubleshooting.
- save_timeline · method · L401-L414 — Persists the extracted timeline data to a JSON file at the given or default output path.
- load_timeline · method · L416-L421 — Loads previously saved timeline data from a JSON file.
- run_step2_timeline · function · L423-L444 — Entry-point function that instantiates TimelineExtractor, runs extraction on outlines loaded from a file, and saves the result.
