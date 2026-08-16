# slice-worker/file_transfer.go

- FileTransfer · struct · L15-L18 — FileTransfer
- NewFileTransfer · function · L21-L27 — func NewFileTransfer() *FileTransfer
- SetProgressCallback · method · L30-L32 — func (ft *FileTransfer) SetProgressCallback(cb func(taskID string, fileName string, downloaded, total int64))
- DownloadFile · method · L35-L101 — func (ft *FileTransfer) DownloadFile(ctx context.Context, url, destPath, taskID string) error
- UploadFile · method · L104-L142 — func (ft *FileTransfer) UploadFile(ctx context.Context, filePath, uploadURL, taskID string) error
- UploadFileWithProgress · method · L145-L189 — func (ft *FileTransfer) UploadFileWithProgress(ctx context.Context, filePath, uploadURL, taskID string) error
- uploadURLResponse · struct · L192-L195 — uploadURLResponse
- GetUploadURL · method · L201-L235 — func (ft *FileTransfer) GetUploadURL(ctx context.Context, backendURL, taskID, fileName, token string) (string, string, error)
- progressReader · struct · L238-L245 — progressReader
- Read · method · L247-L254 — func (pr *progressReader) Read(p []byte) (n int, err error)
