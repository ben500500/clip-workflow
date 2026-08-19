import client from './client';

export interface DedupeUploadResult {
  path: string;
  file_name: string;
  file_size: number;
  content_type: string;
}

export interface DedupeUploadedFile {
  // 上传成功后的本地标识（用于前端列表展示）
  uid: string;
  file_name: string;
  file_size: number;
  // 上传成功后由后端返回的服务器本地 path，供 batch-slice/run 使用
  path: string;
  status: 'uploading' | 'done' | 'error';
  error?: string;
}

export const dedupeApi = {
  /** 去重处理入口：上传一个视频到服务器本地临时目录，返回 path 供 batch-slice/run 使用。 */
  upload: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/dedupe/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<DedupeUploadResult>;
  },
};
