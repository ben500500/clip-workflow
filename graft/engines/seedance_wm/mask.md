# engines/seedance_wm/mask.py · [[seedance-wm-engine]] [[seedance-wm-mask-generation]]

Module that converts watermark bounding boxes into per-frame single-channel mask PNGs (white=watermark, black=background) with morphological dilation margin for inpainting.

- generate_mask_sequence · function · L19-L77 — Generates a full frame-level mask sequence by merging one or more watermark bboxes (expanded by a margin) into identical per-frame masks written as PNGs.
