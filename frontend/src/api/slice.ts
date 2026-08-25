import client from './client';
import type { ApiList, DedupeConfig, SliceOutput, SliceTask } from '../types';

export interface BadgeItem {
  file_key: string;
  position: string;
  width?: number;
  offset?: number;
  opacity?: number;
}

export interface BadgeUploadResult {
  file_name: string;
  file_key: string;
  file_size: number;
  upload_id: string;
}

// 固定文字角标（文字版角标，无需上传图片）
export interface TextOverlayItem {
  text: string;
  position: string;
  font_size?: number;
  color?: string;
  border_color?: string;
  vertical?: boolean;
  offset?: number;
}

export interface SubtitleUploadResult {
  file_name: string;
  file_key: string;
  file_size: number;
  upload_id: string;
}

export const sliceApi = {
  run: (
    episodeId: string,
    mode: string,
    data?: {
      dedupe_config?: DedupeConfig;
      // 多视频号素材去重：多版本生成数（>1 时切片后自动派生 N 个去重版本）
      variant_count?: number;
      video_path?: string;
      engine?: string;
      auto_accept_all?: boolean;
      // 后端兜底：无候选片段时后端自动补一轮 AI 选点（前端提交即走，关窗口安全）
      auto_autoclip_if_empty?: boolean;
      // 补选点时的 AI 选点配置
      autoclip_config?: {
        max_clips?: number;
        min_score_threshold?: number;
        min_duration?: number;
        max_duration?: number;
        frame_analysis?: boolean;
      };
      // 快速转换：跳过 AI 选点与区间检测，整段源视频直接应用下方配置转换输出
      no_cut?: boolean;
      watermark_enabled?: boolean;
      watermark_text?: string;
      watermark_font_size?: number;
      watermark_opacity?: number;
      watermark_position?: string;
      watermark_style?: string;
      // 图片角标：每个含 file_key（上传的角标图片 MinIO key）、position（位置）、width（可选宽度）、offset（可选偏移）、opacity（可选透明度）
      badges?: BadgeItem[];
      // 角标默认尺寸（px）：角标未单独设 width 时生效；0=保持原图尺寸
      badge_default_width?: number;
      // 竖屏转横屏智能裁切（切片前预处理）
      vert2horiz_enabled?: boolean;
      vert2horiz_mode?: 'fixed' | 'dynamic';
      vert2horiz_ratio?: number;
      vert2horiz_output_size?: string;
      vert2horiz_detect_interval?: number;
      vert2horiz_smooth_window?: number;
      // 动态模式最小移动阈值（px）：越大越稳、越小越跟手
      vert2horiz_min_step?: number;
      // 动态模式人脸舒适区边距比例（占人脸高度，默认 0.30）：人脸头像大部分仍在画面内时保持窗口不动，抑制频繁移动抖动
      vert2horiz_face_margin?: number;
      // ASR 字幕烧录：开启后对源视频做 ASR 识别并烧录到成品视频
      subtitle_enabled?: boolean;
      // 字幕字号（相对输出视频高度的比例，默认 0.07；可调大让字幕更清晰易读）
      subtitle_font_ratio?: number;
      // 字幕字间距（ASS Spacing 像素，默认 0 更紧凑；负值/调小让字幕文字更紧凑，调大则字距变宽）
      subtitle_spacing?: number;
      // 字幕字体粗细（ASS Bold：0=不加粗，-1 或 1=加粗，默认 0 不加粗）
      subtitle_bold?: number;
      // 字幕样式：default（白字黑边+半透明黑底）/ custom（自定义字体色+边框色，无底色）
      subtitle_style?: 'default' | 'custom';
      // 上传的字幕文件（MinIO key，通过 uploadSubtitle 上传）；提供后直接应用该字幕，跳过 ASR 识别
      subtitle_file_key?: string;
      // 自定义样式的字体颜色（CSS 十六进制）
      subtitle_color?: string;
      // 自定义样式的边框颜色（CSS 十六进制）
      subtitle_border_color?: string;
      // 源视频字幕打码：先把片源自带字幕打码，再烧录自己的 ASR 字幕
      subtitle_mask_enabled?: boolean;
      subtitle_mask_style?: 'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill';
      // 打码预设（三档：auto=自动/fine=精细/quick=快速），收敛 temporal/spatial 两个开关
      subtitle_mask_preset?: 'auto' | 'fine' | 'quick' | string;
      // 精细化（帧级检测）：只在字幕/水印实际出现的时段打码
      subtitle_mask_temporal?: boolean;
      // 仅字幕显示区域打码（空间精细化）：需开启 temporal 后才能开启，
      // 只对字幕文字实际占用的横向子区域打码，而不是整条横带都盖住。
      subtitle_mask_spatial?: boolean;
      subtitle_mask_width_ratio?: number;
      subtitle_mask_height_ratio?: number;
      subtitle_mask_bottom_ratio?: number;
      // 打码时间轴整体偏移（秒）：字幕比SRT晚出现用正值延后（0.5=延后0.5秒）
      subtitle_mask_srt_offset?: number;
      // 字幕对齐源字幕打码区域（默认开启）：开启源字幕打码并检测到字幕区域时，
      // 把 ASR 字幕默认位置对齐到打码区域（与被打掉的源字幕位置重合）
      subtitle_align_mask?: boolean;
      // 恒定水印/角标打码：打掉片源固定水印（独立开关）
      watermark_mask_enabled?: boolean;
      watermark_mask_style?: 'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill';
      watermark_mask_width_ratio?: number;
      watermark_mask_height_ratio?: number;
      watermark_mask_bottom_ratio?: number;
      // 固定文字角标（文字版角标）：在成品指定位置叠加固定文字
      text_overlays?: TextOverlayItem[];
      // 成品重新剪辑：以某个切片输出为源，重新裁剪出一个新片段
      output_id?: string;
      cut_start?: number;
      cut_end?: number;
      // 视频封面：选择图片作为视频首帧（MinIO key，通过 uploadBadge 上传）
      cover_image_key?: string;
      // 钩子视频：作为片头拼接在封面首帧与本体之间（[封面][钩子][本体]，MinIO key，通过 uploadHook 上传）
      hook_video_key?: string;
      // 钩子视频文件夹：选择整个文件夹，含多个钩子视频（MinIO key 列表，通过 uploadHookFolder 上传）。
      // 切片时每个成品随机从文件夹中取一个钩子作为片头。优先于 hook_video_key。
      hook_video_keys?: string[];
      // 高光混剪：把入选高光段按源时间顺序混剪拼接为一个成品
      highlight_mix_enabled?: boolean;
      // 输出总时长上限（秒）：累计各高光段不超过该值，最后一段会超额时丢弃
      highlight_mix_max_duration?: number;
      // 单段最大时长（秒）：仅纳入时长不超过该值的短高光段
      highlight_mix_max_clip_duration?: number;
      // 拼接顺序：time（源时间顺序，默认）/ score（评分从高到低）
      highlight_mix_order?: 'time' | 'score';
      // 输出档位：original（默认）/ auto（源宽>720 或 fps>30 自动降 720P@30）/ 1080p / 720p / 480p
      output_tier?: 'original' | 'auto' | '1080p' | '720p' | '480p' | string;
    }
  ) =>
    client.post(`/episodes/${episodeId}/slice/run`, { mode, ...data }) as Promise<{
      task_id: string;
      engine: string;
      message: string;
    }>,

  // 上传角标图片
  uploadBadge: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/slice/badge-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<BadgeUploadResult>;
  },

  // 上传钩子视频（作为片头拼接在封面与本体之间）
  uploadHook: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/slice/hook-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<BadgeUploadResult>;
  },

  // 上传整个钩子视频文件夹（多个视频，切片时随机组合）。
  // 返回每个视频的 file_key 列表，前端作为 hook_video_keys 传入切片请求。
  uploadHookFolder: (files: File[], onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    return client.post('/slice/hook-folder-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<{
      folder_id: string;
      items: Array<{ file_name: string; file_key: string; file_size: number }>;
      errors: string[];
    }>;
  },

  // 更新剧集封面（按剧集独立存储，作为切片首帧叠加；传 null 清除该集封面）
  updateEpisodeCover: (episodeId: string, coverImageKey: string | null) =>
    client.put(`/episodes/${episodeId}`, { cover_image_key: coverImageKey }) as Promise<{
      id: string;
      cover_image_key: string | null;
    }>,

  // 为已上传的封面/钩子/角标等 raw-footage 文件生成临时预览 URL（悬停预览用）
  getRawPreviewUrl: (fileKey: string) =>
    client.get('/slice/raw-preview', { params: { file_key: fileKey } }) as Promise<{
      file_key: string;
      url: string;
    }>,

  // 上传字幕文件（srt/vtt）
  uploadSubtitle: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/slice/subtitle-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    }) as Promise<SubtitleUploadResult>;
  },

  listTasks: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/slice/tasks`) as Promise<SliceTask[]>,

  // 读取当前用户的切片个人配置（保存到个人账号，跨设备/浏览器持久化）
  getPreferences: () =>
    client.get(`/slice/preferences`) as Promise<{ slice_config: Record<string, unknown> | null }>,

  // 保存当前用户的切片个人配置到个人账号
  savePreferences: (sliceConfig: Record<string, unknown>) =>
    client.put(`/slice/preferences`, { slice_config: sliceConfig }) as Promise<{
      ok: boolean;
      slice_config: Record<string, unknown>;
    }>,

  getTask: (taskId: string) =>
    client.get(`/slice-tasks/${taskId}`) as Promise<SliceTask>,

  getOutputs: (taskId: string) =>
    client.get(`/slice-tasks/${taskId}/outputs`) as Promise<SliceOutput[]>,

  cancel: (taskId: string) =>
    client.post(`/slice-tasks/${taskId}/cancel`) as Promise<{ message: string }>,

  delete: (taskId: string) =>
    client.delete(`/slice-tasks/${taskId}`) as Promise<{ message: string; task_id: string }>,

  retry: (taskId: string) =>
    client.post(`/slice-tasks/${taskId}/retry`) as Promise<{
      task_id: string;
      message: string;
    }>,

  listWorkers: () =>
    client.get(`/workers`) as Promise<any[]>,

  syncWorkers: () =>
    client.post(`/workers/sync-redis`) as Promise<{ synced: number; message: string }>,

  enableWorker: (nodeId: string) =>
    client.post(`/workers/${nodeId}/enable`) as Promise<{ message: string; enabled: boolean }>,

  disableWorker: (nodeId: string) =>
    client.post(`/workers/${nodeId}/disable`) as Promise<{ message: string; enabled: boolean }>,

  setWorkerCpuPercent: (nodeId: string, cpuPercent: number) =>
    client.post(`/workers/${nodeId}/cpu-percent`, { cpu_percent: cpuPercent }) as Promise<{
      message: string;
      cpu_percent: number;
    }>,

  deleteWorker: (nodeId: string) =>
    client.delete(`/workers/${encodeURIComponent(nodeId)}`) as Promise<{
      ok: boolean;
      node_id: string;
      deleted: boolean;
      message: string;
    }>,

  // 获取服务器端当前引擎版本（用于判断节点是否需要推送更新）
  getEnginesStatus: () =>
    client.get(`/workers/engines/status`) as Promise<{
      engines_dir: string;
      version: string;
      file_count: number;
      files: string[];
    }>,

  // 向指定节点推送引擎更新（无需重新部署）
  pushWorkerUpdate: (nodeId: string) =>
    client.post(`/workers/${encodeURIComponent(nodeId)}/push-update`) as Promise<{
      ok: boolean;
      node_id: string;
      target_version: string;
      message: string;
    }>,
};
