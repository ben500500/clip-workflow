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
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
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
};
