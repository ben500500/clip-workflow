---
name: Redis Task Coordination Contract
slug: redis-task-coordination-contract
type: concept
sources:
  - path: slice-worker/redis_client.go
    hash: 9e927d48a03637cb0144a9ec2f60d8932bd15f91d9c3096e3c5b1687a41cd9c6
  - path: slice-worker/tray_common.go
    hash: 364b126de1c8bf280cb71d734bf4fe0331cc52e1834f0d2a0bbac179d2c618e3
  - path: slice-worker/tray.go
    hash: da296d0d58701255e632a94b05a5bcca4b9ca96e56203685a5f7c65c6d115fac
sources_digest: 501ab55fa4af3460579c822a7c29f1d2715b570b40c3cecba6a5a3c65b1c0ad4
links:
  - to: slice-worker-node
    relation: part_of
    description: Redis client is the worker's coordination backbone.
  - to: slice-worker-node
    relation: implements
    description: The worker must honor the backend's stream/lease/claim semantics.
generator:
  version: 1
covers:
  - symbol: RedisClient
    kind: struct
    at: 'slice-worker/redis_client.go:L15-L18'
  - symbol: NewRedisClient
    kind: function
    at: 'slice-worker/redis_client.go:L21-L36'
  - symbol: Close
    kind: method
    at: 'slice-worker/redis_client.go:L39-L41'
  - symbol: nodeKey
    kind: function
    at: 'slice-worker/redis_client.go:L44-L46'
  - symbol: RegisterNode
    kind: method
    at: 'slice-worker/redis_client.go:L53-L99'
  - symbol: UnregisterNode
    kind: method
    at: 'slice-worker/redis_client.go:L102-L111'
  - symbol: Heartbeat
    kind: method
    at: 'slice-worker/redis_client.go:L114-L135'
  - symbol: FetchTask
    kind: method
    at: 'slice-worker/redis_client.go:L138-L167'
  - symbol: parseStreamMessage
    kind: function
    at: 'slice-worker/redis_client.go:L170-L180'
  - symbol: AckTask
    kind: method
    at: 'slice-worker/redis_client.go:L188-L196'
  - symbol: RequeueTask
    kind: method
    at: 'slice-worker/redis_client.go:L199-L204'
  - symbol: CreateConsumerGroup
    kind: method
    at: 'slice-worker/redis_client.go:L207-L213'
  - symbol: ClaimStaleTasks
    kind: method
    at: 'slice-worker/redis_client.go:L219-L247'
  - symbol: PendingOverview
    kind: method
    at: 'slice-worker/redis_client.go:L253-L262'
  - symbol: UpdateTaskStatus
    kind: method
    at: 'slice-worker/redis_client.go:L265-L273'
  - symbol: TouchTask
    kind: method
    at: 'slice-worker/redis_client.go:L276-L280'
  - symbol: TryAcquireTaskLease
    kind: method
    at: 'slice-worker/redis_client.go:L288-L294'
  - symbol: RefreshTaskLease
    kind: method
    at: 'slice-worker/redis_client.go:L299-L314'
  - symbol: ReleaseTaskLease
    kind: method
    at: 'slice-worker/redis_client.go:L318-L326'
  - symbol: taskLeaseKey
    kind: function
    at: 'slice-worker/redis_client.go:L329-L331'
  - symbol: IsTaskCancelled
    kind: method
    at: 'slice-worker/redis_client.go:L334-L343'
  - symbol: ExpireTaskStatus
    kind: method
    at: 'slice-worker/redis_client.go:L346-L348'
  - symbol: GetTaskHash
    kind: method
    at: 'slice-worker/redis_client.go:L351-L353'
  - symbol: GetTaskStatus
    kind: method
    at: 'slice-worker/redis_client.go:L356-L365'
  - symbol: IsNodeEnabled
    kind: method
    at: 'slice-worker/redis_client.go:L368-L377'
  - symbol: GetNodeCPUPercent
    kind: method
    at: 'slice-worker/redis_client.go:L381-L400'
  - symbol: SetNodeEnabled
    kind: method
    at: 'slice-worker/redis_client.go:L403-L409'
  - symbol: SetNodeCPUPercent
    kind: method
    at: 'slice-worker/redis_client.go:L413-L421'
  - symbol: GetNodeUpdateCommand
    kind: method
    at: 'slice-worker/redis_client.go:L426-L435'
  - symbol: ClearNodeUpdateCommand
    kind: method
    at: 'slice-worker/redis_client.go:L438-L440'
  - symbol: StreamMessage
    kind: struct
    at: 'slice-worker/redis_client.go:L443-L448'
  - symbol: NodeInfo
    kind: struct
    at: 'slice-worker/redis_client.go:L451-L473'
  - symbol: SliceTask
    kind: struct
    at: 'slice-worker/redis_client.go:L476-L524'
  - symbol: BadgeItem
    kind: struct
    at: 'slice-worker/redis_client.go:L532-L539'
  - symbol: CoverItem
    kind: struct
    at: 'slice-worker/redis_client.go:L543-L546'
  - symbol: HookItem
    kind: struct
    at: 'slice-worker/redis_client.go:L550-L553'
  - symbol: TaskSource
    kind: struct
    at: 'slice-worker/redis_client.go:L556-L558'
  - symbol: TaskOutput
    kind: struct
    at: 'slice-worker/redis_client.go:L561-L569'
  - symbol: TrayController
    kind: interface
    at: 'slice-worker/tray.go:L19-L29'
  - symbol: TrayUI
    kind: struct
    at: 'slice-worker/tray.go:L32-L52'
  - symbol: NewTrayUI
    kind: function
    at: 'slice-worker/tray.go:L55-L62'
  - symbol: SetStatus
    kind: method
    at: 'slice-worker/tray.go:L65-L79'
  - symbol: SetCPUPercent
    kind: method
    at: 'slice-worker/tray.go:L82-L93'
  - symbol: registerTray
    kind: function
    at: 'slice-worker/tray_common.go:L25-L29'
  - symbol: StopAllTrays
    kind: function
    at: 'slice-worker/tray_common.go:L32-L39'
  - symbol: runTray
    kind: function
    at: 'slice-worker/tray_common.go:L49-L185'
  - symbol: NewTrayController
    kind: function
    at: 'slice-worker/tray_common.go:L188-L190'
---
<!-- context:generated:start -->
## Summary

The shared data contract between the Go worker and the Python backend: node registration in `slice:nodes:{id}` hashes, online-node sets and tag indexes, task lifecycle via Redis Streams consumer groups with XAutoClaim stale-task claiming, task status in `slice:task:{id}` hashes with lease-based concurrency, and control keys for enable/disable and CPU percent. Both sides must agree on field names and semantics; the worker's redis_client.go is the Go-side mirror of the backend reader.

## Related

- part of [[slice-worker-node]] — Redis client is the worker's coordination backbone.
- implements [[slice-worker-node]] — The worker must honor the backend's stream/lease/claim semantics.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
