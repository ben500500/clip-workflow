---
name: LLM Manager & Providers
slug: llm-manager-providers
type: system
sources:
  - path: autoclip/app/core/llm_manager.py
    hash: 5fdc899a4e2ceef373e16eb1ca87c607710d3b9c9d453508da91c03b49e90381
  - path: autoclip/app/core/llm_providers.py
    hash: 49d405f096e6b17de3dac0bad43b49d9e91ba6cb8b4972fd21686d2b12f4289b
  - path: autoclip/app/core/ollama_client.py
    hash: 9271f9c4a550785b8ff22a5c7d47ca0e92a0b4fe4d6dfece3c5a9d6535649e55
sources_digest: eb91fc9f52c582add3b41d131364b8b779eaafdb00e9ecc7ee694a41f04bc6c5
links:
  - to: autoclip-pipeline
    relation: uses
    description: >-
      All four pipeline steps and the publish-material/script-optimizer services
      call get_llm_manager for model invocation; LLMCallError propagates to halt
      the pipeline.
  - to: autoclip-service-entry
    relation: uses
    description: >-
      main.py initializes the LLM manager singleton and uses it for all
      model-backed endpoints.
generator:
  version: 1
covers:
  - symbol: LLMManager
    kind: class
    at: 'autoclip/app/core/llm_manager.py:L23-L277'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L26-L30'
  - symbol: _get_default_settings_file
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L32-L38'
  - symbol: _load_settings
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L40-L79'
  - symbol: _save_settings
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L81-L89'
  - symbol: _initialize_provider
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L91-L107'
  - symbol: _get_api_key_for_provider
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L109-L143'
  - symbol: update_settings
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L145-L149'
  - symbol: set_provider
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L151-L174'
  - symbol: call
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L176-L185'
  - symbol: call_with_retry
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L187-L201'
  - symbol: test_provider_connection
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L203-L210'
  - symbol: set_runtime_model
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L212-L233'
  - symbol: get_current_provider_info
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L235-L246'
  - symbol: _get_provider_display_name
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L248-L255'
  - symbol: get_all_available_models
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L257-L270'
  - symbol: parse_json_response
    kind: method
    at: 'autoclip/app/core/llm_manager.py:L272-L277'
  - symbol: get_llm_manager
    kind: function
    at: 'autoclip/app/core/llm_manager.py:L284-L289'
  - symbol: initialize_llm_manager
    kind: function
    at: 'autoclip/app/core/llm_manager.py:L292-L296'
  - symbol: ProviderType
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L16-L21'
  - symbol: ModelInfo
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L24-L31'
  - symbol: LLMResponse
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L34-L39'
  - symbol: LLMProvider
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L41-L91'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L44-L47'
  - symbol: call
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L50-L62'
  - symbol: test_connection
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L65-L72'
  - symbol: get_available_models
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L75-L82'
  - symbol: _build_full_input
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L84-L91'
  - symbol: DashScopeProvider
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L93-L252'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L96-L110'
  - symbol: call
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L112-L194'
  - symbol: test_connection
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L196-L226'
  - symbol: get_available_models
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L228-L252'
  - symbol: OpenAIProvider
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L254-L342'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L257-L268'
  - symbol: call
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L270-L297'
  - symbol: test_connection
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L299-L316'
  - symbol: get_available_models
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L318-L342'
  - symbol: GeminiProvider
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L344-L422'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L347-L355'
  - symbol: call
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L357-L383'
  - symbol: test_connection
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L385-L396'
  - symbol: get_available_models
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L398-L422'
  - symbol: SiliconFlowProvider
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L424-L518'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L427-L429'
  - symbol: call
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L431-L472'
  - symbol: test_connection
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L474-L485'
  - symbol: get_available_models
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L487-L518'
  - symbol: LLMProviderFactory
    kind: class
    at: 'autoclip/app/core/llm_providers.py:L520-L551'
  - symbol: create_provider
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L531-L537'
  - symbol: get_all_available_models
    kind: method
    at: 'autoclip/app/core/llm_providers.py:L540-L551'
  - symbol: OllamaClient
    kind: class
    at: 'autoclip/app/core/ollama_client.py:L32-L142'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/core/ollama_client.py:L35-L37'
  - symbol: available
    kind: method
    at: 'autoclip/app/core/ollama_client.py:L40-L52'
  - symbol: describe_image
    kind: method
    at: 'autoclip/app/core/ollama_client.py:L54-L104'
  - symbol: _parse_json
    kind: method
    at: 'autoclip/app/core/ollama_client.py:L107-L142'
  - symbol: get_ollama_client
    kind: function
    at: 'autoclip/app/core/ollama_client.py:L149-L154'
---
<!-- context:generated:start -->
## Summary

Central LLM abstraction layer: LLMManager orchestrates provider selection and invocation with persistent settings (JSON file) separated from ephemeral runtime model overrides, delegating to LLMProviderFactory/LLMProvider implementations for DashScope, OpenAI, Gemini, and SiliconFlow. Includes call_with_retry with exponential backoff (3 attempts, skipping retries on ValueError) and a legacy parse_json_response bridge. OllamaClient is a separate local-vision path for frame analysis, deliberately isolated from the online LLM path and degrading silently to None on failure.

## Related

- uses [[autoclip-pipeline]] — All four pipeline steps and the publish-material/script-optimizer services call get_llm_manager for model invocation; LLMCallError propagates to halt the pipeline.
- uses [[autoclip-service-entry]] — main.py initializes the LLM manager singleton and uses it for all model-backed endpoints.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
