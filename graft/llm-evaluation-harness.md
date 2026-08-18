---
name: LLM Evaluation Harness
slug: llm-evaluation-harness
type: file
sources:
  - path: eval/grade_highlight_llm.py
    hash: 215139b726eeb7e8fa1609cdd4a9d2b07f59cd06ed29eda301a45c06458224c6
sources_digest: 3c7a99e83bbf9989a12cb3d58a6f339569b6a9813b791665fb0627dc55aa32aa
links:
  - to: clip-workflow-pages
    relation: validates
    description: >-
      Grades the timeline/scoring LLM outputs that drive the autoclip candidates
      reviewed in ClipReview.
generator:
  version: 1
covers:
  - symbol: time_to_seconds
    kind: function
    at: 'eval/grade_highlight_llm.py:L37-L48'
  - symbol: srt_block_end
    kind: function
    at: 'eval/grade_highlight_llm.py:L51-L57'
  - symbol: load_prompt
    kind: function
    at: 'eval/grade_highlight_llm.py:L60-L62'
  - symbol: extract_json
    kind: function
    at: 'eval/grade_highlight_llm.py:L65-L92'
  - symbol: call_llm
    kind: function
    at: 'eval/grade_highlight_llm.py:L98-L123'
  - symbol: iou
    kind: function
    at: 'eval/grade_highlight_llm.py:L129-L132'
  - symbol: grade_timeline
    kind: function
    at: 'eval/grade_highlight_llm.py:L135-L213'
  - symbol: grade_scoring
    kind: function
    at: 'eval/grade_highlight_llm.py:L216-L276'
  - symbol: _is_num
    kind: function
    at: 'eval/grade_highlight_llm.py:L279-L284'
  - symbol: main
    kind: function
    at: 'eval/grade_highlight_llm.py:L290-L348'
---
<!-- context:generated:start -->
## Summary

Lightweight zero-dependency eval harness for the two core AutoClip LLM calls (timeline extraction and scoring). Grades against golden answers computing coverage, IoU, time tolerance (10s), duration violations, endpoint correctness, monotonicity, and reason-length compliance, aggregated into a weighted 0-1 score. --dry-run substitutes golden answers as predictions to validate grading logic without API calls; special handling prevents models from padding SRT block-end timestamps.

## Related

- validates [[clip-workflow-pages]] — Grades the timeline/scoring LLM outputs that drive the autoclip candidates reviewed in ClipReview.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
