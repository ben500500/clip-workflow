---
name: AutoClip Integration
slug: autoclip-integration
type: system
sources:
  - path: backend/app/services/autoclip_service.py
    hash: a223da0870865c9d47eb7a563a15d5fdc38ffdca7d594ccd01d625bf621255c2
sources_digest: 386bc2aa83841a844c973c2f004f6f6f70bb007085b934666a91ff0737159b73
links:
  - to: batch-slicing-workflow
    relation: uses
    description: run_autoclip and detect_intervals drive the autoclip phase
  - to: configuration-database-bootstrap
    relation: configures
    description: AUTOCLIP_URL base endpoint
generator:
  version: 1
covers:
  - symbol: create_autoclip_project
    kind: function
    at: 'backend/app/services/autoclip_service.py:L11-L27'
  - symbol: upload_video
    kind: function
    at: 'backend/app/services/autoclip_service.py:L30-L50'
  - symbol: trigger_pipeline
    kind: function
    at: 'backend/app/services/autoclip_service.py:L53-L84'
  - symbol: get_pipeline_progress
    kind: function
    at: 'backend/app/services/autoclip_service.py:L87-L101'
  - symbol: get_clips
    kind: function
    at: 'backend/app/services/autoclip_service.py:L104-L137'
  - symbol: check_autoclip_health
    kind: function
    at: 'backend/app/services/autoclip_service.py:L140-L159'
  - symbol: delete_autoclip_project
    kind: function
    at: 'backend/app/services/autoclip_service.py:L162-L174'
  - symbol: generate_subtitle
    kind: function
    at: 'backend/app/services/autoclip_service.py:L176-L206'
---
<!-- context:generated:start -->
## Summary

Async HTTP client wrapping the AutoClip microservice: create project, upload video, trigger 6-step pipeline (explicitly forwarding frame_analysis/llm_model/llm_provider from system config to fix ignored model selection), poll progress, get clips (always sends duration params, 0=unlimited), health probe (checks both /api/v1-prefixed and root paths for prefix mismatch), delete for rollback, and ASR subtitle generation. All functions return None/empty on failure rather than raising.

## Related

- uses [[batch-slicing-workflow]] — run_autoclip and detect_intervals drive the autoclip phase
- configures [[configuration-database-bootstrap]] — AUTOCLIP_URL base endpoint
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
