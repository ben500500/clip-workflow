import type { DedupeFieldDef, DedupePresetDef } from '../api/dedupe';

/**
 * 去重配置单一来源化（Issue #252）——前端侧共享数据/缓存。
 *
 * 权威来源是后端 GET /api/dedupe/presets（其默认参数直接来自 engines/slice.py 的
 * DEDUPE_PRESETS）。前端各页面档位下拉 / DedupeManualConfig 动态渲染都通过
 * useDedupePresets() 拉取并缓存。此处保留一份**回退默认**（与既有硬编码完全一致），
 * 当接口不可用/加载失败时不阻塞页面，回退到现有默认。
 */

// ── localStorage 缓存键 ──
export const DEDUPE_PRESETS_CACHE_KEY = 'dedupe_presets_cache_v1';
// 接口来源与本地回退的区分标记
export const DEDUPE_PRESETS_SOURCE_KEY = 'dedupe_presets_source_v1';

/** 档位下拉选项（回退默认，与各页面既有硬编码一致）。 */
export const FALLBACK_DEDUPE_PRESETS: DedupePresetDef[] = [
  { value: 'std_crop_desat', label: '保守裁切降饱和（推荐）' },
  { value: 'std_retro_scan', label: '复古扫描' },
  { value: 'light', label: '轻' },
  { value: 'standard', label: '标准' },
  { value: 'heavy', label: '重' },
];

/** 各档位默认参数（回退默认，仅用于接口不可用时保证行为不回归）。 */
export const FALLBACK_DEDUPE_DEFAULTS: Record<string, Record<string, unknown>> = {
  light: {
    crop: 0.02, hflip: false, speed: 1.02, saturation: 0.92, gamma: 1.02,
    contrast: 1.01, brightness: 0.005, noise: 0, vignette: null, roll_band: 0,
    jitter: 0, sharpen: 0,
  },
  standard: {
    crop: 0.03, hflip: false, speed: 1.03, saturation: 0.88, gamma: 1.02,
    contrast: 1.02, brightness: 0.008, noise: 1, vignette: null, roll_band: 0,
    jitter: 0, sharpen: 0.4,
  },
  heavy: {
    crop: 0.05, hflip: false, speed: 1.05, saturation: 0.84, gamma: 1.03,
    contrast: 1.03, brightness: 0.012, noise: 2, vignette: null, roll_band: 0,
    jitter: 0, sharpen: 0.6,
  },
  std_crop_desat: {
    crop: 0.05, hflip: false, speed: 1.03, saturation: 0.9, gamma: 1.02,
    contrast: 1.02, brightness: 0.008, noise: 0, vignette: null, roll_band: 0,
    jitter: 0, sharpen: 0.3,
  },
  std_retro_scan: {
    crop: 0.05, hflip: false, speed: 1.04, saturation: 0.85, gamma: 1.03,
    contrast: 1.03, brightness: 0.01, noise: 7, vignette: 'PI/5', roll_band: 0,
    jitter: 0, sharpen: 0.4,
  },
};

/** 字段定义（回退默认，与后端 DEDUPE_FIELD_DEFS 一致，供接口不可用时动态渲染）。 */
export const FALLBACK_DEDUPE_FIELDS: DedupeFieldDef[] = [
  { key: 'crop', label: '裁切比例', type: 'number', control: 'number', group: '空间层', min: 0, max: 0.2, step: 0.005, tip: '裁掉四周的比例（改构图/像素对齐），0~20%，越大越明显。' },
  { key: 'hflip', label: '水平镜像', type: 'bool', control: 'switch', group: '空间层', default: false, tip: '水平翻转画面，直接破坏帧哈希。' },
  { key: 'speed', label: '变速系数', type: 'number', control: 'number', group: '时域层', min: 1, max: 1.2, step: 0.01, default: 1.0, tip: '整体提速系数（1.0~1.2），改变时长与帧对齐。' },
  { key: 'saturation', label: '饱和度', type: 'number', control: 'slider', group: '色彩层', min: 0.5, max: 1.5, step: 0.01, default: 1.0, tip: '饱和度系数，越小越灰（去重常用降饱和）。' },
  { key: 'gamma', label: '伽马', type: 'number', control: 'number', group: '色彩层', min: 0.8, max: 1.4, step: 0.01, default: 1.0, tip: '伽马值，微调亮度层次。' },
  { key: 'contrast', label: '对比度', type: 'number', control: 'number', group: '色彩层', min: 0.8, max: 1.4, step: 0.01, default: 1.0, tip: '对比度系数。' },
  { key: 'brightness', label: '亮度', type: 'number', control: 'number', group: '色彩层', min: -0.2, max: 0.2, step: 0.005, default: 0, tip: '亮度调整（-0.2~0.2）。' },
  { key: 'colorbalance', label: '复古偏色', type: 'string', control: 'text', group: '色彩层', hidden: true },
  { key: 'colortemperature', label: '暖冷色温', type: 'string', control: 'text', group: '色彩层', hidden: true },
  { key: 'noise', label: '颗粒噪点', type: 'number', control: 'slider', group: '质感层', min: 0, max: 20, step: 1, default: 0, tip: '胶片颗粒/老电视颗粒强度，0 关闭。' },
  { key: 'sharpen', label: '锐化/降噪', type: 'number', control: 'slider', group: '质感层', min: 0, max: 2, step: 0.1, default: 0, tip: 'unsharp 锐化量，微调画质细节差异，0 关闭。' },
  { key: 'scanline', label: '扫描线', type: 'dict', control: 'group', group: '质感层', hidden: true, tip: '老电视扫描线（dict 或 None）。' },
  {
    key: 'vignette', label: '暗角', type: 'string', control: 'select', group: '质感层',
    options: [
      { value: '', label: '关闭' }, { value: 'PI/6', label: '轻' },
      { value: 'PI/5', label: '中' }, { value: 'PI/4', label: '重' },
    ],
    tip: '边缘压暗（PI/6 轻 ~ PI/4 重），空值关闭。',
  },
  { key: 'roll_band', label: '滚动暗带', type: 'number', control: 'slider', group: '质感层', min: 0, max: 30, step: 1, default: 0, tip: '上下缓慢滚动的亮度条带强度，0 关闭。' },
  { key: 'jitter', label: '画面抖动', type: 'number', control: 'slider', group: '质感层', min: 0, max: 8, step: 1, default: 0, tip: '正弦摆动强度（px），0 关闭。' },
  {
    key: 'watermark', label: '贴纸水印叠加', type: 'dict', control: 'group', group: '贴纸水印叠加', default: null,
    tip: '叠加半透明文字标识作为去重差异化（区别于动态水印）。',
    fields: [
      { key: 'enabled', label: '开启贴纸水印', type: 'bool', control: 'switch', default: false },
      { key: 'text', label: '水印文字', type: 'string', control: 'text', default: 'Clip', max_len: 20 },
      { key: 'opacity', label: '透明度', type: 'number', control: 'slider', min: 0.05, max: 0.9, step: 0.05, default: 0.25 },
      {
        key: 'position', label: '位置', type: 'string', control: 'select', default: 'bottom-right',
        options: [
          { value: 'top-left', label: '左上' }, { value: 'top-right', label: '右上' },
          { value: 'top-center', label: '上中' }, { value: 'center', label: '居中' },
          { value: 'bottom-left', label: '左下' }, { value: 'bottom-right', label: '右下' },
          { value: 'bottom-center', label: '下中' },
        ],
      },
      { key: 'drift', label: '缓慢漂移', type: 'bool', control: 'switch', default: false, tip: '水印随时间缓慢移动，增强时序差异化。' },
    ],
  },
  { key: 'audio', label: '音频指纹差异化', type: 'string', control: 'text', group: '音频层', hidden: true, tip: 'L3 音频指纹差异化，None 不叠加。' },
  {
    key: 'sparkle', label: '若隐若现星星点', type: 'dict', control: 'group', group: '扩展特效（星星点 / 人脸漂浮水印）', default: null,
    tip: '叠加带呼吸闪烁的星点/光点，几乎不可察觉但在帧级特征上增加差异化。',
    fields: [
      { key: 'enabled', label: '开启星星点', type: 'bool', control: 'switch', default: false },
      { key: 'count', label: '光点数量', type: 'number', control: 'number', min: 1, max: 8, step: 1, default: 3 },
      { key: 'size', label: '光点大小', type: 'number', control: 'number', min: 1, max: 6, step: 1, default: 3 },
      { key: 'opacity', label: '峰值亮度', type: 'number', control: 'slider', min: 1, max: 40, step: 1, default: 10 },
    ],
  },
  {
    key: 'face_watermark', label: '人脸漂浮水印', type: 'dict', control: 'group', group: '扩展特效（星星点 / 人脸漂浮水印）', default: null,
    tip: '跟随人脸移动的极淡水印（复用人脸检测引擎），人脸位置变化时水印随之漂浮。',
    fields: [
      { key: 'enabled', label: '开启人脸漂浮水印', type: 'bool', control: 'switch', default: false },
      { key: 'text', label: '水印文字', type: 'string', control: 'text', default: 'W', max_len: 10 },
      { key: 'opacity', label: '透明度', type: 'number', control: 'slider', min: 0.02, max: 0.3, step: 0.01, default: 0.08 },
      { key: 'font_size', label: '字号', type: 'number', control: 'number', min: 12, max: 60, step: 1, default: 24 },
    ],
  },
];

/** 默认档位（无选择时的回退值）。 */
export const DEFAULT_DEDUPE_PRESET = 'std_crop_desat';
