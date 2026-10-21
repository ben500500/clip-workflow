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

export interface WechatDlProviderInfo {
  channel: string;
  display_name: string;
  home: string | null;
  /** 官方接口文档地址（如 智令 doc/107），无则 null */
  doc: string | null;
  rechargeable: boolean;
  desc: string;
  balance: number | null;
  balance_unit: string;
  balance_error: string | null;
}

// ── 视频反推提示词（智令 doc/120 提交 + doc/119 轮询）──
/** 反推任务来源：url=粘贴链接，upload=本地视频上传（doc/125） */
export type WechatDlPromptSourceType = 'url' | 'upload';

export interface WechatDlPromptTask {
  id: string;
  created_by: string | null;
  source_type: WechatDlPromptSourceType;
  source_url: string;
  /** 上传来源时的原始文件名（url 来源为 null） */
  file_name: string | null;
  provider_task_id: string | null;
  /** processing / success / failed */
  status: string;
  /** 提示词正文（markdown），success 时有值 */
  content: string | null;
  error: string | null;
  max_duration: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface WechatDlPromptTaskList {
  items: WechatDlPromptTask[];
  total: number;
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

  // ── 重试失败的下载任务 ──
  retry: (id: string) =>
    client.post(`/wechat-dl/tasks/${id}/retry`) as Promise<{ ok: boolean; message: string }>,

  // ── 方向① 闭环：下载完成 → 一键入切片 ──
  toSlice: (id: string, data?: { mode?: string; dedupe_config?: Record<string, unknown> }) =>
    client.post(`/wechat-dl/tasks/${id}/to-slice`, data || { mode: 'fast' }) as Promise<{
      slice_task_id: string;
      episode_id: string;
      mode: string;
      message: string;
    }>,

  // ── 一键导入切片项目 ──
  importToProject: (taskId: string, data: WechatDlImportToProjectInput) =>
    client.post(`/wechat-dl/tasks/${taskId}/import-to-project`, data) as Promise<WechatDlImportToProjectResult>,

  // ── 解析服务商信息（API 名称 / 官网 / 文档 / 余量）──
  getProviders: () =>
    client.get('/wechat-dl/providers') as Promise<{ items: WechatDlProviderInfo[] }>,

  // ── 视频反推提示词（异步：提交后轮询）──
  submitReversePrompt: (data: { source_url: string; max_duration?: number }) =>
    client.post('/wechat-dl/reverse-prompt', data) as Promise<WechatDlPromptTask>,

  // ── 本地视频上传反推（doc/125 签名直传 → doc/120，ISSUE #363）──
  uploadReversePrompt: (
    data: { file: File; max_duration?: number },
    onUploadProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    form.append('file', data.file);
    if (data.max_duration != null) form.append('max_duration', String(data.max_duration));
    return client.post('/wechat-dl/reverse-prompt/upload', form, {
      // 与仓库其它上传一致：显式 multipart，boundary 由 axios/浏览器补
      headers: { 'Content-Type': 'multipart/form-data' },
      // 大视频上传慢：60s 默认超时会把 500MB 上传直接掐断
      timeout: 0,
      onUploadProgress: (e) => {
        if (!onUploadProgress) return;
        const total = e.total || 0;
        if (total > 0) onUploadProgress(Math.min(100, Math.round((e.loaded / total) * 100)));
      },
    }) as Promise<WechatDlPromptTask>;
  },

  getReversePrompt: (id: string) =>
    client.get(`/wechat-dl/reverse-prompt/${id}`) as Promise<WechatDlPromptTask>,

  // 失败任务一键重试（复制原参数新建任务，仅链接型；上传型请重新上传）
  retryReversePrompt: (id: string) =>
    client.post(`/wechat-dl/reverse-prompt/${id}/retry`) as Promise<WechatDlPromptTask>,

  listReversePrompts: (params?: { limit?: number }) =>
    client.get('/wechat-dl/reverse-prompt', { params }) as Promise<WechatDlPromptTaskList>,
};
