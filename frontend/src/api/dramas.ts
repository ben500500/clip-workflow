import client from './client';

// ========== 剧目（ISSUE #130 剧目管理）==========

export interface Drama {
  id: string;
  code: string; // DR-<8位HEX>
  name: string;
  frequency: string | null; // 男频 / 女频
  type: string | null; // AI真人剧 / 真人剧 / 动漫…
  tags: string[] | null; // 题材多选标签
  topics?: string[] | null; // 发布话题标签（按大方向带入并保存，发布时复用）
  rating: string | null; // 评级
  synopsis: string | null; // 剧情简介
  cover_file_key: string | null; // 封面 MinIO key
  cover_url?: string | null; // 封面临时可访问 URL
  listing_status: string;
  updated_date: string | null;
  listed_at: string | null;
  material_link: string | null;
  material_link_pwd_masked?: boolean;
  created_by: string | null;
  operator_id: string | null;
  theater_id?: string | null;      // 所属剧场
  theater_name?: string | null;    // 所属剧场名
  created_at: string;
  updated_at: string;
}

export interface DramaDetail extends Drama {
  stills: Array<{ id: string; file_key: string; sort_order: number; presigned_url?: string | null }>;
  account_ids: string[];
  // 剧集维度打通切片产线：归属剧集的 id / 数量
  episode_ids?: string[];
  episode_count?: number;
}

export interface DramaStill {
  id: string;
  drama_id: string;
  file_key: string;
  sort_order: number;
}

export interface DramaCreateParams {
  name: string;
  frequency?: string | null;
  type?: string | null;
  tags?: string[] | null;
  rating?: string | null;
  synopsis?: string | null;
  cover_file_key?: string | null;
  listing_status?: string;
  updated_date?: string | null;
  listed_at?: string | null;
  material_link?: string | null;
  material_link_pwd?: string | null;
  operator_id?: string | null;
  topics?: string[] | null;
  theater_id?: string | null;      // 所属剧场（剧目直接挂剧场）
  account_ids?: string[] | null;
}

export interface DramaUpdateParams {
  name?: string;
  frequency?: string | null;
  type?: string | null;
  tags?: string[] | null;
  rating?: string | null;
  synopsis?: string | null;
  cover_file_key?: string | null;
  listing_status?: string;
  updated_date?: string | null;
  listed_at?: string | null;
  material_link?: string | null;
  material_link_pwd?: string | null;
  operator_id?: string | null;
  topics?: string[] | null;
  theater_id?: string | null;      // 所属剧场（剧目直接挂剧场）
}

export interface DramaImportRow {
  name: string;
  frequency?: string | null;
  type?: string | null;
  tags?: string[] | null;
  rating?: string | null;
  listing_status?: string;
  updated_date?: string | null;
  listed_at?: string | null;
  material_link?: string | null;
  material_link_pwd?: string | null;
  account_name?: string | null;
  theater_name?: string | null;    // 所属剧场名（剧目直接挂剧场）
}

export interface DramaImportPreviewResult {
  new: Array<{ name: string; fields: Record<string, unknown> }>;
  update: Array<{ id: string; code: string; name: string; diff: Record<string, { old: unknown; new: unknown }> }>;
  unchanged: Array<{ id: string; code: string; name: string }>;
  summary: { new_count: number; update_count: number; unchanged_count: number };
  message: string;
}

export interface DramaImportConfirmItem {
  id?: string | null; // update 时必填 = preview update[].id
  name: string;
  frequency?: string | null;
  type?: string | null;
  tags?: string[] | null;
  rating?: string | null;
  synopsis?: string | null;
  listing_status?: string;
  updated_date?: string | null;
  listed_at?: string | null;
  material_link?: string | null;
  material_link_pwd?: string | null;
  account_name?: string | null;
  theater_name?: string | null;    // 所属剧场名（剧目直接挂剧场）
}

export interface DramaPublishContext {
  drama_id: string;
  code: string;
  name: string;
  story: string;
  tags: string[];
  topics: string[]; // 发布话题标签（剧目详情按大方向带入并保存，发布时复用）
  has_synopsis: boolean;
}

// ========== 话题大方向预设（ISSUE #93 视频号中老年短剧话题）==========

export interface TopicPreset {
  key: string;
  name: string;
  desc: string;
  topics: string[];
}

export interface TopicPresetsResult {
  presets: TopicPreset[];
  total: number;
  message: string;
}

// ========== API ==========

// 获取视频号中老年短剧话题大方向预设
export function getTopicPresets(): Promise<TopicPresetsResult> {
  return client.get('/dramas/topic-presets');
}

export function listDramas(params?: {
  q?: string;
  frequency?: string;
  rating?: string;
  listing_status?: string;
  account_id?: string;
  theater_id?: string;
}): Promise<Drama[]> {
  return client.get('/dramas', { params });
}

export function getDrama(dramaId: string): Promise<DramaDetail> {
  return client.get(`/dramas/${dramaId}`);
}

export function createDrama(data: DramaCreateParams): Promise<DramaDetail> {
  return client.post('/dramas', data);
}

export function updateDrama(dramaId: string, data: DramaUpdateParams): Promise<DramaDetail> {
  return client.put(`/dramas/${dramaId}`, data);
}

export function deleteDrama(dramaId: string): Promise<void> {
  return client.delete(`/dramas/${dramaId}`);
}

// 剧照
// 上传剧目封面/剧照图片，返回 file_key（MinIO）
export function uploadDramaImage(file: File, onProgress?: (percent: number) => void): Promise<{ file_name: string; file_key: string; file_size: number }> {
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/dramas/image-upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 3600000,
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress(percent);
      }
    },
  }) as Promise<{ file_name: string; file_key: string; file_size: number }>;
}

export function addDramaStill(dramaId: string, fileKey: string, sortOrder?: number): Promise<DramaStill> {
  return client.post('/dramas/stills', { drama_id: dramaId, file_key: fileKey, sort_order: sortOrder ?? 0 });
}

export function deleteDramaStill(stillId: string): Promise<void> {
  return client.delete(`/dramas/stills/${stillId}`);
}

// 剧目↔视频号关联
export function linkDramaAccounts(dramaId: string, accountIds: string[]): Promise<{ account_ids: string[] }> {
  return client.post(`/dramas/${dramaId}/accounts`, { account_ids: accountIds });
}

// 导入
export function dramaImportParse(file: File, onProgress?: (percent: number) => void): Promise<{
  rows: DramaImportRow[];
  total: number;
  file_name: string;
  message: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/dramas/import/parse', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000,
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress(percent);
      }
    },
  }) as Promise<{ rows: DramaImportRow[]; total: number; file_name: string; message: string }>;
}

export function dramaImportPreview(rows: DramaImportRow[], fileName?: string): Promise<DramaImportPreviewResult> {
  return client.post('/dramas/import/preview', { rows, file_name: fileName });
}

export function dramaImportConfirm(
  acceptNew: DramaImportConfirmItem[],
  acceptUpdate: DramaImportConfirmItem[],
  fileName?: string
): Promise<{ imported: number; updated: number; skipped: number; errors: unknown[]; import_history_id?: string }> {
  return client.post('/dramas/import/confirm', {
    accept_new: acceptNew,
    accept_update: acceptUpdate,
    file_name: fileName,
  });
}

// 发布联动
export function getDramaPublishContext(dramaId: string): Promise<DramaPublishContext> {
  return client.get(`/dramas/${dramaId}/publish-context`);
}

export function linkDramaMaterial(
  dramaId: string,
  materialId: string,
  accountId?: string
): Promise<{ id: string; drama_id: string; material_id: string }> {
  return client.post('/dramas/materials/link', { drama_id: dramaId, material_id: materialId, account_id: accountId });
}

// ========== 剧集维度打通切片产线 ==========

// 单集切片产线阶段状态
export interface DramaEpisodeStage {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'unknown';
  progress: number;
  run_count?: number;
  task_count?: number;
  output_count?: number;
  interval_count?: number;
}

export interface DramaSliceEpisode {
  episode_id: string;
  title: string | null;
  episode_no: number | null;
  source_file_key: string | null;
  status: string | null;
  stages: {
    autoclip: DramaEpisodeStage;
    detect: DramaEpisodeStage;
    slice: DramaEpisodeStage;
  };
  sliced: boolean;
  pending: boolean;
}

export interface DramaSliceStatus {
  drama_id: string;
  code: string;
  name: string;
  total_episodes: number;
  sliced_count: number;
  pending_count: number;
  progress_percent: number;
  episodes: DramaSliceEpisode[];
}

// 关联剧集到剧目（set 语义：传入全集即替换，空列表即清空）
export function linkDramaEpisodes(dramaId: string, episodeIds: string[]): Promise<DramaDetail> {
  return client.post(`/dramas/${dramaId}/episodes`, { episode_ids: episodeIds });
}

// 剧目级切片产线状态聚合（该剧已切片/待切片）
export function getDramaSliceStatus(dramaId: string): Promise<DramaSliceStatus> {
  return client.get(`/dramas/${dramaId}/slice-status`);
}
