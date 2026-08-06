import client from './client';
import type { ApiList, DedupeConfig, SliceOutput, SliceTask } from '../types';

export const sliceApi = {
  run: (
    episodeId: string,
    mode: string,
    data?: { dedupe_config?: DedupeConfig; video_path?: string; engine?: string; auto_accept_all?: boolean }
  ) =>
    client.post(`/episodes/${episodeId}/slice/run`, { mode, ...data }) as Promise<{
      task_id: string;
      engine: string;
      message: string;
    }>,

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
};
