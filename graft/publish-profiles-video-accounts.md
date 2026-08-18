---
name: Publish Profiles & Video Accounts
slug: publish-profiles-video-accounts
type: system
sources:
  - path: backend/app/api/publish_profiles.py
    hash: 2e935850119e576a43ff80976d0031c0dcc43cec621c44c12b5d7c8e605a57cc
  - path: backend/app/api/publish_video_accounts.py
    hash: f2fea0b5088b7c9de7542ef783795e839308ca16872f81fe6b26e8999167500a
sources_digest: 7ed8f178e4151d87d31e594780680cc18345a41b81d10c98c6deab8d9f632c0c
links:
  - to: publish-api-facade
    relation: part_of
    description: These routers are included by the publish facade.
generator:
  version: 1
covers:
  - symbol: PublishProfileCreate
    kind: class
    at: 'backend/app/api/publish_profiles.py:L22-L43'
  - symbol: PublishProfileUpdate
    kind: class
    at: 'backend/app/api/publish_profiles.py:L46-L66'
  - symbol: PublishProfileResponse
    kind: class
    at: 'backend/app/api/publish_profiles.py:L69-L94'
  - symbol: _serialize_publish_profile
    kind: function
    at: 'backend/app/api/publish_profiles.py:L97-L123'
  - symbol: list_publish_profiles
    kind: function
    at: 'backend/app/api/publish_profiles.py:L127-L141'
  - symbol: create_publish_profile
    kind: function
    at: 'backend/app/api/publish_profiles.py:L145-L186'
  - symbol: update_publish_profile
    kind: function
    at: 'backend/app/api/publish_profiles.py:L190-L226'
  - symbol: delete_publish_profile
    kind: function
    at: 'backend/app/api/publish_profiles.py:L230-L252'
  - symbol: VideoAccountCreate
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L22-L34'
  - symbol: VideoAccountUpdate
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L37-L48'
  - symbol: VideoAccountResponse
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L51-L68'
  - symbol: VideoAccountBatchImport
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L71-L74'
  - symbol: _serialize_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L77-L94'
  - symbol: list_video_accounts
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L98-L121'
  - symbol: create_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L125-L149'
  - symbol: batch_import_video_accounts
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L153-L196'
  - symbol: VideoAccountBatchAssignProfile
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L199-L202'
  - symbol: batch_assign_video_account_profile
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L206-L238'
  - symbol: update_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L242-L271'
  - symbol: delete_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L275-L297'
---
<!-- context:generated:start -->
## Summary

Publish profile CRUD with AES/Fernet cookie encryption at rest, cookie masking ('****' sentinel signals unchanged cookie on update), and RBAC so operators only see profiles they own. Video account library manages matrix accounts across platforms with a multi-operator ownership model (created_by tracks acting user, operator_id identifies owner), batch import with duplicate skipping by platform+account_name, and batch profile assignment.

## Related

- part of [[publish-api-facade]] — These routers are included by the publish facade.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
