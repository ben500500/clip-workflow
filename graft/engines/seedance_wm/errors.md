# engines/seedance_wm/errors.py · [[video-processing-engines]] [[watermark-removal-degradation-chain]]

Defines the exit codes and exception hierarchy for the watermark remover, mapping each failure mode to a documented exit code.

- WatermarkRemoverError · class · L30-L37 — Base class for all business exceptions, carrying a message and defaulting to the UNKNOWN exit code.
- __init__ · method · L35-L37 — Stores the human-readable message on the exception instance for later reporting.
- InvalidArgsError · class · L40-L41 — Raised when CLI arguments are invalid, mapping to exit code 1.
- VideoReadError · class · L44-L45 — Raised when video reading fails, mapping to exit code 2.
- DetectFailError · class · L48-L49 — Raised when all watermark detection attempts fail, mapping to exit code 3.
- FfmpegMissingError · class · L52-L53 — Raised when FFmpeg is not installed, mapping to exit code 4.
- InpaintError · class · L56-L57 — Raised when all inpainting fixers fail, mapping to exit code 5.
- MuxError · class · L60-L61 — Raised when video muxing/composition fails, mapping to exit code 6.
- OutOfDiskError · class · L64-L65 — Raised when disk space is insufficient, mapping to exit code 7.
- GpuOomError · class · L68-L71 — Raised on GPU out-of-memory; signals automatic CPU fallback rather than a fatal error, mapping to exit code 8.
- LicenseError · class · L74-L75 — Raised when ProPainter commercial license validation fails, mapping to exit code 9.
