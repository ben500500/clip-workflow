# engines/remove_mask_rois.py · [[video-processing-engines]] [[watermark-removal-degradation-chain]]

- _norm_source_name · function · L108-L110 — Normalizes a source filename to its uppercase base name (stripping directory and extension) so it can be looked up in the ROI tables.
- match_rois · function · L113-L132 — Matches a source filename against the built-in ROI experience tables by exact name, embedded 8-char code, or stripped suffix, returning the confirmed ROI dict or None.
- resolve_rois · function · L135-L147 — Resolves the effective ROI config with priority manual region > filename-matched built-in table > generic default, converting manual regions to (y0,y1,x0,x1) form.
- build_mask · function · L150-L162 — Builds a binary uint8 mask by proportionally scaling each (y0,y1,x0,x1) ROI from the 1280x720 reference frame to the actual video resolution.
- rois_to_bboxes · function · L165-L180 — Scales ROI tuples to the actual resolution and converts them into (x,y,w,h) bounding boxes for engines that consume bbox format.
- probe_video_size · function · L183-L195 — Probes a video file's width and height via OpenCV, returning (0,0) on any failure.
