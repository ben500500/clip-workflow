---
name: Subtitle Mask Regression
slug: subtitle-mask-regression
type: file
sources:
  - path: engines/tests/test_subtitle_mask_regression.py
    hash: ee02ea97c2a6d408fae44863df66a8fc4356b19b710d224c90f5a935c076edc9
sources_digest: 4d6bb1b72ad28df8a7d0cd7d05037b21d7c9e654ab738a4aaadbf84506856a72
links:
  - to: slicing-engine
    relation: validates
    description: >-
      Tests the dynamic subtitle mask filter functions in slice.py against
      hardcoded thresholds from the PR discussion.
generator:
  version: 1
covers:
  - symbol: _have
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L47-L48'
  - symbol: _have_py
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L51-L56'
  - symbol: make_video
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L59-L83'
  - symbol: make_srt
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L86-L92'
  - symbol: run
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L95-L102'
  - symbol: text_density
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L105-L126'
  - symbol: main
    kind: function
    at: 'engines/tests/test_subtitle_mask_regression.py:L129-L198'
---
<!-- context:generated:start -->
## Summary

Regression test automating PR #148 acceptance criteria for the subtitle-mask feature: synthesizes a golden-subtitle video, then validates dynamic masking regions stay within 9% of screen height and subtitle text density drops at least 60%. Loads slice.py dynamically via importlib, skips gracefully (exit 2) if ffmpeg/cv2/numpy missing, and distinguishes real regressions from environment failures.

## Related

- validates [[slicing-engine]] — Tests the dynamic subtitle mask filter functions in slice.py against hardcoded thresholds from the PR discussion.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
