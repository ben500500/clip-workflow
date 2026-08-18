---
name: seedance_wm logging convention
slug: seedance-wm-logging-convention
type: concept
sources:
  - path: engines/seedance_wm/log.py
    hash: ee98e56bf3bc442012dfb7f6bdac73be4ddc3a7bab415b616c67c0ee89224869
sources_digest: d6607c47a39b0eef7917e55f2114a7202f337544754b34e4663d325bb65bbf5b
links: []
generator:
  version: 1
covers:
  - symbol: _UtcFormatter
    kind: class
    at: 'engines/seedance_wm/log.py:L27-L32'
  - symbol: formatTime
    kind: method
    at: 'engines/seedance_wm/log.py:L30-L32'
  - symbol: get_logger
    kind: function
    at: 'engines/seedance_wm/log.py:L35-L39'
  - symbol: _configure
    kind: function
    at: 'engines/seedance_wm/log.py:L42-L47'
  - symbol: set_level
    kind: function
    at: 'engines/seedance_wm/log.py:L50-L52'
  - symbol: add_file_handler
    kind: function
    at: 'engines/seedance_wm/log.py:L55-L61'
---
<!-- context:generated:start -->
## Summary

Project-wide log format [HH:MM:SS.mmm] [LEVEL] [module] written to stderr, with millisecond-precision UTC timestamps via a custom formatter. Loggers are configured lazily on first use with propagation disabled to avoid duplicate output; file handlers auto-create parent directories. String levels like 'warn' are mapped to logging constants.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
