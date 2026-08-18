# engines/seedance_wm/config.py · [[seedance-watermark-removal-engine]]

Defines the YAML-based configuration schema and load/serialize logic for the watermark-removal engine, covering detector, inpainter, temporal, output, logging, and cache settings.

- DetectorConfig · class · L21-L26 — Holds detection settings including primary/fallback algorithms, ROI ratios, confidence threshold, and sampling frame count.
- InpainterConfig · class · L30-L36 — Holds inpainting settings including primary/fallback algorithms, device, fp16, batch size, and pixel expansion.
- TemporalConfig · class · L40-L43 — Holds temporal smoothing settings for frame window size and weighting scheme.
- OutputConfig · class · L47-L52 — Holds video output encoding settings such as codec, CRF, pixel format, and audio retention.
- LoggingConfig · class · L56-L59 — Holds logging level, format template, and log file path settings.
- CacheConfig · class · L63-L66 — Holds cache directory, auto-clean flag, and maximum size in GB settings.
- Config · class · L70-L163 — Aggregates all sub-configs into one root config object and provides YAML load/serialize methods.
- from_yaml · method · L79-L81 — Reads a YAML file from disk and converts it into a Config instance.
- _from_dict · method · L84-L125 — Merges raw YAML dict values into a default Config, overriding only keys present in the file while preserving defaults.
- to_yaml · method · L127-L163 — Serializes the Config instance back into a YAML string for persistence or export.
