---
name: AutoClip Pipeline Stages
slug: autoclip-pipeline-stages
type: system
sources:
  - path: autoclip/app/pipeline/step1_outline.py
    hash: 01ecd210812021bc2cfabaff194bc5b76f4373ceb8918f1ef78ba6f0e9a63757
  - path: autoclip/app/pipeline/step2_timeline.py
    hash: acaf0cc9e58cb9ce27712ab2def2af955e4ca5f87d6594a31ff61df61fff51b8
  - path: autoclip/app/pipeline/step3_scoring.py
    hash: e4cfd7d90fa74a6625108eb53536ef809f5db30599cb3a8d0d47949b79c3cc85
  - path: autoclip/app/pipeline/step4_title.py
    hash: 4feace7f56c823b0bbd3593155ec9bb061da33718e48f20431aa7a1a2744da36
sources_digest: 6e9fa03934abbf2fcee3e4253d2faf93ff3f451d098311c50a0e49ded0ab550f
links:
  - to: autoclip-fastapi-service
    relation: produces
    description: >-
      main.py's _run_pipeline chains run_step1_outline through run_step4_title
      and converts output to contract clips with scores normalized 0-100.
  - to: llm-manager-provider-abstraction
    relation: uses
    description: >-
      Each step calls LLMClient.call_with_retry with prompts from PROMPT_FILES;
      step3 optionally uses OllamaClient for frame analysis.
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

The four-stage video highlight pipeline: step1 extracts a structural outline from SRT chunks (~30min each), step2 localizes precise time ranges per topic (normalizing SRT to FFmpeg time format, enforcing duration constraints via prompt rewriting), step3 scores clips via LLM (classifying suspense_cut vs full_highlight, backfilling transcripts from chunk files, optionally integrating Ollama frame analysis), step4 generates titles batched by chunk. A critical invariant: LLM failures are re-raised as LLMCallError to halt the pipeline rather than silently producing empty/zero-score results that would be filtered out. Step4 deliberately avoids writing clips_metadata.json (deferred to Step 6) to prevent duplicate saves.

## Related

- produces [[autoclip-fastapi-service]] — main.py's _run_pipeline chains run_step1_outline through run_step4_title and converts output to contract clips with scores normalized 0-100.
- uses [[llm-manager-provider-abstraction]] — Each step calls LLMClient.call_with_retry with prompts from PROMPT_FILES; step3 optionally uses OllamaClient for frame analysis.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
