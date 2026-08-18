# backend/app/services/variant_service.py · [[variant-generation-pipeline]]

- build_variant_recipes · function · L75-L120 — Generates N dedupe recipes where index 1 uses the base config and subsequent variants get randomized structural differences across crop/speed/color/noise/audio/segmentation dimensions to spread fingerprints apart.
- _recipe_fingerprint_key · function · L123-L125 — Produces a canonical JSON key for a recipe so the retry loop can detect and avoid reusing an identical recipe.
- _load_output · function · L128-L133 — Loads a SliceOutput row by id from the database.
- _load_output_video_path · function · L136-L149 — Downloads the base slice's video from MinIO to a local temp path so it can be used as the variant generation source.
- _save_variant_row · function · L152-L172 — Persists a new ClipVariant row in pending status and returns its id.
- _update_variant · function · L175-L181 — Updates arbitrary fields on a ClipVariant row by id.
- _save_fingerprint · function · L184-L200 — Persists a VideoFingerprint row for a generated variant.
- _load_group_fingerprints · function · L203-L216 — Loads all completed variant fingerprints within a variant group for collision comparison.
- _check_against_history · function · L219-L253 — Compares a new fingerprint against same-group historical fingerprints (excluding self) and returns minimum distances plus whether a collision occurred.
- _build_variant_cutlist · function · L256-L294 — Builds a segment cutlist that splits the video into 3-5 drifted segments and optionally reorders them to alter the L4 temporal-sequence fingerprint while guaranteeing positive durations and bounds.
- _generate_variant_file · function · L297-L339 — Applies a dedupe recipe to the source video via the slice engine, writes a cutlist, and returns the local path of the produced variant file.
- _probe_duration_sec · function · L342-L352 — Probes a video's duration in seconds via ffprobe, defaulting to 10s on failure.
- generate_variants_for_output · function · L355-L480 — Orchestrates the full variant pipeline: creates a variant group, generates each recipe's file, computes fingerprints, checks collisions against history, retries with regenerated recipes up to MAX_RETRY, and persists results.
- _regenerate_recipe · function · L483-L489 — Regenerates a fresh recipe from the base config to replace a collided or failed one during retry.
- verify_variant_fingerprint · function · L492-L529 — Verifies a variant's fingerprint against thresholds to confirm it is sufficiently distinct.
- guard_account_variant_unique · function · L532-L585 — Guards against sending the same material to multiple accounts by checking variant uniqueness per account.
