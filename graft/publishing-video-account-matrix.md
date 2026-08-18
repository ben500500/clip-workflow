---
name: Publishing & Video Account Matrix
slug: publishing-video-account-matrix
type: concept
sources:
  - path: alembic/versions/0013_video_accounts_mini_programs.py
    hash: 6da891ddec97bd687cf62acd08a4b42b28881bbf5f1611e49a1937f197284449
  - path: alembic/versions/0027_multi_operator_ownership.py
    hash: 7093624a4b1d59db094d790f2776aded2cdc88151c18045e883ee10002b6d014
  - path: alembic/versions/0030_publish_task_dead_letter.py
    hash: 79fee151945967ad4fc8121f259ee84cca00ad642aba704b7d5646e1a00bed71
  - path: alembic/versions/0031_channel_accounts.py
    hash: c512472f71d778a3575dfc5ce8d87953e6516717e9b0a250154204068133aafd
  - path: alembic/versions/0032_channel_video_account_unique.py
    hash: 82b4b46f3e8d2044863a92e207aa75d5e5a81b8c683641570d1a4eebebf5e455
  - path: alembic/versions/0033_publish_time_slots_scheduled_at.py
    hash: 9fa2c89ea44532d842367f2d176dd21afea85a993455f9f2a874004fd8b1a6d2
  - path: alembic/versions/0035_publish_profile_location.py
    hash: ef8f525834b4c02d34a90d6ec6d5ea2710804da55139a5385ab66a2ce3164df6
sources_digest: 6fcd061279056ab8d9046e260fbc1a657bf7cb347dad43099f5a29dc8f611dbf
links:
  - to: multi-operator-rbac-audit
    relation: depends_on
    description: >-
      Publishing tables carry created_by/operator_id and feed the audit tables;
      access control is API-layer enforced.
  - to: short-drama-production-workflow
    relation: uses
    description: >-
      publish_tasks links to prompt_record_id and material_id to trace
      publishing back to generated prompts/materials.
generator:
  version: 1
covers:
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0013_video_accounts_mini_programs.py:L28-L89'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0013_video_accounts_mini_programs.py:L92-L102'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0027_multi_operator_ownership.py:L31-L122'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0027_multi_operator_ownership.py:L125-L151'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0030_publish_task_dead_letter.py:L28-L40'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0030_publish_task_dead_letter.py:L43-L46'
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
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0033_publish_time_slots_scheduled_at.py:L28-L50'
  - symbol: _insert_slot
    kind: function
    at: 'alembic/versions/0033_publish_time_slots_scheduled_at.py:L53-L70'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0033_publish_time_slots_scheduled_at.py:L73-L78'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0035_publish_profile_location.py:L25-L33'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0035_publish_profile_location.py:L36-L40'
---
<!-- context:generated:start -->
## Summary

The publishing subsystem: video_accounts (managed account library with platform/group/mini-program flags), mini_programs, publish_profiles (with graduation fields tier/proxy/fingerprint/egress_ip and location injection), publish_tasks (with batch_id, operator_id, scheduled_at/time_slot_label, retry_count/dead_letter tracking), publish_batches, and publish_time_slots (preset windows 07:00-08:00 and 18:00-20:00, is_preset prevents deletion/editing). Scheduled publishing is signaled by non-null scheduled_at; null means immediate. channel_accounts decouples business ledger records from the publishing pipeline with a unique constraint on video_account_id.

## Related

- depends on [[multi-operator-rbac-audit]] — Publishing tables carry created_by/operator_id and feed the audit tables; access control is API-layer enforced.
- uses [[short-drama-production-workflow]] — publish_tasks links to prompt_record_id and material_id to trace publishing back to generated prompts/materials.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
