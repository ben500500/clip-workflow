import type { SliceTask } from '../types';

// ── 构建切片任务实际应用配置的悬停展示内容 ──
// 将任务上保存的各配置字段汇总为易读的文本（用于「模式」列鼠标悬停提示）
export function buildSliceConfigTooltip(
  t: SliceTask,
  modeLabel: string,
): string {
  const lines: string[] = [];
  lines.push(`模式：${modeLabel}`);

  // 去重配置
  const dd = t.dedupe_config;
  if (dd && Object.keys(dd).length > 0) {
    lines.push(`去重：${JSON.stringify(dd)}`);
  }

  // 竖屏转横屏
  const v2h = t.vert2horiz_config;
  if (v2h && Object.keys(v2h).length > 0) {
    const v2hDesc =
      v2h.enabled === false
        ? '关闭'
        : `${v2h.mode === 'fixed' ? '固定' : '动态'}裁切 输出${v2h.output_size || '-'} 比例${v2h.ratio ?? '-'}`;
    lines.push(`竖屏转横屏：${v2hDesc}`);
  }

  // ASR 字幕烧录
  const sub = t.subtitle_config;
  if (sub && Object.keys(sub).length > 0) {
    const subOn = sub.enabled !== false;
    lines.push(`ASR 字幕烧录：${subOn ? '开启' : '关闭'}`);
  }

  // 文字水印
  const wm = t.watermark_config;
  if (wm && Object.keys(wm).length > 0) {
    const wmOn = wm.enabled !== false;
    lines.push(`文字水印：${wmOn ? '开启' : '关闭'}`);
    if (wmOn && wm.text) lines.push(`  内容：${String(wm.text)}`);
  }

  // 图片角标
  const badges = t.badges_config;
  if (badges && Array.isArray(badges.badges) && badges.badges.length > 0) {
    lines.push(`图片角标：${badges.badges.length} 个`);
  } else if (badges && Object.keys(badges).length > 0) {
    lines.push(`图片角标：${JSON.stringify(badges)}`);
  }
  if (t.badge_default_width) lines.push(`角标默认宽度：${t.badge_default_width}px`);

  // 固定文字角标
  const textOv = t.text_overlays_config;
  if (textOv && Array.isArray(textOv) && textOv.length > 0) {
    lines.push(`固定文字角标：${textOv.length} 个`);
  } else if (textOv && Object.keys(textOv).length > 0) {
    lines.push(`固定文字角标：${JSON.stringify(textOv)}`);
  }

  // 源字幕打码
  const sm = t.subtitle_mask_config;
  if (sm && Object.keys(sm).length > 0) {
    const smOn = sm.enabled !== false;
    const presetName = { auto: '自动', fine: '精细', quick: '快速' } as Record<string, string>;
    const preset = sm.preset ? (presetName[sm.preset] || sm.preset) : (sm.spatial ? '精细' : (sm.temporal === false ? '快速' : '自动'));
    lines.push(`源字幕打码：${smOn ? `开启(${sm.style || 'delogo'}·${preset})` : '关闭'}`);
  }

  // 恒定水印打码
  const wmm = t.watermark_mask_config;
  if (wmm && Object.keys(wmm).length > 0) {
    const wmmOn = wmm.enabled !== false;
    lines.push(`恒定水印打码：${wmmOn ? `开启(${wmm.style || 'delogo'})` : '关闭'}`);
  }

  // 字幕对齐源字幕打码
  if (t.subtitle_align_mask != null && t.subtitle_align_mask !== true) {
    lines.push('字幕对齐源字幕打码：关闭');
  }

  // 兜底：以上均无配置时
  if (lines.length <= 1) {
    lines.push('该任务未记录额外的自定义配置');
  }

  return lines.join('\n');
}
