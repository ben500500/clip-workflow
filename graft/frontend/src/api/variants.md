# frontend/src/api/variants.ts · [[frontend-api-client-layer]]

API client module for variant management, exposing endpoints to fetch the variant matrix, inspect variant details, generate new variants, verify safety, bind variants to accounts, and update dedupe thresholds.

- VariantFingerprint · interface · L3-L7 — Data holder describing a single fingerprint (algorithm, hash, duration) used to identify a variant.
- VariantMatrixItem · interface · L9-L23 — Data holder describing one variant row in the matrix, including its status, distance metrics, and collision flags.
- VariantGroup · interface · L25-L31 — Data holder grouping a base output with its set of variant matrix items.
- VariantMatrix · interface · L33-L36 — Data holder for the full variant matrix: variant groups plus the dedupe thresholds used.
- VariantDetail · interface · L38-L42 — Data holder extending a matrix item with group id, dedupe config, and fingerprints for a single variant's detail view.
- VariantVerifyResult · interface · L44-L48 — Data holder for a verification outcome, reporting whether a variant is safe along with distance metrics and a reason.
