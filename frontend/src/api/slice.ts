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
      video_path?: string;
      engine?: string;
      auto_accept_all?: boolean;
      // 快速转换：跳过 AI 选点与区间检测，整段源视频直接应用下方配置转换输出
      no_cut?: boolean;
      watermark_enabled?: boolean;
      watermark_text?: string;
      watermark_font_size?: number;
      watermark_opacity?: number;
      watermark_position?: string;
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
      subtitle_mask_style?: 'delogo' | 'mosaic' | 'blur' | 'fill';
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
      // 固定文字角标（文字版角标）：在成品指定位置叠加固定文字
      text_overlays?: TextOverlayItem[];
      // 成品重新剪辑：以某个切片输出为源，重新裁剪出一个新片段
      output_id?: string;
      cut_start?: number;
      cut_end?: number;
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
