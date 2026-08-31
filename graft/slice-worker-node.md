---
name: Slice Worker Node
slug: slice-worker-node
type: system
sources:
  - path: slice-worker/callback.go
    hash: f702246fa4b2fed373c715984d507d8c8512a0d5fdfeb76bceb100275b0d6ed0
  - path: slice-worker/config.go
    hash: 24a5ea8c4870aec0fe34fa42e1bb697d270ef2f55ffa720e407142d2733b64fb
  - path: slice-worker/engine_update_test.go
    hash: 519be92d75c872b6a6506e264dc61f6803a7039ad6af102cbe3686871e723001
  - path: slice-worker/engine_update.go
    hash: 59175cd03940a01762ab1ebbdced7caaf95e90a65e875fb5c955f62f49bc2f55
  - path: slice-worker/exec_unix.go
    hash: 1eb3913aa803e243694c6d4e8e60981892695b489b63332b50f9138219859645
  - path: slice-worker/exec_windows.go
    hash: 883135be9e98a52b97d7c11d4f841e1e6ba806ecd7d042a04e921ceea0c6abe5
  - path: slice-worker/file_transfer.go
    hash: eb4cf18cfc1bec640117863da1396f68846235c5a909a8c24375d3e1225caf92
  - path: slice-worker/heartbeat_backend.go
    hash: 11236208dbff7c3708d260878cf47ebc964f6e4d5e980532f28c7ed04641e3d3
  - path: slice-worker/instance_lock.go
    hash: 8f36fa5f18e53fd975ba384be12c10b4977ecf34e8bcdc3de83a308fe5f3bfb5
  - path: slice-worker/main.go
    hash: bc78d3850e3ed4f76c8a5c3d99580862374c10c6c464fd1b02e64daed1430e98
  - path: slice-worker/redis_client.go
    hash: 9e927d48a03637cb0144a9ec2f60d8932bd15f91d9c3096e3c5b1687a41cd9c6
  - path: slice-worker/task_executor.go
    hash: aaa82c70cb559d63c5f7b83eba3c81864b5a2c63ed8e1b16426911aec96ab55b
  - path: slice-worker/worker.go
    hash: bd1b8addc17eb148fc81e26f8fccfb32d94936eed9c682ab3ae24b941ecc603b
sources_digest: 255ed8498ec8f4c22c858436710481d2d5f84a54b2e10b522c34ea187374c23a
links:
  - to: engine-update-versioning
    relation: implements
    description: >-
      worker.go and engine_update.go honor the backend's engine package endpoint
      and version-hash algorithm.
  - to: engine-update-versioning
    relation: uses
    description: Pulls engine tar.gz packages from the backend and applies them atomically.
  - to: redis-task-coordination-contract
    relation: implements
    description: >-
      redis_client.go must match the Python backend reader's stream/hash key
      layout and data contracts.
generator:
  version: 1
covers:
  - symbol: TaskCallback
    kind: struct
    at: 'slice-worker/callback.go:L12-L22'
  - symbol: OutputFileInfo
    kind: struct
    at: 'slice-worker/callback.go:L25-L30'
  - symbol: CallbackService
    kind: struct
    at: 'slice-worker/callback.go:L33-L37'
  - symbol: NewCallbackService
    kind: function
    at: 'slice-worker/callback.go:L40-L47'
  - symbol: SetToken
    kind: method
    at: 'slice-worker/callback.go:L50-L52'
  - symbol: SendCallback
    kind: method
    at: 'slice-worker/callback.go:L55-L88'
  - symbol: Config
    kind: struct
    at: 'slice-worker/config.go:L14-L43'
  - symbol: DefaultNodeID
    kind: function
    at: 'slice-worker/config.go:L50-L66'
  - symbol: DefaultConfig
    kind: function
    at: 'slice-worker/config.go:L69-L87'
  - symbol: LoadConfig
    kind: function
    at: 'slice-worker/config.go:L90-L114'
  - symbol: ClampCPUPercent
    kind: function
    at: 'slice-worker/config.go:L117-L125'
  - symbol: HeartbeatTTL
    kind: method
    at: 'slice-worker/config.go:L128-L133'
  - symbol: EffectiveConsumeStreams
    kind: method
    at: 'slice-worker/config.go:L146-L151'
  - symbol: GetOS
    kind: function
    at: 'slice-worker/config.go:L154-L156'
  - symbol: GetArch
    kind: function
    at: 'slice-worker/config.go:L159-L161'
  - symbol: GetFFmpegVersion
    kind: function
    at: 'slice-worker/config.go:L164-L175'
  - symbol: GetEncoderCapabilities
    kind: function
    at: 'slice-worker/config.go:L196-L214'
  - symbol: GetIP
    kind: function
    at: 'slice-worker/config.go:L221-L259'
  - symbol: isPrivateIPv4
    kind: function
    at: 'slice-worker/config.go:L262-L264'
  - symbol: nodeUpdateCommand
    kind: struct
    at: 'slice-worker/engine_update.go:L33-L36'
  - symbol: ComputeEngineVersion
    kind: function
    at: 'slice-worker/engine_update.go:L41-L60'
  - symbol: listEngineFiles
    kind: function
    at: 'slice-worker/engine_update.go:L63-L89'
  - symbol: PullEngineUpdate
    kind: function
    at: 'slice-worker/engine_update.go:L95-L130'
  - symbol: extractTarGz
    kind: function
    at: 'slice-worker/engine_update.go:L134-L198'
  - symbol: readUpdateCommandJSON
    kind: function
    at: 'slice-worker/engine_update.go:L201-L210'
  - symbol: TestComputeEngineVersionStable
    kind: function
    at: 'slice-worker/engine_update_test.go:L12-L49'
  - symbol: TestExtractTarGz
    kind: function
    at: 'slice-worker/engine_update_test.go:L51-L70'
  - symbol: TestExtractTarGzPathTraversal
    kind: function
    at: 'slice-worker/engine_update_test.go:L72-L85'
  - symbol: pythonBinary
    kind: function
    at: 'slice-worker/exec_unix.go:L15-L20'
  - symbol: SetProcessGroup
    kind: function
    at: 'slice-worker/exec_unix.go:L23-L25'
  - symbol: KillProcessTree
    kind: function
    at: 'slice-worker/exec_unix.go:L28-L38'
  - symbol: pythonBinary
    kind: function
    at: 'slice-worker/exec_windows.go:L11-L13'
  - symbol: SetProcessGroup
    kind: function
    at: 'slice-worker/exec_windows.go:L17-L19'
  - symbol: KillProcessTree
    kind: function
    at: 'slice-worker/exec_windows.go:L22-L29'
  - symbol: itoa
    kind: function
    at: 'slice-worker/exec_windows.go:L31-L48'
  - symbol: FileTransfer
    kind: struct
    at: 'slice-worker/file_transfer.go:L16-L19'
  - symbol: NewFileTransfer
    kind: function
    at: 'slice-worker/file_transfer.go:L22-L28'
  - symbol: SetProgressCallback
    kind: method
    at: 'slice-worker/file_transfer.go:L31-L33'
  - symbol: DownloadFile
    kind: method
    at: 'slice-worker/file_transfer.go:L36-L102'
  - symbol: UploadFile
    kind: method
    at: 'slice-worker/file_transfer.go:L105-L143'
  - symbol: UploadFileWithProgress
    kind: method
    at: 'slice-worker/file_transfer.go:L146-L190'
  - symbol: uploadURLResponse
    kind: struct
    at: 'slice-worker/file_transfer.go:L193-L196'
  - symbol: GetUploadURL
    kind: method
    at: 'slice-worker/file_transfer.go:L202-L239'
  - symbol: progressReader
    kind: struct
    at: 'slice-worker/file_transfer.go:L242-L249'
  - symbol: Read
    kind: method
    at: 'slice-worker/file_transfer.go:L251-L258'
  - symbol: WorkerHeartbeatPayload
    kind: struct
    at: 'slice-worker/heartbeat_backend.go:L15-L30'
  - symbol: WorkerHeartbeatResponse
    kind: struct
    at: 'slice-worker/heartbeat_backend.go:L34-L38'
  - symbol: sendBackendHeartbeat
    kind: method
    at: 'slice-worker/heartbeat_backend.go:L48-L102'
  - symbol: acquireInstanceLock
    kind: function
    at: 'slice-worker/instance_lock.go:L23-L59'
  - symbol: processAlive
    kind: function
    at: 'slice-worker/instance_lock.go:L62-L72'
  - symbol: main
    kind: function
    at: 'slice-worker/main.go:L15-L79'
  - symbol: runDaemon
    kind: function
    at: 'slice-worker/main.go:L82-L121'
  - symbol: runTUI
    kind: function
    at: 'slice-worker/main.go:L124-L197'
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
  - symbol: TaskExecutor
    kind: struct
    at: 'slice-worker/task_executor.go:L19-L22'
  - symbol: NewTaskExecutor
    kind: function
    at: 'slice-worker/task_executor.go:L25-L29'
  - symbol: SetProgressCallback
    kind: method
    at: 'slice-worker/task_executor.go:L32-L34'
  - symbol: ExecuteTask
    kind: method
    at: 'slice-worker/task_executor.go:L41-L391'
  - symbol: parseEngineLine
    kind: method
    at: 'slice-worker/task_executor.go:L395-L417'
  - symbol: collectOutputs
    kind: method
    at: 'slice-worker/task_executor.go:L420-L449'
  - symbol: cutSegment
    kind: struct
    at: 'slice-worker/task_executor.go:L453-L457'
  - symbol: parseCutlist
    kind: function
    at: 'slice-worker/task_executor.go:L461-L483'
  - symbol: parseCutTime
    kind: function
    at: 'slice-worker/task_executor.go:L486-L521'
  - symbol: outputName
    kind: method
    at: 'slice-worker/task_executor.go:L524-L530'
  - symbol: filterCompletedSegments
    kind: method
    at: 'slice-worker/task_executor.go:L539-L553'
  - symbol: preservedOutputs
    kind: method
    at: 'slice-worker/task_executor.go:L556-L571'
  - symbol: outputFileValid
    kind: method
    at: 'slice-worker/task_executor.go:L576-L586'
  - symbol: ffprobeDurationSec
    kind: function
    at: 'slice-worker/task_executor.go:L589-L602'
  - symbol: readCompletedCheckpoint
    kind: method
    at: 'slice-worker/task_executor.go:L608-L621'
  - symbol: appendCompletedCheckpoint
    kind: method
    at: 'slice-worker/task_executor.go:L624-L651'
  - symbol: cutlistForSegments
    kind: function
    at: 'slice-worker/task_executor.go:L655-L661'
  - symbol: formatSec
    kind: function
    at: 'slice-worker/task_executor.go:L664-L674'
  - symbol: mergeOutputPaths
    kind: function
    at: 'slice-worker/task_executor.go:L677-L688'
  - symbol: Worker
    kind: struct
    at: 'slice-worker/worker.go:L26-L53'
  - symbol: RunningTask
    kind: struct
    at: 'slice-worker/worker.go:L56-L67'
  - symbol: NewWorker
    kind: function
    at: 'slice-worker/worker.go:L70-L81'
  - symbol: setBackendEnabled
    kind: method
    at: 'slice-worker/worker.go:L84-L86'
  - symbol: getBackendEnabled
    kind: method
    at: 'slice-worker/worker.go:L89-L91'
  - symbol: SetCallbacks
    kind: method
    at: 'slice-worker/worker.go:L94-L124'
  - symbol: checkEngine
    kind: method
    at: 'slice-worker/worker.go:L132-L156'
  - symbol: Run
    kind: method
    at: 'slice-worker/worker.go:L158-L287'
  - symbol: cleanupOrphanDirs
    kind: method
    at: 'slice-worker/worker.go:L300-L338'
  - symbol: waitRunningTasks
    kind: method
    at: 'slice-worker/worker.go:L341-L359'
  - symbol: claimLoop
    kind: method
    at: 'slice-worker/worker.go:L362-L385'
  - symbol: claimOnce
    kind: method
    at: 'slice-worker/worker.go:L390-L424'
  - symbol: logPendingOverview
    kind: method
    at: 'slice-worker/worker.go:L427-L440'
  - symbol: stuckTaskLoop
    kind: method
    at: 'slice-worker/worker.go:L449-L484'
  - symbol: requeueStuckTask
    kind: method
    at: 'slice-worker/worker.go:L489-L527'
  - symbol: runTask
    kind: method
    at: 'slice-worker/worker.go:L530-L776'
  - symbol: handleTaskError
    kind: method
    at: 'slice-worker/worker.go:L779-L859'
  - symbol: sendFailureCallback
    kind: method
    at: 'slice-worker/worker.go:L862-L874'
  - symbol: watchCancellation
    kind: method
    at: 'slice-worker/worker.go:L877-L897'
  - symbol: leaseRenewal
    kind: method
    at: 'slice-worker/worker.go:L905-L936'
  - symbol: heartbeatLoop
    kind: method
    at: 'slice-worker/worker.go:L939-L961'
  - symbol: engineUpdateLoop
    kind: method
    at: 'slice-worker/worker.go:L970-L986'
  - symbol: checkEngineUpdate
    kind: method
    at: 'slice-worker/worker.go:L989-L1028'
  - symbol: emitProgress
    kind: method
    at: 'slice-worker/worker.go:L1031-L1044'
  - symbol: matchTags
    kind: method
    at: 'slice-worker/worker.go:L1047-L1063'
  - symbol: log
    kind: method
    at: 'slice-worker/worker.go:L1066-L1073'
  - symbol: GetRunningTasks
    kind: method
    at: 'slice-worker/worker.go:L1076-L1083'
  - symbol: CancelTask
    kind: method
    at: 'slice-worker/worker.go:L1086-L1095'
  - symbol: GetCurrentTaskCount
    kind: method
    at: 'slice-worker/worker.go:L1098-L1100'
  - symbol: getHostname
    kind: function
    at: 'slice-worker/worker.go:L1103-L1109'
  - symbol: getFileSize
    kind: function
    at: 'slice-worker/worker.go:L1112-L1117'
  - symbol: strconvParseInt
    kind: function
    at: 'slice-worker/worker.go:L1120-L1132'
---
<!-- context:generated:start -->
## Summary

The Go daemon that executes distributed video-slicing tasks. It consumes tasks from Redis Streams, downloads source media, invokes the shared Python engine (engines/slice.py) via TaskExecutor, uploads outputs to MinIO through presigned URLs, and reports back via HTTP callbacks and dual-write heartbeats (Redis + backend DB). Runs in three modes (daemon, TUI, tray) with a single-instance PID lock per node ID to prevent duplicate heartbeats.

## Related

- implements [[engine-update-versioning]] — worker.go and engine_update.go honor the backend's engine package endpoint and version-hash algorithm.
- uses [[engine-update-versioning]] — Pulls engine tar.gz packages from the backend and applies them atomically.
- implements [[redis-task-coordination-contract]] — redis_client.go must match the Python backend reader's stream/hash key layout and data contracts.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
