import client from './client';

export interface WechatDlTask {
  id: string;
  created_by: string | null;
  source_url: string;
  status: string;
  progress: number;
  message: string | null;
  video_meta: Record<string, unknown> | null;
  source_type: string;
  source_authorize: string | null;
  auth_id: string | null;
  file_key: string | null;
  episode_id: string | null;
  project_id: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface WechatDlTaskList {
  items: WechatDlTask[];
  total: number;
}

export interface WechatDlAuth {
  id: string;
  owner: string | null;
  type: string | null;
  note: string | null;
  scope: string | null;
  file_key: string | null;
  expires_at: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface WechatDlAuthList {
  items: WechatDlAuth[];
  total: number;
}

export interface WechatDlImportResult {
  task_id: string;
  status: string;
  source_type: string;
  source_authorize: string;
  message: string;
}

export interface WechatDlBatchImportResult {
  task_ids: string[];
  created: number;
  skipped: number;
  skipped_reasons: string[];
  message: string;
}

export interface WechatDlImportInput {
  source_url: string;
  source_type?: string;
  project_id?: string;
  auth_id?: string;
  authorize_owner?: string;
  authorize_note?: string;
}

export const wechatDlApi = {
  // ── 单链接导入 ──
  import: (data: WechatDlImportInput) =>
    client.post('/wechat-dl/import', data) as Promise<WechatDlImportResult>,

  // ── 批量导入（P1） ──
  importBatch: (data: {
    source_urls: string[];
    source_type?: string;
    project_id?: string;
    auth_id?: string;
    authorize_owner?: string;
    authorize_note?: string;
  }) => client.post('/wechat-dl/import/batch', data) as Promise<WechatDlBatchImportResult>,

  // ── 任务列表 / 详情 ──
  getTasks: (params?: { status?: string; limit?: number; offset?: number }) =>
    client.get('/wechat-dl/tasks', { params }) as Promise<WechatDlTaskList>,

  getTask: (id: string) =>
    client.get(`/wechat-dl/tasks/${id}`) as Promise<WechatDlTask>,

  // ── 授权材料管理（P1，不含文件通道） ──
  getAuths: () => client.get('/wechat-dl/auths') as Promise<WechatDlAuthList>,

  createAuth: (data: {
    authorize_owner: string;
    authorize_type?: string;
    authorize_scope?: string;
    authorize_note?: string;
    expires_at?: string;
    is_active?: boolean;
  }) => client.post('/wechat-dl/auths', data) as Promise<WechatDlAuth>,

  updateAuth: (id: string, data: {
    authorize_owner?: string;
    authorize_type?: string;
    authorize_scope?: string;
    authorize_note?: string;
    expires_at?: string;
    is_active?: boolean;
  }) => client.put(`/wechat-dl/auths/${id}`, data) as Promise<WechatDlAuth>,

  deleteAuth: (id: string) => client.delete(`/wechat-dl/auths/${id}`) as Promise<void>,

  toggleAuth: (id: string) =>
    client.post(`/wechat-dl/auths/${id}/toggle`) as Promise<{ id: string; is_active: boolean }>,
};
