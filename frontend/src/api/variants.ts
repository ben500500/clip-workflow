import client from './client';

export interface VariantFingerprint {
  algorithm: string;
  hash_value?: string | null;
  duration?: number | null;
}

export interface VariantMatrixItem {
  id: string;
  variant_index: number;
  status: string;
  file_name?: string | null;
  file_key?: string | null;
  preview_url?: string | null;
  phash_distance?: number | null;
  audio_distance?: number | null;
  seg_distance?: number | null;
  // 各算法指纹可用性标注：false 表示指纹缺失，distance 为降级占位 1.0（非真实无差异）
  available?: { phash?: boolean; audio?: boolean; seg?: boolean } | null;
  structural_diff?: Record<string, unknown> | null;
  collision: boolean;
  collision_reason?: string | null;
  account_id?: string | null;
  created_at?: string;
}

export interface VariantGroup {
  variant_group_id: string;
  base_output_id: string;
  base_file_name?: string | null;
  created_at?: string;
  variants: VariantMatrixItem[];
}

export interface VariantMatrix {
  variant_groups: VariantGroup[];
  thresholds: Record<string, number>;
}

export interface VariantDetail extends VariantMatrixItem {
  variant_group_id?: string | null;
  dedupe_config?: Record<string, unknown> | null;
  fingerprints: VariantFingerprint[];
}

export interface VariantVerifyResult {
  safe: boolean;
  distances: Record<string, number>;
  reason?: string;
}

export interface SliceOutputListItem {
  id: string;
  task_id: string;
  file_name: string | null;
  file_key: string | null;
  duration: number | null;
  file_size: number | null;
  resolution: string | null;
  variant_group_id: string | null;
  created_at: string;
  presigned_url: string | null;
}

export interface SliceOutputEpisode {
  episode_id: string | null;
  episode_title: string;
  drama_name: string | null;
  outputs: SliceOutputListItem[];
}

export interface SliceOutputProject {
  project_id: string | null;
  project_name: string;
  episodes: SliceOutputEpisode[];
}

export interface SliceOutputList {
  groups: SliceOutputProject[];
  total: number;
  page: number;
  page_size: number;
}

export const variantsApi = {
  matrix: () => client.get('/variant-matrix') as Promise<VariantMatrix>,

  detail: (id: string) => client.get(`/variants/${id}`) as Promise<VariantDetail>,

  generate: (data: { output_id: string; count?: number; dedupe_config?: Record<string, unknown>; thresholds?: Record<string, unknown> }) =>
    client.post('/variants/generate', data) as Promise<{ task_id: string; output_id: string; count: number }>,

  // 去重处理入口：批量对多个切片输出生成变体（单次投递全部任务，比前端循环稳）
  generateBatch: (data: { output_ids: string[]; count?: number; dedupe_config?: Record<string, unknown>; thresholds?: Record<string, unknown> }) =>
    client.post('/variants/generate-batch', data) as Promise<{
      tasks: { output_id: string; task_id: string }[];
      count: number;
      total: number;
    }>,

  // 去重处理入口：列出全部已切片输出（SliceOutput 多选）
  listSliceOutputs: (params: { page?: number; page_size?: number; keyword?: string } = {}) =>
    client.get('/dedupe/slice-outputs', { params }) as Promise<SliceOutputList>,

  verify: (id: string) =>
    client.post(`/variants/${id}/verify`) as Promise<VariantVerifyResult>,

  bind: (id: string, account_id?: string | null) =>
    client.post(`/variants/${id}/bind`, { variant_id: id, account_id }) as Promise<{ variant_id: string; account_id: string | null }>,

  updateThresholds: (data: Partial<Record<'phash' | 'audio' | 'seg' | 'combined', number>>) =>
    client.put('/variant-thresholds', data) as Promise<Record<string, number>>,

  // #274 A4：清理存量卡住的 running 变体（标记为 failed）
  cleanupStuck: (timeoutMinutes = 30) =>
    client.post('/variants/cleanup-stuck', null, { params: { timeout_minutes: timeoutMinutes } }) as Promise<{
      cleaned: number;
      remaining_running: number;
      stuck_count: number;
    }>,

  // #274 B：删除单变体（DB + MinIO）
  removeVariant: (id: string) =>
    client.delete(`/variants/${id}`) as Promise<{ deleted: string }>,

  // #274 B：删除整组（组内全部变体 + MinIO；基准切片输出保留）
  removeGroup: (groupId: string) =>
    client.delete(`/variants/group/${groupId}`) as Promise<{ deleted: number }>,

  // #274 C：下载变体视频（返回 presigned URL 强制下载链接）
  downloadVariant: (id: string) =>
    client.get(`/variants/${id}/download`) as Promise<{ download_url: string; file_name: string }>,

  // 整组一键打包下载（带 auth，blob 响应）。注意不可用 window.open（带不上 auth header）
  downloadGroupZip: (groupId: string) =>
    client.get(`/variants/group/${groupId}/download-zip`, { responseType: 'blob' }) as Promise<Blob>,
};
