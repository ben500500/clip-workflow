---
name: AutoClip Pipeline
slug: autoclip-pipeline
type: system
sources:
  - path: autoclip/app/core/shared_config.py
    hash: f28db33ee23172143201f295b48967858444ebd96f11aa956a6eae38f305702e
  - path: autoclip/app/pipeline/step1_outline.py
    hash: 01ecd210812021bc2cfabaff194bc5b76f4373ceb8918f1ef78ba6f0e9a63757
  - path: autoclip/app/pipeline/step2_timeline.py
    hash: acaf0cc9e58cb9ce27712ab2def2af955e4ca5f87d6594a31ff61df61fff51b8
  - path: autoclip/app/pipeline/step3_scoring.py
    hash: e4cfd7d90fa74a6625108eb53536ef809f5db30599cb3a8d0d47949b79c3cc85
  - path: autoclip/app/pipeline/step4_title.py
    hash: 4feace7f56c823b0bbd3593155ec9bb061da33718e48f20431aa7a1a2744da36
sources_digest: f53fff2a6e3010fb95c20784ca5afde1f982d890925ffe00a6e7663e652a4c4d
links:
  - to: autoclip-service-entry
    relation: part_of
    description: >-
      main.py's _run_pipeline chains run_step1_outline → run_step2_timeline →
      run_step3_scoring → run_step4_title.
  - to: autoclip-service-entry
    relation: produces
    description: >-
      Pipeline writes step1_outline.json, step2_timeline.json, scored clips, and
      step4_titles.json consumed by the clips API.
  - to: llm-manager-providers
    relation: uses
    description: >-
      Each step calls LLMClient.call_with_retry with prompts loaded from
      PROMPT_FILES; failures re-raise LLMCallError.
generator:
  version: 1
covers:
  - symbol: OutlineExtractor
    kind: class
    at: 'autoclip/app/pipeline/step1_outline.py:L17-L210'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L20-L42'
  - symbol: extract_outline
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L44-L111'
  - symbol: _save_chunks_to_files
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L113-L126'
  - symbol: _save_srt_chunks
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L128-L138'
  - symbol: _parse_outline_response
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L140-L177'
  - symbol: _merge_outlines
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L179-L188'
  - symbol: save_outline
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L190-L203'
  - symbol: load_outline
    kind: method
    at: 'autoclip/app/pipeline/step1_outline.py:L205-L210'
  - symbol: run_step1_outline
    kind: function
    at: 'autoclip/app/pipeline/step1_outline.py:L212-L227'
  - symbol: TimelineExtractor
    kind: class
    at: 'autoclip/app/pipeline/step2_timeline.py:L18-L421'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L21-L42'
  - symbol: _apply_duration_config
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L44-L110'
  - symbol: extract_timeline
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L112-L291'
  - symbol: _parse_and_validate_response
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L293-L372'
  - symbol: _validate_time_format
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L374-L379'
  - symbol: _convert_time_format
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L381-L387'
  - symbol: _save_debug_response
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L389-L399'
  - symbol: save_timeline
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L401-L414'
  - symbol: load_timeline
    kind: method
    at: 'autoclip/app/pipeline/step2_timeline.py:L416-L421'
  - symbol: run_step2_timeline
    kind: function
    at: 'autoclip/app/pipeline/step2_timeline.py:L423-L444'
  - symbol: ClipScorer
    kind: class
    at: 'autoclip/app/pipeline/step3_scoring.py:L19-L288'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L27-L60'
  - symbol: score_clips
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L62-L109'
  - symbol: _get_llm_evaluation
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L111-L197'
  - symbol: _extract_transcript
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L199-L252'
  - symbol: _truncate_transcript
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L254-L270'
  - symbol: _infer_clip_type
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L272-L282'
  - symbol: save_scores
    kind: method
    at: 'autoclip/app/pipeline/step3_scoring.py:L284-L288'
  - symbol: run_step3_scoring
    kind: function
    at: 'autoclip/app/pipeline/step3_scoring.py:L290-L334'
  - symbol: TitleGenerator
    kind: class
    at: 'autoclip/app/pipeline/step4_title.py:L18-L115'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/pipeline/step4_title.py:L21-L34'
  - symbol: generate_titles
    kind: method
    at: 'autoclip/app/pipeline/step4_title.py:L36-L109'
  - symbol: save_clips_with_titles
    kind: method
    at: 'autoclip/app/pipeline/step4_title.py:L111-L115'
  - symbol: run_step4_title
    kind: function
    at: 'autoclip/app/pipeline/step4_title.py:L117-L159'
---
<!-- context:generated:start -->
## Summary

The four-stage video highlight pipeline: step1 extracts a structural outline from SRT chunks, step2 localizes precise time ranges per topic (with duration_config rewriting the prompt and SRT-to-FFmpeg time normalization), step3 scores clips via LLM with transcript backfilling and optional Ollama frame analysis, step4 generates titles. Steps chain sequentially, persist intermediate JSON artifacts to metadata_dir, and deliberately propagate LLMCallError to fail the pipeline rather than emit empty/zero-score results. MIN_SCORE_THRESHOLD defaults to 0.0 so filtering is deferred to the clips API contract (default 60).

## Related

- part of [[autoclip-service-entry]] — main.py's _run_pipeline chains run_step1_outline → run_step2_timeline → run_step3_scoring → run_step4_title.
- produces [[autoclip-service-entry]] — Pipeline writes step1_outline.json, step2_timeline.json, scored clips, and step4_titles.json consumed by the clips API.
- uses [[llm-manager-providers]] — Each step calls LLMClient.call_with_retry with prompts loaded from PROMPT_FILES; failures re-raise LLMCallError.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
