import React from 'react';
import {
  Space, Switch, InputNumber, Input, Select, Slider, Typography, Divider, Tooltip,
} from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';

const { Text } = Typography;

/** 去重手段手动配置值（与引擎 _resolve_dedupe_config 的 manual 字段一一对应）。 */
export interface DedupeManualConfigValue {
  // 空间层
  crop?: number;      // 裁切比例 0~0.2（默认 0.03）
  hflip?: boolean;    // 水平镜像
  // 时域层
  speed?: number;     // 变速系数 1.0~1.2
  // 色彩层
  saturation?: number; // 饱和度 0.5~1.5
  gamma?: number;      // 伽马 0.8~1.4
  contrast?: number;   // 对比度 0.8~1.4
  brightness?: number; // 亮度 -0.2~0.2
  // 质感层
  noise?: number;      // 颗粒噪点强度 0~20
  vignette?: string;   // 暗角角度（PI/x）
  roll_band?: number;  // 滚动暗带强度 0~30
  jitter?: number;     // 画面抖动 0~8
  sharpen?: number;    // 锐化强度 0~2
  watermark?: {
    enabled?: boolean;
    text?: string;
    opacity?: number;
    position?: string;
    drift?: boolean;
  };
}

// 各档位的默认去重参数（与后端 engines/slice.py 的 DEDUPE_PRESETS 保持一致），
// 用于在未手动覆盖时展示当前所选档位的有效值。
const DEDUPE_PRESETS: Record<string, Partial<DedupeManualConfigValue>> = {
  // 画质优先：所有默认档位统一不做镜像（hflip=false），并将明显影响画质的
  // 效果（颗粒噪点 noise / 扫描线 / 复古偏色 / 暖冷色温 / 暗角 vignette /
  // 滚动暗带 roll_band / 抖动 jitter）去掉或降到最低值。保留对画面影响小但
  // 同样能拉低查重风险的手段：轻微裁切 crop / 变速 speed / 轻微降饱和 / 轻微锐化。
  light: {
    crop: 0.02,
    hflip: false,
    speed: 1.02,
    saturation: 0.92,
    gamma: 1.02,
    contrast: 1.01,
    brightness: 0.005,
    noise: 0,
    vignette: '',
    roll_band: 0,
    jitter: 0,
    sharpen: 0,
  },
  standard: {
    crop: 0.03,
    hflip: false,
    speed: 1.03,
    saturation: 0.88,
    gamma: 1.02,
    contrast: 1.02,
    brightness: 0.008,
    noise: 1,
    vignette: '',
    roll_band: 0,
    jitter: 0,
    sharpen: 0.4,
  },
  heavy: {
    crop: 0.05,
    hflip: false,
    speed: 1.05,
    saturation: 0.84,
    gamma: 1.03,
    contrast: 1.03,
    brightness: 0.012,
    noise: 2,
    vignette: '',
    roll_band: 0,
    jitter: 0,
    sharpen: 0.6,
  },
  // 两套推荐配方（无镜像）：与后端 engines/slice.py 的 DEDUPE_PRESETS 保持一致。
  // std_crop_desat 保守裁切降饱和（默认/首选）：裁切+变速+轻微降饱和，画面几乎无感
  std_crop_desat: {
    crop: 0.05,
    hflip: false,
    speed: 1.03,
    saturation: 0.9,
    gamma: 1.02,
    contrast: 1.02,
    brightness: 0.008,
    noise: 0,
    vignette: '',
    roll_band: 0,
    jitter: 0,
    sharpen: 0.3,
  },
  // std_retro_scan 保留（供手动选择）：无镜像，明显影响画质的复古暖调/扫描线/噪点
  //   已按画质优先降到最低（偏色≈0、色温≈中性、无扫描线、噪点≈0），不再作为首选。
  std_retro_scan: {
    crop: 0.05,
    hflip: false,
    speed: 1.04,
    saturation: 0.88,
    gamma: 1.02,
    contrast: 1.02,
    brightness: 0.008,
    noise: 1,
    vignette: '',
    roll_band: 0,
    jitter: 0,
    sharpen: 0.4,
  },
};

const WATERMARK_POSITIONS = [
  { value: 'top-left', label: '左上' },
  { value: 'top-right', label: '右上' },
  { value: 'top-center', label: '上中' },
  { value: 'center', label: '居中' },
  { value: 'bottom-left', label: '左下' },
  { value: 'bottom-right', label: '右下' },
  { value: 'bottom-center', label: '下中' },
];

interface Props {
  value: DedupeManualConfigValue;
  onChange: (v: DedupeManualConfigValue) => void;
  /** 当前所选去重档位（light/standard/heavy），用于展示未手动覆盖时的默认有效值 */
  preset?: string;
}

/** 去重手段手动配置面板（受控组件）。 */
const DedupeManualConfig: React.FC<Props> = ({ value, onChange, preset }) => {
  // 当前档位的默认值：未手动覆盖时展示这些有效值，便于用户知道开启后的实际效果
  const defaults = DEDUPE_PRESETS[preset || 'standard'] || DEDUPE_PRESETS.standard;
  const set = (key: keyof DedupeManualConfigValue, val: unknown) => {
    onChange({ ...value, [key]: val });
  };
  const setWm = (key: string, val: unknown) => {
    const wm = { enabled: true, ...(value.watermark || {}) } as Record<string, unknown>;
    wm[key] = val;
    set('watermark', wm as DedupeManualConfigValue['watermark']);
  };
  const wmEnabled = !!value.watermark?.enabled;

  const row = (label: string, tip: string, control: React.ReactNode) => (
    <Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%', marginBottom: 6 }}>
      <Space size={4}>
        <Text style={{ fontSize: 13 }}>{label}</Text>
        <Tooltip title={tip}><InfoCircleOutlined style={{ color: '#999', fontSize: 12 }} /></Tooltip>
      </Space>
      {control}
    </Space>
  );

  const num = (v?: number) => v ?? 0;

  return (
    <div style={{ maxHeight: 460, overflow: 'auto', paddingRight: 8 }}>
      <Divider orientation="left" plain style={{ marginTop: 0, fontSize: 13 }}>空间层</Divider>
      {row('裁切比例', '裁掉四周的比例（改构图/像素对齐），0~20%，越大越明显。',
        <InputNumber min={0} max={0.2} step={0.005} value={value.crop ?? defaults.crop} style={{ width: 120 }}
          onChange={(v) => set('crop', v ?? 0)} />)}
      {row('水平镜像', '水平翻转画面，直接破坏帧哈希。',
        <Switch size="small" checked={value.hflip ?? defaults.hflip} onChange={(v) => set('hflip', v)} />)}

      <Divider orientation="left" plain style={{ marginTop: 8, fontSize: 13 }}>时域层</Divider>
      {row('变速系数', '整体提速系数（1.0~1.2），改变时长与帧对齐。',
        <InputNumber min={1} max={1.2} step={0.01} value={value.speed ?? defaults.speed} style={{ width: 120 }}
          onChange={(v) => set('speed', v ?? 1.0)} />)}

      <Divider orientation="left" plain style={{ marginTop: 8, fontSize: 13 }}>色彩层</Divider>
      {row('饱和度', '饱和度系数，越小越灰（去重常用降饱和）。',
        <Slider min={0.5} max={1.5} step={0.01} value={value.saturation ?? defaults.saturation} style={{ width: 160 }}
          onChange={(v) => set('saturation', v)} />)}
      {row('伽马', '伽马值，微调亮度层次。',
        <InputNumber min={0.8} max={1.4} step={0.01} value={value.gamma ?? defaults.gamma} style={{ width: 120 }}
          onChange={(v) => set('gamma', v ?? 1.0)} />)}
      {row('对比度', '对比度系数。',
        <InputNumber min={0.8} max={1.4} step={0.01} value={value.contrast ?? defaults.contrast} style={{ width: 120 }}
          onChange={(v) => set('contrast', v ?? 1.0)} />)}
      {row('亮度', '亮度调整（-0.2~0.2）。',
        <InputNumber min={-0.2} max={0.2} step={0.005} value={value.brightness ?? defaults.brightness} style={{ width: 120 }}
          onChange={(v) => set('brightness', v ?? 0)} />)}

      <Divider orientation="left" plain style={{ marginTop: 8, fontSize: 13 }}>质感层（老电视效果）</Divider>
      {row('颗粒噪点', '胶片颗粒/老电视颗粒强度，0 关闭。',
        <Slider min={0} max={20} step={1} value={num(value.noise ?? defaults.noise)} style={{ width: 160 }}
          onChange={(v) => set('noise', v)} />)}
      {row('锐化/降噪', 'unsharp 锐化量，微调画质细节差异，0 关闭。',
        <Slider min={0} max={2} step={0.1} value={num(value.sharpen ?? defaults.sharpen)} style={{ width: 160 }}
          onChange={(v) => set('sharpen', v)} />)}
      {row('暗角', '边缘压暗（PI/6 轻 ~ PI/4 重），空值关闭。',
        <Select
          value={value.vignette ?? defaults.vignette ?? ''}
          onChange={(v) => set('vignette', v)}
          style={{ width: 120 }}
          options={[
            { value: '', label: '关闭' },
            { value: 'PI/6', label: '轻' },
            { value: 'PI/5', label: '中' },
            { value: 'PI/4', label: '重' },
          ]}
        />)}
      {row('滚动暗带', '上下缓慢滚动的亮度条带强度，0 关闭。',
        <Slider min={0} max={30} step={1} value={num(value.roll_band ?? defaults.roll_band)} style={{ width: 160 }}
          onChange={(v) => set('roll_band', v)} />)}
      {row('画面抖动', '正弦摆动强度（px），0 关闭。',
        <Slider min={0} max={8} step={1} value={num(value.jitter ?? defaults.jitter)} style={{ width: 160 }}
          onChange={(v) => set('jitter', v)} />)}

      <Divider orientation="left" plain style={{ marginTop: 8, fontSize: 13 }}>贴纸水印叠加</Divider>
      {row('开启贴纸水印', '叠加半透明文字标识作为去重差异化（区别于动态水印）。',
        <Switch size="small" checked={wmEnabled} onChange={(v) => setWm('enabled', v)} />)}
      {wmEnabled && (
        <Space direction="vertical" style={{ width: '100%' }}>
          {row('水印文字', '叠加的文字内容。',
            <Input value={value.watermark?.text} maxLength={20} style={{ width: 160 }}
              onChange={(e) => setWm('text', e.target.value)} />)}
          {row('透明度', '0.05~0.9，越低越不明显。',
            <Slider min={0.05} max={0.9} step={0.05} value={value.watermark?.opacity ?? 0.25} style={{ width: 160 }}
              onChange={(v) => setWm('opacity', v)} />)}
          {row('位置', '水印在画面中的位置。',
            <Select value={value.watermark?.position ?? 'bottom-right'} style={{ width: 120 }}
              onChange={(v) => setWm('position', v)} options={WATERMARK_POSITIONS} />)}
          {row('缓慢漂移', '水印随时间缓慢移动，增强时序差异化。',
            <Switch size="small" checked={!!value.watermark?.drift} onChange={(v) => setWm('drift', v)} />)}
        </Space>
      )}
    </div>
  );
};

export default DedupeManualConfig;
