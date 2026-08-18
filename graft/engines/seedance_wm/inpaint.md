# engines/seedance_wm/inpaint.py · [[video-processing-engines]] [[watermark-removal-degradation-chain]]

- _lama_model_ready · function · L29-L57 — Checks whether the LaMa ONNX model is fully downloaded to the local HF cache so offline servers avoid hanging on network timeouts.
- resolve_device · function · L60-L70 — Resolves 'auto' to cuda when torch reports a GPU, otherwise falls back to cpu.
- _inpaint_cv2 · function · L73-L81 — Runs OpenCV inpainting (Telea or NS) on a single frame with a fixed radius of 3.
- _inpaint_lama · function · L87-L99 — Runs LaMa inpainting via the remove-ai-watermarks wrapper, lazily loading and caching the erase_lama function and raising if the model or dependency is unavailable.
- inpaint_frames · function · L102-L185 — Iterates frame/mask pairs, applies the inpainting model chain per frame with per-frame fallback on failure, writes clean frames, and reports progress.
- _build_inpaint_chain · function · L188-L223 — Builds the ordered fallback chain of inpainting models, substituting cv2 when lama is unavailable or its model isn't downloaded.
- temporal_smooth · function · L226-L295 — Applies a sliding-window weighted average across clean frames to reduce flicker while keeping only window frames in memory to avoid OOM.
- _read_frame · function · L264-L269 — Reads a frame from disk with bounds checking, caching it in the sliding-window cache to avoid repeated loads.
