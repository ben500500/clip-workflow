# frontend/src/pages/VariantMatrix.tsx · [[variant-matrix-dedup-dashboard]]

- FilterKey · type · L37-L37 — type FilterKey = 'all' | 'collision' | 'unbound';
- VariantMatrix · function · L45-L558 — Main dashboard component that fetches variant groups and thresholds, renders per-group tables with distance/collision columns, and hosts bind/threshold modals.
- handleVerify · function · L140-L151 — Triggers a pre-publish fingerprint re-verification for a variant and reports whether it is safe to publish.
- openBind · function · L153-L156 — Opens the account-binding modal pre-populated with the variant's current account.
- handleBind · function · L158-L171 — Binds a video account to a variant (one account per variant) and refreshes the matrix.
- openThreshold · function · L173-L176 — Opens the collision-threshold config modal seeded with current threshold values.
- handleSaveThreshold · function · L178-L190 — Persists updated collision-detection thresholds via the API and applies the returned values.
- handleDownload · function · L193-L204 — handleDownload = async (v: VariantMatrixItem)
- handleDownloadGroup · function · L207-L236 — handleDownloadGroup = async (g: VariantGroup)
- handleDeleteVariant · function · L239-L247 — handleDeleteVariant = async (v: VariantMatrixItem)
- handleDeleteGroup · function · L250-L258 — handleDeleteGroup = async (g: VariantGroup)
- handleCleanupStuck · function · L261-L276 — handleCleanupStuck = async ()
- DistanceCell · function · L560-L586 — Renders a fingerprint distance value colored green when above threshold (safe) or red when below (collision risk).
