# backend/app/services/fingerprint_service.py · [[variant-deduplication]]

- _run · function · L53-L60 — def _run(cmd: list[str], timeout: int = 60) -> bytes
- _probe_duration · function · L63-L72 — def _probe_duration(path: str) -> float
- _probe_resolution · function · L75-L84 — def _probe_resolution(path: str) -> str
- _extract_sample_frames · function · L90-L103 — def _extract_sample_frames(path: str, count: int = 8) -> list
- _read_frame_rgb · function · L106-L127 — def _read_frame_rgb(path: str, t: float, size: int = 32)
- _dct2 · function · L130-L143 — def _dct2(a: np.ndarray)
- _phash_of_gray · function · L146-L167 — def _phash_of_gray(img) -> Optional[str]
- compute_visual_fingerprint · function · L170-L217 — def compute_visual_fingerprint(path: str) -> dict
- compute_audio_fingerprint · function · L223-L251 — def compute_audio_fingerprint(path: str) -> dict
- _audio_signature · function · L254-L322 — def _audio_signature(samples: np.ndarray, dur: float) -> dict
- compute_segment_fingerprint · function · L328-L370 — def compute_segment_fingerprint(path: str) -> dict
- hamming_distance_hex · function · L376-L389 — def hamming_distance_hex(a: str, b: str) -> float
- vector_distance · function · L392-L403 — def vector_distance(a: Optional[str], b: Optional[str]) -> float
- _extract_algo · function · L413-L430 — def _extract_algo(fp_dict: dict, algo: str)
- _algo_distance · function · L433-L442 — def _algo_distance(fa: dict, fb: dict, algo: str) -> float
- compare_fingerprints · function · L445-L463 — def compare_fingerprints(fa: dict, fb: dict) -> dict
- is_collision · function · L466-L488 — def is_collision(distances: dict, thresholds: Optional[dict] = None) -> tuple[bool, str]
- compute_full_fingerprint · function · L491-L505 — def compute_full_fingerprint(path: str) -> dict
