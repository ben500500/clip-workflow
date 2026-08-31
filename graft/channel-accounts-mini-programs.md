---
name: Channel Accounts & Mini Programs
slug: channel-accounts-mini-programs
type: system
sources:
  - path: backend/app/api/channel_accounts.py
    hash: 29351d38f2bca7bd80c922a9537cf559a2ade7f33461f8b87c5e3348338a18fa
  - path: backend/app/api/publish_mini_programs.py
    hash: 3529eafcc41e9d200264fcb6eba457cb93b79bc3bed661510f3acf5ba46dca9b
sources_digest: 3b9204fb1cf44c80a7ef08e73e43f12e659ec4aeea8954329f617f1f09ebb39e
links:
  - to: publish-api-facade
    relation: part_of
    description: publish_mini_programs is included by the publish facade.
generator:
  version: 1
covers:
  - symbol: OperatorCreate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L39-L42'
  - symbol: OperatorUpdate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L45-L48'
  - symbol: OperatorResponse
    kind: class
    at: 'backend/app/api/channel_accounts.py:L51-L59'
  - symbol: ChannelAccountCreate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L62-L75'
  - symbol: ChannelAccountFromVideoAccount
    kind: class
    at: 'backend/app/api/channel_accounts.py:L78-L90'
  - symbol: ChannelAccountUpdate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L93-L104'
  - symbol: ChannelAccountResponse
    kind: class
    at: 'backend/app/api/channel_accounts.py:L107-L130'
  - symbol: _serialize_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L135-L143'
  - symbol: _load_report_metrics
    kind: function
    at: 'backend/app/api/channel_accounts.py:L146-L189'
  - symbol: _serialize_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L192-L217'
  - symbol: _load_theater_names
    kind: function
    at: 'backend/app/api/channel_accounts.py:L220-L226'
  - symbol: _reload_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L229-L237'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/channel_accounts.py:L240-L248'
  - symbol: _parse_uuid
    kind: function
    at: 'backend/app/api/channel_accounts.py:L251-L257'
  - symbol: _validate_operator_identity
    kind: function
    at: 'backend/app/api/channel_accounts.py:L260-L266'
  - symbol: list_channel_accounts
    kind: function
    at: 'backend/app/api/channel_accounts.py:L272-L313'
  - symbol: get_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L317-L337'
  - symbol: create_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L341-L388'
  - symbol: create_channel_from_video_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L396-L432'
  - symbol: update_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L436-L477'
  - symbol: delete_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L481-L497'
  - symbol: add_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L503-L524'
  - symbol: update_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L528-L565'
  - symbol: delete_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L569-L592'
  - symbol: _load_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L597-L604'
  - symbol: _load_video_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L607-L615'
  - symbol: _find_or_create_video_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L618-L662'
  - symbol: _ensure_no_existing
    kind: function
    at: 'backend/app/api/channel_accounts.py:L665-L681'
  - symbol: _check_access
    kind: function
    at: 'backend/app/api/channel_accounts.py:L684-L688'
  - symbol: MiniProgramCreate
    kind: class
    at: 'backend/app/api/publish_mini_programs.py:L20-L26'
  - symbol: MiniProgramUpdate
    kind: class
    at: 'backend/app/api/publish_mini_programs.py:L29-L35'
  - symbol: MiniProgramResponse
    kind: class
    at: 'backend/app/api/publish_mini_programs.py:L38-L48'
  - symbol: _serialize_mini_program
    kind: function
    at: 'backend/app/api/publish_mini_programs.py:L51-L61'
  - symbol: list_mini_programs
    kind: function
    at: 'backend/app/api/publish_mini_programs.py:L65-L76'
  - symbol: create_mini_program
    kind: function
    at: 'backend/app/api/publish_mini_programs.py:L80-L96'
  - symbol: update_mini_program
    kind: function
    at: 'backend/app/api/publish_mini_programs.py:L100-L121'
  - symbol: delete_mini_program
    kind: function
    at: 'backend/app/api/publish_mini_programs.py:L125-L142'
---
<!-- context:generated:start -->
## Summary

WeChat Channels business/cooperation ledger (ChannelAccount) decoupled from the publishing account library via a soft video_account_id FK, with CRUD for accounts and operators. Auto-syncs to the VideoAccount library when creating a ledger entry without an existing binding, enforces idempotency preventing duplicate ledgers per video account, and aggregates report metrics (VideoMetric/AdMetric) by video_account_id. Mini-program link library provides simple CRUD with enabled_only filter and explicit enabled defaulting to True.

## Related

- part of [[publish-api-facade]] — publish_mini_programs is included by the publish facade.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
