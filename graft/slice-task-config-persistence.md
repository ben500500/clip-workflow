---
name: Slice Task Config Persistence
slug: slice-task-config-persistence
type: concept
sources:
  - path: alembic/versions/0003_slice_task_vert2horiz.py
    hash: 4b3a497a6c7d9aff443fdb468a907a75b8ecfbe0dd59bb102d78738f831fd61e
  - path: alembic/versions/0018_slice_task_badges.py
    hash: 84d9470822a251db0ccb9f8f23b4400a0041bf30f59615ed057315783911a8a7
  - path: alembic/versions/0019_slice_task_badge_default_width.py
    hash: 8be530eebc751a1b2acfb1e222dd4484d809b9dbc1a7f65afb211bdb4de3ed8f
  - path: alembic/versions/0020_slice_task_subtitle.py
    hash: f04e33aa170d930c4b23eed51ea51f68a95b87761549806de8eb9670c3e41827
  - path: alembic/versions/0021_slice_task_text_overlays.py
    hash: 3bf4eac203b65b6302493f5b1f983bfdcb64da19b0caf259c370e33f7382ea35
  - path: alembic/versions/0023_slice_task_subtitle_mask.py
    hash: d6a053b6f83b40b1155aed5c1f1717948069ddd95c5ea7ef54eb01c01a7db8c3
  - path: alembic/versions/0024_user_preferences.py
    hash: c925c9df64eb298a668d8b27df9a9b9e7fd1476781fbe4bd0f6dc8dcdd664a74
  - path: alembic/versions/0025_slice_task_subtitle_align_mask.py
    hash: b069a96d911a1e35388336a0d92d70a4353e27383eb56fb5c7e0155ea805afd0
  - path: alembic/versions/0035_slice_task_cover_image.py
    hash: 82bd3bd669022a61921665b6be12b78c3b723ff63b097f4c3574998b1cc546a3
sources_digest: 54930dad3c346e254f73d2424e90ff63961351aba118e69bf07877980d418015
links:
  - to: alembic-migration-chain
    relation: part_of
    description: >-
      These migrations are members of the linear chain, each chaining from the
      prior revision.
generator:
  version: 1
covers:
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0003_slice_task_vert2horiz.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0003_slice_task_vert2horiz.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0018_slice_task_badges.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0018_slice_task_badges.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0019_slice_task_badge_default_width.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0019_slice_task_badge_default_width.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0020_slice_task_subtitle.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0020_slice_task_subtitle.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0021_slice_task_text_overlays.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0021_slice_task_text_overlays.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0023_slice_task_subtitle_mask.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0023_slice_task_subtitle_mask.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0024_user_preferences.py:L24-L33'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0024_user_preferences.py:L36-L38'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0025_slice_task_subtitle_align_mask.py:L24-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0025_slice_task_subtitle_align_mask.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0035_slice_task_cover_image.py:L26-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0035_slice_task_cover_image.py:L30-L31'
---
<!-- context:generated:start -->
## Summary

A cross-cutting invariant: per-slice-task configuration (vert2horiz, badges, badge_default_width, subtitle, text_overlays, subtitle_mask, subtitle_align_mask, cover_image) is persisted as JSON/boolean columns on slice_tasks so it survives retries. Migrations add these via raw SQL with IF NOT EXISTS guards for idempotency, and user-level defaults live in a separate user_preferences table with a unique user_id constraint.

## Related

- part of [[alembic-migration-chain]] — These migrations are members of the linear chain, each chaining from the prior revision.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
