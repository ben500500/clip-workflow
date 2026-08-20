---
name: frontend reusable UI components
slug: frontend-reusable-ui-components
type: system
sources:
  - path: frontend/src/components/DedupeManualConfig.tsx
    hash: a5edec8a5255d61a0739cbfb23fadfc028d091c2fb3238f2d038de62b69e0ab6
  - path: frontend/src/components/ErrorHint.tsx
    hash: d061b34d299494646551db180aace87d89dc2970f4870fc29e67c7138e2565e5
  - path: frontend/src/components/ResizableTable.tsx
    hash: 140bbf4ccd04d466df86bccb4c56b129a00eb0f5e7e94edd1774749289f66f41
sources_digest: c7945b6221cb50e1cd3e6a31cb8037a37b13ecbb76660ef7458417d3c8153eb3
links:
  - to: dedupe-config-contract
    relation: implements
    description: >-
      DedupeManualConfig mirrors the backend DEDUPE_PRESETS and manual field
      structure.
  - to: frontend-api-layer
    relation: configures
    description: DedupeManualConfig's onChange value is sent via sliceApi.run.
generator:
  version: 1
covers:
  - symbol: DedupeManualConfigValue
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L12-L51'
  - symbol: Props
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L53-L58'
  - symbol: DedupeManualConfig
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L66-L218'
  - symbol: set
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L70-L72'
  - symbol: setDict
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L73-L77'
  - symbol: row
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L79-L87'
  - symbol: renderControl
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L90-L138'
  - symbol: num
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L95-L95'
  - symbol: renderDictGroup
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L141-L179'
  - symbol: ErrorHintProps
    kind: interface
    at: 'frontend/src/components/ErrorHint.tsx:L7-L14'
  - symbol: ErrorHint
    kind: function
    at: 'frontend/src/components/ErrorHint.tsx:L20-L37'
  - symbol: ResizableHeaderCell
    kind: function
    at: 'frontend/src/components/ResizableTable.tsx:L11-L93'
  - symbol: handleMouseDown
    kind: function
    at: 'frontend/src/components/ResizableTable.tsx:L29-L37'
  - symbol: handleMove
    kind: function
    at: 'frontend/src/components/ResizableTable.tsx:L41-L46'
  - symbol: handleUp
    kind: function
    at: 'frontend/src/components/ResizableTable.tsx:L47-L51'
  - symbol: ResizableTableProps
    kind: interface
    at: 'frontend/src/components/ResizableTable.tsx:L95-L100'
  - symbol: ResizableTable
    kind: function
    at: 'frontend/src/components/ResizableTable.tsx:L108-L155'
---
<!-- context:generated:start -->
## Summary

Small reusable presentational components: ErrorHint (compact error indicator with hover tooltip, returns null on empty error), ResizableTable (drag-to-resize column widths via a ResizeContext, enforces 48px min width, returns proper <th> to preserve Ant Design structure), and DedupeManualConfig (controlled form mirroring the backend dedupe parameter contract with preset defaults).

## Related

- implements [[dedupe-config-contract]] — DedupeManualConfig mirrors the backend DEDUPE_PRESETS and manual field structure.
- configures [[frontend-api-layer]] — DedupeManualConfig's onChange value is sent via sliceApi.run.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
