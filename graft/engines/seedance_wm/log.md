# engines/seedance_wm/log.py · [[seedance-wm-engine]] [[seedance-wm-logging-convention]]

Logging module enforcing the TRD §5.3/API §2 spec: all logs go to stderr in [HH:MM:SS.mmm] [LEVEL] [module] format, with optional file output to ./remove-wm.log.

- _UtcFormatter · class · L27-L32 — Custom logging formatter that emits millisecond-precision timestamps matching the [HH:MM:SS.mmm] spec.
- formatTime · method · L30-L32 — Overrides logging's default time formatting to append milliseconds to the HH:MM:SS timestamp.
- get_logger · function · L35-L39 — Returns a named logger, lazily configuring it once on first use so handlers are not duplicated.
- _configure · function · L42-L47 — Sets up a logger to write INFO-level logs to stderr with the spec formatter and disables propagation.
- set_level · function · L50-L52 — Changes the root logger's level by mapping a string name to a logging level, defaulting to INFO for unknown values.
- add_file_handler · function · L55-L61 — Adds a file handler that writes logs to a UTF-8 file, creating parent directories as needed.
