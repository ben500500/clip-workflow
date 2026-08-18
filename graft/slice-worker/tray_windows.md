# slice-worker/tray_windows.go · [[worker-platform-abstractions]]

- WindowsTray · struct · L26-L36 — WindowsTray
- newPlatformTrayController · function · L39-L41 — func newPlatformTrayController() TrayController
- iconBytes · method · L43-L50 — func (t *WindowsTray) iconBytes() []byte
- Start · method · L54-L67 — func (t *WindowsTray) Start(ui *TrayUI)
- onReady · method · L69-L119 — func (t *WindowsTray) onReady()
- refresh · method · L122-L144 — func (t *WindowsTray) refresh()
- SetOnline · method · L146-L151 — func (t *WindowsTray) SetOnline(online bool)
- Notify · method · L153-L156 — func (t *WindowsTray) Notify(title, msg string)
- Stop · method · L158-L161 — func (t *WindowsTray) Stop()
