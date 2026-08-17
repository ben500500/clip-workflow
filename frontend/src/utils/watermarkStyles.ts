// ── 动态文字水印形态/运动样式（与后端 engines/slice.py build_watermark_filter 对齐）──
// 每种形态决定水印在画面中的位置 + 运动轨迹 + 可选特效。
export const WATERMARK_STYLE_OPTIONS = [
  { value: 'scroll', label: '横滚', desc: '底部/顶部水平匀速横滚 + 透明度呼吸（默认）' },
  { value: 'float', label: '斜漂', desc: '横向滚动 + 纵向缓慢上下漂移，避开主体' },
  { value: 'wave', label: '波浪', desc: '水平滚动 + 正弦上下浮动，更有节奏感' },
  { value: 'bounce', label: '折返', desc: '左右往返折返游走，适合高频发布防查重' },
  { value: 'breath', label: '呼吸', desc: '固定居中，透明度明暗脉动，低调常驻' },
  { value: 'blink', label: '闪现', desc: '固定位置定时闪现（每 4s 亮 0.7s）' },
] as const;

export type WatermarkStyle = (typeof WATERMARK_STYLE_OPTIONS)[number]['value'];

// 形态值 → 中文名（供 tooltip 展示）
export const WATERMARK_STYLE_LABEL: Record<string, string> = Object.fromEntries(
  WATERMARK_STYLE_OPTIONS.map((o) => [o.value, o.label]),
);
