---
name: seedance_wm mask generation
slug: seedance-wm-mask-generation
type: file
sources:
  - path: engines/seedance_wm/mask.py
    hash: 96da5961936e4bed860239356372efc91153a364debab215aab2c88065a6cb78
sources_digest: edbd51d44dc8ab5d1091a6325585def207cf5194786440079bdc623697af8285
links:
  - to: seedance-wm-engine
    relation: part_of
    description: >-
      Consumed by pipeline.py as stage 3; its output directory and mask file
      list feed the inpaint stage.
  - to: seedance-wm-logging-convention
    relation: uses
    description: Uses get_logger from log.py for structured logging.
generator:
  version: 1
covers:
  - symbol: generate_mask_sequence
    kind: function
    at: 'engines/seedance_wm/mask.py:L19-L77'
---
<!-- context:generated:start -->
## Summary

Stage 3 of the pipeline: converts one or more watermark bboxes into a single merged per-frame uint8 mask PNG sequence (white=watermark, black=background), expanding each box by a configurable margin (default 5px) to give the LaMa inpainting model repair room. Validates boxes are non-empty and within frame bounds. Merging all boxes into one mask per frame is a deliberate choice so downstream inpainting sees the full watermark region at once.

## Related

- part of [[seedance-wm-engine]] — Consumed by pipeline.py as stage 3; its output directory and mask file list feed the inpaint stage.
- uses [[seedance-wm-logging-convention]] — Uses get_logger from log.py for structured logging.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
