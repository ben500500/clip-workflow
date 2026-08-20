# backend/app/services/variant_service.py · [[variant-generation-pipeline]]

- _pick_audio_mode · function · L93-L101 — def _pick_audio_mode(used_audio: list) -> str
- build_variant_recipes · function · L104-L166 — def build_variant_recipes(count: int, base_dedupe: Optional[dict] = None) -> list[dict]
- _recipe_fingerprint_key · function · L169-L171 — def _recipe_fingerprint_key(recipe: dict) -> str
- _load_output · function · L174-L183 — async def _load_output(output_id) -> Optional[SliceOutput]
- _load_output_video_path · function · L186-L199 — async def _load_output_video_path(output: SliceOutput) -> Optional[str]
- _save_variant_row · function · L202-L222 — async def _save_variant_row( output: SliceOutput, variant_index: int, recipe: dict, created_by=None, variant_group_id=None, ) -> uuid.UUID
- _update_variant · function · L225-L231 — async def _update_variant(variant_id, **fields)
- mark_output_variants_failed · function · L234-L249 — async def mark_output_variants_failed(output_id: str, error_message: str) -> int
- _save_fingerprint · function · L252-L268 — async def _save_fingerprint( variant_id, output_id, variant_group_id, file_key, algo, hash_value, vector, duration, resolution, )
- _load_group_fingerprints · function · L271-L286 — async def _load_group_fingerprints(variant_group_id) -> list[dict]
- _check_against_history · function · L289-L325 — async def _check_against_history(full_fp: dict, variant_group_id=None, exclude_variant_id=None) -> dict
- _build_variant_cutlist · function · L328-L366 — def _build_variant_cutlist(dur: float, structural: dict) -> list[tuple]
- _generate_variant_file · function · L369-L411 — async def _generate_variant_file(source_path: str, recipe: dict, out_name: str) -> str
- _probe_duration_sec · function · L414-L424 — def _probe_duration_sec(path: str) -> float
- generate_variants_for_output · function · L427-L555 — async def generate_variants_for_output( output_id: str, count: int = 1, base_dedupe: Optional[dict] = None, created_by: Optional[str] = None, thresholds: Optional[dict] = None, bucket: str = "sliced", ) -> dict
- _regenerate_recipe · function · L558-L570 — def _regenerate_recipe(base: Optional[dict], prev: dict, used_audio: list) -> dict
- verify_variant_fingerprint · function · L573-L615 — async def verify_variant_fingerprint(variant_id: str, thresholds: Optional[dict] = None) -> dict
- guard_account_variant_unique · function · L618-L675 — async def guard_account_variant_unique(account_id, output_id=None, variant_group_id=None) -> dict
