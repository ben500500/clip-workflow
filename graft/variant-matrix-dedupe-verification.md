---
name: Variant Matrix & Dedupe Verification
slug: variant-matrix-dedupe-verification
type: system
sources:
  - path: frontend/src/pages/VariantMatrix.tsx
    hash: 49538da9a658de7e58deb49660344014da420df48d27a01ada42182d8b21a2c4
sources_digest: e9426c90a5e4f8dff2c69f5dedaf2a0b636ba4111228baeaf5bfa782b27b0de9
links:
  - to: frontend-api-layer
    relation: uses
    description: >-
      Uses variantsApi (matrix, verify, bind, updateThresholds) and
      publishApi.getVideoAccounts.
generator:
  version: 1
covers:
  - symbol: VariantMatrix
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L35-L310'
  - symbol: handleVerify
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L76-L87'
  - symbol: openBind
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L89-L92'
  - symbol: handleBind
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L94-L107'
  - symbol: openThreshold
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L109-L112'
  - symbol: handleSaveThreshold
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L114-L126'
  - symbol: DistanceCell
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L312-L324'
---
<!-- context:generated:start -->
## Summary

VariantMatrix renders a dedupe variant matrix with fingerprint distances (phash, audio, seg, combined) and collision status, enforcing a one-account-per-variant binding rule to prevent platform detection of duplicate content, with operator-adjustable collision thresholds and color-coded distance cells.

## Related

- uses [[frontend-api-layer]] — Uses variantsApi (matrix, verify, bind, updateThresholds) and publishApi.getVideoAccounts.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
