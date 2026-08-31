---
name: AutoClip Service Entry
slug: autoclip-service-entry
type: system
sources:
  - path: autoclip/app/celery_app.py
    hash: 327c7f58746649147016e97778b9a3c9cab81dc3a61900fb64c5f73210e8dab9
  - path: autoclip/app/main.py
    hash: da9158c536e9c4af5c8f6282c9b7f5551a69bfdb5e6641c411d79bf9d08049c9
  - path: autoclip/app/services/publish_material_generator.py
    hash: 5b813e54c12c0f2a5f9e3727ea3b4fe7302191fb678dc7b916fc88eea8f28620
  - path: autoclip/app/services/script_optimizer.py
    hash: 1d294540710689138f3a2d7eb1d8b1415793485eaad10d448266e92ab043f154
sources_digest: f493b4eab413d81f956b4c159757830030c50aac9bbd7fd3115aae0006352938
links:
  - to: alembic-migration-chain
    relation: uses
    description: >-
      celery_app configures Redis broker/result backend with JSON serialization
      and Asia/Shanghai timezone for async tasks.
  - to: autoclip-pipeline
    relation: uses
    description: >-
      Invokes the four pipeline steps asynchronously and converts their output
      to the external clips contract.
  - to: llm-manager-providers
    relation: uses
    description: >-
      Script optimizer and publish material generator call get_llm_manager;
      publish material enforces a hardcoded compliance rule forbidding real
      names/places/brands.
generator:
  version: 1
covers:
  - symbol: ffprobe_duration
    kind: function
    at: 'autoclip/app/main.py:L63-L72'
  - symbol: _update_progress
    kind: function
    at: 'autoclip/app/main.py:L75-L79'
  - symbol: _fail
    kind: function
    at: 'autoclip/app/main.py:L82-L88'
  - symbol: _srt_time_to_seconds
    kind: function
    at: 'autoclip/app/main.py:L93-L104'
  - symbol: _safe_str
    kind: function
    at: 'autoclip/app/main.py:L107-L116'
  - symbol: _to_contract_clips
    kind: function
    at: 'autoclip/app/main.py:L119-L164'
  - symbol: _parse_srt_ts
    kind: function
    at: 'autoclip/app/main.py:L169-L173'
  - symbol: _filter_srt_by_time
    kind: function
    at: 'autoclip/app/main.py:L176-L220'
  - symbol: _run_asr
    kind: function
    at: 'autoclip/app/main.py:L223-L260'
  - symbol: _asr_cache_enabled
    kind: function
    at: 'autoclip/app/main.py:L263-L265'
  - symbol: _asr_cache_dir
    kind: function
    at: 'autoclip/app/main.py:L268-L272'
  - symbol: _asr_cache_key
    kind: function
    at: 'autoclip/app/main.py:L281-L309'
  - symbol: _asr_cache_get
    kind: function
    at: 'autoclip/app/main.py:L312-L322'
  - symbol: _asr_cache_put
    kind: function
    at: 'autoclip/app/main.py:L325-L335'
  - symbol: _run_pipeline
    kind: function
    at: 'autoclip/app/main.py:L338-L501'
  - symbol: health
    kind: function
    at: 'autoclip/app/main.py:L507-L508'
  - symbol: SeedancePromptRequest
    kind: class
    at: 'autoclip/app/main.py:L511-L516'
  - symbol: generate_prompt
    kind: function
    at: 'autoclip/app/main.py:L520-L547'
  - symbol: _current_llm_model
    kind: function
    at: 'autoclip/app/main.py:L550-L556'
  - symbol: SubtitleGenerateRequest
    kind: class
    at: 'autoclip/app/main.py:L559-L568'
  - symbol: generate_subtitle
    kind: function
    at: 'autoclip/app/main.py:L572-L647'
  - symbol: PublishMaterialRequest
    kind: class
    at: 'autoclip/app/main.py:L650-L653'
  - symbol: ScriptOptimizeRequest
    kind: class
    at: 'autoclip/app/main.py:L656-L659'
  - symbol: optimize_script
    kind: function
    at: 'autoclip/app/main.py:L663-L685'
  - symbol: generate_material
    kind: function
    at: 'autoclip/app/main.py:L689-L710'
  - symbol: health_v1
    kind: function
    at: 'autoclip/app/main.py:L715-L716'
  - symbol: ProjectCreate
    kind: class
    at: 'autoclip/app/main.py:L719-L721'
  - symbol: create_project
    kind: function
    at: 'autoclip/app/main.py:L725-L738'
  - symbol: upload
    kind: function
    at: 'autoclip/app/main.py:L742-L756'
  - symbol: PipelineRun
    kind: class
    at: 'autoclip/app/main.py:L759-L784'
  - symbol: pipeline_run
    kind: function
    at: 'autoclip/app/main.py:L788-L813'
  - symbol: progress
    kind: function
    at: 'autoclip/app/main.py:L817-L825'
  - symbol: clips
    kind: function
    at: 'autoclip/app/main.py:L829-L841'
  - symbol: _split_overlong_clips
    kind: function
    at: 'autoclip/app/main.py:L844-L869'
  - symbol: load_publish_material_template
    kind: function
    at: 'autoclip/app/services/publish_material_generator.py:L27-L32'
  - symbol: _build_input
    kind: function
    at: 'autoclip/app/services/publish_material_generator.py:L35-L46'
  - symbol: generate_publish_material
    kind: function
    at: 'autoclip/app/services/publish_material_generator.py:L49-L80'
  - symbol: _parse_material
    kind: function
    at: 'autoclip/app/services/publish_material_generator.py:L83-L122'
  - symbol: _normalize_material
    kind: function
    at: 'autoclip/app/services/publish_material_generator.py:L125-L155'
  - symbol: _build_input
    kind: function
    at: 'autoclip/app/services/script_optimizer.py:L36-L44'
  - symbol: optimize_script_text
    kind: function
    at: 'autoclip/app/services/script_optimizer.py:L47-L76'
  - symbol: _clean_output
    kind: function
    at: 'autoclip/app/services/script_optimizer.py:L79-L103'
---
<!-- context:generated:start -->
## Summary

FastAPI application exposing project management, upload, pipeline execution, progress polling, and clip retrieval endpoints, plus auxiliary services for subtitle generation, prompt generation, script optimization, and publish material creation. Uses an in-memory project registry (state lost on restart), ASR caching keyed by video content hash, SRT subtitle windowing, and a contract conversion layer mapping internal pipeline output to the external API schema. Supports multiple ASR backends (aliyun_speech, whisper, funasr_local) via env vars.

## Related

- uses [[alembic-migration-chain]] — celery_app configures Redis broker/result backend with JSON serialization and Asia/Shanghai timezone for async tasks.
- uses [[autoclip-pipeline]] — Invokes the four pipeline steps asynchronously and converts their output to the external clips contract.
- uses [[llm-manager-providers]] — Script optimizer and publish material generator call get_llm_manager; publish material enforces a hardcoded compliance rule forbidding real names/places/brands.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
