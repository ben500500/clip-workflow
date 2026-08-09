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
}

export interface PromptGenerateParams {
  text: string;
  duration: number;
  theme?: string;
  tone?: string;
  characters?: string;
  extra_requirements?: string;
  save?: boolean;
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

export const shortdramaApi = {
  generate: (params: PromptGenerateParams) =>
    client.post('/shortdrama/prompt/generate', params) as Promise<PromptGenerateResult>,

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

  // ── 长 / 短提示词模板管理（可编辑并持久化） ──
  getTemplates: () =>
    client.get('/shortdrama/prompt/templates') as Promise<PromptTemplates>,

  saveTemplates: (templates: Partial<PromptTemplates>) =>
    client.put('/shortdrama/prompt/templates', templates) as Promise<PromptTemplates>,
};
