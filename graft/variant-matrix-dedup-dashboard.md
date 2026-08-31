---
name: Variant Matrix Dedup Dashboard
slug: variant-matrix-dedup-dashboard
type: system
sources:
  - path: frontend/src/pages/VariantMatrix.tsx
    hash: 49538da9a658de7e58deb49660344014da420df48d27a01ada42182d8b21a2c4
sources_digest: e9426c90a5e4f8dff2c69f5dedaf2a0b636ba4111228baeaf5bfa782b27b0de9
links: []
generator:
  version: 1
covers:
  - symbol: FilterKey
    kind: type
    at: 'frontend/src/pages/VariantMatrix.tsx:L37-L37'
  - symbol: VariantMatrix
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L45-L558'
  - symbol: handleVerify
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L140-L151'
  - symbol: openBind
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L153-L156'
  - symbol: handleBind
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L158-L171'
  - symbol: openThreshold
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L173-L176'
  - symbol: handleSaveThreshold
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L178-L190'
  - symbol: handleDownload
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L193-L204'
  - symbol: handleDownloadGroup
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L207-L236'
  - symbol: handleDeleteVariant
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L239-L247'
  - symbol: handleDeleteGroup
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L250-L258'
  - symbol: handleCleanupStuck
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L261-L276'
  - symbol: DistanceCell
    kind: function
    at: 'frontend/src/pages/VariantMatrix.tsx:L560-L586'
---
<!-- context:generated:start -->
## Summary

VariantMatrix page renders a dedup dashboard showing groups of generated video variants with fingerprint distances (phash, audio, seg, combined) and collision status. Enforces a one-account-per-variant binding rule to prevent platform detection of duplicate content, color-codes distance cells against operator-adjustable thresholds, and lets operators verify safety and bind variants to accounts.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
