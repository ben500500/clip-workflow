import client from './client';

export interface ShortdramaPromptRecord {
  id: string;
  source_text: string;
  duration: number;
  theme: string | null;
  tone: string | null;
  characters: string | null;
  extra_requirements: string | null;
  model: string | null;
  prompt_text: string;
  prompt_long: string | null;
  prompt_short: string | null;
  created_at: string;
  // 成片视频附件（Seedance 生成结果，可一键导入去水印流程）
  video_file_name?: string | null;
  video_file_key?: string | null;
  video_bucket?: string | null;
  video_file_size?: number | null;
  video_status?: string | null;
  video_error_message?: string | null;
  video_url?: string | null;
  video_uploaded_at?: string | null;
  // 一键豆包生成任务状态
  doubao_status?: string | null;
  doubao_account_type?: string | null;
  doubao_qrcode?: string | null;
  doubao_message?: string | null;
  doubao_error_message?: string | null;
  doubao_approved_prompt?: string | null;
  doubao_rewrite_history?: DoubaoRewriteItem[] | null;
  doubao_rewrite_count?: number | null;
}

export interface DoubaoRewriteItem {
  round?: number;
  attempt?: number;
  original?: string;
  rewritten?: string;
  reason?: string;
  created_at?: string;
}

export interface DoubaoGenerateParams {
  account_type: 'free' | 'pro';
  duration?: number | null;
}

export interface DoubaoGenerateResult {
  record_id: string;
  doubao_status: string;
  message: string;
}

export interface PromptGenerateParams {
  text: string;
  duration: number;
  theme?: string;
  tone?: string;
  characters?: string;
  extra_requirements?: string;
  save?: boolean;
  // 是否把本次所选时长保存为当前登录用户的默认值（前端选择时长后即作为默认值）
  save_duration_as_default?: boolean;
}

export interface PromptGenerateResult {
  prompt: string;
  versions?: {
    long?: string;
    short?: string;
    ai?: string;
  } | null;
  duration: number;
  model?: string | null;
  record_id?: string | null;
  message: string;
}

export interface PromptTemplates {
  long: string;
  short: string;
  updated_at?: string;
}

export interface ScriptOptimizeParams {
  text: string;
  theme?: string;
  tone?: string;
  extra_requirements?: string;
}

export interface ScriptOptimizeResult {
  optimized_text: string;
  model?: string | null;
  message: string;
}

export const shortdramaApi = {
  generate: (params: PromptGenerateParams) =>
    client.post('/shortdrama/prompt/generate', params) as Promise<PromptGenerateResult>,

  optimizeScript: (params: ScriptOptimizeParams) =>
    client.post('/shortdrama/prompt/optimize', params) as Promise<ScriptOptimizeResult>,

  listPrompts: (limit = 50) =>
    client.get('/shortdrama/prompts', { params: { limit } }) as Promise<ShortdramaPromptRecord[]>,

  getPrompt: (recordId: string) =>
    client.get(`/shortdrama/prompts/${recordId}`) as Promise<ShortdramaPromptRecord>,

  deletePrompt: (recordId: string) =>
    client.delete(`/shortdrama/prompts/${recordId}`) as Promise<{ message: string; record_id: string }>,

  // ── 成片视频：上传 / 播放 / 删除 / 一键导入去水印 ──
  uploadVideo: (recordId: string, file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post(`/shortdrama/prompts/${recordId}/video`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<ShortdramaPromptRecord>;
  },

  getVideo: (recordId: string) =>
    client.get(`/shortdrama/prompts/${recordId}/video`) as Promise<{
      record_id: string;
      file_name: string;
      url: string;
      file_size: number | null;
      status: string | null;
    }>,

  deleteVideo: (recordId: string) =>
    client.delete(`/shortdrama/prompts/${recordId}/video`) as Promise<{
      message: string;
      record_id: string;
    }>,

  importToWatermark: (recordId: string) =>
    client.post(`/shortdrama/prompts/${recordId}/import-to-watermark`) as Promise<{
      record_id: string;
      file_name: string | null;
      source_file_key: string;
      bucket: string;
      file_size: number | null;
      url?: string | null;
      message: string;
    }>,

  // ── 提示词生成默认时长（当前登录用户） ──
  getDefaultDuration: () =>
    client.get('/shortdrama/prompt/default-duration') as Promise<{
      duration: number;
      message: string;
    }>,

  setDefaultDuration: (duration: number) =>
    client.put('/shortdrama/prompt/default-duration', { duration }) as Promise<{
      duration: number;
      message: string;
    }>,

  // ── 长 / 短提示词模板管理（可编辑并持久化） ──
  getTemplates: () =>
    client.get('/shortdrama/prompt/templates') as Promise<PromptTemplates>,

  saveTemplates: (templates: Partial<PromptTemplates>) =>
    client.put('/shortdrama/prompt/templates', templates) as Promise<PromptTemplates>,

  // ── 一键豆包生成（RPA 自动出片） ──
  doubaoGenerate: (recordId: string, params: DoubaoGenerateParams) =>
    client.post(`/shortdrama/prompts/${recordId}/doubao/generate`, params) as Promise<DoubaoGenerateResult>,

  doubaoConfirmRewrite: (recordId: string, decision: 'approved' | 'rejected' | 'cancelled') =>
    client.post(`/shortdrama/prompts/${recordId}/doubao/confirm-rewrite`, { decision }) as Promise<DoubaoGenerateResult>,

  doubaoCancel: (recordId: string) =>
    client.post(`/shortdrama/prompts/${recordId}/doubao/cancel`) as Promise<DoubaoGenerateResult>,

  doubaoStatus: (recordId: string) =>
    client.get(`/shortdrama/prompts/${recordId}/doubao/status`) as Promise<ShortdramaPromptRecord>,

  getDoubaoAccountType: () =>
    client.get('/shortdrama/doubao/account-type') as Promise<{
      account_type: 'free' | 'pro';
      limits: { free_max_seconds: number; pro_max_seconds: number };
    }>,

  setDoubaoAccountType: (accountType: 'free' | 'pro') =>
    client.put('/shortdrama/doubao/account-type', { account_type: accountType }) as Promise<{
      account_type: 'free' | 'pro';
      message: string;
    }>,
};
