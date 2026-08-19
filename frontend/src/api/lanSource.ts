import client from './client';

// ── 局域网获取剧集（lan_source） ──

export interface LanSourceConfig {
  enabled: boolean;
  base_url: string;
  manage_base: string;
  api_prefix: string;
  download_timeout: number;
  queue: string;
  default_project: string;
  concurrency: number;
}

export interface LanSourceManageDrama {
  name: string;
  drama_id: string | null;
  total: number | null;
  desc: string | null;
}

export interface LanSourceEpisodeItem {
  episode: number | null;
  title: string | null;
  url: string;
  size?: number | null;
}

export interface LanSourceEpisodeStatus {
  episode: number | null;
  title?: string | null;
  url?: string;
  status: string; // pending / downloaded / completed / failed
  episode_id?: string | null;
  error?: string | null;
}

export interface LanSourceImportTask {
  id: string;
  created_by: string | null;
  drama_name: string;
  drama_id: string | null;
  project_id: string | null;
  status: string;
  progress: number;
  message: string | null;
  total_episodes: number | null;
  imported_count: number;
  failed_count: number;
  episode_items: LanSourceEpisodeStatus[];
  error_message: string | null;
  celery_task_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LanSourceTaskList {
  items: LanSourceImportTask[];
  total: number;
}

export interface LanSourceImportResult {
  task_id: string;
  drama_name: string;
  status: string;
  message: string;
}

export const lanSourceApi = {
  // 只读配置
  getConfig: () => client.get('/lan-source/config') as Promise<LanSourceConfig>,

  // 剧目清单（来自管理平台）
  getDramas: () =>
    client.get('/lan-source/dramas') as Promise<{ items: LanSourceManageDrama[] }>,

  // 预览某剧目直链（发现但不入库）
  preview: (dramaName: string) =>
    client.get('/lan-source/preview', { params: { drama_name: dramaName } }) as Promise<{
      drama_name: string;
      items: LanSourceEpisodeItem[];
    }>,

  // 提交导入任务
  import: (data: { drama_name: string; project_id?: string; total_episodes?: number }) =>
    client.post('/lan-source/import', data) as Promise<LanSourceImportResult>,

  // 任务列表 / 详情
  getTasks: (params?: { status?: string; limit?: number; offset?: number }) =>
    client.get('/lan-source/tasks', { params }) as Promise<LanSourceTaskList>,

  getTask: (id: string) =>
    client.get(`/lan-source/tasks/${id}`) as Promise<LanSourceImportTask>,

  // 已导入剧集一键投入切片
  toSlice: (id: string, data?: { mode?: string; dedupe_config?: Record<string, unknown> }) =>
    client.post(`/lan-source/tasks/${id}/to-slice`, data || { mode: 'fast' }) as Promise<{
      slice_task_id: string;
      episode_id: string;
      mode: string;
      message: string;
    }>,
};
