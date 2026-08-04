import client from './client';
import type { ApiResponse, Episode } from '../types';

export const uploadApi = {
  /** 上传视频文件 */
  uploadFile(projectId: number, file: File, onProgress?: (percent: number) => void) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', String(projectId));

    return client.post<ApiResponse<Episode>>('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    });
  },

  /** 获取上传记录 */
  getUploads(episodeId: number) {
    return client.get<ApiResponse<Episode>>(`/upload/${episodeId}`);
  },
};