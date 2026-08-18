# engines/seedance_watermark_remover.py

CLI tool that removes Seedance 2.0 'AI生成' and static corner watermarks from videos via median-frame detection, segment-wise region masking, and CPU inpainting with ffmpeg reassembly.

- _load_raiw_fill · function · L63-L79 — Loads the remove-ai-watermarks region eraser (LaMa/MI-GAN/cv2) as a fill callable, with fallback to a backend-resolving wrapper or None if unavailable.
- _fill · function · L75-L76 — Wraps the RAiW erase call resolving the auto backend so a single fill(frame, mask) callable is returned.
- _onnx_model_ready · function · L85-L108 — Checks whether a HuggingFace model repo is fully downloaded to local cache, so offline runs avoid per-frame download timeouts.
- _get_raiw_fill · function · L111-L115 — Caches and returns the lazily-loaded RAiW fill callable.
- _multi_canny · function · L122-L128 — Unions Canny edge maps across three threshold pairs so both sharp and faint watermark edges survive detection.
- _auto_detect · function · L131-L200 — Scans wide corner bands and center stripes of the median frame, scoring regions by edge density times temporal stability, and returns deduplicated high-confidence watermark boxes.
- _build_mask · function · L203-L239 — Builds a sparse text mask for a watermark region by combining multi-scale Canny strokes with local background-difference detection of semi-transparent text interiors.
- _inpaint_telea · function · L246-L248 — Performs fast OpenCV TELEA inpainting on a frame using the given mask.
- _make_inpaint · function · L251-L292 — Builds a per-frame inpaint callable, resolving the effective backend and downgrading to cv2 TELEA when LaMa/MI-GAN models are not downloaded or fill fails.
- _inpaint · function · L284-L290 — Invokes the chosen fill backend, falling back to cv2 TELEA on any exception.
- remove_watermark · function · L295-L492 — Orchestrates the full pipeline: samples frames, splits into segments for independent watermark detection, builds a per-frame mask plan with boundary filling, inpaints every frame, and reassembles with original audio via ffmpeg.
- _masks_for_frame · function · L426-L430 — Returns the mask plan for a given frame index, falling back to the last segment's masks.
- main · function · L495-L551 — Parses CLI arguments and invokes remove_watermark, handling output path and manual region options.
