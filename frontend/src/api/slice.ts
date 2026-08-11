import client from './client';
import type { ApiList, DedupeConfig, SliceOutput, SliceTask } from '../types';

export interface BadgeItem {
  file_key: string;
  position: string;
  width?: number;
  offset?: number;
  opacity?: number;
}

export interface BadgeUploadResult {
  file_name: string;
  file_key: string;
  file_size: number;
  upload_id: string;
}

export const sliceApi = {
  run: (
    episodeId: string,
    mode: string,
    data?: {
      dedupe_config?: DedupeConfig;
      video_path?: string;
      engine?: string;
      auto_accept_all?: boolean;
      watermark_enabled?: boolean;
      watermark_text?: string;
      watermark_font_size?: number;
      watermark_opacity?: number;
      watermark_position?: string;
      // 图片角标：每个含 file_key（上传的角标图片 MinIO key）、position（位置）、width（可选宽度）、offset（可选偏移）、opacity（可选透明度）
      badges?: BadgeItem[];
      // 角标默认尺寸（px）：角标未单独设 width 时生效；0=保持原图尺寸
      badge_default_width?: number;
      // 竖屏转横屏智能裁切（切片前预处理）
      vert2horiz_enabled?: boolean;
      vert2horiz_mode?: 'fixed' | 'dynamic';
      vert2horiz_ratio?: number;
      vert2horiz_output_size?: string;
      vert2horiz_detect_interval?: number;
      vert2horiz_smooth_window?: number;
      // 成品重新剪辑：以某个切片输出为源，重新裁剪出一个新片段
      output_id?: string;
      cut_start?: number;
      cut_end?: number;
    }
  ) =>
    client.post(`/episodes/${episodeId}/slice/run`, { mode, ...data }) as Promise<{
      task_id: string;
      engine: string;
      message: string;
    }>,

  // 上传角标图片
  uploadBadge: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/slice/badge-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<BadgeUploadResult>;
  },

  listTasks: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/slice/tasks`) as Promise<SliceTask[]>,

  getTask: (taskId: string) =>
    client.get(`/slice-tasks/${taskId}`) as Promise<SliceTask>,

  getOutputs: (taskId: string) =>
    client.get(`/slice-tasks/${taskId}/outputs`) as Promise<SliceOutput[]>,

  cancel: (taskId: string) =>
    client.post(`/slice-tasks/${taskId}/cancel`) as Promise<{ message: string }>,

  delete: (taskId: string) =>
    client.delete(`/slice-tasks/${taskId}`) as Promise<{ message: string; task_id: string }>,

  retry: (taskId: string) =>
    client.post(`/slice-tasks/${taskId}/retry`) as Promise<{
      task_id: string;
      message: string;
    }>,

  listWorkers: () =>
    client.get(`/workers`) as Promise<any[]>,

  syncWorkers: () =>
    client.post(`/workers/sync-redis`) as Promise<{ synced: number; message: string }>,

  enableWorker: (nodeId: string) =>
    client.post(`/workers/${nodeId}/enable`) as Promise<{ message: string; enabled: boolean }>,

  disableWorker: (nodeId: string) =>
    client.post(`/workers/${nodeId}/disable`) as Promise<{ message: string; enabled: boolean }>,

  setWorkerCpuPercent: (nodeId: string, cpuPercent: number) =>
    client.post(`/workers/${nodeId}/cpu-percent`, { cpu_percent: cpuPercent }) as Promise<{
      message: string;
      cpu_percent: number;
    }>,
};
