# slice-worker/file_transfer.go · [[slice-worker-node]]

- FileTransfer · struct · L16-L19 — FileTransfer
- NewFileTransfer · function · L22-L28 — func NewFileTransfer() *FileTransfer
- SetProgressCallback · method · L31-L33 — func (ft *FileTransfer) SetProgressCallback(cb func(taskID string, fileName string, downloaded, total int64))
- DownloadFile · method · L36-L102 — func (ft *FileTransfer) DownloadFile(ctx context.Context, url, destPath, taskID string) error
- UploadFile · method · L105-L143 — func (ft *FileTransfer) UploadFile(ctx context.Context, filePath, uploadURL, taskID string) error
- UploadFileWithProgress · method · L146-L190 — func (ft *FileTransfer) UploadFileWithProgress(ctx context.Context, filePath, uploadURL, taskID string) error
- uploadURLResponse · struct · L193-L196 — uploadURLResponse
- GetUploadURL · method · L202-L239 — func (ft *FileTransfer) GetUploadURL(ctx context.Context, backendURL, taskID, fileName, token string) (string, string, error)
- progressReader · struct · L242-L249 — progressReader
- Read · method · L251-L258 — func (pr *progressReader) Read(p []byte) (n int, err error)
