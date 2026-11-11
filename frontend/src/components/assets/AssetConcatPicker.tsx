import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Radio, Select, Space, Typography } from 'antd';
import { assetApi } from '../../api/assets';
import type { AssetAutoConcatOrder, AssetItem } from '../../api/assets';
import { durationText } from './AssetBits';

const { Text } = Typography;

/** 一次拉多少条：后端 page_size 封顶 200；拼接素材是「几条常驻正片段」的量级 */
const LOAD_SIZE = 200;

interface Props {
  /** 弹窗开着才拉：库里随时有人在传新片段，进页面缓存一次会让新片段看不见 */
  active: boolean;
  /** 已选的拼接素材 id（asset_items.id）；null＝这次不提拼装要求 */
  value: string | null;
  onChange: (id: string | null) => void;
  order: AssetAutoConcatOrder;
  onOrderChange: (order: AssetAutoConcatOrder) => void;
}

/**
 * 批 Q（11-10，需求⑤）：投板那一屏挑「成片到手后和哪条拼」。
 *
 * 为什么把这个选择放在**投出去之前**：自动拼是回收之后才做的，晚了 25 分钟。
 * 要是等片子到手才发现挑的那条拼不了（是图片／链接素材还没取回原片），号池已经烧了，
 * 人只能手工再拼一遍——而那正是需求⑤要消掉的那一步。所以后端把判据放在
 * `POST /assets/productions/dispatch` 的闸门段（复用手工口同一套 `_resolve_concat_input`），
 * 这里只把「库里真实存在、且真的能当一段」的那些列出来，选不到拼不了的东西。
 *
 * 三件事必须写在界面上（都是后端实测口径，藏起来一线会当成 bug 报）：
 * 1. **0 元**：不调模型、不调智令，纯本机 ffmpeg，跟手工拼接一个价。
 * 2. **排在最前那段决定画幅**——所以「素材片段在前」会把竖屏钩子片补边进第二段。
 * 3. **钉在单行上**，不是只活在这次请求里：进程重启后带「只回收」再跑一次照样会拼。
 */
const AssetConcatPicker: React.FC<Props> = ({ active, value, onChange, order, onOrderChange }) => {
  const [rows, setRows] = useState<AssetItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    // 只列视频：图片后端不当一段用（口径与手工口一致），链接素材没文件的照旧列出来但选不动，
    // 让一线看见"是这条、得先去取回原片"，而不是悄悄少一条。
    assetApi
      .listAssets({ media_kind: 'video', page_size: LOAD_SIZE, sort: 'created_desc' })
      .then((res) => {
        if (cancelled) return;
        setRows(res.items || []);
        setTotal(res.total || 0);
      })
      .catch((e) => {
        if (!cancelled) setLoadError((e as Error).message || '素材列表拉不到');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active]);

  const byId = useMemo(() => {
    const m: Record<string, AssetItem> = {};
    rows.forEach((a) => {
      m[a.id] = a;
    });
    return m;
  }, [rows]);

  const options = useMemo(
    () =>
      rows.map((a) => {
        const noFile = !a.file_key;
        return {
          value: a.id,
          // 后端 `_resolve_concat_input` 对没文件的行直接 400，这里不给点
          disabled: noFile,
          label: `${a.code || a.id.slice(0, 8)} · ${a.title || a.file_name || '未命名'} · ${
            durationText(a.duration)
          }${noFile ? ' · 桶里没原片，不能拼' : ''}`,
        };
      }),
    [rows],
  );

  const picked = value ? byId[value] : null;
  /** 已选但这次列表里没有（多半刚被删）：不静默丢掉，点名让人重挑 */
  const missing = !!value && !picked;

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <Select
        showSearch
        allowClear
        loading={loading}
        style={{ width: '100%' }}
        placeholder="不拼（回收到的成片原样进产物）"
        value={value ?? undefined}
        onChange={(v) => onChange((v as string) ?? null)}
        options={options}
        optionFilterProp="label"
        filterOption={(input, option) =>
          String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
        }
      />
      {loadError && <Alert type="warning" showIcon message={`片段列表拉不到：${loadError}`} />}
      {missing && (
        <Alert
          type="warning"
          showIcon
          message={`已选的那条（${value?.slice(0, 8)}）不在当前列表里（多半刚被删）——提交会被后端点名拒掉，重新挑一条`}
        />
      )}
      {!!picked && !picked.file_key && (
        <Alert
          type="warning"
          showIcon
          message={`${picked.code} 是链接素材、库里没有原片文件：先「查视频时长」把文件取回来，否则后端会在投出去之前就拒收`}
        />
      )}

      <Radio.Group
        value={order}
        onChange={(e) => onOrderChange(e.target.value as AssetAutoConcatOrder)}
        disabled={!picked}
        size="small"
      >
        <Radio value="hook_first">钩子片在前 · 片段在后</Radio>
        <Radio value="material_first">片段在前 · 钩子片在后</Radio>
      </Radio.Group>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {picked
          ? `每支收回来都会和「${picked.code}·${picked.title || picked.file_name || '未命名'}」拼一条，`
          : '两段直拼，不选点不剪切；'}
        排在<b>最前</b>那段决定画幅（当前按
        {order === 'hook_first' ? '钩子片' : '所选片段'}）。拼成 0 元、每支只拼一次，
        要求钉在单上：进程重启后走「只回收」也照样拼。
      </Text>
      {total > rows.length && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          库里共 {total} 条视频，这里只列最近 {rows.length} 条（按入库时间倒序）——
          找不到说明那条太早，去素材列表按编号搜出来再挑。
        </Text>
      )}
    </Space>
  );
};

export default AssetConcatPicker;
