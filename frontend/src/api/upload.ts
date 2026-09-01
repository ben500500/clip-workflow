import client from './client';
import type { Episode } from '../types';

export const uploadApi = {
  uploadFile: (projectId: string, file: File, onProgress?: (percent: number) => void, signal?: AbortSignal) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', projectId);
    return client.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      signal,
      onUploadProgress: (progressEvent) => {
        if (!onProgress) return;
        // total 缺失（极少数浏览器/请求下 progressEvent.total 为 0/undefined）
        // 时无法计算百分比，回传 -1 让前端显示「上传中…」活动态，避免进度条冻在 0%。
        if (!progressEvent.total) {
          onProgress(-1);
          return;
        }
        const percent = Math.min(99, Math.round((progressEvent.loaded * 100) / progressEvent.total));
        onProgress(percent);
      },
    }) as Promise<Episode>;
  },

  resume: (data: { file_name: string; file_size: number; chunk_size?: number; metadata?: Record<string, unknown> }) =>
    client.post('/upload/resume', data) as Promise<{
      id: string;
      file_name: string;
      file_size: number;
      chunk_size: number;
      offset: number;
      metadata: Record<string, unknown>;
    }>,

  uploadChunk: (uploadId: string, blob: Blob, offset: number) =>
    client.patch(`/upload/${uploadId}`, blob, {
      headers: { 'Content-Type': 'application/octet-stream', 'Upload-Offset': String(offset) },
    }) as Promise<{ id: string; offset: number; completed: boolean; progress_pct: number }>,

  complete: (data: { upload_id: string; project_id: string; title?: string; episode_no?: number }) =>
    client.post('/upload/complete', data) as Promise<Episode>,

  // 多视频批量上传正片：可选择是否合并成一个视频创建项目（项目名称由用户输入）
  uploadMulti: (params: {
    projectId?: string;
    projectName?: string;
    files: File[];
    merge: boolean;
    title?: string;
    description?: string;
    secondDiff?: boolean;
    onProgress?: (percent: number) => void;
  }) => {
    const formData = new FormData();
    if (params.projectId) formData.append('project_id', params.projectId);
    if (params.projectName) formData.append('project_name', params.projectName);
    formData.append('merge', params.merge ? 'true' : 'false');
    if (params.title) formData.append('title', params.title);
    if (params.description) formData.append('description', params.description);
    if (params.secondDiff !== undefined) {
      formData.append('second_diff_detect', params.secondDiff ? 'true' : 'false');
    }
    params.files.forEach((f) => formData.append('files', f));
    return client.post('/upload/multi', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 7200000,
      onUploadProgress: (progressEvent) => {
        if (!params.onProgress) return;
        if (!progressEvent.total) {
          params.onProgress(-1);
          return;
        }
        const percent = Math.min(99, Math.round((progressEvent.loaded * 100) / progressEvent.total));
        params.onProgress(percent);
      },
    }) as Promise<{
      project_id: string;
      project_name: string;
      episodes: Episode[];
      message: string;
      warnings?: string[];
    }>;
  },
};
