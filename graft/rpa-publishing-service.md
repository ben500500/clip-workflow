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
    at: 'backend/app/services/publish_service.py:L85-L94'
  - symbol: _cache_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L97-L111'
  - symbol: _pop_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L114-L117'
  - symbol: release_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L120-L131'
  - symbol: VideoChannelPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L134-L1074'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/publish_service.py:L155-L171'
  - symbol: _connect
    kind: method
    at: 'backend/app/services/publish_service.py:L173-L207'
  - symbol: publish
    kind: method
    at: 'backend/app/services/publish_service.py:L209-L257'
  - symbol: _publish_body
    kind: method
    at: 'backend/app/services/publish_service.py:L259-L398'
  - symbol: _post_publish_comments_from_payload
    kind: method
    at: 'backend/app/services/publish_service.py:L400-L413'
  - symbol: _post_publish_comments
    kind: method
    at: 'backend/app/services/publish_service.py:L415-L475'
  - symbol: _close_connection
    kind: method
    at: 'backend/app/services/publish_service.py:L477-L489'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L491-L502'
  - symbol: _probe_upload_risk_signal
    kind: method
    at: 'backend/app/services/publish_service.py:L504-L540'
  - symbol: _upload_video
    kind: method
    at: 'backend/app/services/publish_service.py:L542-L570'
  - symbol: _wait_for_upload
    kind: method
    at: 'backend/app/services/publish_service.py:L572-L621'
  - symbol: _set_title
    kind: method
    at: 'backend/app/services/publish_service.py:L623-L668'
  - symbol: _set_description
    kind: method
    at: 'backend/app/services/publish_service.py:L670-L677'
  - symbol: _set_location
    kind: method
    at: 'backend/app/services/publish_service.py:L679-L703'
  - symbol: _merge_tags_into_description
    kind: method
    at: 'backend/app/services/publish_service.py:L705-L719'
  - symbol: _set_tags
    kind: method
    at: 'backend/app/services/publish_service.py:L721-L731'
  - symbol: _set_cover
    kind: method
    at: 'backend/app/services/publish_service.py:L733-L757'
  - symbol: _select_jump_type
    kind: method
    at: 'backend/app/services/publish_service.py:L759-L783'
  - symbol: _attach_mini_program
    kind: method
    at: 'backend/app/services/publish_service.py:L785-L803'
  - symbol: _take_screenshot
    kind: method
    at: 'backend/app/services/publish_service.py:L805-L812'
  - symbol: _click_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L814-L833'
  - symbol: _wait_for_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L835-L867'
  - symbol: _save_pending_payload
    kind: method
    at: 'backend/app/services/publish_service.py:L869-L909'
  - symbol: _refill_pending_form
    kind: method
    at: 'backend/app/services/publish_service.py:L911-L952'
  - symbol: _selector_ok
    kind: method
    at: 'backend/app/services/publish_service.py:L954-L966'
  - symbol: confirm_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L968-L1059'
  - symbol: check_login_status
    kind: method
    at: 'backend/app/services/publish_service.py:L1061-L1074'
  - symbol: DouyinPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L1077-L1107'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L1085-L1095'
  - symbol: _set_tags
    kind: method
    at: 'backend/app/services/publish_service.py:L1097-L1107'
  - symbol: KuaishouPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L1110-L1128'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L1118-L1128'
  - symbol: get_publisher
    kind: function
    at: 'backend/app/services/publish_service.py:L1131-L1143'
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
