---
name: Multi-Operator RBAC & Audit
slug: multi-operator-rbac-audit
type: concept
sources:
  - path: alembic/versions/0008_data_scope.py
    hash: bfcddc6b498678069fba836c4957583c733b7a583e27205df3f1ffd473b4a263
  - path: alembic/versions/0027_multi_operator_ownership.py
    hash: 7093624a4b1d59db094d790f2776aded2cdc88151c18045e883ee10002b6d014
  - path: alembic/versions/0028_multi_operator_audit.py
    hash: c5f93fd8ed88acfa5b5ac3a60d042a579f963a94615b361c9b228db6eb5583fd
  - path: alembic/versions/0031_channel_accounts.py
    hash: c512472f71d778a3575dfc5ce8d87953e6516717e9b0a250154204068133aafd
  - path: alembic/versions/0032_channel_video_account_unique.py
    hash: 82b4b46f3e8d2044863a92e207aa75d5e5a81b8c683641570d1a4eebebf5e455
sources_digest: c7d7ded28aaeda417c1562fc6f57273b67c0cc025ae8c0422bb029d12cc54c20
links:
  - to: alembic-migration-chain
    relation: part_of
    description: These migrations implement the RBAC/audit schema within the linear chain.
generator:
  version: 1
covers:
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0008_data_scope.py:L28-L47'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0008_data_scope.py:L50-L53'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0027_multi_operator_ownership.py:L31-L122'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0027_multi_operator_ownership.py:L125-L151'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0028_multi_operator_audit.py:L31-L135'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0028_multi_operator_audit.py:L138-L144'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0031_channel_accounts.py:L28-L70'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0031_channel_accounts.py:L73-L75'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0032_channel_video_account_unique.py:L27-L32'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0032_channel_video_account_unique.py:L35-L40'
---
<!-- context:generated:start -->
## Summary

Phase-based data isolation and ownership: data_scope (all/own) on users with role-based backfill, created_by/operator_id columns on projects, video_accounts, and publish_profiles, and a family of audit tables (publish_audits, login_audits, cookie_access_logs, risk_events) with request_id for end-to-end tracing. Access control is enforced at the API layer, not the database; only superadmin/admin may query audit tables. All columns default NULL to avoid table locks and preserve backward compatibility.

## Related

- part of [[alembic-migration-chain]] — These migrations implement the RBAC/audit schema within the linear chain.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
