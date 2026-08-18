---
name: Slice Config Tooltip & Watermark Styles
slug: slice-config-tooltip-watermark-styles
type: file
sources:
  - path: frontend/src/utils/sliceConfigTooltip.ts
    hash: 843fcf3added57163116806cef61f0dbe9076b946c30ce2a8bfe96df0107f102
  - path: frontend/src/utils/watermarkStyles.ts
    hash: dd5d77449a6513e938a2133545b42048bd2a4cd994c43c10aba38ac67090b0d7
sources_digest: c67fe74ed83d955a839882c0585e4db93ff0fb3d3c69558ee6428dc41b925271
links:
  - to: shared-frontend-types-formatting
    relation: uses
    description: Consumes SliceTask type and WATERMARK_STYLE_LABEL.
generator:
  version: 1
covers:
  - symbol: buildSliceConfigTooltip
    kind: function
    at: 'frontend/src/utils/sliceConfigTooltip.ts:L6-L91'
  - symbol: WatermarkStyle
    kind: type
    at: 'frontend/src/utils/watermarkStyles.ts:L12-L12'
---
<!-- context:generated:start -->
## Summary

buildSliceConfigTooltip converts a SliceTask's config fields into a human-readable Chinese tooltip for the mode column, and WATERMARK_STYLE_OPTIONS defines six watermark animation styles (scroll, float, wave, bounce, breath, blink). The watermark styles align with the backend engines/slice.py build_watermark_filter function, ensuring frontend selections map to matching server-side rendering logic.

## Related

- uses [[shared-frontend-types-formatting]] — Consumes SliceTask type and WATERMARK_STYLE_LABEL.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
