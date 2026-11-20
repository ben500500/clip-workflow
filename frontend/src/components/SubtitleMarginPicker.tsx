import { InputNumber, Select, Tooltip, Typography } from 'antd';

const { Text } = Typography;

// 字幕高度预设：字幕块距画面底部的距离（占屏高比例），越小越贴底。
// 引擎语义：margin_v = int(屏高 × ratio)（ASS 底边 MarginV），
// 默认 0.25 = 字幕块位于画面下方 1/4 处；0.05 ≈ 字幕几乎压着底边。
export const SUBTITLE_MARGIN_PRESETS = [
  { value: 0.05, label: '贴底（距底 5%）' },
  { value: 0.08, label: '很贴底（距底 8%）' },
  { value: 0.12, label: '贴近底部（12%）' },
  { value: 0.18, label: '偏下（18%）' },
  { value: 0.25, label: '标准（1/4 处）' },
  { value: 0.35, label: '偏上（35%）' },
];

interface SubtitleMarginPickerProps {
  value: number;
  onChange: (v: number) => void;
  /** 数字框精调下限（默认 0.02） */
  min?: number;
  /** 数字框精调上限（默认 0.6） */
  max?: number;
  /** 标签是否加粗（切片任务页用加粗） */
  labelStrong?: boolean;
  /** 数字框宽度 */
  numberWidth?: number;
}

/** ASR 字幕高度选择器：预设下拉（含贴底档）+ 数字框精调，三处切片配置共用。 */
export default function SubtitleMarginPicker({
  value,
  onChange,
  min = 0.02,
  max = 0.6,
  labelStrong = false,
  numberWidth = 80,
}: SubtitleMarginPickerProps) {
  const isPreset = SUBTITLE_MARGIN_PRESETS.some((p) => Math.abs(p.value - value) < 1e-6);
  const Label = labelStrong ? (
    <Text strong style={{ fontSize: 12, cursor: 'help' }}>字幕高度</Text>
  ) : (
    <Text style={{ fontSize: 12, cursor: 'help' }}>字幕高度</Text>
  );
  return (
    <>
      <Tooltip title="字幕高度：字幕块距画面底部的距离（占屏高比例），越小越贴底。0.25 = 默认（画面下方 1/4 处）；预设外数值用右侧数字框精调">
        {Label}
      </Tooltip>
      <Select
        size="small"
        style={{ width: 150 }}
        value={isPreset ? value : 'custom'}
        onChange={(v) => {
          if (v !== 'custom') onChange(v as number);
        }}
        options={[
          ...SUBTITLE_MARGIN_PRESETS,
          ...(!isPreset ? [{ value: 'custom', label: `自定义（${value.toFixed(2)}）` }] : []),
        ]}
      />
      <InputNumber
        size="small"
        min={min}
        max={max}
        step={0.01}
        value={value}
        onChange={(v) => onChange(v ?? 0.25)}
        style={{ width: numberWidth }}
      />
    </>
  );
}
