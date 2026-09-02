import type { TextOverlayItem } from '../api/slice';

/**
 * 一键切片配置预设 —— 单一事实源（C2 收敛，供 EpisodeDetail / BatchSlice / ProjectDetail 三页面共用）
 *
 * 行为零变化约束：
 *  - 预设名称（"默认配置"）、默认值、字段语义、storage 键（slice_presets_v1 / slice_active_preset）全部原样保留；
 *  - 旧 localStorage 中保存过的自定义预设不失效（加载时逐字段读取，缺省字段在应用侧按既有回退逻辑处理）。
 */

// ─── storage 键（唯一事实源） ───
export const SLICE_PRESET_STORAGE_KEY = 'slice_presets_v1';
export const SLICE_ACTIVE_PRESET_KEY = 'slice_active_preset';

// ─── 单一模型（取 EpisodeDetail 全集，为三页面唯一类型；字段与后端 SlicePreset 语义对齐） ───
export interface SlicePreset {
  id: string;
  name: string;
  // 竖屏转横屏
  vert2horiz_enabled: boolean;
  vert2horiz_mode: 'fixed' | 'dynamic';
  vert2horiz_ratio: number;
  vert2horiz_output_size: string;
  vert2horiz_detect_interval: number;
  vert2horiz_smooth_window: number;
  vert2horiz_min_step: number;
  vert2horiz_face_margin: number;
  // ASR 字幕
  subtitle_enabled: boolean;
  subtitle_font_ratio: number;
  // 字幕高度（距画面底边的比例，默认 1/4=0.25，字幕块中心约在 3/4 屏高处）
  subtitle_margin_ratio: number;
  subtitle_spacing: number;
  subtitle_bold: number;
  subtitle_style: 'default' | 'custom';
  subtitle_color: string;
  subtitle_border_color: string;
  // 源视频字幕打码
  subtitle_mask_enabled: boolean;
  subtitle_mask_style: 'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill';
  subtitle_mask_temporal: boolean;
  subtitle_mask_spatial: boolean;
  subtitle_mask_preset?: 'auto' | 'fine' | 'quick' | string;
  subtitle_mask_width_ratio: number;
  subtitle_mask_height_ratio: number;
  subtitle_mask_bottom_ratio: number;
  subtitle_mask_srt_offset: number;
  // 字幕对齐源字幕打码区域（默认开启）
  subtitle_align_mask: boolean;
  // 恒定水印/角标打码
  watermark_mask_enabled: boolean;
  watermark_mask_style: 'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill';
  watermark_mask_width_ratio: number;
  watermark_mask_height_ratio: number;
  watermark_mask_bottom_ratio: number;
  // 固定文字
  text_overlay_enabled: boolean;
  text_overlays: TextOverlayItem[];
  // 动态文字水印
  watermark_enabled: boolean;
  watermark_text: string;
  watermark_font_size: number;
  watermark_opacity: number;
  watermark_position: string;
  watermark_style: string;
  // 图片角标默认尺寸
  badge_default_width: number;
  // 去重模式（一键切片启用后按档位做画面去重）
  dedupe_enabled: boolean;
  dedupe_preset: string;
  // 输出档位（高分辨率/高 fps 素材降档提速）：original=不处理 / auto=自动降档 / 1080p / 720p / 480p
  output_tier: string;
  // AI 智能选点参数（可选：旧预设无，缺失时按页面默认）
  max_clips?: number;
  min_score_threshold?: number | null;
  min_clip_duration?: number | null;
  max_clip_duration?: number | null;
  frame_analysis?: boolean;
  // 画面理解视觉模型提供商：`ollama`（本地 MiniCPM-V）/ `llm`（在线 OpenAI 兼容视觉模型）
  frame_analysis_provider?: string;
  highlight_mode?: boolean;
  highlight_max_duration?: number;
  auto_autoclip_if_empty?: boolean;
  // 高光混剪（把入选高光段按源时间顺序混剪拼接为一个成品）
  highlight_mix_enabled: boolean;
  // 输出总时长上限（秒，可选）：累计各高光段不超过该值，最后一段会超额时丢弃
  highlight_mix_max_duration?: number;
  // 单段最大时长（秒，可选）：仅纳入时长不超过该值的短高光段
  highlight_mix_max_clip_duration?: number;
  // 拼接顺序：time（源时间顺序，默认）/ score（评分从高到低）
  highlight_mix_order?: 'time' | 'score';
}

// ─── 默认配置（在默认项基础上：竖屏转横屏开 / ASR字幕开 / 固定文字开） ───
export const DEFAULT_SLICE_PRESET: SlicePreset = {
  id: 'default',
  name: '默认配置',
  vert2horiz_enabled: true,
  vert2horiz_mode: 'dynamic',
  vert2horiz_ratio: 0.5625,
  vert2horiz_output_size: '1280x720',
  vert2horiz_detect_interval: 2,
  vert2horiz_smooth_window: 15,
  vert2horiz_min_step: 5,
  vert2horiz_face_margin: 0.30,
  subtitle_enabled: true,
  subtitle_font_ratio: 0.30,
  // 字幕高度：距底 1/4 屏高（字幕块中心约在 3/4 屏高处，偏下不挡画面主体）
  subtitle_margin_ratio: 0.25,
  subtitle_spacing: -2,
  subtitle_bold: 0,
  subtitle_style: 'custom',
  subtitle_color: '#EDD736',
  subtitle_border_color: '#000000',
  subtitle_mask_enabled: false,
  subtitle_mask_style: 'delogo',
  subtitle_mask_temporal: true,
  subtitle_mask_spatial: false,
  subtitle_mask_preset: 'auto',
  subtitle_mask_width_ratio: 0.9,
  subtitle_mask_height_ratio: 0.12,
  subtitle_mask_bottom_ratio: 0.02,
  subtitle_mask_srt_offset: 0,
  subtitle_align_mask: true,
  text_overlay_enabled: true,
  text_overlays: [
    { text: '热门短剧', position: 'top-right', font_size: 40, color: '#EDD736', border_color: '#000000', vertical: false, offset: 10 },
    { text: '免费热门短剧', position: 'bottom-left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: 10 },
    { text: '本故事纯属虚构', position: 'left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: true, offset: 10 },
  ],
  watermark_enabled: false,
  watermark_text: '',
  watermark_font_size: 28,
  watermark_opacity: 0.5,
  watermark_position: 'bottom',
  watermark_style: 'scroll',
  watermark_mask_enabled: false,
  watermark_mask_style: 'delogo',
  watermark_mask_width_ratio: 0.9,
  watermark_mask_height_ratio: 0.12,
  watermark_mask_bottom_ratio: 0.02,
  badge_default_width: 0,
  dedupe_enabled: false,
  dedupe_preset: 'std_crop_desat',
  output_tier: 'auto',
  highlight_mix_enabled: false,
  highlight_mix_max_duration: undefined,
  highlight_mix_max_clip_duration: undefined,
  highlight_mix_order: 'time',
};

/**
 * 批量切片专用额外配置（不纳入预设，仅 BatchSlice 页使用）。
 */
export interface BatchSliceExtras {
  autoclipEnabled?: boolean;
  intervalEnabled?: boolean;
  intervalMode?: 'credits' | 'static' | 'watermark';
}

/**
 * 共享映射：SlicePreset → 批量切片后端 slice_config（单一事实源）。
 *
 * 批量切片接口（backend/app/api/batch_slice.py → _trigger_slice）对 slice_config
 * 按白名单透传，本函数严格对齐该白名单字段名，确保前端预设里配置的每一项都能生效。
 *
 * AI 选点参数统一为扁平 `max_clips/min_clip_duration/max_clip_duration/`
 * `min_score_threshold/frame_analysis/frame_analysis_provider`（与 SlicePreset 一致），
 * 再映射进后端 `autoclip_config` 期望的 `min_duration/max_duration`（与 EpisodeDetail 一致）。
 */
export function buildBatchSlicePayload(
  preset: Omit<SlicePreset, 'id' | 'name'>,
  extras: BatchSliceExtras = {},
): Record<string, unknown> {
  return {
    // 透传 SlicePreset 全字段（白名单过滤掉 id/name/扁平 AI 选点等非后端字段）
    ...preset,
    mode: 'fast',
    auto_accept_all: true,
    // AI 智能选点：扁平参数并入 autoclip_config / autoclip_enabled
    autoclip_enabled: extras.autoclipEnabled ?? true,
    autoclip_config: {
      max_clips: preset.max_clips,
      min_score_threshold: preset.min_score_threshold ?? undefined,
      min_duration: preset.min_clip_duration ?? undefined,
      max_duration: preset.max_clip_duration ?? undefined,
      frame_analysis: preset.frame_analysis,
      frame_analysis_provider: preset.frame_analysis_provider ?? undefined,
      highlight_mode: preset.highlight_mode,
      highlight_max_duration: preset.highlight_mode ? preset.highlight_max_duration : undefined,
    },
    // 通用区间检测：配置并入 interval_config / interval_enabled
    interval_enabled: extras.intervalEnabled ?? true,
    interval_config: { mode: extras.intervalMode ?? 'credits' },
    // 去重：仅开关启用时下发档位（与单切片一致）
    dedupe_config: preset.dedupe_enabled ? { preset: preset.dedupe_preset } : undefined,
    // 固定文字角标：仅开启时透传
    text_overlays: preset.text_overlay_enabled ? preset.text_overlays : [],
    // 恒定水印/角标打码：仅开启时透传
    watermark_mask_enabled: preset.watermark_mask_enabled,
    watermark_mask_style: preset.watermark_mask_enabled ? preset.watermark_mask_style : undefined,
    watermark_mask_width_ratio: preset.watermark_mask_enabled ? preset.watermark_mask_width_ratio : undefined,
    watermark_mask_height_ratio: preset.watermark_mask_enabled ? preset.watermark_mask_height_ratio : undefined,
    watermark_mask_bottom_ratio: preset.watermark_mask_enabled ? preset.watermark_mask_bottom_ratio : undefined,
    // 高光混剪：仅启用时透传
    highlight_mix_enabled: preset.highlight_mix_enabled,
    highlight_mix_max_duration: preset.highlight_mix_enabled ? preset.highlight_mix_max_duration : undefined,
    highlight_mix_max_clip_duration: preset.highlight_mix_enabled ? preset.highlight_mix_max_clip_duration : undefined,
    highlight_mix_order: preset.highlight_mix_enabled ? preset.highlight_mix_order : undefined,
  };
}

/**
 * 读取保存的自定义预设（localStorage slice_presets_v1 存的都是非默认预设，与旧逻辑一致）。
 * 失败或为空返回 []。BatchSlice / ProjectDetail 用它展示「一键切片配置」下拉选项。
 */
export function loadCustomPresets(): SlicePreset[] {
  try {
    const raw = localStorage.getItem(SLICE_PRESET_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // 去重：排除可能混入的默认预设 id（防御），保持既有读取逻辑语义
    return parsed.filter((p: SlicePreset) => p && p.id !== DEFAULT_SLICE_PRESET.id);
  } catch {
    return [];
  }
}

/**
 * 读取完整预设列表（默认头 + 自定义）并解析激活 id。
 * EpisodeDetail 用它初始化预设下拉与首次进入要应用的配置。
 * 返回值：{ presets: [默认, ...自定义], activeId }
 *   - 无已存数据时 presets=[DEFAULT]、activeId=DEFAULT.id（与旧逻辑一致）。
 *   - 激活 id 无效（被删除/不存在）时回退默认 id。
 */
export function loadPresetList(): { presets: SlicePreset[]; activeId: string } {
  try {
    const custom = loadCustomPresets();
    const presets = [DEFAULT_SLICE_PRESET, ...custom];
    let activeId = DEFAULT_SLICE_PRESET.id;
    const savedActive = localStorage.getItem(SLICE_ACTIVE_PRESET_KEY);
    if (savedActive && presets.some((p) => p.id === savedActive)) {
      activeId = savedActive;
    }
    return { presets, activeId };
  } catch {
    return { presets: [DEFAULT_SLICE_PRESET], activeId: DEFAULT_SLICE_PRESET.id };
  }
}

/**
 * 持久化预设列表（自动剔除默认预设，只存自定义，与旧逻辑一致）与激活 id。
 */
export function persistPresets(list: SlicePreset[], activeId: string): void {
  try {
    const withoutDefault = list.filter((p) => p.id !== DEFAULT_SLICE_PRESET.id);
    localStorage.setItem(SLICE_PRESET_STORAGE_KEY, JSON.stringify(withoutDefault));
    localStorage.setItem(SLICE_ACTIVE_PRESET_KEY, activeId);
  } catch {
    // 存储失败忽略（与旧逻辑一致）
  }
}
