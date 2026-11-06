import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Checkbox,
  Empty,
  Modal,
  Pagination,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  DownloadOutlined,
  PlayCircleOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { assetApi, type AssetBatch, type AssetOutput } from '../../api/assets';

const { Text } = Typography;

interface Props {
  /** 从别的页签带进来的批次初值（点批次跳转），只作初值 */
  batchId?: string;
  /** 后台任务跑完（横幅收敛）触发重拉 */
  reloadToken?: number;
}

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

/**
 * 成片素材墙（批 K）：回收回来的豆包成片不再藏在生产单行里，一面缩略图墙摆开——
 *
 * - **缩略图**＝产物首帧（output_thumb）。回收落库时后端自动排抽帧（批 K 接上了
 *   批 F 留的第二个写入方）；抽帧是后台任务，刚回收完的几条要等一两分钟才有图，
 *   没图的卡片画占位不报错，右上角「刷新」重拉直链（直链 1 小时过期也靠它续）。
 * - **预览**＝点卡片开播放器（内联 presign，不落盘）；验收不合格的也给看，
 *   播放器上方标红——看一眼为什么废和能不能投出去是两件事。
 * - **多选下载**＝勾选后串行走 `/outputs/{id}/download`（presigned attachment），
 *   每条都落 `downloaded_at` + 审计，跟单条下载同一套账。浏览器对连续多文件下载
 *   可能弹一次「允许下载多个文件」，允许即可；文件名后端已带素材名防重名。
 *
 * 筛选按**素材的导入批次**收敛（走 asset_items 侧）：拼接产物不挂生产单，
 * 按生产单查会漏，按素材查永远查得到。
 */
const AssetOutputWall: React.FC<Props> = ({ batchId, reloadToken }) => {
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  const [kindFilter, setKindFilter] = useState<string | undefined>('doubao_raw');
  const [qcFilter, setQcFilter] = useState<string | undefined>();
  const [items, setItems] = useState<AssetOutput[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  /** 勾选放 Set：翻页保留（墙是「挑片子」不是「勾表格」，翻页不该清空已挑的） */
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [downProgress, setDownProgress] = useState('');

  // 预览：点卡片 → 内联播放口拿直链
  const [preview, setPreview] = useState<{ output: AssetOutput; url: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // 批次下拉（与审核台同款：编号 + 名称 + 条数，免手填 UUID）
  const [batches, setBatches] = useState<AssetBatch[]>([]);
  useEffect(() => {
    assetApi
      .listBatches({ limit: 100 })
      .then((res) => setBatches(res.items || []))
      .catch(() => {
        /* 批次下拉拿不到不影响墙 */
      });
  }, []);

  const fetchList = useCallback(
    async (p: number = 1) => {
      setLoading(true);
      try {
        const res = await assetApi.listOutputs({
          batch_id: batchFilter,
          kind: kindFilter,
          limit: PAGE_SIZE,
          offset: (p - 1) * PAGE_SIZE,
        });
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(p);
      } catch (e) {
        message.error((e as Error).message || '加载成片列表失败');
      } finally {
        setLoading(false);
      }
    },
    [batchFilter, kindFilter],
  );

  useEffect(() => {
    fetchList(1);
  }, [batchFilter, kindFilter, fetchList]);

  // 后台抽帧/回收任务收敛后重拉（新片就有图了）；qc 筛选变化也在这里一起走
  useEffect(() => {
    fetchList(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qcFilter, reloadToken]);

  const batchOptions = useMemo(() => {
    const opts = batches.map((b) => ({
      value: b.id,
      label: `${b.code} · ${b.name || '未命名'}（${b.item_count ?? 0} 条）`,
    }));
    if (batchFilter && !opts.some((o) => o.value === batchFilter)) {
      opts.unshift({ value: batchFilter, label: `当前批次 ${batchFilter.slice(0, 8)}…` });
    }
    return opts;
  }, [batches, batchFilter]);

  const toggle = (id: string, checked: boolean) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const pickedItems = useMemo(() => items.filter((i) => picked.has(i.id)), [items, picked]);

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

  /**
   * 多选下载：串行一条条来。并行全开会被浏览器当弹窗攻击拦掉一部分，
   * 串行每条间隔 400ms，最多弹一次「允许多文件下载」确认。
   * 每条都走 `/download` 口：downloaded_at + 审计自动落，跟单条下载同一套账。
   */
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

  const qc = (s: string | null) => (s ? QC_LABELS[s] : undefined);

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* ── 筛选 + 动作行 ── */}
      <Space size={8} wrap>
        <Select
          style={{ width: 240 }}
          placeholder="批次（可选）"
          allowClear
          showSearch
          optionFilterProp="label"
          value={batchFilter}
          onChange={(v) => {
            setBatchFilter(v);
            setPicked(new Set());
          }}
          options={batchOptions}
        />
        <Select
          style={{ width: 140 }}
          value={kindFilter}
          onChange={(v) => {
            setKindFilter(v);
            setPicked(new Set());
          }}
          options={KIND_OPTIONS.map((k) => ({ value: k.value, label: k.label }))}
        />
        <Tooltip title="验收结论：passed=过、warn=有提醒、failed=不合格（不合格的仍可预览，但下载口会拦）。">
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
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => fetchList(page)}>
          刷新
        </Button>
        <Tooltip title="首帧是后台抽的：刚回收完的片子要等一两分钟才有图；直链 1 小时过期，过期了点刷新续。">
          <Text type="secondary" style={{ fontSize: 12 }}>
            <QuestionCircleOutlined /> 共 {total} 条
          </Text>
        </Tooltip>
      </Space>

      {/* ── 勾选动作行 ── */}
      <Space size={8} wrap>
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          disabled={!pickedItems.length}
          loading={downloading}
          onClick={downloadPicked}
        >
          {downloading ? `下载中${downProgress}` : `下载勾选的 ${pickedItems.length} 条`}
        </Button>
        <Button
          disabled={!items.length}
          onClick={() => setPicked(new Set(items.map((i) => i.id)))}
        >
          本页全选
        </Button>
        <Button disabled={!picked.size} onClick={() => setPicked(new Set())}>
          清空勾选
        </Button>
        {picked.size > items.length && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            另有 {picked.size - items.length} 条在别的页勾着，翻回去下载
          </Text>
        )}
      </Space>

      {/* ── 墙 ── */}
      {!loading && !items.length ? (
        <Empty
          description={
            qcFilter || batchFilter
              ? '这个筛选条件下没有成片。清掉筛选试试，或者先去「生产单与投放」投板回收。'
              : '还没有成片。去「生产单与投放」投板，片子回收回来就摆在这里。'
          }
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
            const q = qc(o.qc_status);
            return (
              <div
                key={o.id}
                style={{
                  border: '1px solid #f0f0f0',
                  borderRadius: 8,
                  overflow: 'hidden',
                  background: '#fff',
                }}
              >
                {/* 缩略图：竖屏成片 9:16，objectFit cover 裁齐 */}
                <div
                  style={{ position: 'relative', paddingTop: '133%', background: '#fafafa' }}
                  onClick={() => openPreview(o)}
                  role="button"
                >
                  {o.thumb_url ? (
                    <img
                      src={o.thumb_url}
                      alt={o.file_name || ''}
                      style={{
                        position: 'absolute',
                        inset: 0,
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        cursor: 'pointer',
                      }}
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
                  {/* 播放角标 + 时长 */}
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
                  {/* 勾选框：压在图左上角 */}
                  <Checkbox
                    checked={picked.has(o.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => toggle(o.id, e.target.checked)}
                    style={{ position: 'absolute', left: 6, top: 6 }}
                  />
                </div>
                {/* 标注：素材码 + 钩子号 + 验收 + 已下载 */}
                <div style={{ padding: '6px 8px 8px' }}>
                  <div style={{ marginBottom: 2 }}>
                    <Text strong style={{ fontSize: 12 }} ellipsis>
                      {o.asset_code || o.asset_id.slice(0, 8)}
                      {o.hook_code ? `｜${o.hook_code}` : ''}
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
        />
      )}

      {/* ── 预览播放器 ── */}
      <Modal
        open={!!preview}
        title={
          preview
            ? `${preview.output.file_name || preview.output.id.slice(0, 8)}${
                preview.output.hook_code ? `（${preview.output.hook_code}）` : ''
              }`
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
            <video
              src={preview.url}
              controls
              autoPlay
              style={{ width: '100%', maxHeight: 480, background: '#000' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {[
                fmtDuration(preview.output.duration),
                fmtSize(preview.output.file_size),
                preview.output.resolution,
              ]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          </Space>
        )}
      </Modal>
    </Space>
  );
};

export default AssetOutputWall;
