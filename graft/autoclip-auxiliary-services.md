---
name: AutoClip Auxiliary Services
slug: autoclip-auxiliary-services
type: system
sources:
  - path: autoclip/app/services/publish_material_generator.py
    hash: 5b813e54c12c0f2a5f9e3727ea3b4fe7302191fb678dc7b916fc88eea8f28620
  - path: autoclip/app/services/script_optimizer.py
    hash: 1d294540710689138f3a2d7eb1d8b1415793485eaad10d448266e92ab043f154
  - path: autoclip/app/services/seedance_prompt_generator.py
    hash: 66e3b4c78cc5d3e22fa77e143faac2cc4859d95c3952f1132c07e2ec31f71a73
sources_digest: e17b1099a6ab7c1901832417882a8176e9f2a740ea4f7a5a518507a7d481a1c8
links:
  - to: autoclip-fastapi-service
    relation: produces
    description: >-
      main.py exposes endpoints that invoke these generators for prompt
      generation, publish material creation, and script optimization.
  - to: llm-manager-provider-abstraction
    relation: uses
    description: All three services call get_llm_manager for model invocation with retry.
generator:
  version: 1
covers:
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
---
<!-- context:generated:start -->
## Summary

Three standalone AI feature services: seedance_prompt_generator produces three prompt versions (fixed short template, fixed long template with timing/cinematography rules, and AI seven-section prompt) with duration normalization to 3-300s and a compliance footer; publish_material_generator produces short titles/captions/hashtags/comments with a hardcoded rule forbidding real names/places/brands; script_optimizer rewrites scripts preserving plot mainline while enforcing strict formatting (【角色名】dialogue, （画外音旁白）narration) and 150-500 char output. All three reuse the shared LLM manager and share the compliance constraint.

## Related

- produces [[autoclip-fastapi-service]] — main.py exposes endpoints that invoke these generators for prompt generation, publish material creation, and script optimization.
- uses [[llm-manager-provider-abstraction]] — All three services call get_llm_manager for model invocation with retry.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
