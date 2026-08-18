---
name: RPA Publishing Service
slug: rpa-publishing-service
type: system
sources:
  - path: backend/app/services/publish_service.py
    hash: ad8ddb02bbbc2dad889c31745016efb746e2cf16fbb8c2a7e09cf2fb8febfbae
sources_digest: 6623dc9cf645b6a733a69cca95540d8dbe902af96637e491fc2eeeeae9c8c721
links:
  - to: multi-operator-routing-service
    relation: uses
    description: >-
      Consumes CDP connection URLs and bearer tokens for multi-operator
      scenarios
  - to: variant-generation-pipeline
    relation: uses
    description: verify_variant_fingerprint guards pre-publish safety before publishing
generator:
  version: 1
covers:
  - symbol: PublishTimeoutError
    kind: class
    at: 'backend/app/services/publish_service.py:L27-L33'
  - symbol: UploadRiskError
    kind: class
    at: 'backend/app/services/publish_service.py:L36-L51'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/publish_service.py:L48-L51'
  - symbol: _get_playwright
    kind: function
    at: 'backend/app/services/publish_service.py:L83-L92'
  - symbol: _cache_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L95-L109'
  - symbol: _pop_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L112-L115'
  - symbol: release_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L118-L129'
  - symbol: VideoChannelPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L132-L1066'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/publish_service.py:L153-L169'
  - symbol: _connect
    kind: method
    at: 'backend/app/services/publish_service.py:L171-L199'
  - symbol: publish
    kind: method
    at: 'backend/app/services/publish_service.py:L201-L249'
  - symbol: _publish_body
    kind: method
    at: 'backend/app/services/publish_service.py:L251-L390'
  - symbol: _post_publish_comments_from_payload
    kind: method
    at: 'backend/app/services/publish_service.py:L392-L405'
  - symbol: _post_publish_comments
    kind: method
    at: 'backend/app/services/publish_service.py:L407-L467'
  - symbol: _close_connection
    kind: method
    at: 'backend/app/services/publish_service.py:L469-L481'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L483-L494'
  - symbol: _probe_upload_risk_signal
    kind: method
    at: 'backend/app/services/publish_service.py:L496-L532'
  - symbol: _upload_video
    kind: method
    at: 'backend/app/services/publish_service.py:L534-L562'
  - symbol: _wait_for_upload
    kind: method
    at: 'backend/app/services/publish_service.py:L564-L613'
  - symbol: _set_title
    kind: method
    at: 'backend/app/services/publish_service.py:L615-L660'
  - symbol: _set_description
    kind: method
    at: 'backend/app/services/publish_service.py:L662-L669'
  - symbol: _set_location
    kind: method
    at: 'backend/app/services/publish_service.py:L671-L695'
  - symbol: _merge_tags_into_description
    kind: method
    at: 'backend/app/services/publish_service.py:L697-L711'
  - symbol: _set_tags
    kind: method
    at: 'backend/app/services/publish_service.py:L713-L723'
  - symbol: _set_cover
    kind: method
    at: 'backend/app/services/publish_service.py:L725-L749'
  - symbol: _select_jump_type
    kind: method
    at: 'backend/app/services/publish_service.py:L751-L775'
  - symbol: _attach_mini_program
    kind: method
    at: 'backend/app/services/publish_service.py:L777-L795'
  - symbol: _take_screenshot
    kind: method
    at: 'backend/app/services/publish_service.py:L797-L804'
  - symbol: _click_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L806-L825'
  - symbol: _wait_for_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L827-L859'
  - symbol: _save_pending_payload
    kind: method
    at: 'backend/app/services/publish_service.py:L861-L901'
  - symbol: _refill_pending_form
    kind: method
    at: 'backend/app/services/publish_service.py:L903-L944'
  - symbol: _selector_ok
    kind: method
    at: 'backend/app/services/publish_service.py:L946-L958'
  - symbol: confirm_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L960-L1051'
  - symbol: check_login_status
    kind: method
    at: 'backend/app/services/publish_service.py:L1053-L1066'
  - symbol: DouyinPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L1069-L1099'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L1077-L1087'
  - symbol: _set_tags
    kind: method
    at: 'backend/app/services/publish_service.py:L1089-L1099'
  - symbol: KuaishouPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L1102-L1120'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L1110-L1120'
  - symbol: get_publisher
    kind: function
    at: 'backend/app/services/publish_service.py:L1123-L1135'
---
<!-- context:generated:start -->
## Summary

Playwright-based automation for publishing to WeChat Video Channel via a shared Chromium instance over CDP. Maintains process-level state (_PENDING_TABS for cached filled forms awaiting confirmation, _shared_playwright reused across Celery tasks). Embeds tags into descriptions (platform lacks a tag input), enforces a 900-second overall timeout, and uses probe-based risk detection to distinguish UploadRiskError (platform risk control) from PublishTimeoutError. Handles 114 hidden file inputs via file chooser events and verifies playability via readyState/duration rather than CSS selectors.

## Related

- uses [[multi-operator-routing-service]] — Consumes CDP connection URLs and bearer tokens for multi-operator scenarios
- uses [[variant-generation-pipeline]] — verify_variant_fingerprint guards pre-publish safety before publishing
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
