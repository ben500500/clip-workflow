# engines/seedance_wm/errors.py · [[video-processing-engines]] [[watermark-removal-degradation-chain]]

- WatermarkRemoverError · class · L30-L37 — class WatermarkRemoverError(Exception)
- __init__ · method · L35-L37 — def __init__(self, message: str, *args)
- InvalidArgsError · class · L40-L41 — class InvalidArgsError(WatermarkRemoverError)
- VideoReadError · class · L44-L45 — class VideoReadError(WatermarkRemoverError)
- DetectFailError · class · L48-L49 — class DetectFailError(WatermarkRemoverError)
- FfmpegMissingError · class · L52-L53 — class FfmpegMissingError(WatermarkRemoverError)
- InpaintError · class · L56-L57 — class InpaintError(WatermarkRemoverError)
- MuxError · class · L60-L61 — class MuxError(WatermarkRemoverError)
- OutOfDiskError · class · L64-L65 — class OutOfDiskError(WatermarkRemoverError)
- GpuOomError · class · L68-L71 — class GpuOomError(WatermarkRemoverError)
- LicenseError · class · L74-L75 — class LicenseError(WatermarkRemoverError)
