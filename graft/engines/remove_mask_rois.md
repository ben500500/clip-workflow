# engines/remove_mask_rois.py

- _norm_source_name · function · L108-L110 — def _norm_source_name(source_name: str) -> str
- match_rois · function · L113-L132 — def match_rois(source_name: str, scope: str = 'small') -> Optional[dict]
- resolve_rois · function · L135-L147 — def resolve_rois(source_name: str, manual_region=None, scope: str = 'small') -> dict
- build_mask · function · L150-L162 — def build_mask(rois: dict, H: int, W: int) -> "np.ndarray"
- rois_to_bboxes · function · L165-L180 — def rois_to_bboxes(rois: dict, width: int, height: int) -> list[tuple[int, int, int, int]]
- probe_video_size · function · L183-L195 — def probe_video_size(video_path: str) -> tuple[int, int]
