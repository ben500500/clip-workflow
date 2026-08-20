# slice-worker/tray_darwin.go · [[worker-platform-abstractions]]

- MacOSTray · struct · L20-L29 — MacOSTray
- newPlatformTrayController · function · L32-L34 — func newPlatformTrayController() TrayController
- iconBytes · method · L36-L43 — func (t *MacOSTray) iconBytes() []byte
- Start · method · L51-L58 — func (t *MacOSTray) Start(ui *TrayUI)
- onReady · method · L60-L123 — func (t *MacOSTray) onReady()
- setCPU · method · L126-L130 — func (t *MacOSTray) setCPU(target int)
- refresh · method · L132-L160 — func (t *MacOSTray) refresh()
- SetOnline · method · L162-L166 — func (t *MacOSTray) SetOnline(online bool)
- Notify · method · L168-L170 — func (t *MacOSTray) Notify(title, msg string)
- Stop · method · L172-L174 — func (t *MacOSTray) Stop()
