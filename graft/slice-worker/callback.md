# slice-worker/callback.go

- TaskCallback · struct · L12-L22 — TaskCallback
- OutputFileInfo · struct · L25-L30 — OutputFileInfo
- CallbackService · struct · L33-L37 — CallbackService
- NewCallbackService · function · L40-L47 — func NewCallbackService(nodeID string) *CallbackService
- SetToken · method · L50-L52 — func (cs *CallbackService) SetToken(token string)
- SendCallback · method · L55-L88 — func (cs *CallbackService) SendCallback(callbackURL string, data *TaskCallback) error
