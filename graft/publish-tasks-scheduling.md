---
name: Publish Tasks & Scheduling
slug: publish-tasks-scheduling
type: system
sources:
  - path: backend/app/api/publish_batches.py
    hash: 14e25816ec6fa324809d2a5dfc76a0aa9b70720a6669336f640e6494a767239d
  - path: backend/app/api/publish_tasks.py
    hash: 9549e994dee17b119402e4919d096011ceb7b8cebd4e155f9c8e548e0c7bb6fe
  - path: backend/app/api/publish_time_slots.py
    hash: 154052d5194f77846154ab5eeca7af7e10a6a93cfcc326f4ac18714334768f5b
sources_digest: 5f16aa24bc57eac2251b36cfc7e9987a00264f79f62fb412b1628041faadeaf2
links:
  - to: publish-api-facade
    relation: part_of
    description: These routers are included by the publish facade.
  - to: variant-matrix-deduplication
    relation: uses
    description: >-
      publish_batches guards against duplicate variant publishing via
      guard_account_variant_unique.
generator:
  version: 1
covers:
  - symbol: PublishTaskAssignRequest
    kind: class
    at: 'backend/app/api/publish_batches.py:L29-L40'
  - symbol: PublishBatchResponse
    kind: class
    at: 'backend/app/api/publish_batches.py:L43-L52'
  - symbol: _serialize_publish_batch
    kind: function
    at: 'backend/app/api/publish_batches.py:L55-L64'
  - symbol: list_publish_batches
    kind: function
    at: 'backend/app/api/publish_batches.py:L68-L78'
  - symbol: get_publish_batch
    kind: function
    at: 'backend/app/api/publish_batches.py:L82-L106'
  - symbol: get_publish_batch_stats
    kind: function
    at: 'backend/app/api/publish_batches.py:L110-L155'
  - symbol: create_publish_batch
    kind: function
    at: 'backend/app/api/publish_batches.py:L159-L238'
  - symbol: PublishTaskCreate
    kind: class
    at: 'backend/app/api/publish_tasks.py:L30-L51'
  - symbol: PublishTaskResponse
    kind: class
    at: 'backend/app/api/publish_tasks.py:L54-L86'
  - symbol: PublishTaskConfirmResponse
    kind: class
    at: 'backend/app/api/publish_tasks.py:L89-L93'
  - symbol: PublishBatchCreate
    kind: class
    at: 'backend/app/api/publish_tasks.py:L96-L98'
  - symbol: PublishTaskScheduleUpdate
    kind: class
    at: 'backend/app/api/publish_tasks.py:L101-L111'
  - symbol: create_publish_task
    kind: function
    at: 'backend/app/api/publish_tasks.py:L115-L153'
  - symbol: create_publish_tasks_batch
    kind: function
    at: 'backend/app/api/publish_tasks.py:L157-L204'
  - symbol: _resolve_schedule
    kind: function
    at: 'backend/app/api/publish_tasks.py:L207-L250'
  - symbol: _check_publish_limits
    kind: function
    at: 'backend/app/api/publish_tasks.py:L253-L320'
  - symbol: _create_publish_task_internal
    kind: function
    at: 'backend/app/api/publish_tasks.py:L323-L391'
  - symbol: _to_uuid_or_none
    kind: function
    at: 'backend/app/api/publish_tasks.py:L336-L343'
  - symbol: list_publish_tasks
    kind: function
    at: 'backend/app/api/publish_tasks.py:L395-L428'
  - symbol: get_publish_task
    kind: function
    at: 'backend/app/api/publish_tasks.py:L432-L447'
  - symbol: get_publish_task_screenshot
    kind: function
    at: 'backend/app/api/publish_tasks.py:L451-L475'
  - symbol: confirm_publish_task
    kind: function
    at: 'backend/app/api/publish_tasks.py:L479-L514'
  - symbol: reschedule_publish_task
    kind: function
    at: 'backend/app/api/publish_tasks.py:L518-L577'
  - symbol: requeue_publish_task
    kind: function
    at: 'backend/app/api/publish_tasks.py:L581-L621'
  - symbol: PublishTimeSlotCreate
    kind: class
    at: 'backend/app/api/publish_time_slots.py:L38-L42'
  - symbol: PublishTimeSlotUpdate
    kind: class
    at: 'backend/app/api/publish_time_slots.py:L45-L49'
  - symbol: PublishTimeSlotResponse
    kind: class
    at: 'backend/app/api/publish_time_slots.py:L52-L62'
  - symbol: _serialize_slot
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L65-L75'
  - symbol: _validate_time_range
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L78-L89'
  - symbol: list_publish_time_slots
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L93-L103'
  - symbol: create_publish_time_slot
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L107-L126'
  - symbol: update_publish_time_slot
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L130-L158'
  - symbol: delete_publish_time_slot
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L162-L179'
  - symbol: resolve_scheduled_at
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L182-L227'
  - symbol: _random_in_window
    kind: function
    at: 'backend/app/api/publish_time_slots.py:L207-L216'
---
<!-- context:generated:start -->
## Summary

Publish task lifecycle: CRUD, batch creation (atomic all-or-nothing multi-platform), screenshot retrieval, manual confirmation triggering actual publish via Celery, rescheduling/cancellation, and dead-letter requeue. Enforces publish profile limits via row-locking, derives operator_id automatically from video accounts, keeps scheduled tasks in 'scheduled' status until a daemon triggers them, and handles Celery enqueue failures without blocking task creation. Time-slot resolution randomly picks a time within a window (spreading publish risk), storing naive UTC while windows are Beijing time (UTC+8), and rejects cross-midnight windows.

## Related

- part of [[publish-api-facade]] — These routers are included by the publish facade.
- uses [[variant-matrix-deduplication]] — publish_batches guards against duplicate variant publishing via guard_account_variant_unique.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
