---
name: Worker Platform Abstractions
slug: worker-platform-abstractions
type: system
sources:
  - path: slice-worker/exec_unix.go
    hash: 1eb3913aa803e243694c6d4e8e60981892695b489b63332b50f9138219859645
  - path: slice-worker/exec_windows.go
    hash: 883135be9e98a52b97d7c11d4f841e1e6ba806ecd7d042a04e921ceea0c6abe5
  - path: slice-worker/tray_common.go
    hash: 364b126de1c8bf280cb71d734bf4fe0331cc52e1834f0d2a0bbac179d2c618e3
  - path: slice-worker/tray_darwin_nocgo.go
    hash: 6ee4f717f5c651df7c33cb54b5a3e6c3250aab65c9fb5aa769186619b7eb1f96
  - path: slice-worker/tray_darwin.go
    hash: c4be27578e7e87d6f06247bdbc0f0835db7abbc416e9e2ca52d831fbe6e1efd3
  - path: slice-worker/tray_other.go
    hash: 2eb2ae7e0a13dce177b707861db082c39b6a07d592128ac0f6871274f96a7411
  - path: slice-worker/tray_windows.go
    hash: e82ad00a0fb50404af0e3f3246e662c3aba17fdfb5aadd4832d35e21bc8fdcce
  - path: slice-worker/tray.go
    hash: da296d0d58701255e632a94b05a5bcca4b9ca96e56203685a5f7c65c6d115fac
  - path: slice-worker/tui.go
    hash: 64ba4bf1d3b3186e398514fadbc47c0f6eb68593f79f1ca47d377693fbea0cf2
sources_digest: 9537a4191ef753eeadaf3e71b30dea359329cd95027273a0de48fa168f8aedc6
links:
  - to: slice-worker-node
    relation: part_of
    description: >-
      These files provide the platform-specific plumbing the worker main loop
      runs on.
generator:
  version: 1
covers:
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
  - symbol: MacOSTray
    kind: struct
    at: 'slice-worker/tray_darwin.go:L20-L29'
  - symbol: newPlatformTrayController
    kind: function
    at: 'slice-worker/tray_darwin.go:L32-L34'
  - symbol: iconBytes
    kind: method
    at: 'slice-worker/tray_darwin.go:L36-L43'
  - symbol: Start
    kind: method
    at: 'slice-worker/tray_darwin.go:L51-L58'
  - symbol: onReady
    kind: method
    at: 'slice-worker/tray_darwin.go:L60-L123'
  - symbol: setCPU
    kind: method
    at: 'slice-worker/tray_darwin.go:L126-L130'
  - symbol: refresh
    kind: method
    at: 'slice-worker/tray_darwin.go:L132-L160'
  - symbol: SetOnline
    kind: method
    at: 'slice-worker/tray_darwin.go:L162-L166'
  - symbol: Notify
    kind: method
    at: 'slice-worker/tray_darwin.go:L168-L170'
  - symbol: Stop
    kind: method
    at: 'slice-worker/tray_darwin.go:L172-L174'
  - symbol: NoCgoMacTray
    kind: struct
    at: 'slice-worker/tray_darwin_nocgo.go:L14-L16'
  - symbol: newPlatformTrayController
    kind: function
    at: 'slice-worker/tray_darwin_nocgo.go:L18-L20'
  - symbol: Start
    kind: method
    at: 'slice-worker/tray_darwin_nocgo.go:L22-L25'
  - symbol: Stop
    kind: method
    at: 'slice-worker/tray_darwin_nocgo.go:L27-L27'
  - symbol: SetOnline
    kind: method
    at: 'slice-worker/tray_darwin_nocgo.go:L29-L29'
  - symbol: Notify
    kind: method
    at: 'slice-worker/tray_darwin_nocgo.go:L31-L33'
  - symbol: NoopTray
    kind: struct
    at: 'slice-worker/tray_other.go:L13-L15'
  - symbol: newPlatformTrayController
    kind: function
    at: 'slice-worker/tray_other.go:L17-L19'
  - symbol: Start
    kind: method
    at: 'slice-worker/tray_other.go:L21-L24'
  - symbol: Stop
    kind: method
    at: 'slice-worker/tray_other.go:L26-L26'
  - symbol: SetOnline
    kind: method
    at: 'slice-worker/tray_other.go:L28-L28'
  - symbol: Notify
    kind: method
    at: 'slice-worker/tray_other.go:L30-L32'
  - symbol: WindowsTray
    kind: struct
    at: 'slice-worker/tray_windows.go:L26-L36'
  - symbol: newPlatformTrayController
    kind: function
    at: 'slice-worker/tray_windows.go:L39-L41'
  - symbol: iconBytes
    kind: method
    at: 'slice-worker/tray_windows.go:L43-L50'
  - symbol: Start
    kind: method
    at: 'slice-worker/tray_windows.go:L54-L67'
  - symbol: onReady
    kind: method
    at: 'slice-worker/tray_windows.go:L69-L119'
  - symbol: refresh
    kind: method
    at: 'slice-worker/tray_windows.go:L122-L144'
  - symbol: SetOnline
    kind: method
    at: 'slice-worker/tray_windows.go:L146-L151'
  - symbol: Notify
    kind: method
    at: 'slice-worker/tray_windows.go:L153-L156'
  - symbol: Stop
    kind: method
    at: 'slice-worker/tray_windows.go:L158-L161'
  - symbol: TaskStatus
    kind: struct
    at: 'slice-worker/tui.go:L73-L84'
  - symbol: LogEntry
    kind: struct
    at: 'slice-worker/tui.go:L87-L91'
  - symbol: TUIModel
    kind: struct
    at: 'slice-worker/tui.go:L94-L116'
  - symbol: NewTUIModel
    kind: function
    at: 'slice-worker/tui.go:L119-L128'
  - symbol: Init
    kind: method
    at: 'slice-worker/tui.go:L133-L138'
  - symbol: Update
    kind: method
    at: 'slice-worker/tui.go:L141-L212'
  - symbol: View
    kind: method
    at: 'slice-worker/tui.go:L215-L243'
  - symbol: renderHeader
    kind: method
    at: 'slice-worker/tui.go:L247-L258'
  - symbol: renderStatusBar
    kind: method
    at: 'slice-worker/tui.go:L260-L274'
  - symbol: renderTaskList
    kind: method
    at: 'slice-worker/tui.go:L276-L307'
  - symbol: renderTaskItem
    kind: method
    at: 'slice-worker/tui.go:L309-L380'
  - symbol: renderProgressBar
    kind: method
    at: 'slice-worker/tui.go:L382-L391'
  - symbol: renderLogPanel
    kind: method
    at: 'slice-worker/tui.go:L393-L438'
  - symbol: renderFooter
    kind: method
    at: 'slice-worker/tui.go:L440-L447'
  - symbol: addLog
    kind: method
    at: 'slice-worker/tui.go:L451-L462'
  - symbol: getActiveTasks
    kind: method
    at: 'slice-worker/tui.go:L464-L472'
  - symbol: formatDuration
    kind: function
    at: 'slice-worker/tui.go:L474-L482'
  - symbol: TickMsg
    kind: type
    at: 'slice-worker/tui.go:L486-L486'
  - symbol: TaskStartMsg
    kind: struct
    at: 'slice-worker/tui.go:L488-L492'
  - symbol: TaskProgressMsg
    kind: struct
    at: 'slice-worker/tui.go:L494-L499'
  - symbol: TaskCompleteMsg
    kind: struct
    at: 'slice-worker/tui.go:L501-L504'
  - symbol: TaskErrorMsg
    kind: struct
    at: 'slice-worker/tui.go:L506-L509'
  - symbol: LogMsg
    kind: struct
    at: 'slice-worker/tui.go:L511-L514'
  - symbol: StatusMsg
    kind: struct
    at: 'slice-worker/tui.go:L516-L518'
  - symbol: tickCmd
    kind: method
    at: 'slice-worker/tui.go:L522-L526'
---
<!-- context:generated:start -->
## Summary

The cross-platform surface of the worker: process management (Unix process groups vs Windows taskkill), Python binary resolution (python3 vs python, with SLICE_PYTHON override for 3.10+), and the TrayController interface with per-OS implementations (Windows systray, macOS cgo systray, macOS no-cgo fallback, Linux no-op). systray.Run must run on the main goroutine with a locked OS thread on both desktop platforms, so the worker main loop runs in a separate goroutine.

## Related

- part of [[slice-worker-node]] — These files provide the platform-specific plumbing the worker main loop runs on.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
