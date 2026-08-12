import client from './client';

// 批量切片批次项
export interface BatchSliceItem {
  id: string;
  batch_id: string;
  seq?: number;
  title?: string;
  source_path?: string;
  source_file_key?: string;
  episode_id?: string;
  status: string;
  progress: number;
  message?: string;
  error_message?: string;
  output_count: number;
  processed_at?: string;
  created_at: string;
}

// 批量切片批次
export interface BatchSlice {
  id: string;
  name?: string;
  drama_name?: string;
  project_id: string;
  status: string;
  total: number;
  done: number;
  failed: number;
  output_count: number;
  delete_source: boolean;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

// 单个剧集
export interface BatchEpisodeItem {
  title?: string;
  path: string;
}

// 输出项
export interface BatchOutputItem {
  file_name?: string;
  file_key?: string;
  duration?: number;
  file_size?: number;
  resolution?: string;
  presigned_url?: string;
}

// 每集输出
export interface BatchOutputEntry {
  seq?: number;
  title?: string;
  episode_id?: string;
  status: string;
  outputs: BatchOutputItem[];
}

export interface BatchOutputs {
  batch_id: string;
  items: BatchOutputEntry[];
}

export const batchSliceApi = {
  // 创建批量切片批次（剧名 + 剧集列表 + 一键切片配置）
  run: (payload: {
    drama: string;
    episodes: BatchEpisodeItem[];
    slice_config?: Record<string, unknown>;
    delete_source?: boolean;
  }) =>
    client.post('/batch-slice/run', payload) as Promise<BatchSlice>,

  // 批次进度
  get: (batchId: string) =>
    client.get(`/batch-slice/${batchId}`) as Promise<BatchSlice>,

  // 批次项（每集状态）
  items: (batchId: string) =>
    client.get(`/batch-slice/${batchId}/items`) as Promise<BatchSliceItem[]>,

  // 输出列表
  outputs: (batchId: string) =>
    client.get(`/batch-slice/${batchId}/outputs`) as Promise<BatchOutputs>,
};
