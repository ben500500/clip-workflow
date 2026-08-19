import React from 'react';
import {
  Space, Switch, InputNumber, Input, Select, Slider, Typography, Divider, Tooltip,
} from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import type { DedupeFieldDef } from '../api/dedupe';
import { useDedupePresets } from '../hooks/useDedupePresets';

const { Text } = Typography;

/** 去重手段手动配置值（与引擎 _resolve_dedupe_config 的 manual 字段一一对应）。 */
export interface DedupeManualConfigValue {
  // 空间层
  crop?: number;      // 裁切比例 0~0.2
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
  // 扩展特效（三方向）
  sparkle?: {            // 方向一：若隐若现星星点/小光环
    enabled?: boolean;
    count?: number;
    size?: number;
    opacity?: number;
    seed?: number;
  };
  face_watermark?: {     // 方向三：人脸跟踪动态漂浮淡色水印
    enabled?: boolean;
    text?: string;
    opacity?: number;
    font_size?: number;
    interval?: number;
  };
}

interface Props {
  value: DedupeManualConfigValue;
  onChange: (v: DedupeManualConfigValue) => void;
  /** 当前所选去重档位，用于展示未手动覆盖时的默认有效值 */
  preset?: string;
}

/**
 * 去重手段手动配置面板（受控组件，**动态渲染**）。
 *
 * 字段定义来自 GET /api/dedupe/presets（useDedupePresets），新增去重手段只需后端
 * 追加字段定义，前端自动出现对应控件。接口不可用时回退内置字段定义，行为不回归。
 */
const DedupeManualConfig: React.FC<Props> = ({ value, onChange, preset }) => {
  const { fields, getDefault } = useDedupePresets();
  const defaults = getDefault(preset);

  const set = (key: string, val: unknown) => {
    onChange({ ...value, [key]: val });
  };
  const setDict = (key: string, fieldKey: string, val: unknown) => {
    const cur = (value as Record<string, Record<string, unknown>>)[key] || {};
    const next = { enabled: true, ...cur, [fieldKey]: val };
    set(key, next);
  };

  const row = (label: string, tip: string | undefined, control: React.ReactNode) => (
    <Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%', marginBottom: 6 }}>
      <Space size={4}>
        <Text style={{ fontSize: 13 }}>{label}</Text>
        {tip && <Tooltip title={tip}><InfoCircleOutlined style={{ color: '#999', fontSize: 12 }} /></Tooltip>}
      </Space>
      {control}
    </Space>
  );

  // 渲染单个字段的控件（number/slider/switch/select/text）
  const renderControl = (
    def: DedupeFieldDef,
    currentVal: unknown,
    onChangeVal: (v: unknown) => void,
  ) => {
    const num = (v?: unknown): number => (typeof v === 'number' ? v : 0);
    switch (def.control) {
      case 'switch':
        return (
          <Switch size="small" checked={!!currentVal} onChange={(v) => onChangeVal(v)} />
        );
      case 'select':
        return (
          <Select
            value={(currentVal as string) ?? ''}
            onChange={(v) => onChangeVal(v)}
            style={{ width: 120 }}
            options={def.options || []}
          />
        );
      case 'slider':
        return (
          <Slider
            min={def.min ?? 0} max={def.max ?? 100} step={def.step ?? 1}
            value={num(currentVal)} style={{ width: 160 }}
            onChange={(v) => onChangeVal(v)}
          />
        );
      case 'number':
        return (
          <InputNumber
            min={def.min} max={def.max} step={def.step}
            value={num(currentVal)} style={{ width: 120 }}
            onChange={(v) => onChangeVal(v ?? def.default ?? 0)}
          />
        );
      case 'text':
        return (
          <Input
            value={(currentVal as string) ?? ''}
            maxLength={def.max_len}
            style={{ width: 160 }}
            onChange={(e) => onChangeVal(e.target.value)}
          />
        );
      default:
        return null;
    }
  };

  // 渲染一个 dict/group 字段（带 enabled 开关 + 子字段）
  const renderDictGroup = (def: DedupeFieldDef) => {
    const cur = (value as Record<string, Record<string, unknown>>)[def.key] as
      | Record<string, unknown>
      | undefined;
    const enabled = !!cur?.enabled;
    const enabledDef = def.fields?.find((f) => f.key === 'enabled');
    return (
      <React.Fragment key={def.key}>
        {row(
          enabledDef?.label || def.label,
          def.tip,
          <Switch
            size="small"
            checked={enabled}
            onChange={(v) => setDict(def.key, 'enabled', v)}
          />,
        )}
        {enabled && def.fields && (
          <Space direction="vertical" style={{ width: '100%' }}>
            {def.fields
              .filter((f) => f.key !== 'enabled')
              .map((sub) => {
                const subDefault = defaults[def.key];
                const subDefDefault =
                  (subDefault && (subDefault as Record<string, unknown>)[sub.key]) ??
                  sub.default;
                return row(
                  sub.label,
                  sub.tip,
                  renderControl(sub, cur?.[sub.key] ?? subDefDefault, (v) =>
                    setDict(def.key, sub.key, v),
                  ),
                );
              })}
          </Space>
        )}
      </React.Fragment>
    );
  };

  // 按 group 分组渲染，group 顺序与字段定义顺序保持一致
  const groups: { name: string; fields: DedupeFieldDef[] }[] = [];
  const groupIndex: Record<string, number> = {};
  for (const def of fields) {
    if (def.hidden) continue; // 引擎支持但 UI 不暴露的字段不渲染
    const g = def.group || '其他';
    if (!(g in groupIndex)) {
      groupIndex[g] = groups.length;
      groups.push({ name: g, fields: [] });
    }
    groups[groupIndex[g]].fields.push(def);
  }

  return (
    <div style={{ maxHeight: 460, overflow: 'auto', paddingRight: 8 }}>
      {groups.map(({ name, fields: groupFields }) => (
        <React.Fragment key={name}>
          <Divider orientation="left" plain style={{ marginTop: groupFields === groups[0].fields ? 0 : 8, fontSize: 13 }}>
            {name}
          </Divider>
          {groupFields.map((def) => {
            if (def.type === 'dict' || def.control === 'group') {
              return renderDictGroup(def);
            }
            const presetVal = defaults[def.key];
            return row(
              def.label,
              def.tip,
              renderControl(def, value[def.key as keyof DedupeManualConfigValue] ?? presetVal ?? def.default, (v) =>
                set(def.key, v),
              ),
            );
          })}
        </React.Fragment>
      ))}
    </div>
  );
};

export default DedupeManualConfig;
