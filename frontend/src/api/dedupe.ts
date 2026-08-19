import client from './client';

/** 去重字段定义（UI 渲染契约，来自 GET /api/dedupe/presets）。 */
export interface DedupeFieldDef {
  key: string;
  label: string;
  type: 'number' | 'bool' | 'string' | 'dict';
  control: 'number' | 'slider' | 'switch' | 'select' | 'text' | 'group';
  group?: string;
  tip?: string;
  hidden?: boolean;
  min?: number;
  max?: number;
  step?: number;
  default?: unknown;
  max_len?: number;
  options?: { value: string; label: string }[];
  fields?: DedupeFieldDef[];
}

/** 去重档位定义。 */
export interface DedupePresetDef {
  value: string;
  label: string;
  desc?: string;
}

/** GET /api/dedupe/presets 的完整响应。 */
export interface DedupePresetsData {
  presets: DedupePresetDef[];
  fields: DedupeFieldDef[];
  defaults: Record<string, Record<string, unknown>>;
}

export interface DedupeUploadResult {
  path: string;
  file_name: string;
  file_size: number;
  content_type: string;
}

export interface DedupeUploadedFile {
  // 上传成功后的本地标识（用于前端列表展示）
  uid: string;
  file_name: string;
  file_size: number;
  // 上传成功后由后端返回的服务器本地 path，供 batch-slice/run 使用
  path: string;
  status: 'uploading' | 'done' | 'error';
  error?: string;
}

export const dedupeApi = {
  /** 去重处理入口：上传一个视频到服务器本地临时目录，返回 path 供 batch-slice/run 使用。 */
  upload: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/dedupe/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<DedupeUploadResult>;
  },
  /** 去重配置单一来源：返回档位列表 + 字段定义 + 每档全量默认参数。 */
  getPresets: () => client.get('/dedupe/presets') as Promise<DedupePresetsData>,
};
