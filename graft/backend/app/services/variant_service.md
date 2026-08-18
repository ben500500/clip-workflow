# backend/app/services/variant_service.py

- build_variant_recipes · function · L75-L120 — def build_variant_recipes(count: int, base_dedupe: Optional[dict] = None) -> list[dict]
- _recipe_fingerprint_key · function · L123-L125 — def _recipe_fingerprint_key(recipe: dict) -> str
- _load_output · function · L128-L133 — async def _load_output(output_id) -> Optional[SliceOutput]
- _load_output_video_path · function · L136-L149 — async def _load_output_video_path(output: SliceOutput) -> Optional[str]
- _save_variant_row · function · L152-L172 — async def _save_variant_row( output: SliceOutput, variant_index: int, recipe: dict, created_by=None, variant_group_id=None, ) -> uuid.UUID
- _update_variant · function · L175-L181 — async def _update_variant(variant_id, **fields)
- _save_fingerprint · function · L184-L200 — async def _save_fingerprint( variant_id, output_id, variant_group_id, file_key, algo, hash_value, vector, duration, resolution, )
- _load_group_fingerprints · function · L203-L216 — async def _load_group_fingerprints(variant_group_id) -> list[dict]
- _check_against_history · function · L219-L253 — async def _check_against_history(full_fp: dict, variant_group_id=None, exclude_variant_id=None) -> dict
- _build_variant_cutlist · function · L256-L294 — def _build_variant_cutlist(dur: float, structural: dict) -> list[tuple]
- _generate_variant_file · function · L297-L339 — async def _generate_variant_file(source_path: str, recipe: dict, out_name: str) -> str
- _probe_duration_sec · function · L342-L352 — def _probe_duration_sec(path: str) -> float
- generate_variants_for_output · function · L355-L480 — async def generate_variants_for_output( output_id: str, count: int = 1, base_dedupe: Optional[dict] = None, created_by: Optional[str] = None, thresholds: Optional[dict] = None, bucket: str = "sliced", ) -> dict
- _regenerate_recipe · function · L483-L489 — def _regenerate_recipe(base: Optional[dict], prev: dict) -> dict
- verify_variant_fingerprint · function · L492-L529 — async def verify_variant_fingerprint(variant_id: str, thresholds: Optional[dict] = None) -> dict
- guard_account_variant_unique · function · L532-L585 — async def guard_account_variant_unique(account_id, output_id=None, variant_group_id=None) -> dict
