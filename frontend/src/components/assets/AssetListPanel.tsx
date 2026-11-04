import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, DatePicker, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  BulbOutlined, CloudDownloadOutlined, DownloadOutlined, FileTextOutlined, MergeCellsOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  ASSET_STAGE_LABELS, ASSET_STATUS_LABELS, DEFAULT_TIER, DURATION_TIERS, assetApi,
} from '../../api/assets';
import type {
  AssetItem, AssetAnalyzeResponse, AssetCostEstimateResponse, AssetResolveResponse, AssetSummaryGenerateResponse,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { AssetStatusTag, StageTags, durationText, yuan } from './AssetBits';
import CostConfirmModal from './CostConfirmModal';
import AssetDetailDrawer from './AssetDetailDrawer';
import AssetComposeModal from './AssetComposeModal';

const { Text } = Typography;
const { RangePicker } = DatePicker;


interface Props {
  /** 导入/反推/出文案/回源解析：material + operator + admin */
  canProduce: boolean;
  /** 仅 admin：余额闸门 blocked 时可以强行提交（余额接口有波动） */
  isAdmin: boolean;
  batchId?: string;
}

/**
 * 素材列表面板：一行＝一条素材，五个阶段一眼看清卡在哪。
 *
 * 三个批量动作都是「可能花钱或花时间」的，所以一律走成本确认单：
 *  - 反推按**计时上限**扣费（不是实际时长），默认档 180，600 档一条 0.324 元；
 *  - 回源解析 0.01 元/次，≥2 条后端要求 confirmed=true；
 *  - 出文案走 AutoClip（LLM 在那边），同步等，单次条数由后端上限裁。
 * 整批排队（batch_id + offset/limit）是给 200 条那种批次的：提交成功的条会自己离开队列，
 * 所以 offset 默认 0，只有某条反复失败才往后挪。
 */
const AssetListPanel: React.FC<Props> = ({ canProduce, isAdmin, batchId }) => {
  const [items, setItems] = useState<AssetItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<AssetItem[]>([]);

  // 筛选
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [sourceKind, setSourceKind] = useState<string | undefined>();
  const [stagePrompt, setStagePrompt] = useState<string | undefined>();
  const [dates, setDates] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);

  // 详情抽屉
  const [drawerId, setDrawerId] = useState<string | null>(null);

  // 拼接弹窗（存整行而不是 id：弹窗里要显示编号/画幅/时长，不该为此再发一次请求）
  const [composeAsset, setComposeAsset] = useState<AssetItem | null>(null);

  // 反推确认
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzePreview, setAnalyzePreview] = useState<AssetCostEstimateResponse | null>(null);
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [tier, setTier] = useState<number>(DEFAULT_TIER);
  const [confirmed, setConfirmed] = useState(false);
  const [force, setForce] = useState(false);
  const [retryFailed, setRetryFailed] = useState(false);

  // 回源解析确认
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolvePreview, setResolvePreview] = useState<AssetCostEstimateResponse | null>(null);
  const [resolveConfirmed, setResolveConfirmed] = useState(false);
  const [resolveBusy, setResolveBusy] = useState(false);

  const [genBusy, setGenBusy] = useState(false);
  const [refreshBusy, setRefreshBusy] = useState(false);

  const fetchList = useCallback(
    async (p: number = page, ps: number = pageSize) => {
      setLoading(true);
      try {
        const data = await assetApi.listAssets({
          page: p,
          page_size: ps,
          keyword: keyword || undefined,
          status,
          source_kind: sourceKind,
          stage_prompt: stagePrompt,
          batch_id: batchFilter,
          date_from: dates?.[0] ? dates[0]!.format('YYYY-MM-DD') : undefined,
          date_to: dates?.[1] ? dates[1]!.format('YYYY-MM-DD') : undefined,
        });
        setItems(data.items || []);
        setTotal(data.total || 0);
        setPage(data.page || p);
      } catch (e) {
        message.error((e as Error).message || '加载素材列表失败');
      } finally {
        setLoading(false);
      }
    },
    [keyword, status, sourceKind, stagePrompt, batchFilter, dates, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, sourceKind, stagePrompt, batchFilter, dates]);

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);
  const runningCount = useMemo(() => items.filter((i) => i.stage_prompt === 'running').length, [items]);

  // ── 反推 ──
  const openAnalyze = async () => {
    if (!ids.length) {
      message.warning('先勾选要反推的素材');
      return;
    }
    setAnalyzeOpen(true);
    setConfirmed(false);
    setForce(false);
    setPreviewLoading(true);
    try {
      setAnalyzePreview(await assetApi.estimateCost({ count: ids.length, max_duration: tier }));
    } catch (e) {
      message.error((e as Error).message || '成本预估失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const refreshAnalyzePreview = async (nextTier: number) => {
    setTier(nextTier);
    setPreviewLoading(true);
    try {
      setAnalyzePreview(await assetApi.estimateCost({ count: ids.length, max_duration: nextTier }));
    } finally {
      setPreviewLoading(false);
    }
  };

  const submitAnalyze = async () => {
    setAnalyzeLoading(true);
    try {
      const res: AssetAnalyzeResponse = await assetApi.analyzeBatch({
        asset_ids: ids,
        max_duration: tier,
        confirmed: true,
        force,
        retry_failed: retryFailed,
      });
      Modal.info({
        title: '反推已提交',
        width: 520,
        content: <Text>{res.message}</Text>,
      });
      setAnalyzeOpen(false);
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '提交反推失败');
    } finally {
      setAnalyzeLoading(false);
    }
  };

  // ── 出文案 ──
  const generateSummaries = async () => {
    const ok = ids.filter((_, i) => selected[i].stage_prompt === 'success');
    if (!ok.length) {
      message.warning('选中的素材里没有「反推成功」的——文案是从反推详规里出的，得先有详规');
      return;
    }
    setGenBusy(true);
    try {
      const res: AssetSummaryGenerateResponse = await assetApi.generateSummaries({ asset_ids: ok });
      message.success(res.message);
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '出文案失败');
    } finally {
      setGenBusy(false);
    }
  };

  // ── 回源解析（拿时长，0.01 元/次）──
  const openResolve = async () => {
    const linkItems = selected.filter((s) => s.source_kind === 'link');
    if (!linkItems.length) {
      message.warning('回源解析只对**链接**素材有意义：文件素材上传时已经知道时长');
      return;
    }
    setResolveOpen(true);
    setResolveConfirmed(false);
    setPreviewLoading(true);
    try {
      setResolvePreview(
        await assetApi.estimateCost({
          count: linkItems.length,
          max_duration: DEFAULT_TIER,
          need_parse: true,
        }),
      );
    } finally {
      setPreviewLoading(false);
    }
  };

  const submitResolve = async () => {
    setResolveBusy(true);
    try {
      const linkIds = selected.filter((s) => s.source_kind === 'link').map((s) => s.id);
      const res: AssetResolveResponse = await assetApi.resolveAssets({
        asset_ids: linkIds,
        confirmed: linkIds.length >= 2,
      });
      const notes = (res.results || []).filter((r) => r.note && !r.ok);
      Modal.info({
        title: `回源解析：拿到时长 ${res.resolved} 条，实扣 ${yuan(res.charged)}`,
        width: 640,
        content: (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>{res.message}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              渠道分布：{Object.entries(res.channels || {}).map(([k, v]) => `${k}×${v}`).join('，') || '无'}
            </Text>
            {!!res.skipped?.length && (
              <Alert
              type="warning"
              showIcon
              message={`跳过 ${res.skipped.length} 条`}
              description={res.skipped.slice(0, 5).map((x) => `${x.code}：${x.reason}`).join('；')}
            />
            )}
            {!!notes.length && (
              <Alert
                type="info"
                showIcon
                message={`${notes.length} 条给了说明（有 note ≠ 失败：命中免费兜底渠道本来就不回时长）`}
                description={notes.slice(0, 5).map((n) => `${n.code}: ${n.note}`).join('；')}
              />
            )}
          </Space>
        ),
      });
      setResolveOpen(false);
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '回源解析失败');
    } finally {
      setResolveBusy(false);
    }
  };

  // ── 收敛在跑的反推任务 ──
  const refreshRunning = async () => {
    setRefreshBusy(true);
    try {
      const payload = batchFilter ? { batch_id: batchFilter } : { asset_ids: ids };
      if (!batchFilter && !ids.length) {
        message.warning('勾选素材，或先按批次筛选再整批收敛');
        setRefreshBusy(false);
        return;
      }
      const res = await assetApi.refreshAnalyzeBatch(payload);
      message.success(res.message);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '收敛失败');
    } finally {
      setRefreshBusy(false);
    }
  };

  const showSource = async (asset: AssetItem) => {
    try {
      const res = await assetApi.downloadAssetSource(asset.id);
      if (res.url) {
        window.open(res.url, '_blank');
      } else {
        Modal.info({ title: '这条素材不在自有桶', content: <Text>{res.note}</Text>, width: 560 });
      }
    } catch (e) {
      message.error((e as Error).message || '取原片失败');
    }
  };

  const columns: ColumnsType<AssetItem> = [
    {
      title: '编号',
      dataIndex: 'code',
      width: 110,
      render: (v: string, row) => (
        <a onClick={() => setDrawerId(row.id)}>
          <Text style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12 }}>{v}</Text>
        </a>
      ),
    },
    {
      title: '标题 / 来源',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string | null, row) => (
        <Space direction="vertical" size={0}>
          {/* 链接素材永远没有标题（title 只有文件上传时取文件名），
              旧文案写死「未反推」会和五阶段里绿色的「推」自相矛盾，11-03 验收截图上就是这样 */}
          <Text strong={!!v}>
            {v || (
              <Text type="secondary">
                {row.source_url ? '（链接素材：无标题，只有来源地址）' : '（未取到标题）'}
              </Text>
            )}
          </Text>
          {row.source_url ? (
            <a href={row.source_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
              {row.source_url.slice(0, 60)}
            </a>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {row.file_name || '-'}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '来路',
      dataIndex: 'source_kind',
      width: 80,
      render: (v: string, row) => (
        <Tag>{v === 'link' ? row.platform || '链接' : '文件'}</Tag>
      ),
    },
    {
      title: '时长',
      dataIndex: 'duration',
      width: 76,
      render: (v: number | null) =>
        v === null || v === undefined ? (
          <Tooltip title="分享页链接库里不存原片，智令反推也只回提示词。要时长点「解析」（0.01 元/次）">
            <Text type="warning">未知</Text>
          </Tooltip>
        ) : (
          durationText(v)
        ),
    },
    {
      title: '五阶段',
      key: 'stages',
      width: 130,
      render: (_, row) => <StageTags asset={row} />,
    },
    {
      title: '文案',
      key: 'copies',
      width: 110,
      render: (_, row) => (
        <Space size={4}>
          <Text>{row.summary_count ?? 0}</Text>
          {(row.pending_review_count ?? 0) > 0 && (
            <Tag color="orange">待审 {row.pending_review_count}</Tag>
          )}
          {(row.approved_count ?? 0) > 0 && <Tag color="green">过 {row.approved_count}</Tag>}
        </Space>
      ),
    },
    {
      title: '生产单',
      dataIndex: 'production_count',
      width: 70,
      render: (v?: number) => v ?? 0,
    },
    {
      title: '成本',
      key: 'cost',
      width: 110,
      render: (_, row) => (
        <Tooltip title={`反推 ${yuan(row.cost_prompt)}｜回源解析 ${yuan(row.cost_parse)}`}>
          <Text>{yuan((row.cost_prompt || 0) + (row.cost_parse || 0))}</Text>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 96,
      render: (v: AssetItem['status']) => <AssetStatusTag status={v} />,
    },
    {
      title: '导入',
      dataIndex: 'created_at',
      width: 120,
      render: (v: string | null) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {parseServerTime(v)?.format('MM-DD HH:mm') || '-'}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'ops',
      width: 190,
      fixed: 'right',
      render: (_, row) => (
        <Space size={2}>
          <Button size="small" onClick={() => setDrawerId(row.id)}>
            详情
          </Button>
          <Tooltip title="原片直链（文件素材走自有桶；链接素材不在桶里，会提示用来源链接自取）">
            <Button size="small" icon={<DownloadOutlined />} onClick={() => showSource(row)} />
          </Tooltip>
          {canProduce && (
            <Tooltip title="两段直拼：再选一条素材／一个切片／本地文件，选谁在前（0 元，不选点不剪切）">
              <Button size="small" icon={<MergeCellsOutlined />} onClick={() => setComposeAsset(row)} />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      styles={{ body: { paddingTop: 12 } }}
      title={
        <Space wrap>
          <Input
            placeholder="搜编号/标题/链接"
            allowClear
            prefix={<SearchOutlined />}
            style={{ width: 200 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => fetchList(1, pageSize)}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 120 }}
            value={status}
            onChange={setStatus}
            options={Object.entries(ASSET_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Select
            placeholder="来路"
            allowClear
            style={{ width: 100 }}
            value={sourceKind}
            onChange={setSourceKind}
            options={[
              { value: 'link', label: '链接' },
              { value: 'file', label: '文件' },
            ]}
          />
          <Select
            placeholder="反推阶段"
            allowClear
            style={{ width: 120 }}
            value={stagePrompt}
            onChange={setStagePrompt}
            options={Object.entries(ASSET_STAGE_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Input
            placeholder="批次 ID"
            allowClear
            style={{ width: 150 }}
            value={batchFilter}
            onChange={(e) => setBatchFilter(e.target.value || undefined)}
            onPressEnter={() => fetchList(1, pageSize)}
          />
          <RangePicker
            value={dates as any}
            onChange={(v) => setDates(v as [dayjs.Dayjs | null, dayjs.Dayjs | null] | null)}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchList(page, pageSize)}>
            刷新
          </Button>
        </Space>
      }
      extra={
        canProduce ? (
          <Space wrap>
            <Button type="primary" icon={<FileTextOutlined />} onClick={openAnalyze} disabled={!ids.length}>
              反推提示词（{ids.length}）
            </Button>
            <Button icon={<BulbOutlined />} loading={genBusy} onClick={generateSummaries} disabled={!ids.length}>
              出钩子文案（{ids.length}）
            </Button>
            <Tooltip title="整批收敛 stage_prompt=running 的任务，一次请求收完（不必逐条点）">
              <Button icon={<ReloadOutlined />} loading={refreshBusy} onClick={refreshRunning}>
                收敛在跑（本页 {runningCount}）
              </Button>
            </Tooltip>
            <Tooltip title="doc/107 按次 0.01 元，计入批次成本；只对链接素材">
              <Button icon={<CloudDownloadOutlined />} onClick={openResolve} disabled={!ids.length}>
                回源解析（{ids.length}）
              </Button>
            </Tooltip>
          </Space>
        ) : (
          <Text type="secondary">当前角色只读：导入/反推/出文案需素材专员或运营</Text>
        )
      }
    >
      <Table<AssetItem>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1300 }}
        rowSelection={
          canProduce
            ? {
                selectedRowKeys: ids,
                onChange: (_, rows) => setSelected(rows),
              }
            : undefined
        }
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPageSize(ps);
            fetchList(p, ps);
          },
        }}
      />

      <CostConfirmModal
        open={analyzeOpen}
        title={`批量反推提示词（${ids.length} 条）`}
        preview={analyzePreview}
        previewLoading={previewLoading}
        loading={analyzeLoading}
        needConfirm
        confirmed={confirmed}
        onConfirmChange={setConfirmed}
        allowForce={isAdmin}
        force={force}
        onForceChange={setForce}
        onOk={submitAnalyze}
        onCancel={() => setAnalyzeOpen(false)}
        extra={
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space>
              <Text>计时上限档位：</Text>
              <Select
                style={{ width: 160 }}
                value={tier}
                onChange={refreshAnalyzePreview}
                options={DURATION_TIERS.map((t) => ({ value: t, label: `${t}s${t === DEFAULT_TIER ? '（默认）' : ''}` }))}
              />
            </Space>
            <Alert
              type="info"
              showIcon
              message="反推按计时上限扣费，不按视频实际时长"
              description={
                <span style={{ fontSize: 12 }}>
                  0.00054 元/秒 × 档位。600 档一条 0.324 元，180 档一条 0.0972 元 —— 档位选错是批次成本翻倍的最快方式。
                  落库的 cost_prompt 是按档位推算的额度（智令不逐单回传金额），用于对账，别当精确值。
                </span>
              }
            />
            <Checkbox checked={retryFailed} onChange={(e) => setRetryFailed(e.target.checked)}>
              <Text style={{ fontSize: 12 }}>同时重跑反推失败的素材（默认跳过已跑过的）</Text>
            </Checkbox>
          </Space>
        }
      />

      <CostConfirmModal
        open={resolveOpen}
        title={`回源解析（${selected.filter((s) => s.source_kind === 'link').length} 条链接素材）`}
        preview={resolvePreview}
        previewLoading={previewLoading}
        loading={resolveBusy}
        needConfirm
        confirmed={resolveConfirmed}
        onConfirmChange={setResolveConfirmed}
        okText="确认解析（0.01 元/次）"
        onOk={submitResolve}
        onCancel={() => setResolveOpen(false)}
        extra={
          <Alert
            type="warning"
            showIcon
            message="这一步会真扣钱，且预估按「全部走付费渠道」算"
            description={
              <span style={{ fontSize: 12 }}>
                实际命中 yuanbao/preview 免费兜底时库里记 0，对账只会偏高不会偏低。
                拿到时长才能算「这条能不能塞进 180s 档」，所以它是反推前的可选一步，不是反推的替代。
              </span>
            }
          />
        }
      />

      <AssetDetailDrawer
        open={!!drawerId}
        assetId={drawerId}
        canProduce={canProduce}
        onClose={() => setDrawerId(null)}
        onChanged={() => fetchList(page, pageSize)}
      />

      <AssetComposeModal
        open={!!composeAsset}
        asset={composeAsset}
        onClose={() => setComposeAsset(null)}
        onDone={() => fetchList(page, pageSize)}
      />
    </Card>
  );
};

export default AssetListPanel;
