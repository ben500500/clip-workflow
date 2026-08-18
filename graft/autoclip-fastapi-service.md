---
name: AutoClip FastAPI Service
slug: autoclip-fastapi-service
type: system
sources:
  - path: autoclip/app/main.py
    hash: 4b7a13caea6461ffe50ccd6b015f25216cab71411aad95eb12d3b577a8924e7b
sources_digest: 2d651fbad6c569ac3ee955e8621a44d64352cd638eeea6cd25e021ade8079a34
links:
  - to: autoclip-auxiliary-services
    relation: uses
    description: >-
      Integrates seedance_prompt_generator, publish_material_generator, and
      script_optimizer for auxiliary AI endpoints.
  - to: autoclip-pipeline-stages
    relation: uses
    description: Chains run_step1_outline through run_step4_title in _run_pipeline.
  - to: llm-manager-provider-abstraction
    relation: uses
    description: Uses get_llm_manager for model configuration.
generator:
  version: 1
covers:
  - symbol: ffprobe_duration
    kind: function
    at: 'autoclip/app/main.py:L64-L73'
  - symbol: _update_progress
    kind: function
    at: 'autoclip/app/main.py:L76-L80'
  - symbol: _fail
    kind: function
    at: 'autoclip/app/main.py:L83-L89'
  - symbol: _srt_time_to_seconds
    kind: function
    at: 'autoclip/app/main.py:L94-L105'
  - symbol: _safe_str
    kind: function
    at: 'autoclip/app/main.py:L108-L117'
  - symbol: _to_contract_clips
    kind: function
    at: 'autoclip/app/main.py:L120-L160'
  - symbol: _parse_srt_ts
    kind: function
    at: 'autoclip/app/main.py:L165-L169'
  - symbol: _filter_srt_by_time
    kind: function
    at: 'autoclip/app/main.py:L172-L216'
  - symbol: _run_asr
    kind: function
    at: 'autoclip/app/main.py:L219-L256'
  - symbol: _asr_cache_enabled
    kind: function
    at: 'autoclip/app/main.py:L259-L261'
  - symbol: _asr_cache_dir
    kind: function
    at: 'autoclip/app/main.py:L264-L268'
  - symbol: _asr_cache_key
    kind: function
    at: 'autoclip/app/main.py:L271-L281'
  - symbol: _asr_cache_get
    kind: function
    at: 'autoclip/app/main.py:L284-L294'
  - symbol: _asr_cache_put
    kind: function
    at: 'autoclip/app/main.py:L297-L307'
  - symbol: _run_pipeline
    kind: function
    at: 'autoclip/app/main.py:L310-L403'
  - symbol: health
    kind: function
    at: 'autoclip/app/main.py:L409-L410'
  - symbol: SeedancePromptRequest
    kind: class
    at: 'autoclip/app/main.py:L413-L418'
  - symbol: generate_prompt
    kind: function
    at: 'autoclip/app/main.py:L422-L449'
  - symbol: _current_llm_model
    kind: function
    at: 'autoclip/app/main.py:L452-L458'
  - symbol: SubtitleGenerateRequest
    kind: class
    at: 'autoclip/app/main.py:L461-L470'
  - symbol: generate_subtitle
    kind: function
    at: 'autoclip/app/main.py:L474-L549'
  - symbol: PublishMaterialRequest
    kind: class
    at: 'autoclip/app/main.py:L552-L555'
  - symbol: ScriptOptimizeRequest
    kind: class
    at: 'autoclip/app/main.py:L558-L561'
  - symbol: optimize_script
    kind: function
    at: 'autoclip/app/main.py:L565-L587'
  - symbol: generate_material
    kind: function
    at: 'autoclip/app/main.py:L591-L612'
  - symbol: health_v1
    kind: function
    at: 'autoclip/app/main.py:L617-L618'
  - symbol: ProjectCreate
    kind: class
    at: 'autoclip/app/main.py:L621-L623'
  - symbol: create_project
    kind: function
    at: 'autoclip/app/main.py:L627-L640'
  - symbol: upload
    kind: function
    at: 'autoclip/app/main.py:L644-L658'
  - symbol: PipelineRun
    kind: class
    at: 'autoclip/app/main.py:L661-L674'
  - symbol: pipeline_run
    kind: function
    at: 'autoclip/app/main.py:L678-L697'
  - symbol: progress
    kind: function
    at: 'autoclip/app/main.py:L701-L709'
  - symbol: clips
    kind: function
    at: 'autoclip/app/main.py:L713-L725'
---
<!-- context:generated:start -->
## Summary

The FastAPI entry point exposing REST endpoints for project management, upload, pipeline execution, progress polling, and clip retrieval, plus auxiliary endpoints for subtitles, prompts, script optimization, and publish materials. Runs the pipeline asynchronously via asyncio.to_thread to avoid blocking the event loop. Key design decisions: in-memory project registry (state lost on restart), ASR subtitle caching keyed by video content hash, SRT time-window filtering, and a contract conversion layer mapping internal pipeline output to the external API schema with scores normalized to 0-100.

## Related

- uses [[autoclip-auxiliary-services]] — Integrates seedance_prompt_generator, publish_material_generator, and script_optimizer for auxiliary AI endpoints.
- uses [[autoclip-pipeline-stages]] — Chains run_step1_outline through run_step4_title in _run_pipeline.
- uses [[llm-manager-provider-abstraction]] — Uses get_llm_manager for model configuration.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
