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
  authorize_note?: string;
}

export interface WechatDlImportToProjectInput {
  target: 'new' | 'existing';
  project_name?: string;
  project_id?: string;
}

export interface WechatDlImportToProjectResult {
  project_id: string;
  episode_id: string;
  target: string;
}

export const wechatDlApi = {
  // ── 单链接导入 ──
  import: (data: WechatDlImportInput) =>
    client.post('/wechat-dl/import', data) as Promise<WechatDlImportResult>,

  // ── 批量导入 ──
  importBatch: (data: {
    source_urls: string[];
    source_type?: string;
    project_id?: string;
    authorize_note?: string;
  }) => client.post('/wechat-dl/import/batch', data) as Promise<WechatDlBatchImportResult>,

  // ── 任务列表 / 详情 ──
  getTasks: (params?: { status?: string; limit?: number; offset?: number }) =>
    client.get('/wechat-dl/tasks', { params }) as Promise<WechatDlTaskList>,

  getTask: (id: string) =>
    client.get(`/wechat-dl/tasks/${id}`) as Promise<WechatDlTask>,

  // ── 一键导入切片项目 ──
  importToProject: (taskId: string, data: WechatDlImportToProjectInput) =>
    client.post(`/wechat-dl/tasks/${taskId}/import-to-project`, data) as Promise<WechatDlImportToProjectResult>,
};
