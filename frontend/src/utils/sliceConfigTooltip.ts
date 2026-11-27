import React from 'react';
import type { SliceTask } from '../types';
import { formatDateTime, formatTaskDuration, getStatusLabel } from './format';
import { WATERMARK_STYLE_LABEL } from './watermarkStyles';

const MISSING = '该字段未记录（历史任务）';
const HIDDEN = '[已隐藏凭据]';
const PREVIEW_LINES = 5;

type TooltipRow = {
  key: string;
  label: string;
  value: React.ReactNode;
  missing?: boolean;
};

// 后端任务快照可能携带选点/切片输入，但当前共享 SliceTask 类型尚未声明它们。
// 仅在当前文件做局部兼容读取，不修改调用方或共享类型。
type SliceTaskWithInputs = SliceTask & {
  cutlist?: string | null;
  intervals?: string | null;
  slice_autoclip_run_id?: string | null;
};

const FIELD_LABELS: Record<string, string> = {
  id: '任务 ID',
  task_id: '任务 ID',
  episode_id: '剧集 ID',
  mode: '模式',
  status: '状态',
  node_id: 'Worker 节点',
  created_at: '创建时间',
  started_at: '开始时间',
  completed_at: '完成时间',
  last_progress_at: '最后心跳',
  progress: '进度',
  progress_message: '进度文案',
  outputs_done: '已产出（实时）',
  outputs_total: '计划产出',
  output_count: '已产出（记录）',
  source_bucket: '源桶',
  source_file_key: '源文件 Key',
  cutlist: 'Cutlist',
  intervals: '排除区间',
  slice_autoclip_run_id: 'AI 选点运行 ID',
  output_tier: '输出档位',
  variant_count: '变体数量',
  cover_image_key: '封面 Key',
  hook_video_key: '单钩子视频 Key',
  hook_video_keys: '钩子视频 Key 列表',
  hook_mix_mode: '钩子混搭模式',
  hook_mix_output_count: '混搭输出数量',
  hook_position: '钩子位置',
  outro_video_key: '片尾视频 Key',
  dual_mix_config: '双批混拼配置',
  remotion_mix_config: 'Remotion 混剪配置',
  remotion_status: 'Remotion 状态',
  remotion_output_file_key: 'Remotion 产物 Key',
  dedupe_config: '去重配置',
  vert2horiz_config: '竖屏转横屏',
  subtitle_config: 'ASR 字幕烧录',
  subtitle_align_mask: '字幕对齐源字幕打码',
  subtitle_mask_config: '源字幕打码',
  watermark_mask_config: '水印打码',
  watermark_config: '动态水印',
  badges_config: '图片角标',
  badge_default_width: '角标默认宽度',
  text_overlays_config: '固定文字',
  enabled: '开启状态',
  template: '模板',
  preset: '预设',
  level: '档位',
  manual: '手动覆盖',
  intro: '片头',
  outro: '片尾',
  transition_frames: '转场帧数',
  subtitle_style: '字幕样式',
  output_size: '输出尺寸',
  ratio: '比例',
  detect_interval: '检测间隔',
  smooth_window: '平滑窗口',
  min_step: '最小移动步长',
  face_margin: '人脸边距',
  font_ratio: '字号比例',
  fontRatio: '字号比例',
  margin_ratio: '字幕底部边距',
  spacing: '字间距',
  bold: '字体粗细',
  style: '样式',
  temporal: '帧级检测',
  spatial: '空间精细化',
  width_ratio: '宽度占比',
  height_ratio: '高度占比',
  bottom_ratio: '底部位置占比',
  srt_offset: 'SRT 时间偏移',
  srt: '字幕内容（SRT）',
  subtitle: '字幕',
  file_key: '文件 Key',
  cover_file_key: '封面文件 Key',
  text: '文字',
  position: '位置',
  width: '宽度',
  height: '高度',
  size: '大小',
  font_size: '字号',
  fontSize: '字号',
  color: '颜色',
  border_color: '边框颜色',
  borderColor: '边框颜色',
  vertical: '竖排',
  offset: '偏移',
  opacity: '透明度',
  duration_seconds: '时长（秒）',
  background: '背景',
  title: '标题',
  episode: '剧集',
  cover_use_episode: '使用剧集封面',
  crop: '裁切比例',
  hflip: '水平镜像',
  speed: '变速系数',
  saturation: '饱和度系数',
  gamma: '伽马',
  contrast: '对比度',
  brightness: '亮度调整',
  colorbalance: '复古偏色',
  colortemperature: '色温',
  noise: '颗粒噪点',
  sharpen: '锐化/降噪',
  scanline: '扫描线',
  vignette: '暗角',
  roll_band: '滚动暗带',
  jitter: '画面抖动',
  watermark: '贴纸水印',
  audio: '音频指纹差异化',
  sparkle: '星星点',
  face_watermark: '人脸漂浮水印',
  drift: '缓慢漂移',
  seed: '随机种子',
  interval: '检测间隔',
  count: '数量',
  order: '拼接顺序',
  max_duration: '总时长上限',
  max_clip_duration: '单段最大时长',
  highlight_count: '高光批数量',
  main_count: '正片批数量',
  highlight_position: '高光批位置',
};

const RAW_FIELD_KEYS = new Map(Object.entries(FIELD_LABELS).map(([key, label]) => [label, key]));

const VALUE_LABELS: Record<string, Record<string, string>> = {
  output_tier: {
    original: '原始档位（original）',
    auto: '自动降档（auto）',
    '1080p': '1080P',
    '720p': '720P',
    '480p': '480P',
  },
  hook_mix_mode: {
    sequential: '顺序循环（sequential）',
    random: '随机混搭（random）',
    combine: '全部钩子拼接（combine）',
  },
  hook_position: {
    head: '片头（head）',
    tail: '片尾（tail）',
  },
  highlight_position: {
    head: '片头（head）',
    tail: '片尾（tail）',
  },
  remotion_status: {
    pending: '等待渲染（pending）',
    rendering: '渲染中（rendering）',
    done: '已完成（done）',
    failed: '失败（failed）',
  },
  source_bucket: {
    'raw-footage': '原始素材桶（raw-footage）',
    sliced: '成品桶（sliced）',
  },
  template: { highlight: '高光（highlight）' },
  preset: {
    auto: '自动（auto）',
    fine: '精细（fine）',
    quick: '快速（quick）',
    light: '轻（light）',
    standard: '标准（standard）',
    heavy: '重（heavy）',
    std_crop_desat: '保守裁切降饱和（std_crop_desat）',
    std_retro_scan: '复古扫描（std_retro_scan）',
  },
  level: {
    auto: '自动（auto）',
    fine: '精细（fine）',
    quick: '快速（quick）',
    light: '轻（light）',
    standard: '标准（standard）',
    heavy: '重（heavy）',
  },
  mode: { fixed: '固定裁切（fixed）', dynamic: '动态裁切（dynamic）' },
  order: {
    time: '源时间顺序（time）',
    score: '评分顺序（score）',
    random: '随机顺序（random）',
  },
  style: {
    ...WATERMARK_STYLE_LABEL,
    delogo: '去框（delogo）',
    mosaic: '马赛克（mosaic）',
    blur: '模糊（blur）',
    gblur: '高斯模糊（gblur）',
    fill: '填充（fill）',
  },
  position: {
    left: '最左侧',
    'top-left': '左上',
    'top-center': '上中',
    'top-right': '右上',
    center: '居中',
    'bottom-left': '左下',
    'bottom-center': '下中',
    'bottom-right': '右下',
  },
};

const SENSITIVE_KEY = /(?:api[-_]?key|access[-_]?key|secret|password|passwd|token|authorization|cookie|credential|private[-_]?key|session[-_]?id|presigned[-_]?url|signature)/i;

function isSensitiveKey(key: string): boolean {
  return SENSITIVE_KEY.test(key);
}

/** 对无法按字段过滤的原始 JSON/错误文本再做一次保守脱敏。 */
function redactSecrets(text: string): string {
  return text
    .replace(/\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi, `Bearer ${HIDDEN}`)
    .replace(/\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g, HIDDEN)
    .replace(
      /((?:api[-_]?key|access[-_]?key|secret(?:[-_]?key)?|password|passwd|token|authorization|cookie|signature)["']?\s*[:=]\s*["']?)([^"'\s,}&]+)/gi,
      `$1${HIDDEN}`,
    )
    .replace(
      /([?&](?:api[-_]?key|access[-_]?key|secret(?:[-_]?key)?|password|passwd|token|authorization|cookie|signature)=)[^&#\s]+/gi,
      `$1${HIDDEN}`,
    );
}

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] || key;
}

function childPath(parent: string, key: string): string {
  return parent ? `${parent} · ${fieldLabel(key)}` : fieldLabel(key);
}

function formatValue(key: string, value: unknown): React.ReactNode {
  if (value === null) return '无（已记录为 null）';
  if (value === undefined) return MISSING;
  if (typeof value === 'boolean') {
    return key === 'enabled'
      ? `${value ? '开启' : '关闭'}（${String(value)}）`
      : `${value ? '是' : '否'}（${String(value)}）`;
  }
  if (typeof value === 'string') {
    const safeText = redactSecrets(value);
    if (!value) {
      return key === 'vignette' || key === 'audio'
        ? '关闭（已记录为空字符串）'
        : '空字符串（已记录）';
    }
    return VALUE_LABELS[key]?.[value] || safeText;
  }
  if (typeof value === 'number') {
    if ((key === 'width' || key === 'height' || key === 'font_size' || key === 'fontSize') && Number.isFinite(value)) {
      return `${value}px`;
    }
    return String(value);
  }
  if (typeof value === 'bigint') return String(value);
  if (typeof value === 'symbol') return value.toString();
  if (typeof value === 'function') return '函数（已记录）';
  return String(value);
}

function fieldRow(key: string, value: unknown, label = fieldLabel(key)): TooltipRow {
  return {
    key,
    label,
    value: value === null || value === undefined ? MISSING : formatValue(key, value),
    missing: value === null || value === undefined,
  };
}

function emptyRow(key: string, label: string, value: React.ReactNode): TooltipRow {
  return { key, label, value };
}

/** 将任意嵌套配置拍平为 definition-list 行，数组逐项展开，绝不输出大块 JSON。 */
function flattenConfig(
  value: unknown,
  path: string,
  rows: TooltipRow[],
  ancestors: WeakSet<object>,
): void {
  const leafLabel = path.split(' · ').pop() || path;
  const leafKey = RAW_FIELD_KEYS.get(leafLabel) || leafLabel;

  if (value === null || value === undefined) {
    rows.push({
      key: `row-${rows.length}`,
      label: path,
      value: value === null ? '无（已记录为 null）' : MISSING,
      missing: value === undefined,
    });
    return;
  }

  if (typeof value !== 'object') {
    rows.push({
      key: `row-${rows.length}`,
      label: path,
      value: isSensitiveKey(leafKey) ? HIDDEN : formatValue(leafKey, value),
    });
    return;
  }

  if (ancestors.has(value)) {
    rows.push(emptyRow(`row-${rows.length}`, path, '循环引用（未展开）'));
    return;
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      if (value.length === 0) {
        rows.push(emptyRow(`row-${rows.length}`, path, '无（已记录为空列表）'));
        return;
      }
      value.forEach((item, index) => {
        flattenConfig(item, `${path} · 第 ${index + 1} 项`, rows, ancestors);
      });
      return;
    }

    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      rows.push(emptyRow(`row-${rows.length}`, path, '无（已记录为空对象）'));
      return;
    }
    entries.forEach(([key, item]) => {
      const nextPath = childPath(path, key);
      if (isSensitiveKey(key)) {
        rows.push(emptyRow(`row-${rows.length}`, nextPath, HIDDEN));
      } else {
        flattenConfig(item, nextPath, rows, ancestors);
      }
    });
  } finally {
    ancestors.delete(value);
  }
}

function configRows(title: string, value: unknown): TooltipRow[] {
  if (value === null || value === undefined) {
    return [{ key: title, label: title, value: MISSING, missing: true }];
  }
  const rows: TooltipRow[] = [];
  flattenConfig(value, title, rows, new WeakSet());
  return rows;
}

function linePreviewRows(label: string, value: unknown): TooltipRow[] {
  if (value === null || value === undefined) {
    return [{ key: label, label, value: MISSING, missing: true }];
  }

  // 后端当前以文本形式保存这两类输入；同时兼容数组快照。
  const lines = Array.isArray(value)
    ? value.map((item) => {
        if (item !== null && typeof item === 'object') {
          return Object.entries(item as Record<string, unknown>)
            .map(([key, itemValue]) => `${fieldLabel(key)}：${String(formatValue(key, itemValue))}`)
            .join('，');
        }
        return String(formatValue('', item));
      })
    : typeof value === 'string'
      ? (value ? value.split(/\r\n|\n|\r/) : [])
      : null;

  if (!lines) return configRows(label, value);

  const rows: TooltipRow[] = [{
    key: `${label}-count`,
    label: `${label}行数`,
    value: lines.length === 0
      ? '0 行（已记录为空）'
      : `共 ${lines.length} 行${lines.length > PREVIEW_LINES ? '，仅展示前 5 行' : ''}`,
  }];

  lines.slice(0, PREVIEW_LINES).forEach((line, index) => {
    rows.push({
      key: `${label}-line-${index}`,
      label: `${label}第 ${index + 1} 行`,
      value: line.trim() ? redactSecrets(line) : '（空行）',
    });
  });

  if (lines.length > PREVIEW_LINES) {
    rows.push(emptyRow(
      `${label}-omitted`,
      `${label}省略`,
      `其余 ${lines.length - PREVIEW_LINES} 行未展开`,
    ));
  }
  return rows;
}

function hookKeyRows(value: unknown): TooltipRow[] {
  const label = '钩子视频 Key 列表';
  if (value === null || value === undefined) {
    return [{ key: label, label, value: MISSING, missing: true }];
  }
  if (!Array.isArray(value)) return configRows(label, value);
  if (value.length === 0) {
    return [emptyRow(label, label, '0 个（已记录为空列表）')];
  }
  const rows: TooltipRow[] = [emptyRow(`${label}-count`, label, `${value.length} 个`)];
  value.forEach((key, index) => {
    rows.push({
      key: `${label}-${index}`,
      label: `钩子 Key ${index + 1}`,
      value: key === null
        ? '无（已记录为 null）'
        : redactSecrets(String(key)),
    });
  });
  return rows;
}

function dualMixRows(value: unknown): TooltipRow[] {
  const title = '双批混拼配置';
  if (value === null || value === undefined) {
    return [{ key: title, label: title, value: MISSING, missing: true }];
  }
  if (typeof value !== 'string') return configRows(title, value);
  if (!value.trim()) return [emptyRow(title, title, '空字符串（已记录）')];

  try {
    return configRows(title, JSON.parse(value));
  } catch {
    return [{
      key: `${title}-raw`,
      label: `${title}（原文）`,
      value: React.createElement(
        React.Fragment,
        null,
        React.createElement('span', { style: { color: '#ff7875' } }, 'JSON 解析失败，显示原始内容：'),
        React.createElement(
          'span',
          { style: { display: 'block', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } },
          redactSecrets(value),
        ),
      ),
    }];
  }
}

function DefinitionRows({ rows }: { rows: TooltipRow[] }) {
  return React.createElement(
    'dl',
    { style: { margin: 0 } },
    rows.map((row) => React.createElement(
      'div',
      {
        key: row.key,
        style: {
          display: 'grid',
          gridTemplateColumns: '100px minmax(0, 1fr)',
          gap: 8,
          padding: '3px 0',
          alignItems: 'start',
        },
      },
      React.createElement(
        'dt',
        { style: { color: '#aaa', fontWeight: 400, overflowWrap: 'anywhere' } },
        row.label,
      ),
      React.createElement(
        'dd',
        {
          style: {
            margin: 0,
            minWidth: 0,
            color: row.missing ? '#888' : '#ddd',
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            wordBreak: 'break-word',
          },
        },
        row.value,
      ),
    )),
  );
}

function ConfigSection({ title, rows }: { title: string; rows: TooltipRow[] }) {
  return React.createElement(
    'section',
    { style: { borderTop: '1px solid rgba(255,255,255,0.12)', marginTop: 10, paddingTop: 8 } },
    React.createElement('h4', { style: { margin: '0 0 5px', fontSize: 12, lineHeight: 1.5, color: '#fff' } }, title),
    React.createElement(DefinitionRows, { rows }),
  );
}

function dateValue(value: string | null | undefined): React.ReactNode {
  return value ? formatDateTime(value) : MISSING;
}

/** 构建切片任务实际应用配置的结构化悬停内容，供 Antd Tooltip title 使用。 */
export function buildSliceConfigTooltip(
  t: SliceTask,
  modeLabel: string,
): React.ReactNode {
  const task = t as SliceTaskWithInputs;
  const mode = modeLabel || task.mode || MISSING;
  const progress = typeof task.progress === 'number' && Number.isFinite(task.progress)
    ? `${task.progress}%`
    : MISSING;

  const taskRows: TooltipRow[] = [
    fieldRow('id', task.id),
    fieldRow('episode_id', task.episode_id),
    { key: 'mode', label: '模式', value: mode },
    {
      key: 'status',
      label: '状态',
      value: task.status
        ? `${getStatusLabel(task.status)}（${task.status}）`
        : MISSING,
      missing: !task.status,
    },
    fieldRow('node_id', task.node_id, task.node_id ? 'Worker 节点' : 'Worker 节点（未分配或未记录）'),
    { key: 'created_at', label: '创建时间', value: dateValue(task.created_at) },
    {
      key: 'started_at',
      label: '开始时间',
      value: task.started_at ? formatDateTime(task.started_at) : '尚未开始',
    },
    {
      key: 'completed_at',
      label: '完成时间',
      value: task.completed_at ? formatDateTime(task.completed_at) : '尚未完成',
    },
    { key: 'last_progress_at', label: '最后心跳时间', value: dateValue(task.last_progress_at) },
    {
      key: 'duration',
      label: '耗时',
      value: task.started_at ? formatTaskDuration(task) : '尚未开始',
    },
    { key: 'progress', label: '进度', value: progress },
    fieldRow('progress_message', task.progress_message),
    fieldRow('outputs_done', task.outputs_done),
    fieldRow('outputs_total', task.outputs_total),
    fieldRow('output_count', task.output_count),
    fieldRow('source_bucket', task.source_bucket),
    fieldRow('source_file_key', task.source_file_key),
  ];

  const outputRows: TooltipRow[] = [
    fieldRow('output_tier', task.output_tier),
    fieldRow('variant_count', task.variant_count),
    fieldRow('cover_image_key', task.cover_image_key),
    task.hook_video_key === null || task.hook_video_key === undefined
      ? fieldRow('hook_video_key', task.hook_video_key)
      : {
          key: 'hook_video_key',
          label: '单钩子视频（1 个）',
          value: formatValue('hook_video_key', task.hook_video_key),
        },
    ...hookKeyRows(task.hook_video_keys),
    fieldRow('hook_mix_mode', task.hook_mix_mode),
    fieldRow('hook_mix_output_count', task.hook_mix_output_count),
    fieldRow('hook_position', task.hook_position),
    fieldRow('outro_video_key', task.outro_video_key),
  ];

  const remotionRows: TooltipRow[] = [
    ...dualMixRows(task.dual_mix_config),
    ...configRows('Remotion 混剪配置', task.remotion_mix_config),
    fieldRow('remotion_status', task.remotion_status),
    fieldRow('remotion_output_file_key', task.remotion_output_file_key),
  ];

  const badgeRows: TooltipRow[] = [
    ...configRows('图片角标', task.badges_config),
    fieldRow('badge_default_width', task.badge_default_width),
  ];

  return React.createElement(
    'div',
    {
      style: {
        width: 520,
        maxHeight: 560,
        overflowY: 'auto',
        boxSizing: 'border-box',
        fontSize: 12,
        lineHeight: 1.55,
        color: '#ddd',
      },
    },
    React.createElement(
      'header',
      { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 } },
      React.createElement('strong', { style: { fontSize: 13, color: '#fff' } }, '切片任务配置'),
      React.createElement('span', { style: { color: '#ddd', overflowWrap: 'anywhere' } }, `模式：${mode}`),
    ),
    React.createElement(ConfigSection, { title: '任务概要', rows: taskRows }),
    React.createElement(ConfigSection, {
      title: '选点 / 切片输入',
      rows: [
        ...linePreviewRows('Cutlist', task.cutlist),
        ...linePreviewRows('Intervals', task.intervals),
        fieldRow('slice_autoclip_run_id', task.slice_autoclip_run_id),
      ],
    }),
    React.createElement(ConfigSection, { title: '输出与钩子', rows: outputRows }),
    React.createElement(ConfigSection, { title: '高光 / 双批 / Remotion', rows: remotionRows }),
    React.createElement(ConfigSection, { title: '去重', rows: configRows('去重配置', task.dedupe_config) }),
    React.createElement(ConfigSection, { title: '竖屏转横屏', rows: configRows('竖屏转横屏', task.vert2horiz_config) }),
    React.createElement(ConfigSection, {
      title: 'ASR 字幕烧录',
      rows: [
        ...configRows('ASR 字幕烧录', task.subtitle_config),
        fieldRow('subtitle_align_mask', task.subtitle_align_mask),
      ],
    }),
    React.createElement(ConfigSection, { title: '源字幕打码', rows: configRows('源字幕打码', task.subtitle_mask_config) }),
    React.createElement(ConfigSection, { title: '水印打码', rows: configRows('水印打码', task.watermark_mask_config) }),
    React.createElement(ConfigSection, { title: '动态水印', rows: configRows('动态水印', task.watermark_config) }),
    React.createElement(ConfigSection, { title: '图片角标', rows: badgeRows }),
    React.createElement(ConfigSection, { title: '固定文字', rows: configRows('固定文字', task.text_overlays_config) }),
  );
}
