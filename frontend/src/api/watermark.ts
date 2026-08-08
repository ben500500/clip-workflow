import client from './client';

export interface WatermarkVideoItem {
  id: string;
  file_name: string;
  file_size: number | null;
  status: string;
  progress: number;
  error_message: string | null;
  output_url: string | null;
  source_url: string | null;
  output_file_size: number | null;
  created_at: string;
  started_at?: string | null;
  completed_at: string | null;
  duration_seconds?: number | null;
}

export interface WatermarkTaskItem {
  id: string;
  engine: string;
  engine_display: string;
  name: string | null;
  options: Record<string, unknown>;
  status: string;
  progress: number;
  total_count: number;
  completed_count: number;
  failed_count: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  duration_seconds?: number | null;
}

export interface WatermarkTaskDetail extends WatermarkTaskItem {
  videos: WatermarkVideoItem[];
}

export interface WatermarkUploadResult {
  file_name: string;
  source_file_key: string;
  file_size: number;
  upload_id: string;
}

export interface WatermarkRunParams {
  engine: 'remove_ai' | 'seedance' | 'seedance_wm' | 'remove_mask';
  mark?: string;
  backend?: string;
  temporal_consistency?: boolean;
  region?: string;
  use_lama?: boolean;
  segments?: number;
  detector?: string;
  inpainter?: string;
  keep_audio?: boolean;
  radius?: number;
  iterations?: number;
  name?: string;
  files: string[];
}

export const watermarkApi = {
  upload: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/watermark/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<WatermarkUploadResult>;
  },

  run: (params: WatermarkRunParams) =>
    client.post('/watermark/run', params) as Promise<{
      task_id: string;
      engine: string;
      message: string;
    }>,

  listTasks: () =>
    client.get('/watermark/tasks') as Promise<WatermarkTaskItem[]>,

  getTask: (taskId: string) =>
    client.get(`/watermark/tasks/${taskId}`) as Promise<WatermarkTaskDetail>,

  deleteTask: (taskId: string) =>
    client.delete(`/watermark/tasks/${taskId}`) as Promise<{ message: string; task_id: string }>,

  batchDeleteTasks: (taskIds: string[]) =>
    client.post('/watermark/tasks/batch-delete', { task_ids: taskIds }) as Promise<{
      message: string;
      deleted: number;
    }>,

  deleteVideo: (videoId: string) =>
    client.delete(`/watermark/videos/${videoId}`) as Promise<{ message: string; video_id: string }>,

  downloadVideo: (videoId: string) =>
    client.get(`/watermark/videos/${videoId}/download`) as Promise<{
      url: string;
      file_name: string;
    }>,

  batchDownload: (videoIds: string[]) =>
    client.post('/watermark/videos/batch-download', { video_ids: videoIds }) as Promise<{
      files: { video_id: string; file_name: string; url: string }[];
    }>,
};
