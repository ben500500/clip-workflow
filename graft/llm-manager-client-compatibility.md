---
name: LLM Manager & Client Compatibility
slug: llm-manager-client-compatibility
type: system
sources:
  - path: autoclip/app/utils/llm_client.py
    hash: e1353d4dde15fd1f5c9bf968fe965c86d71b3a61d4c88724229bb1f6b46d9cf7
sources_digest: 3b3af92b4f0577acae68e065904f7a2a91b5af46d88fae8b5ae6e46b0a8c9a44
links:
  - to: frame-analysis
    relation: uses
    description: >-
      frame_analyzer uses get_ollama_client from core.ollama_client, a separate
      local-model path.
  - to: seedance-prompt-generation
    relation: uses
    description: seedance_prompt_generator reuses LLMManager from core.llm_manager.
generator:
  version: 1
covers:
  - symbol: LLMCallError
    kind: class
    at: 'autoclip/app/utils/llm_client.py:L38-L43'
  - symbol: LLMClient
    kind: class
    at: 'autoclip/app/utils/llm_client.py:L46-L280'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L49-L51'
  - symbol: call
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L53-L68'
  - symbol: call_with_retry
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L70-L86'
  - symbol: _preprocess_llm_response
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L88-L112'
  - symbol: _auto_fix_response
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L114-L125'
  - symbol: _validate_json_structure
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L127-L152'
  - symbol: parse_json_response
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L154-L276'
  - symbol: sanitize_string
    kind: function
    at: 'autoclip/app/utils/llm_client.py:L165-L173'
  - symbol: fix_common_json_errors
    kind: function
    at: 'autoclip/app/utils/llm_client.py:L175-L219'
  - symbol: get_current_provider_info
    kind: method
    at: 'autoclip/app/utils/llm_client.py:L278-L280'
---
<!-- context:generated:start -->
## Summary

Central LLM invocation layer. LLMManager in core.llm_manager is the canonical interface; llm_client.py is a legacy compatibility wrapper exposing LLMClient with multi-layer JSON parsing fallback (strip prefixes, markdown fences, regex extraction, fix_common_json_errors) and structural validation requiring list-of-dicts with outline/start_time/end_time. LLMCallError surfaces model failures so runs end in a failed state rather than silently swallowing errors.

## Related

- uses [[frame-analysis]] — frame_analyzer uses get_ollama_client from core.ollama_client, a separate local-model path.
- uses [[seedance-prompt-generation]] — seedance_prompt_generator reuses LLMManager from core.llm_manager.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
