---
name: Video Publishing Pipeline
slug: video-publishing-pipeline
type: system
sources:
  - path: backend/app/services/publish_service.py
    hash: 34f37428ee2c49936c4150bc41af8b8f72578e79691231d07efd61bef4debe91
sources_digest: bcfb3fa17a59ae5b4d684df8ea4aa2d54a36aa1af768c2dd2badd1c57a922d1f
links:
  - to: minio-storage-service
    relation: uses
    description: Downloads cover images via minio_service before upload
  - to: redis-stream-task-coordination
    relation: uses
    description: >-
      Persists pending publish payloads to Redis via multi_operator for
      worker-restart resilience
generator:
  version: 1
covers:
  - symbol: PublishTimeoutError
    kind: class
    at: 'backend/app/services/publish_service.py:L27-L33'
  - symbol: _get_playwright
    kind: function
    at: 'backend/app/services/publish_service.py:L48-L57'
  - symbol: _cache_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L60-L74'
  - symbol: _pop_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L77-L80'
  - symbol: release_pending_tab
    kind: function
    at: 'backend/app/services/publish_service.py:L83-L94'
  - symbol: VideoChannelPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L97-L822'
  - symbol: __init__
    kind: method
    at: 'backend/app/services/publish_service.py:L118-L134'
  - symbol: _connect
    kind: method
    at: 'backend/app/services/publish_service.py:L136-L164'
  - symbol: publish
    kind: method
    at: 'backend/app/services/publish_service.py:L166-L281'
  - symbol: _post_publish_comments_from_payload
    kind: method
    at: 'backend/app/services/publish_service.py:L283-L296'
  - symbol: _post_publish_comments
    kind: method
    at: 'backend/app/services/publish_service.py:L298-L358'
  - symbol: _close_connection
    kind: method
    at: 'backend/app/services/publish_service.py:L360-L372'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L374-L385'
  - symbol: _upload_video
    kind: method
    at: 'backend/app/services/publish_service.py:L387-L404'
  - symbol: _wait_for_upload
    kind: method
    at: 'backend/app/services/publish_service.py:L406-L429'
  - symbol: _set_title
    kind: method
    at: 'backend/app/services/publish_service.py:L431-L448'
  - symbol: _set_description
    kind: method
    at: 'backend/app/services/publish_service.py:L450-L457'
  - symbol: _merge_tags_into_description
    kind: method
    at: 'backend/app/services/publish_service.py:L459-L473'
  - symbol: _set_tags
    kind: method
    at: 'backend/app/services/publish_service.py:L475-L485'
  - symbol: _set_cover
    kind: method
    at: 'backend/app/services/publish_service.py:L487-L511'
  - symbol: _select_jump_type
    kind: method
    at: 'backend/app/services/publish_service.py:L513-L537'
  - symbol: _attach_mini_program
    kind: method
    at: 'backend/app/services/publish_service.py:L539-L557'
  - symbol: _take_screenshot
    kind: method
    at: 'backend/app/services/publish_service.py:L559-L566'
  - symbol: _click_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L568-L587'
  - symbol: _wait_for_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L589-L621'
  - symbol: _save_pending_payload
    kind: method
    at: 'backend/app/services/publish_service.py:L623-L660'
  - symbol: _refill_pending_form
    kind: method
    at: 'backend/app/services/publish_service.py:L662-L700'
  - symbol: _selector_ok
    kind: method
    at: 'backend/app/services/publish_service.py:L702-L714'
  - symbol: confirm_publish
    kind: method
    at: 'backend/app/services/publish_service.py:L716-L807'
  - symbol: check_login_status
    kind: method
    at: 'backend/app/services/publish_service.py:L809-L822'
  - symbol: DouyinPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L825-L855'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L833-L843'
  - symbol: _set_tags
    kind: method
    at: 'backend/app/services/publish_service.py:L845-L855'
  - symbol: KuaishouPublisher
    kind: class
    at: 'backend/app/services/publish_service.py:L858-L876'
  - symbol: _need_login
    kind: method
    at: 'backend/app/services/publish_service.py:L866-L876'
  - symbol: get_publisher
    kind: function
    at: 'backend/app/services/publish_service.py:L879-L891'
---
<!-- context:generated:start -->
## Summary

The single RPA-based video publishing pipeline for short-video platforms, converging all Publisher implementations into one module. Uses Playwright via CDP to automate WeChat Video Channel uploads, with a manual-confirmation workflow where filled forms are cached in process-level _PENDING_TABS keyed by task_id. Embeds tags as #话题# in description (no standalone tag input), truncates titles to 16 chars, waits for a real <video> element before considering upload complete, and raises PublishTimeoutError on timeout rather than silently succeeding. Persists pending payloads to Redis for worker-restart resilience and optionally posts comments without blocking the success path.

## Related

- uses [[minio-storage-service]] — Downloads cover images via minio_service before upload
- uses [[redis-stream-task-coordination]] — Persists pending publish payloads to Redis via multi_operator for worker-restart resilience
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
