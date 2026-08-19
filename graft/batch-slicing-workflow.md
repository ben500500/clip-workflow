---
name: Batch Slicing Workflow
slug: batch-slicing-workflow
type: system
sources:
  - path: backend/app/models/material.py
    hash: a88c6f0f451a2c6fac47bf9ad2a307d26d478224ebab1d5d478b62a13e7f82d8
  - path: backend/app/services/batch_decoupled_service.py
    hash: 05649e2ec4b11377e6b4db183671fd5a63dddcd77ec78779ec0a66dd22accf96
  - path: backend/app/services/batch_slice_service.py
    hash: 1cf6ef9f55f8d50cfa2b7025a66dd6eb241f1ee0ffbecc7413ec4c7acf96df18
sources_digest: dce404ac584ae67a96965911849cfe6da398ed139836a6dc8f7d523023b3eb33
links:
  - to: celery-task-layer
    relation: uses
    description: Dispatches selection/slice tasks and runs on beat schedules
  - to: engine-execution-layer
    relation: uses
    description: Interval detection and slicing invoke engine subprocesses
  - to: orm-model-registry
    relation: uses
    description: 'BatchSlice, BatchSliceItem, SliceTask, ClipCandidate models'
generator:
  version: 1
covers:
  - symbol: Project
    kind: class
    at: 'backend/app/models/material.py:L29-L45'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L44-L45'
  - symbol: Episode
    kind: class
    at: 'backend/app/models/material.py:L48-L76'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L75-L76'
  - symbol: AutoClipProject
    kind: class
    at: 'backend/app/models/material.py:L79-L94'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L93-L94'
  - symbol: AutoClipRun
    kind: class
    at: 'backend/app/models/material.py:L97-L120'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L119-L120'
  - symbol: ClipCandidate
    kind: class
    at: 'backend/app/models/material.py:L123-L146'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L145-L146'
  - symbol: DetectedInterval
    kind: class
    at: 'backend/app/models/material.py:L149-L167'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L166-L167'
  - symbol: SliceTask
    kind: class
    at: 'backend/app/models/material.py:L170-L220'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L219-L220'
  - symbol: SliceOutput
    kind: class
    at: 'backend/app/models/material.py:L223-L245'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L244-L245'
  - symbol: Publication
    kind: class
    at: 'backend/app/models/material.py:L248-L266'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L265-L266'
  - symbol: SystemConfig
    kind: class
    at: 'backend/app/models/material.py:L269-L278'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L277-L278'
  - symbol: PlatformProfile
    kind: class
    at: 'backend/app/models/material.py:L281-L295'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L294-L295'
  - symbol: ImportTemplate
    kind: class
    at: 'backend/app/models/material.py:L298-L310'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L309-L310'
  - symbol: ImportHistory
    kind: class
    at: 'backend/app/models/material.py:L313-L329'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L328-L329'
  - symbol: BatchSlice
    kind: class
    at: 'backend/app/models/material.py:L332-L362'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L361-L362'
  - symbol: BatchSliceItem
    kind: class
    at: 'backend/app/models/material.py:L365-L393'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/material.py:L392-L393'
  - symbol: _get_batch
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L56-L61'
  - symbol: _load_items
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L64-L71'
  - symbol: _load_item
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L74-L79'
  - symbol: _update_item
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L82-L87'
  - symbol: _update_batch
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L90-L95'
  - symbol: _get_operator
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L98-L104'
  - symbol: _resolve_project
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L107-L123'
  - symbol: run_batch_decoupled
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L129-L186'
  - symbol: process_selection
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L192-L246'
  - symbol: dispatch_ready_slices
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L252-L322'
  - symbol: finalize_slices
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L328-L400'
  - symbol: aggregate_batches
    kind: function
    at: 'backend/app/services/batch_decoupled_service.py:L406-L470'
  - symbol: _get_batch
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L55-L59'
  - symbol: _load_items
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L62-L69'
  - symbol: _update_item
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L72-L77'
  - symbol: _update_batch
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L80-L85'
  - symbol: _set_phase
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L88-L99'
  - symbol: _find_or_create_project
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L102-L120'
  - symbol: _upload_and_create_episode
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L123-L153'
  - symbol: _trigger_autoclip
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L156-L177'
  - symbol: _wait_autoclip
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L180-L201'
  - symbol: _trigger_detect
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L204-L230'
  - symbol: _wait_detect
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L233-L256'
  - symbol: _accept_all_candidates
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L259-L271'
  - symbol: _trigger_slice
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L274-L307'
  - symbol: _wait_slice
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L310-L336'
  - symbol: _delete_source
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L339-L360'
  - symbol: run_batch
    kind: function
    at: 'backend/app/services/batch_slice_service.py:L363-L536'
---
<!-- context:generated:start -->
## Summary

Two pipeline modes: serial (historical, per-episode upload→autoclip→auto-accept→detect→slice→delete) and decoupled producer-consumer (upload+dispatch selection, beat-driven dispatch_ready_slices publishes to Redis Streams consumed by Go workers, finalize_slices polls terminal states, aggregate_batches idempotently summarizes). Decoupled mode sets items to 'slicing' phase to prevent duplicate dispatch; falls back to whole-video slicing when autoclip yields no candidates. SliceTask persists all processing options so retries preserve original intent.

## Related

- uses [[celery-task-layer]] — Dispatches selection/slice tasks and runs on beat schedules
- uses [[engine-execution-layer]] — Interval detection and slicing invoke engine subprocesses
- uses [[orm-model-registry]] — BatchSlice, BatchSliceItem, SliceTask, ClipCandidate models
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
