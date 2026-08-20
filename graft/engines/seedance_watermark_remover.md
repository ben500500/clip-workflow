# engines/seedance_watermark_remover.py · [[video-processing-engines]]

- _load_raiw_fill · function · L63-L79 — def _load_raiw_fill()
- _fill · function · L75-L76 — def _fill(frame_bgr, mask, _erase=erase, _resolve=resolve_backend)
- _onnx_model_ready · function · L85-L108 — def _onnx_model_ready(repo_name: str) -> bool
- _get_raiw_fill · function · L111-L115 — def _get_raiw_fill()
- _multi_canny · function · L122-L128 — def _multi_canny(gray)
- _auto_detect · function · L131-L200 — def _auto_detect(median_frame, width, height, std_map=None)
- _build_mask · function · L203-L239 — def _build_mask(median_frame_bgr, region_xywh, frame_shape)
- _inpaint_telea · function · L246-L248 — def _inpaint_telea(frame_bgr, mask)
- _make_inpaint · function · L251-L292 — def _make_inpaint(backend: str)
- _inpaint · function · L284-L290 — def _inpaint(frame_bgr, mask)
- remove_watermark · function · L295-L492 — def remove_watermark(input_path, output_path, manual_region=None, backend="auto", segments=4, roi_source_name=None)
- _masks_for_frame · function · L426-L430 — def _masks_for_frame(i)
- main · function · L495-L551 — def main()
