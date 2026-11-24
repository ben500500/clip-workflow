import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Select, Space, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetItem, AssetOverlayBadge, AssetOverlayParams, AssetOverlayText } from '../../api/assets';
import { HelpDot } from './AssetBits';

const { Text } = Typography;

/**
 * 后端 BADGE_POSITIONS 的七位（`GET /assets/overlay-presets` 也会回 positions）。
 * 这份只做「列表口还没回就先渲染」的兜底，真正的可选值一律以接口回的为准——
 * 引擎侧 `slice.py:1253` 对不认识的位置是悄悄回落 top-left，中间层再自己扩一位
 * 就会造出「界面选了右下、片子上在左上、系统报成功」。
 */
export const FALLBACK_POSITIONS = [
  'top-left', 'top-center', 'top-right', 'left', 'bottom-left', 'bottom-center', 'bottom-right',
];

/** 位置的大白话名（一线不认 top-left，认「左上」） */
export const POSITION_LABELS: Record<string, string> = {
  'top-left': '左上',
  'top-center': '上中',
  'top-right': '右上',
  left: '左中',
  'bottom-left': '左下',
  'bottom-center': '下中',
  'bottom-right': '右下',
};

export const posLabel = (p: string): string => POSITION_LABELS[p] || p;

/** 区间与后端 `_int_in_range`／`_opacity` 逐字对齐，越界在输入框就拦住，别等接口 400 */
export const BADGE_WIDTH = { min: 0, max: 2000, default: 0 };
export const BADGE_OFFSET = { min: 0, max: 600, default: 10 };
export const TEXT_FONT = { min: 12, max: 200, default: 36 };
export const TEXT_OFFSET = { min: 0, max: 600, default: 10 };

export const emptyOverlay = (): AssetOverlayParams => ({ badges: [], text_overlays: [] });

export const overlayIsEmpty = (v: AssetOverlayParams | null | undefined): boolean =>
  !(v?.badges?.length || v?.text_overlays?.length);

/** 界面自己算的一行预告（口径与后端 `overlay_summary` 一致，省一次往返） */
export const overlayBriefText = (v: AssetOverlayParams | null | undefined): string => {
  if (overlayIsEmpty(v)) return '不叠加';
  const parts: string[] = [];
  if (v?.badges?.length) parts.push(`${v.badges.length} 个角标（${v.badges.map((b) => posLabel(b.position)).join('、')}）`);
  if (v?.text_overlays?.length) {
    parts.push(`${v.text_overlays.length} 行字（${v.text_overlays.map((t) => t.text.slice(0, 8)).join('、')}）`);
  }
  return parts.join(' ＋ ');
};

export interface OverlayLimits {
  maxBadges: number;
  maxTexts: number;
  maxChars: number;
}

const DEFAULT_LIMITS: OverlayLimits = { maxBadges: 6, maxTexts: 6, maxChars: 30 };

interface EditorProps {
  /** 抽屉／弹窗开着才去拉图片列表：库里的角标图随时有人在传，进页面缓存一次会让新图看不见 */
  active: boolean;
  value: AssetOverlayParams;
  onChange: (next: AssetOverlayParams) => void;
  positions?: string[];
  limits?: Partial<OverlayLimits>;
  disabled?: boolean;
}

/**
 * 叠加参数编辑器（角标图 ＋ 固定文字），预设抽屉和组合导出屏共用同一份。
 *
 * 为什么角标只能「从素材库挑图」：后端 `validate_overlay` 收的是 `asset_id`，
 * 和批 G 那条教训同源——手填 MinIO key 时打错一个字符照样能存，出片才发现没卡，
 * 而且事后查不到成因。这里的 id 全部由图片列表带回来，选不到库里不存在的图。
 *
 * 为什么每个数字框都带 min/max：越界值后端当场 400（不学引擎的静默回落），
 * 但一线在界面上撞 400 会比在输入框里改一下费劲得多。
 */
export const OverlayParamsEditor: React.FC<EditorProps> = ({
  active, value, onChange, positions, limits, disabled,
}) => {
  const pos = useMemo(() => positions && positions.length ? positions : FALLBACK_POSITIONS, [positions]);
  const cap: OverlayLimits = { ...DEFAULT_LIMITS, ...(limits || {}) };
  const badges = value.badges || [];
  const texts = value.text_overlays || [];

  const [images, setImages] = useState<AssetItem[]>([]);
  const [imgLoading, setImgLoading] = useState(false);
  const [imgError, setImgError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setImgLoading(true);
    setImgError(null);
    assetApi
      .listAssets({ media_kind: 'image', page_size: 200, sort: 'created_desc' })
      .then((res) => { if (!cancelled) setImages(res.items || []); })
      .catch((e) => { if (!cancelled) setImgError((e as Error).message || '图片素材拉不到'); })
      .finally(() => { if (!cancelled) setImgLoading(false); });
    return () => { cancelled = true; };
  }, [active]);

  const imgOptions = useMemo(
    () =>
      images.map((a) => {
        const noFile = !a.file_key;
        return {
          value: a.id,
          // 后端 `resolve_badge_refs` 对没文件的行直接 400，这里不给点
          disabled: noFile,
          label: `${a.code || a.id.slice(0, 8)} · ${a.title || a.file_name || '未命名'}${noFile ? ' · 桶里没文件，用不了' : ''}`,
        };
      }),
    [images],
  );

  const patchBadge = (idx: number, patch: Partial<AssetOverlayBadge>) => {
    const next = badges.map((b, i) => (i === idx ? { ...b, ...patch } : b));
    onChange({ ...value, badges: next });
  };
  const patchText = (idx: number, patch: Partial<AssetOverlayText>) => {
    const next = texts.map((t, i) => (i === idx ? { ...t, ...patch } : t));
    onChange({ ...value, text_overlays: next });
  };

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {imgError && <Alert type="warning" showIcon message={`角标图列表拉不到：${imgError}`} />}

      <div>
        <Space size={6}>
          <Text strong>角标图</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>最多 {cap.maxBadges} 个</Text>
          <HelpDot text="角标图必须是素材库里的图片素材（比如剧名条、警示角标）。宽度 0＝按原图尺寸贴，边距是离画面边缘多少像素，透明度 0.05～1。位置选了就得是那个位置：引擎侧对不认识的位置会悄悄回落左上角，所以后端对坏值是直接拒、不是容错。" />
        </Space>
        {badges.map((b, idx) => (
          <Space key={idx} wrap size={6} style={{ marginTop: 6 }}>
            <Select
              size="small"
              showSearch
              loading={imgLoading}
              disabled={disabled}
              style={{ width: 240 }}
              placeholder={imgLoading ? '读图片列表…' : '挑一张图（素材库图片）'}
              value={b.asset_id || undefined}
              onChange={(v) => patchBadge(idx, { asset_id: v as string })}
              options={imgOptions}
              optionFilterProp="label"
            />
            <Select
              size="small"
              disabled={disabled}
              style={{ width: 96 }}
              value={b.position || undefined}
              placeholder="位置"
              onChange={(v) => patchBadge(idx, { position: v as string })}
              options={pos.map((p) => ({ value: p, label: posLabel(p) }))}
            />
            <InputNumber
              size="small"
              disabled={disabled}
              style={{ width: 96 }}
              min={BADGE_WIDTH.min}
              max={BADGE_WIDTH.max}
              value={b.width ?? BADGE_WIDTH.default}
              addonAfter="宽"
              onChange={(v) => patchBadge(idx, { width: Number(v ?? BADGE_WIDTH.default) })}
            />
            <InputNumber
              size="small"
              disabled={disabled}
              style={{ width: 96 }}
              min={BADGE_OFFSET.min}
              max={BADGE_OFFSET.max}
              value={b.offset ?? BADGE_OFFSET.default}
              addonAfter="边距"
              onChange={(v) => patchBadge(idx, { offset: Number(v ?? BADGE_OFFSET.default) })}
            />
            <InputNumber
              size="small"
              disabled={disabled}
              style={{ width: 104 }}
              min={0.05}
              max={1}
              step={0.05}
              value={b.opacity ?? 1}
              addonAfter="透明"
              onChange={(v) => patchBadge(idx, { opacity: Number(v ?? 1) })}
            />
            {!disabled && (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => onChange({ ...value, badges: badges.filter((_, i) => i !== idx) })}
              />
            )}
          </Space>
        ))}
        {!disabled && (
          <div style={{ marginTop: 6 }}>
            <Button
              size="small"
              icon={<PlusOutlined />}
              disabled={badges.length >= cap.maxBadges}
              onClick={() =>
                onChange({
                  ...value,
                  badges: [...badges, { asset_id: '', position: pos[0], width: 0, offset: BADGE_OFFSET.default, opacity: 1 }],
                })
              }
            >
              加一个角标
            </Button>
          </div>
        )}
      </div>

      <div>
        <Space size={6}>
          <Text strong>固定文字</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>最多 {cap.maxTexts} 行、每行 {cap.maxChars} 字</Text>
          <HelpDot text="剧名、警示语、「后果自负」这类烧进画面的字。颜色要 #RGB 或 #RRGGBB（比如 #FFF、#FFFFFF），写汉字名或 rgb() 后端当场拒。竖排是给「剧名贴侧边」那种版面。" />
        </Space>
        {texts.map((t, idx) => (
          <Space key={idx} wrap size={6} style={{ marginTop: 6 }}>
            <Input
              size="small"
              disabled={disabled}
              style={{ width: 200 }}
              maxLength={cap.maxChars}
              placeholder="写什么字"
              value={t.text}
              onChange={(e) => patchText(idx, { text: e.target.value })}
            />
            <Select
              size="small"
              disabled={disabled}
              style={{ width: 96 }}
              value={t.position || undefined}
              placeholder="位置"
              onChange={(v) => patchText(idx, { position: v as string })}
              options={pos.map((p) => ({ value: p, label: posLabel(p) }))}
            />
            <InputNumber
              size="small"
              disabled={disabled}
              style={{ width: 96 }}
              min={TEXT_FONT.min}
              max={TEXT_FONT.max}
              value={t.font_size ?? TEXT_FONT.default}
              addonAfter="字号"
              onChange={(v) => patchText(idx, { font_size: Number(v ?? TEXT_FONT.default) })}
            />
            <Input
              size="small"
              disabled={disabled}
              style={{ width: 92 }}
              placeholder="#FFFFFF"
              value={t.color ?? '#FFFFFF'}
              onChange={(e) => patchText(idx, { color: e.target.value })}
            />
            <Input
              size="small"
              disabled={disabled}
              style={{ width: 92 }}
              placeholder="#000000 描边"
              value={t.border_color ?? '#000000'}
              onChange={(e) => patchText(idx, { border_color: e.target.value })}
            />
            <InputNumber
              size="small"
              disabled={disabled}
              style={{ width: 96 }}
              min={TEXT_OFFSET.min}
              max={TEXT_OFFSET.max}
              value={t.offset ?? TEXT_OFFSET.default}
              addonAfter="边距"
              onChange={(v) => patchText(idx, { offset: Number(v ?? TEXT_OFFSET.default) })}
            />
            <Checkbox
              disabled={disabled}
              checked={!!t.vertical}
              onChange={(e) => patchText(idx, { vertical: e.target.checked })}
            >
              竖排
            </Checkbox>
            {!disabled && (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => onChange({ ...value, text_overlays: texts.filter((_, i) => i !== idx) })}
              />
            )}
          </Space>
        ))}
        {!disabled && (
          <div style={{ marginTop: 6 }}>
            <Button
              size="small"
              icon={<PlusOutlined />}
              disabled={texts.length >= cap.maxTexts}
              onClick={() =>
                onChange({
                  ...value,
                  text_overlays: [
                    ...texts,
                    { text: '', position: pos[0], font_size: TEXT_FONT.default, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: TEXT_OFFSET.default },
                  ],
                })
              }
            >
              加一行字
            </Button>
          </div>
        )}
      </div>

      {overlayIsEmpty(value) && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          现在一个角标、一行字都没有＝不叠加（拼接本身照旧出片，只是不叠东西）。
        </Text>
      )}
    </Space>
  );
};

export default OverlayParamsEditor;
