---
name: Frontend Shared UI Components
slug: frontend-shared-ui-components
type: system
sources:
  - path: frontend/src/components/DedupeManualConfig.tsx
    hash: 6bf98508e17a711ac02a5dac2e676c8f6d48ff443d35f011d6a41402e1e765a8
  - path: frontend/src/components/ErrorHint.tsx
    hash: d061b34d299494646551db180aace87d89dc2970f4870fc29e67c7138e2565e5
  - path: frontend/src/components/ResizableTable.tsx
    hash: 140bbf4ccd04d466df86bccb4c56b129a00eb0f5e7e94edd1774749289f66f41
sources_digest: 3cfd2f6ed0cbc9902ea291606f0f21b4cf78632fe6c298804b32bbcf0d6aa6a4
links:
  - to: slicing-engine
    relation: implements
    description: >-
      DedupeManualConfig mirrors the manual dedupe config structure and presets
      from engines/slice.py.
generator:
  version: 1
covers:
  - symbol: DedupeManualConfigValue
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L10-L34'
  - symbol: Props
    kind: interface
    at: 'frontend/src/components/DedupeManualConfig.tsx:L124-L129'
  - symbol: DedupeManualConfig
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L132-L231'
  - symbol: set
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L135-L137'
  - symbol: setWm
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L138-L142'
  - symbol: row
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L145-L153'
  - symbol: num
    kind: function
    at: 'frontend/src/components/DedupeManualConfig.tsx:L155-L155'
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

Reusable presentational components: ErrorHint (compact error indicator with hover tooltip, returns null on empty error), ResizableTable (drag-to-resize column widths via ResizeContext, enforces 48px min width and returns a proper <th> to preserve Ant Design structure), and DedupeManualConfig (controlled form mirroring the engine's _resolve_dedupe_config manual field, with DEDUPE_PRESETS constant mirroring engines/slice.py to show effective defaults).

## Related

- implements [[slicing-engine]] — DedupeManualConfig mirrors the manual dedupe config structure and presets from engines/slice.py.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
