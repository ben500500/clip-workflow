import React, { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Checkbox,
  Empty,
  Modal,
  Pagination,
  Segmented,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  DownOutlined,
  DownloadOutlined,
  PlayCircleOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { assetApi, type AssetBatch, type AssetOutput, type AssetOutputGroup } from '../../api/assets';

const { Text } = Typography;

const PAGE_SIZE = 60;

const KIND_OPTIONS = [
  { value: 'doubao_raw', label: '豆包成片' },
  { value: 'composed', label: '拼接成片' },
  { value: 'package', label: '交付包' },
  { value: 'copy', label: '文案文件' },
];

const QC_LABELS: Record<string, { color: string; text: string }> = {
  passed: { color: 'green', text: '验收过' },
  warn: { color: 'orange', text: '有提醒' },
  failed: { color: 'red', text: '不合格' },
};

function fmtSize(n: number | null): string {
  if (!n) return '';
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}M`;
  return `${Math.round(n / 1024)}K`;
}

function fmtDuration(n: number | null): string {
  if (n == null) return '';
  return `${n.toFixed(1)}s`;
}

const qcOf = (s: string | null) => (s ? QC_LABELS[s] : undefined);

/**
 * 组内成片墙（两级视图第二级）：一个素材/批次的片子，勾选下载、预览、翻页都在这一层。
 * 勾选集是组件自己的：收起即卸载、勾选清空（列表层不做跨组汇总，挑片子就在一组里挑）。
 */
const OutputGrid: React.FC<{
  assetId?: string;
  batchId?: string;
  kind?: string;
  qc?: string;
  owner?: 'me' | 'all';
  active?: boolean;
  reloadToken?: number;
  /** P1：勾选上报到跨组篮子（output_id, checked) */
  onBasketChange?: (outputId: string, checked: boolean) => void;
}> = ({ assetId, batchId, kind, qc, owner, active = true, reloadToken, onBasketChange }) => {
  const [items, setItems] = useState<AssetOutput[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [downProgress, setDownProgress] = useState('');
  const [preview, setPreview] = useState<{ output: AssetOutput; url: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const fetchList = useCallback(
    async (p: number = 1) => {
      setLoading(true);
      try {
        const res = await assetApi.listOutputs({
          asset_id: assetId,
          batch_id: batchId,
          kind,
          qc_status: qc || undefined,
          owner,
          limit: PAGE_SIZE,
          offset: (p - 1) * PAGE_SIZE,
        });
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(p);
      } catch (e) {
        message.error((e as Error).message || '加载成片失败');
      } finally {
        setLoading(false);
      }
    },
    [assetId, batchId, kind, qc, owner],
  );

  // A′ UX：页签切回来自动刷新（网格跟着组层一起）
  const wasActiveG = React.useRef(active);
  useEffect(() => {
    if (active && !wasActiveG.current) fetchList(page);
    wasActiveG.current = active;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    fetchList(1);
  }, [fetchList]);

  useEffect(() => {
    if (reloadToken) fetchList(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const pickedItems = items.filter((i) => picked.has(i.id));

  const openPreview = async (o: AssetOutput) => {
    setPreviewLoading(true);
    try {
      const res = await assetApi.previewOutput(o.id);
      setPreview({ output: o, url: res.url });
    } catch (e) {
      message.error((e as Error).message || '拿播放地址失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  /** 多选下载：串行一条条来（并行全开会被浏览器拦一部分），每条走 /download 口落账。 */
  const downloadPicked = async () => {
    if (!pickedItems.length || downloading) return;
    setDownloading(true);
    let ok = 0;
    const failed: string[] = [];
    for (let i = 0; i < pickedItems.length; i++) {
      const o = pickedItems[i];
      setDownProgress(`(${i + 1}/${pickedItems.length}) ${o.file_name || o.id.slice(0, 8)}`);
      try {
        const res = await assetApi.downloadOutput(o.id);
        const a = document.createElement('a');
        a.href = res.url;
        a.download = res.file_name || '';
        document.body.appendChild(a);
        a.click();
        a.remove();
        ok += 1;
      } catch (e) {
        failed.push(o.file_name || o.id.slice(0, 8));
        message.warning(`${o.file_name || o.id.slice(0, 8)}：${(e as Error).message || '下载失败'}`);
      }
      await new Promise((r) => setTimeout(r, 400));
    }
    setDownloading(false);
    setDownProgress('');
    if (ok) message.success(`已发起 ${ok} 条下载，浏览器右上角下载列表里看进度`);
    if (failed.length) message.warning(`${failed.length} 条没下成：${failed.slice(0, 3).join('、')}`);
    fetchList(page);
  };

  return (
    <div style={{ padding: '4px 0 8px 8px' }}>
      <Space size={8} wrap style={{ marginBottom: 8 }}>
        <Button
          type="primary"
          size="small"
          icon={<DownloadOutlined />}
          disabled={!pickedItems.length}
          loading={downloading}
          onClick={downloadPicked}
        >
          {downloading ? `下载中${downProgress}` : `下载勾选的 ${pickedItems.length} 条`}
        </Button>
        <Button size="small" disabled={!items.length} onClick={() => setPicked(new Set(items.map((i) => i.id)))}>
          本页全选
        </Button>
        <Button size="small" disabled={!picked.size} onClick={() => setPicked(new Set())}>
          清空
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {loading ? '加载中…' : `共 ${total} 条`}
        </Text>
      </Space>

      {!loading && !items.length ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={qc ? '这个验收条件下没有成片，清掉验收筛选试试。' : '这一组还没有成片。'}
        />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(168px, 1fr))',
            gap: 12,
          }}
        >
          {items.map((o) => {
            const q = qcOf(o.qc_status);
            return (
              <div
                key={o.id}
                style={{ border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden', background: '#fff' }}
              >
                <div style={{ position: 'relative', paddingTop: '133%', background: '#fafafa' }} onClick={() => openPreview(o)} role="button">
                  {o.thumb_url ? (
                    <img
                      src={o.thumb_url}
                      alt={o.file_name || ''}
                      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', cursor: 'pointer' }}
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        position: 'absolute',
                        inset: 0,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#bbb',
                        fontSize: 12,
                        gap: 4,
                      }}
                    >
                      <PlayCircleOutlined style={{ fontSize: 22 }} />
                      没有预览图
                    </div>
                  )}
                  <div
                    style={{
                      position: 'absolute',
                      right: 6,
                      bottom: 6,
                      background: 'rgba(0,0,0,0.55)',
                      color: '#fff',
                      fontSize: 12,
                      borderRadius: 4,
                      padding: '1px 6px',
                    }}
                  >
                    {fmtDuration(o.duration) || '—'}
                  </div>
                  <Checkbox
                    checked={picked.has(o.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      setPicked((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(o.id);
                        else next.delete(o.id);
                        return next;
                      });
                      // P1：勾选同步到跨组篮子（收起不清——跨组挑片）
                      onBasketChange?.(o.id, e.target.checked);
                    }}
                    style={{ position: 'absolute', left: 6, top: 6 }}
                  />
                </div>
                <div style={{ padding: '6px 8px 8px' }}>
                  <div style={{ marginBottom: 2 }}>
                    <Text strong style={{ fontSize: 12 }} ellipsis>
                      {o.asset_code || o.asset_id.slice(0, 8)}
                      {o.hook_code ? `｜${o.hook_code}` : ''}
                      {o.owner_name ? `｜投：${o.owner_name}` : o.production_id ? '' : '｜公共'}
                    </Text>
                  </div>
                  <Space size={4} wrap>
                    {q ? (
                      <Tooltip title={o.qc_note || undefined}>
                        <Tag color={q.color} style={{ fontSize: 11, lineHeight: '18px', marginInlineEnd: 0 }}>
                          {q.text}
                        </Tag>
                      </Tooltip>
                    ) : (
                      <Tag style={{ fontSize: 11, lineHeight: '18px', marginInlineEnd: 0 }}>未验</Tag>
                    )}
                    {o.downloaded_at && (
                      <Tooltip title={`素材库内下载于 ${o.downloaded_at.slice(0, 16).replace('T', ' ')}`}>
                        <Tag color="blue" style={{ fontSize: 11, lineHeight: '18px', marginInlineEnd: 0 }}>
                          已下载
                        </Tag>
                      </Tooltip>
                    )}
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {[fmtSize(o.file_size), o.resolution].filter(Boolean).join(' · ')}
                    </Text>
                  </Space>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {total > PAGE_SIZE && (
        <Pagination
          current={page}
          pageSize={PAGE_SIZE}
          total={total}
          showSizeChanger={false}
          onChange={(p) => fetchList(p)}
          style={{ marginTop: 12 }}
        />
      )}

      <Modal
        open={!!preview}
        title={
          preview
            ? `${preview.output.file_name || preview.output.id.slice(0, 8)}${preview.output.hook_code ? `（${preview.output.hook_code}）` : ''}`
            : ''
        }
        width={560}
        footer={
          preview && (
            <Space>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={async () => {
                  try {
                    const res = await assetApi.downloadOutput(preview.output.id);
                    const a = document.createElement('a');
                    a.href = res.url;
                    a.download = res.file_name || '';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    message.success('已发起下载');
                  } catch (e) {
                    message.error((e as Error).message || '下载失败');
                  }
                }}
              >
                下载这条
              </Button>
              <Button onClick={() => setPreview(null)}>关闭</Button>
            </Space>
          )
        }
        onCancel={() => setPreview(null)}
        destroyOnHidden
      >
        {preview && (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {preview.output.qc_status === 'failed' && (
              <Tag color="red">验收不合格：{preview.output.qc_note || '见验收记录'}——下载口会拦，先看清为什么废</Tag>
            )}
            <video src={preview.url} controls autoPlay style={{ width: '100%', maxHeight: 480, background: '#000' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {[fmtDuration(preview.output.duration), fmtSize(preview.output.file_size), preview.output.resolution]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          </Space>
        )}
      </Modal>
    </div>
  );
};

/**
 * 成片素材墙（批 K 建，2026-11-07 改两级）：
 *
 * 第一级＝按素材（钩子）/按批次的组清单（每组：最新缩略图＋成片数＋最近回收时间），
 * 点一行展开第二级＝这组的墙（缩略图点开预览、勾选串行下载、翻页）。
 * 聚合走 `/assets/outputs/groups`（batch_id 走素材侧收敛，拼接产物也归组）；
 * 类型/验收筛选在两级都生效。首帧是后台抽的，刚回收完要等一两分钟才有图，
 * 没图的画占位；直链 1 小时过期，「刷新」重拉。
 */
const AssetOutputWall: React.FC<{
  batchId?: string;
  reloadToken?: number;
  /** A′ 默认视图矩阵：operator=me、admin/material=all（页面层按角色传） */
  ownerDefault?: 'me' | 'all';
  /** 是否给「我的｜全部」开关（可审角色才有归属概念） */
  ownerSwitchable?: boolean;
  /** A′ UX：页签切回来自动刷新 */
  active?: boolean;
}> = ({
  batchId,
  reloadToken,
  ownerDefault = 'all',
  ownerSwitchable = false,
  active = true,
}) => {
  const [viewMode, setViewMode] = useState<'asset' | 'batch'>('asset');
  const [ownerView, setOwnerView] = useState<'me' | 'all'>(ownerDefault);
  const [packaging, setPackaging] = useState(false);
  // P1（评审定稿⑧）：跨组投放篮子——勾选跨组/跨页/刷新持久（sessionStorage）
  const [basket, setBasket] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(sessionStorage.getItem('asset-output-basket') ?? '[]'));
    } catch {
      return new Set();
    }
  });
  const persistBasket = (b: Set<string>) => {
    setBasket(b);
    sessionStorage.setItem('asset-output-basket', JSON.stringify([...b]));
  };
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  const [kindFilter, setKindFilter] = useState<string | undefined>('doubao_raw');
  const [qcFilter, setQcFilter] = useState<string | undefined>();
  const [groups, setGroups] = useState<AssetOutputGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  /** 当前展开的组（单开：点另一行切换，再点收起） */
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  // 批次下拉（按素材模式筛组用）
  const [batches, setBatches] = useState<AssetBatch[]>([]);
  useEffect(() => {
    assetApi
      .listBatches({ limit: 100 })
      .then((res) => setBatches(res.items || []))
      .catch(() => {
        /* 批次下拉拿不到不影响墙 */
      });
  }, []);

  const fetchGroups = useCallback(async () => {
    setGroupsLoading(true);
    try {
      const res = await assetApi.listOutputGroups({
        group_by: viewMode,
        batch_id: viewMode === 'asset' ? batchFilter : undefined,
        kind: kindFilter,
        qc_status: qcFilter || undefined,
        owner: ownerView,
      });
      setGroups(res.groups || []);
      setExpandedKey(null);
    } catch (e) {
      message.error((e as Error).message || '加载成片分组失败');
    } finally {
      setGroupsLoading(false);
    }
  }, [viewMode, batchFilter, kindFilter, qcFilter, ownerView]);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  // A′ UX：切走再切回页签时自动刷新（展开中的组内网格也带同一 active）
  const wasActive = React.useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) fetchGroups();
    wasActive.current = active;
  }, [active, fetchGroups]);

  useEffect(() => {
    if (reloadToken) fetchGroups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  // P1（评审定稿⑧）：跨组篮子打包下载——后端 zip＋manifest（发布侧"下载即落位"）
  const downloadBasket = async () => {
    if (!basket.size || packaging) return;
    setPackaging(true);
    try {
      const blob = await assetApi.packageOutputs([...basket]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'delivery-package.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      message.success(`已发起 ${basket.size} 条打包下载，浏览器右上角看进度`);
      persistBasket(new Set());
    } catch (e) {
      const msg = (e as Error).message || '打包失败';
      if (msg.includes('验收')) message.error(msg, 8);
      else message.error(msg.slice(0, 200), 8);
    } finally {
      setPackaging(false);
    }
  };

  // P1：跨组篮子的勾选回调（grid 勾选时调用）
  const handleBasketChange = (outputId: string, checked: boolean) => {
    const next = new Set(basket);
    if (checked) next.add(outputId);
    else next.delete(outputId);
    persistBasket(next);
  };

  const batchOptions = batches.map((b) => ({
    value: b.id,
    label: `${b.code} · ${b.name || '未命名'}（${b.item_count ?? 0} 条）`,
  }));

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* ── 筛选行：视图切换＋两级共用的筛选 ── */}
      <Space size={8} wrap>
        {ownerSwitchable && (
          <Segmented
            size="small"
            value={ownerView}
            onChange={(v) => setOwnerView(v as 'me' | 'all')}
            options={[
              { label: '我的', value: 'me' },
              { label: '全部', value: 'all' },
            ]}
          />
        )}
        <Segmented
          value={viewMode}
          onChange={(v) => setViewMode(v as 'asset' | 'batch')}
          options={[
            { label: '按素材（钩子）', value: 'asset' },
            { label: '按批次', value: 'batch' },
          ]}
        />
        {viewMode === 'asset' && (
          <Select
            style={{ width: 240 }}
            placeholder="批次（可选）"
            allowClear
            showSearch
            optionFilterProp="label"
            value={batchFilter}
            onChange={setBatchFilter}
            options={batchOptions}
          />
        )}
        <Select
          style={{ width: 140 }}
          value={kindFilter}
          onChange={setKindFilter}
          options={KIND_OPTIONS.map((k) => ({ value: k.value, label: k.label }))}
        />
        <Tooltip title="验收结论：passed=过、warn=有提醒、failed=不合格（不合格的仍可预览，下载口会拦）。">
          <span>
            <Select
              style={{ width: 130 }}
              placeholder="验收（可选）"
              allowClear
              value={qcFilter}
              onChange={setQcFilter}
              options={[
                { value: 'passed', label: '验收过' },
                { value: 'warn', label: '有提醒' },
                { value: 'failed', label: '不合格' },
              ]}
            />
            <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
          </span>
        </Tooltip>
        <Button icon={<ReloadOutlined />} loading={groupsLoading} onClick={() => fetchGroups()}>
          刷新
        </Button>
        {basket.size > 0 && (
          <Button
            type="primary"
            size="small"
            icon={<DownloadOutlined />}
            loading={packaging}
            onClick={downloadBasket}
          >
            打包下载（{basket.size} 条）
          </Button>
        )}
        {basket.size > 0 && (
          <Button size="small" onClick={() => persistBasket(new Set())}>
            清空篮子
          </Button>
        )}
        <Tooltip title="首帧是后台抽的：刚回收完要等一两分钟才有图；直链 1 小时过期，过期了点刷新续。">
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 {groups.length} 组
          </Text>
        </Tooltip>
      </Space>

      {/* ── 第一级：组清单 ── */}
      {!groupsLoading && !groups.length ? (
        <Empty
          description={
            kindFilter || qcFilter || batchFilter
              ? '这个筛选条件下没有成片。清掉筛选试试，或者先去「生产单与投板」投板回收。'
              : '还没有成片。去「生产单与投板」投板，片子回收回来就摆在这里。'
          }
        />
      ) : (
        <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden' }}>
          {groups.map((g) => {
            const open = expandedKey === g.key;
            return (
              <div key={g.key} style={{ borderBottom: '1px solid #f0f0f0' }}>
                <div
                  role="button"
                  onClick={() => setExpandedKey(open ? null : g.key)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '8px 12px',
                    cursor: 'pointer',
                    background: open ? '#fafafa' : '#fff',
                  }}
                >
                  {g.thumb_url ? (
                    <img
                      src={g.thumb_url}
                      alt=""
                      style={{ width: 32, height: 44, objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: 32,
                        height: 44,
                        borderRadius: 4,
                        background: '#f5f5f5',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#ccc',
                        flexShrink: 0,
                      }}
                    >
                      <PlayCircleOutlined />
                    </div>
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text strong style={{ fontSize: 13 }} ellipsis>
                      {g.label}
                    </Text>
                    {g.sub && (
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {g.sub}
                        </Text>
                      </div>
                    )}
                  </div>
                  <Tag color="blue">{g.count} 条</Tag>
                  {g.latest_at && (
                    <Text type="secondary" style={{ fontSize: 12, flexShrink: 0 }}>
                      最近 {g.latest_at.slice(5, 16).replace('T', ' ')}
                    </Text>
                  )}
                  {open ? <DownOutlined style={{ color: '#999' }} /> : <RightOutlined style={{ color: '#999' }} />}
                </div>
                {/* 第二级：该组的墙。单开即卸载，勾选随收起清空（挑片子就在一组里挑） */}
                {open && (
                  <OutputGrid
                    assetId={viewMode === 'asset' ? g.key : undefined}
                    batchId={viewMode === 'batch' ? (g.key === 'none' ? undefined : g.key) : undefined}
                    kind={kindFilter}
                    qc={qcFilter}
                    owner={ownerView}
                    active={active}
                    reloadToken={reloadToken}
                    onBasketChange={handleBasketChange}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </Space>
  );
};

export default AssetOutputWall;
