---
name: Seedance Prompt Generation
slug: seedance-prompt-generation
type: system
sources:
  - path: autoclip/app/services/seedance_prompt_generator.py
    hash: 66e3b4c78cc5d3e22fa77e143faac2cc4859d95c3952f1132c07e2ec31f71a73
  - path: backend/app/api/shortdrama.py
    hash: b3c29bd20822e3feaf1424bc2a2ef465b17ff351d4b33b1b3899d6b32ee9c969
sources_digest: c901f710fb636528d6a1b2973c7ca557711b68b17838134a894c52ddbfaa0804
links:
  - to: llm-manager-client-compatibility
    relation: uses
    description: >-
      seedance_prompt_generator uses LLMManager for AI prompt generation;
      llm_client.py wraps it for legacy callers.
  - to: publish-material-generation
    relation: uses
    description: >-
      shortdrama.py and publish_material.py both call the external AutoClip
      service for prompt/material generation.
generator:
  version: 1
covers:
  - symbol: build_short_prompt
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L69-L80'
  - symbol: build_long_prompt
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L83-L93'
  - symbol: load_seedance_template
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L96-L101'
  - symbol: _build_input
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L104-L116'
  - symbol: generate_seedance_prompt
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L119-L137'
  - symbol: generate_prompt_versions
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L140-L195'
  - symbol: _normalize_duration
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L198-L210'
  - symbol: _ensure_compliance_footer
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L221-L228'
  - symbol: _extract_prompt_text
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L231-L258'
  - symbol: _dict_to_prompt
    kind: function
    at: 'autoclip/app/services/seedance_prompt_generator.py:L261-L276'
  - symbol: _load_prompt_templates
    kind: function
    at: 'backend/app/api/shortdrama.py:L83-L95'
  - symbol: _save_prompt_templates
    kind: function
    at: 'backend/app/api/shortdrama.py:L98-L113'
  - symbol: PromptGenerateRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L121-L134'
  - symbol: PromptTemplatesResponse
    kind: class
    at: 'backend/app/api/shortdrama.py:L137-L140'
  - symbol: ScriptOptimizeRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L143-L149'
  - symbol: ScriptOptimizeResponse
    kind: class
    at: 'backend/app/api/shortdrama.py:L152-L155'
  - symbol: PromptGenerateResponse
    kind: class
    at: 'backend/app/api/shortdrama.py:L158-L164'
  - symbol: PromptRecordItem
    kind: class
    at: 'backend/app/api/shortdrama.py:L167-L207'
  - symbol: _serialize_record
    kind: function
    at: 'backend/app/api/shortdrama.py:L215-L254'
  - symbol: generate_shortdrama_prompt
    kind: function
    at: 'backend/app/api/shortdrama.py:L263-L355'
  - symbol: _normalize_duration
    kind: function
    at: 'backend/app/api/shortdrama.py:L358-L366'
  - symbol: optimize_shortdrama_script
    kind: function
    at: 'backend/app/api/shortdrama.py:L370-L416'
  - symbol: list_shortdrama_prompts
    kind: function
    at: 'backend/app/api/shortdrama.py:L420-L441'
  - symbol: get_shortdrama_prompt
    kind: function
    at: 'backend/app/api/shortdrama.py:L445-L456'
  - symbol: delete_shortdrama_prompt
    kind: function
    at: 'backend/app/api/shortdrama.py:L460-L475'
  - symbol: _get_record_or_404
    kind: function
    at: 'backend/app/api/shortdrama.py:L478-L489'
  - symbol: upload_shortdrama_video
    kind: function
    at: 'backend/app/api/shortdrama.py:L498-L571'
  - symbol: get_shortdrama_video
    kind: function
    at: 'backend/app/api/shortdrama.py:L575-L592'
  - symbol: delete_shortdrama_video
    kind: function
    at: 'backend/app/api/shortdrama.py:L596-L615'
  - symbol: import_shortdrama_video_to_watermark
    kind: function
    at: 'backend/app/api/shortdrama.py:L619-L643'
  - symbol: get_shortdrama_prompt_templates
    kind: function
    at: 'backend/app/api/shortdrama.py:L652-L664'
  - symbol: PromptTemplatesUpdateRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L667-L669'
  - symbol: update_shortdrama_prompt_templates
    kind: function
    at: 'backend/app/api/shortdrama.py:L673-L697'
  - symbol: DoubaoGenerateRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L716-L720'
  - symbol: DoubaoGenerateResponse
    kind: class
    at: 'backend/app/api/shortdrama.py:L723-L726'
  - symbol: DoubaoRewriteConfirmRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L729-L731'
  - symbol: start_doubao_generate
    kind: function
    at: 'backend/app/api/shortdrama.py:L735-L780'
  - symbol: confirm_doubao_rewrite
    kind: function
    at: 'backend/app/api/shortdrama.py:L784-L832'
  - symbol: cancel_doubao_generate
    kind: function
    at: 'backend/app/api/shortdrama.py:L836-L860'
  - symbol: get_doubao_status
    kind: function
    at: 'backend/app/api/shortdrama.py:L864-L875'
  - symbol: get_prompt_default_duration
    kind: function
    at: 'backend/app/api/shortdrama.py:L884-L899'
  - symbol: PromptDefaultDurationRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L902-L904'
  - symbol: update_prompt_default_duration
    kind: function
    at: 'backend/app/api/shortdrama.py:L908-L918'
  - symbol: get_doubao_account_type
    kind: function
    at: 'backend/app/api/shortdrama.py:L922-L932'
  - symbol: update_doubao_account_type
    kind: function
    at: 'backend/app/api/shortdrama.py:L936-L950'
  - symbol: switch_doubao_account
    kind: function
    at: 'backend/app/api/shortdrama.py:L954-L973'
  - symbol: get_doubao_config
    kind: function
    at: 'backend/app/api/shortdrama.py:L977-L982'
  - symbol: _load_doubao_limits
    kind: function
    at: 'backend/app/api/shortdrama.py:L985-L995'
  - symbol: SeedanceGenerateRequest
    kind: class
    at: 'backend/app/api/shortdrama.py:L1015-L1019'
  - symbol: SeedanceGenerateResponse
    kind: class
    at: 'backend/app/api/shortdrama.py:L1022-L1025'
  - symbol: _load_seedance_config
    kind: function
    at: 'backend/app/api/shortdrama.py:L1028-L1037'
  - symbol: _require_seedance_enabled
    kind: function
    at: 'backend/app/api/shortdrama.py:L1040-L1048'
  - symbol: get_seedance_config
    kind: function
    at: 'backend/app/api/shortdrama.py:L1052-L1064'
  - symbol: start_seedance_generate
    kind: function
    at: 'backend/app/api/shortdrama.py:L1068-L1109'
  - symbol: cancel_seedance_generate
    kind: function
    at: 'backend/app/api/shortdrama.py:L1113-L1149'
  - symbol: get_seedance_status
    kind: function
    at: 'backend/app/api/shortdrama.py:L1153-L1164'
---
<!-- context:generated:start -->
## Summary

Generates Seedance short-drama video prompts from user script text, producing three versions (fixed short template, fixed long template, AI-generated seven-section prompt). Reuses the shared LLMManager/DASHSCOPE config, normalizes duration to 3-300s, robustly parses LLM responses (JSON wrappers, markdown fences, dict fallbacks), and appends a compliance footer banning real names/brands. The backend shortdrama.py API delegates to this external service via HTTP.

## Related

- uses [[llm-manager-client-compatibility]] — seedance_prompt_generator uses LLMManager for AI prompt generation; llm_client.py wraps it for legacy callers.
- uses [[publish-material-generation]] — shortdrama.py and publish_material.py both call the external AutoClip service for prompt/material generation.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
