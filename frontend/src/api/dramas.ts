import client from './client';

// ========== 剧目（ISSUE #130 剧目管理）==========

export interface Drama {
  id: string;
  code: string; // DR-<8位HEX>
  name: string;
  frequency: string | null; // 男频 / 女频
  type: string | null; // AI真人剧 / 真人剧 / 动漫…
  tags: string[] | null; // 题材多选标签
  rating: string | null; // 评级
  synopsis: string | null; // 剧情简介
  cover_file_key: string | null; // 封面 MinIO key
  listing_status: string;
  updated_date: string | null;
  listed_at: string | null;
  material_link: string | null;
  material_link_pwd_masked?: boolean;
  created_by: string | null;
  operator_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DramaDetail extends Drama {
  stills: Array<{ id: string; file_key: string; sort_order: number }>;
  account_ids: string[];
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
}

export interface DramaPublishContext {
  drama_id: string;
  code: string;
  name: string;
  story: string;
  tags: string[];
  has_synopsis: boolean;
}

// ========== API ==========

export function listDramas(params?: {
  q?: string;
  frequency?: string;
  rating?: string;
  listing_status?: string;
  account_id?: string;
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
