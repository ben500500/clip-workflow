---
name: Data Import & Template Workflow
slug: data-import-template-workflow
type: system
sources:
  - path: frontend/src/pages/DataImport.tsx
    hash: e4878acff05eb6067d0cea018315968ec441b2c4947d778725e14c52c00874e5
sources_digest: 1e249a50a83c3cf9ee5dc48115db1b4985cefb2ffac63fa5121ab5ed68d75396
links:
  - to: shared-frontend-types-formatting
    relation: uses
    description: >-
      Uses PlatformDetectResult and ImportHistoryRecord types and formatDate
      utility.
generator:
  version: 1
covers:
  - symbol: SmartImportPanel
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L15-L174'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L22-L41'
  - symbol: handleConfirm
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L43-L60'
  - symbol: ImportPanelProps
    kind: interface
    at: 'frontend/src/pages/DataImport.tsx:L178-L183'
  - symbol: ImportPanel
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L185-L249'
  - symbol: ImportHistoryPanel
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L253-L278'
  - symbol: DataImport
    kind: function
    at: 'frontend/src/pages/DataImport.tsx:L282-L342'
---
<!-- context:generated:start -->
## Summary

The data import page with three tabs: smart import (auto platform detection with manual one-to-one field mapping enforced by removing conflicting assignments), standard template import via reusable ImportPanel cards, and import history. The smart flow keeps the uploaded file in state until confirmation so cancellation is possible.

## Related

- uses [[shared-frontend-types-formatting]] — Uses PlatformDetectResult and ImportHistoryRecord types and formatDate utility.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
