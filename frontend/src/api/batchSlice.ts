import client from './client';
import type { SliceOutput } from '../types';

export interface BatchEpisodeItem {
  title?: string;
  path: string;
}

export interface BatchSliceRunRequest {
  drama: string;
  episodes: BatchEpisodeItem[];
  slice_config?: Record<string, unknown>;
  auto_delete_source?: boolean;
}

export interface BatchSliceRunResponse {
  batch_id: string;
  total: number;
  message: string;
}

export interface BatchSliceItem {
  id: string;
  seq: number;
  title: string | null;
  source_path: string | null;
  file_name: string | null;
  episode_id: string | null;
  slice_task_id: string | null;
  status: string;
  phase: string | null;
  progress: number;
  output_count: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface BatchSlice {
  id: string;
  name: string | null;
  project_id: string | null;
  slice_config: Record<string, unknown> | null;
  status: string;
  total: number;
  done: number;
  failed: number;
  output_count: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface BatchSliceOutputItem {
  seq: number;
  title: string | null;
  episode_id: string | null;
  slice_task_id: string | null;
  item_status: string;
  output: Record<string, unknown> | null;
}

export interface BatchSliceOutputResponse {
  batch_id: string;
  items: BatchSliceOutputItem[];
}

export const batchSliceApi = {
  run: (data: BatchSliceRunRequest) =>
    client.post('/batch-slice/run', data) as Promise<BatchSliceRunResponse>,

  list: (page = 1, pageSize = 20) =>
    client.get('/batch-slice', { params: { page, page_size: pageSize } }) as Promise<BatchSlice[]>,

  getById: (batchId: string) =>
    client.get(`/batch-slice/${batchId}`) as Promise<BatchSlice>,

  getItems: (batchId: string) =>
    client.get(`/batch-slice/${batchId}/items`) as Promise<BatchSliceItem[]>,

  getOutputs: (batchId: string) =>
    client.get(`/batch-slice/${batchId}/outputs`) as Promise<BatchSliceOutputResponse>,

  retry: (batchId: string) =>
    client.post(`/batch-slice/${batchId}/retry`) as Promise<BatchSliceRunResponse>,

  cancel: (batchId: string) =>
    client.post(`/batch-slice/${batchId}/cancel`) as Promise<{ batch_id: string; message: string }>,
};
