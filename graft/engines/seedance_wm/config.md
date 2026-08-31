# engines/seedance_wm/config.py · [[video-processing-engines]]

Defines the YAML-based configuration schema and load/serialize logic for the watermark-removal engine, covering detector, inpainter, temporal, output, logging, and cache settings.

- DetectorConfig · class · L21-L26 — Holds detection settings including primary/fallback algorithms, ROI ratios, confidence threshold, and sampling frame count.
- InpainterConfig · class · L30-L37 — Holds inpainting settings including primary/fallback algorithms, device, fp16, batch size, and pixel expansion.
- TemporalConfig · class · L41-L44 — Holds temporal smoothing settings for frame window size and weighting scheme.
- OutputConfig · class · L48-L53 — Holds video output encoding settings such as codec, CRF, pixel format, and audio retention.
- LoggingConfig · class · L57-L60 — Holds logging level, format template, and log file path settings.
- CacheConfig · class · L64-L67 — Holds cache directory, auto-clean flag, and maximum size in GB settings.
- Config · class · L71-L164 — Aggregates all sub-configs into one root config object and provides YAML load/serialize methods.
- from_yaml · method · L80-L82 — Reads a YAML file from disk and converts it into a Config instance.
- _from_dict · method · L85-L126 — Merges raw YAML dict values into a default Config, overriding only keys present in the file while preserving defaults.
- to_yaml · method · L128-L164 — Serializes the Config instance back into a YAML string for persistence or export.
