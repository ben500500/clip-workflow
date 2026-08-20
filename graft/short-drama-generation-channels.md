---
name: Short-Drama Generation Channels
slug: short-drama-generation-channels
type: system
sources:
  - path: backend/app/models/shortdrama.py
    hash: 638627f330df49bff2aa249f95703cc9af781a7c04a731762f63c4e393922488
  - path: backend/app/services/ark_client.py
    hash: fd517b36b8373e751a93e8c95d4a56a14cca1e85c4ba70341b55a5359cb78997
  - path: backend/app/services/doubao_service.py
    hash: 2ccd27cc036a39262908b281436bd778609f1e8f9e9e8314b4cea945cf28b706
sources_digest: cca8ff3a8c276c04178cf964abe555b020ce8cf36a5cb0abe2d85bfd4e3ce8fc
links:
  - to: celery-task-layer
    relation: produces
    description: doubao_generate_task and seedance_generate_task drive these services
  - to: orm-model-registry
    relation: uses
    description: Persists to ShortdramaPrompt records
generator:
  version: 1
covers:
  - symbol: ShortdramaPrompt
    kind: class
    at: 'backend/app/models/shortdrama.py:L26-L100'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/shortdrama.py:L99-L100'
  - symbol: WatermarkTask
    kind: class
    at: 'backend/app/models/shortdrama.py:L103-L131'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/shortdrama.py:L130-L131'
  - symbol: WatermarkVideo
    kind: class
    at: 'backend/app/models/shortdrama.py:L134-L161'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/shortdrama.py:L160-L161'
  - symbol: _normalize_bool
    kind: function
    at: 'backend/app/services/ark_client.py:L56-L64'
  - symbol: SeedanceConfig
    kind: class
    at: 'backend/app/services/ark_client.py:L67-L127'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/ark_client.py:L86-L107'
  - symbol: to_public_dict
    kind: method
    at: 'backend/app/services/ark_client.py:L109-L121'
  - symbol: validate
    kind: method
    at: 'backend/app/services/ark_client.py:L123-L127'
  - symbol: load_seedance_config
    kind: function
    at: 'backend/app/services/ark_client.py:L130-L182'
  - symbol: SeedanceClient
    kind: class
    at: 'backend/app/services/ark_client.py:L185-L298'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/ark_client.py:L188-L189'
  - symbol: _base
    kind: method
    at: 'backend/app/services/ark_client.py:L191-L192'
  - symbol: _headers
    kind: method
    at: 'backend/app/services/ark_client.py:L194-L198'
  - symbol: _task_url
    kind: method
    at: 'backend/app/services/ark_client.py:L200-L201'
  - symbol: _cancel_url
    kind: method
    at: 'backend/app/services/ark_client.py:L203-L204'
  - symbol: create_task
    kind: method
    at: 'backend/app/services/ark_client.py:L210-L252'
  - symbol: get_task
    kind: method
    at: 'backend/app/services/ark_client.py:L258-L283'
  - symbol: cancel_task
    kind: method
    at: 'backend/app/services/ark_client.py:L289-L298'
  - symbol: resolve_duration_policy
    kind: function
    at: 'backend/app/services/ark_client.py:L301-L316'
  - symbol: poll_task
    kind: function
    at: 'backend/app/services/ark_client.py:L319-L379'
  - symbol: NeedLoginError
    kind: class
    at: 'backend/app/services/doubao_service.py:L47-L48'
  - symbol: get_account_limits
    kind: function
    at: 'backend/app/services/doubao_service.py:L51-L59'
  - symbol: DoubaoGenerator
    kind: class
    at: 'backend/app/services/doubao_service.py:L62-L917'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/doubao_service.py:L65-L70'
  - symbol: _connect
    kind: method
    at: 'backend/app/services/doubao_service.py:L72-L85'
  - symbol: _close
    kind: method
    at: 'backend/app/services/doubao_service.py:L87-L108'
  - symbol: _sleep
    kind: method
    at: 'backend/app/services/doubao_service.py:L114-L116'
  - symbol: _take_screenshot
    kind: method
    at: 'backend/app/services/doubao_service.py:L118-L124'
  - symbol: _extract_qrcode
    kind: method
    at: 'backend/app/services/doubao_service.py:L126-L152'
  - symbol: _click_login_button
    kind: method
    at: 'backend/app/services/doubao_service.py:L154-L175'
  - symbol: _detect_login_modal
    kind: method
    at: 'backend/app/services/doubao_service.py:L177-L186'
  - symbol: _dismiss_modal
    kind: method
    at: 'backend/app/services/doubao_service.py:L188-L202'
  - symbol: _has_login_button
    kind: method
    at: 'backend/app/services/doubao_service.py:L204-L220'
  - symbol: _login_status
    kind: method
    at: 'backend/app/services/doubao_service.py:L222-L256'
  - symbol: _extract_account
    kind: method
    at: 'backend/app/services/doubao_service.py:L258-L302'
  - symbol: clear_login
    kind: method
    at: 'backend/app/services/doubao_service.py:L304-L324'
  - symbol: _is_cancelled
    kind: method
    at: 'backend/app/services/doubao_service.py:L330-L340'
  - symbol: generate
    kind: method
    at: 'backend/app/services/doubao_service.py:L342-L490'
  - symbol: progress_cb
    kind: function
    at: 'backend/app/services/doubao_service.py:L381-L382'
  - symbol: _run_video_generation
    kind: method
    at: 'backend/app/services/doubao_service.py:L492-L610'
  - symbol: _set_duration
    kind: method
    at: 'backend/app/services/doubao_service.py:L616-L630'
  - symbol: _send_prompt
    kind: method
    at: 'backend/app/services/doubao_service.py:L632-L715'
  - symbol: _wait_for_generation_outcome
    kind: method
    at: 'backend/app/services/doubao_service.py:L717-L767'
  - symbol: _extract_reject_reason
    kind: method
    at: 'backend/app/services/doubao_service.py:L769-L776'
  - symbol: _get_last_message_text
    kind: method
    at: 'backend/app/services/doubao_service.py:L778-L802'
  - symbol: _llm_rewrite_prompt
    kind: method
    at: 'backend/app/services/doubao_service.py:L804-L856'
  - symbol: _capture_video_url
    kind: method
    at: 'backend/app/services/doubao_service.py:L858-L917'
  - symbol: _on_resp
    kind: function
    at: 'backend/app/services/doubao_service.py:L888-L895'
---
<!-- context:generated:start -->
## Summary

Two independent video generation channels: DoubaoGenerator (Playwright CDP RPA driving Doubao's web UI with QR login, local-LLM prompt rewriting requiring user confirmation up to 5 rounds, text/role selectors due to React dynamic chunks, random delays to dodge risk-control) and SeedanceClient (direct Volcano Ark HTTP API with feature flag defaulting off, 5s/10s duration policy via truncation/blocking). Both write to shared video_* fields on ShortdramaPrompt, traced by gen_channel.

## Related

- produces [[celery-task-layer]] — doubao_generate_task and seedance_generate_task drive these services
- uses [[orm-model-registry]] — Persists to ShortdramaPrompt records
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
