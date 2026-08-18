# frontend/src/pages/VariantMatrix.tsx · [[variant-matrix-dedup-dashboard]]

- VariantMatrix · function · L35-L310 — Main dashboard component that fetches variant groups and thresholds, renders per-group tables with distance/collision columns, and hosts bind/threshold modals.
- handleVerify · function · L76-L87 — Triggers a pre-publish fingerprint re-verification for a variant and reports whether it is safe to publish.
- openBind · function · L89-L92 — Opens the account-binding modal pre-populated with the variant's current account.
- handleBind · function · L94-L107 — Binds a video account to a variant (one account per variant) and refreshes the matrix.
- openThreshold · function · L109-L112 — Opens the collision-threshold config modal seeded with current threshold values.
- handleSaveThreshold · function · L114-L126 — Persists updated collision-detection thresholds via the API and applies the returned values.
- DistanceCell · function · L312-L324 — Renders a fingerprint distance value colored green when above threshold (safe) or red when below (collision risk).
