# engines/seedance_wm/log.py · [[seedance-wm-engine]] [[seedance-wm-logging-convention]]

- _UtcFormatter · class · L27-L32 — class _UtcFormatter(logging.Formatter)
- formatTime · method · L30-L32 — def formatTime(self, record, datefmt=None)
- get_logger · function · L35-L39 — def get_logger(name: str = "seedance_wm") -> logging.Logger
- _configure · function · L42-L47 — def _configure(logger: logging.Logger) -> None
- set_level · function · L50-L52 — def set_level(level: str) -> None
- add_file_handler · function · L55-L61 — def add_file_handler(log_file: str | Path) -> None
