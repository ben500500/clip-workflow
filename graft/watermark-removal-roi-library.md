---
name: Watermark Removal ROI Library
slug: watermark-removal-roi-library
type: system
sources:
  - path: engines/remove_mask_rois.py
    hash: ad940041ad8d0a7124334facf4c8b893bdf5f4ca1adaea6bd9b844aed7a69e40
sources_digest: bdb4b636a97592e0a2730aa86cd9e22618034b19e02d6b98b58cae745475bba6
links:
  - to: opencv-watermark-remover
    relation: uses
    description: >-
      Also consumed by remove_mask engine and seedance_wm/seedance/remove_ai
      engines
  - to: seedance-watermark-removal-engine
    relation: uses
    description: Consumed as fallback when no manual region is specified
generator:
  version: 1
covers:
  - symbol: _norm_source_name
    kind: function
    at: 'engines/remove_mask_rois.py:L108-L110'
  - symbol: match_rois
    kind: function
    at: 'engines/remove_mask_rois.py:L113-L132'
  - symbol: resolve_rois
    kind: function
    at: 'engines/remove_mask_rois.py:L135-L147'
  - symbol: build_mask
    kind: function
    at: 'engines/remove_mask_rois.py:L150-L162'
  - symbol: rois_to_bboxes
    kind: function
    at: 'engines/remove_mask_rois.py:L165-L180'
  - symbol: probe_video_size
    kind: function
    at: 'engines/remove_mask_rois.py:L183-L195'
---
<!-- context:generated:start -->
## Summary

Shared watermark-removal ROI experience library derived from empirical analysis of Seedance video watermarks. Exports hardcoded ROI tables (VIDEO_ROIS_SMALL/LARGE) keyed by video identifiers in (y0,y1,x0,x1) format relative to a 1280×720 reference frame, with fuzzy filename matching, priority resolution (manual > filename > generic defaults), and proportional scaling to actual video dimensions. Dual small/large scopes balance coverage against over-removal; per-video calibration avoids covering moving subjects.

## Related

- uses [[opencv-watermark-remover]] — Also consumed by remove_mask engine and seedance_wm/seedance/remove_ai engines
- uses [[seedance-watermark-removal-engine]] — Consumed as fallback when no manual region is specified
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
