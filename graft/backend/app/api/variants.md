# backend/app/api/variants.py

- VariantGenerateRequest · class · L41-L45 — Request payload for manually triggering variant generation on an existing slice output, with optional dedupe config and threshold overrides.
- VariantBindRequest · class · L48-L50 — Request payload for binding a variant to an account, allowing unbinding via null account_id.
- _get_thresholds · function · L53-L63 — Loads collision-detection thresholds from system_config, merging stored overrides on top of defaults so operators can tune dedupe strictness.
- _list_variant_groups · function · L66-L101 — Aggregates slice outputs into variant groups with their full variant lists, distances, collision flags, and account bindings for the dashboard.
- variant_matrix · function · L105-L111 — Dashboard endpoint returning variant groups plus current thresholds, combining aggregation and config in one response.
- variant_detail · function · L115-L150 — Returns a single variant's metadata, dedupe recipe, and all its fingerprints for pre-publish inspection.
- generate_variants · function · L154-L171 — Validates the target slice output exists, then enqueues an async Celery task to generate variants with the requested count and dedupe config.
- verify_variant · function · L175-L190 — Pre-publish fingerprint recheck that runs the verification task synchronously with a short timeout, failing the request if the variant collides with its group.
- bind_variant_account · function · L194-L216 — Enforces the one-account-per-variant hard constraint by rejecting a bind when the account is already claimed by another variant.
- update_thresholds · function · L220-L239 — Upserts operator-tunable collision thresholds into system_config, merging only provided keys over defaults.
- uuid_of · function · L242-L247 — Parses a string into a UUID, raising a 400 HTTP error on invalid format.
