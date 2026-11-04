import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, DatePicker, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  BulbOutlined, CloudDownloadOutlined, DownloadOutlined, FileTextOutlined, MergeCellsOutlined,
  QuestionCircleOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  ASSET_STAGE_LABELS, ASSET_STATUS_LABELS, DEFAULT_TIER, DURATION_TIERS, assetApi, isAssetJobAck,
} from '../../api/assets';
import type {
  AssetItem, AssetAnalyzeResponse, AssetCostEstimateResponse, AssetResolveResponse,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { AssetStatusTag, StageTags, durationText, yuan } from './AssetBits';
import {
  CategorySelect, CategoryTag, UNCLASSIFIED, invalidateAssetCategories, useAssetCategories,
} from './AssetCategoryBits';
import CostConfirmModal from './CostConfirmModal';
import AssetDetailDrawer from './AssetDetailDrawer';
import AssetComposeModal from './AssetComposeModal';
import { nudgeAssetJobBanner } from './AssetJobBanner';

const { Text } = Typography;
const { RangePicker } = DatePicker;


interface Props {
  /** 导入/反推/出文案/回源解析：material + operator + admin */
  canProduce: boolean;
  /** 仅 admin：余额闸门 blocked 时可以强行提交（余额接口有波动） */
  isAdmin: boolean;
  batchId?: string;
  /**
   * 后台任务收敛一次就自增（D-1）：出文案跑完 ⟶ 阶段标签/状态必须刷新，
   * 但不能靠定时器猜"差不多该刷了"——只有横幅确认任务终态时才 +1。
   */
  reloadToken?: number;
}

/**
 * 素材列表面板：一行＝一条素材，五个阶段一眼看清卡在哪。
 *
 * 三个批量动作都是「可能花钱或花时间」的，所以一律走成本确认单：
 *  - 反推按**计时上限**扣费（不是实际时长），默认档 180，600 档一条 0.324 元；
 *  - 回源解析 0.01 元/次，≥2 条后端要求 confirmed=true；
 *  - 出文案走 AutoClip（LLM 在那边）：单条 ~95s，所以**提交即回任务号**，
 *    后台跑完由顶部横幅通知并刷新本页（`reloadToken`）——一线不该守着转圈的按钮等十几分钟。
 * 整批排队（batch_id + offset/limit）是给 200 条那种批次的：提交成功的条会自己离开队列，
 * 所以 offset 默认 0，只有某条反复失败才往后挪。
 *
 * 「原型」那一列（11-04 拍板①）是**结构层人工标记**：不点也能走完全链，所以既不必填也不拦人；
 * 点原型 0 元、不等模型，因此不走成本确认单，直接批量提交。
 */
const AssetListPanel: React.FC<Props> = ({ canProduce, isAdmin, batchId, reloadToken }) => {
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
  /**
   * 钩子原型筛选（11-04 拍板①）：`UNCLASSIFIED` 走后端 `category_id=none`，
   * 就是「未分类 N 条」那个清欠账入口。不设为必填，所以默认不筛。
   */
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  /** 批量点原型：选一条原型，点「应用到勾选的 N 条」→ POST /assets/categories/assign */
  const [assignTo, setAssignTo] = useState<string | undefined>();
  const [assignBusy, setAssignBusy] = useState(false);
  const cats = useAssetCategories();

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
          category_id: categoryFilter,
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
    [keyword, status, sourceKind, stagePrompt, batchFilter, categoryFilter, dates, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, sourceKind, stagePrompt, batchFilter, categoryFilter, dates]);

  // 后台任务刚收敛完（横幅确认终态后 +1）：阶段标签和状态是后端算的，只能重新拉一次
  useEffect(() => {
    if (!reloadToken) return;
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);
  const runningCount = useMemo(() => items.filter((i) => i.stage_prompt === 'running').length, [items]);

  // ── 读视频详规（原「反推」）──
  const openAnalyze = async () => {
    if (!ids.length) {
      message.warning('先勾选要读详规的素材');
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
        title: '读详规已提交',
        width: 520,
        content: <Text>{res.message}</Text>,
      });
      setAnalyzeOpen(false);
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '提交读详规失败');
    } finally {
      setAnalyzeLoading(false);
    }
  };

  // ── 出文案（提交即回任务号，顶部横幅负责报"跑完了"）──
  const generateSummaries = async () => {
    const ok = ids.filter((_, i) => selected[i].stage_prompt === 'success');
    if (!ok.length) {
      message.warning('选中的素材里没有「读详规成功」的——文案是从视频详规里出的，得先有详规');
      return;
    }
    setGenBusy(true);
    try {
      const res = await assetApi.generateSummaries({ asset_ids: ok, async_mode: true });
      if (isAssetJobAck(res)) {
        // 回执里没结果，只有任务号：告诉人去哪儿看，别在这里猜跑没跑完
        // （busy 由下面的 finally 收，这里不重复置位）
        message.success(res.message, 8);
        // 叫一声让顶部横幅立刻登记，不等下一个 8 秒定轮——否则这 8 秒看着就像没点
        nudgeAssetJobBanner();
        setSelected([]);
        return;
      }
      message.success(res.message);
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '出文案失败');
    } finally {
      setGenBusy(false);
    }
  };

  // ── 查时长（去原链接解析，0.01 元/次）──
  const openResolve = async () => {
    const linkItems = selected.filter((s) => s.source_kind === 'link');
    if (!linkItems.length) {
      message.warning('查时长只对链接导入的素材有意义：上传文件的素材入库时已经知道时长');
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
        title: `查时长：拿到 ${res.resolved} 条，实扣 ${yuan(res.charged)}`,
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
                message={`${notes.length} 条给了说明（有说明不等于失败：命中免费兜底渠道本来就不回时长）`}
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
      message.error((e as Error).message || '查时长失败');
    } finally {
      setResolveBusy(false);
    }
  };

  // ── 收取还在跑的视频读取结果 ──
  const refreshRunning = async () => {
    setRefreshBusy(true);
    try {
      const payload = batchFilter ? { batch_id: batchFilter } : { asset_ids: ids };
      if (!batchFilter && !ids.length) {
        message.warning('先勾选素材，或按批次筛选后一次收取整批');
        setRefreshBusy(false);
        return;
      }
      const res = await assetApi.refreshAnalyzeBatch(payload);
      message.success(res.message);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '收取在跑结果失败');
    } finally {
      setRefreshBusy(false);
    }
  };

  /**
   * 批量点钩子原型（0 元、不等模型，所以直接提交，不走成本确认单）。
   * `assignTo` 留空＝清成未分类（后端 `category_id=null` 的语义是「清空」，不是「不改」）。
   * 后端如实回 not_found，这里必须念出来——不然「改了 3 条、其实库里只有 2 条」没人知道。
   */
  const applyCategory = async () => {
    if (!ids.length) {
      message.warning('先勾选要点原型的素材');
      return;
    }
    setAssignBusy(true);
    try {
      const res = await assetApi.assignCategory({ asset_ids: ids, category_id: assignTo || null });
      const name = assignTo ? cats.byId[assignTo]?.name || '该原型' : '未分类';
      (res.notes || []).forEach((n) => message.info(n));
      if (res.not_found?.length) {
        Modal.warning({
          title: `有 ${res.not_found.length} 条没点到「${name}」`,
          width: 600,
          content: (
            <Space direction="vertical" size={4}>
              <Text>
                改成功 {res.asset_changed} 条；下面这些 id 库里查不到（可能已被删除或归档），没有被改动：
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {res.not_found.slice(0, 12).join('，')}
                {res.not_found.length > 12 ? ` 等 ${res.not_found.length} 条` : ''}
              </Text>
            </Space>
          ),
        });
      } else {
        message.success(
          res.asset_changed
            ? `已把 ${res.asset_changed} 条素材点成「${name}」`
            : `勾选的素材本来就是「${name}」，没有改动`,
        );
      }
      invalidateAssetCategories();
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '点原型失败');
    } finally {
      setAssignBusy(false);
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
              旧文案写死「未反推」会和环节标签里绿色的「读」自相矛盾，11-03 验收截图上就是这样 */}
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
      title: '原型',
      key: 'category',
      width: 78,
      render: (_, row) => <CategoryTag categoryId={row.category_id} categoryName={row.category_name} />,
    },
    {
      title: '时长',
      dataIndex: 'duration',
      width: 76,
      render: (v: number | null) =>
        v === null || v === undefined ? (
          <Tooltip title="链接素材库里没存原片，读视频详规也只回文字提示词。要看时长点「查时长」（0.01 元/次）">
            <Text type="warning">未知</Text>
          </Tooltip>
        ) : (
          durationText(v)
        ),
    },
    {
      title: '五个环节',
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
            <Tag color="orange">等审核 {row.pending_review_count}</Tag>
          )}
          {(row.approved_count ?? 0) > 0 && <Tag color="green">过审 {row.approved_count}</Tag>}
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
        <Tooltip title={`读详规 ${yuan(row.cost_prompt)}｜查时长 ${yuan(row.cost_parse)}`}>
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
          <Tooltip title="原片直链：上传的文件从我们自己的存储里取；链接素材没存原片，会提示你用来源链接自己打开">
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
            placeholder="读详规环节"
            allowClear
            style={{ width: 120 }}
            value={stagePrompt}
            onChange={setStagePrompt}
            options={Object.entries(ASSET_STAGE_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Tooltip
            title={
              <div style={{ maxWidth: 340 }}>
                <div>
                  钩子原型＝这条片子的<strong>结构层</strong>（A–G，名字照《钩子模版换皮参数设定.docx》），
                  和句式标签、公式标签是三回事。
                </div>
                <div style={{ marginTop: 4 }}>
                  原型是<strong>人工点的，也可以不点</strong>——不点照常读详规、出文案、投产。
                </div>
                <div style={{ marginTop: 4 }}>
                  「未分类」是给清欠账用的：现在库里 {cats.unclassified.asset_count} 条素材没点原型，
                  筛出来一条条补。
                </div>
              </div>
            }
          >
            <span>
              <CategorySelect
                items={cats.items}
                value={categoryFilter}
                onChange={setCategoryFilter}
                withUnclassified
                width={150}
                loading={cats.loading}
                placeholder="钩子原型"
              />
              <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
            </span>
          </Tooltip>
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
              读视频详规（{ids.length}）
            </Button>
            {/*
              拍板②（11-04）：出文案没有确认弹窗（D-1 后是"提交即回"的后台任务），
              所以这句软提示挂在按钮悬浮上——正好在花钱那一下看得见，但不拦人。
            */}
            <Tooltip
              title={
                <div style={{ maxWidth: 320 }}>
                  <div>文案是从「视频详规」里出的，而那段是 AI 看片子自己写的、没经过人工核对。</div>
                  <div style={{ marginTop: 4 }}>
                    它读歪了，文案会照着歪着写，一致性检查也判不出来（两边都歪就对得上）。
                    <strong>这一行只提醒、不拦步骤</strong>：觉得歪了就在详情抽屉里驳回文案或重读详规。
                  </div>
                </div>
              }
            >
              <Button icon={<BulbOutlined />} loading={genBusy} onClick={generateSummaries} disabled={!ids.length}>
                出钩子文案（{ids.length}）
              </Button>
            </Tooltip>
            <Tooltip title="把这一批里还在跑的视频读取结果一次性收回来（不用逐条点）">
              <Button icon={<ReloadOutlined />} loading={refreshBusy} onClick={refreshRunning}>
                收取在跑结果（本页 {runningCount}）
              </Button>
            </Tooltip>
            <Tooltip title="去原链接查视频时长：每次 0.01 元，计入批次成本；只适用于链接素材">
              <Button icon={<CloudDownloadOutlined />} onClick={openResolve} disabled={!ids.length}>
                查时长（{ids.length}）
              </Button>
            </Tooltip>
          </Space>
        ) : (
          <Text type="secondary">当前角色只读：导入、读视频详规、出文案由素材专员或运营来做</Text>
        )
      }
    >
      {canProduce && cats.unclassified.asset_count > 0 && categoryFilter !== UNCLASSIFIED && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message={
            <span>
              全站还有 <strong>{cats.unclassified.asset_count}</strong> 条素材没点钩子原型
              （文案侧 {cats.unclassified.copy_count} 条）。不点不影响走流程，
              但按原型批量出文案、按原型对版都得靠这一列。
            </span>
          }
          action={
            <Button size="small" onClick={() => setCategoryFilter(UNCLASSIFIED)}>
              只看未分类
            </Button>
          }
        />
      )}
      {/*
        批量点原型放在表头上方，不塞进 Card 的 extra：
        extra 里本来就有 4 个动作按钮（读详规／出文案／收结果／查时长），再挤一个 260px 的下拉
        会把左边那一整排筛选条件压到换行，一线连「状态」「来路」都找不着。
      */}
      {canProduce && (
        <Space size={8} wrap style={{ marginBottom: 8 }}>
          <Tooltip
            title={
              <div style={{ maxWidth: 320 }}>
                <div>给勾选的素材点钩子原型（0 元、不花钱、不用等模型）。</div>
                <div style={{ marginTop: 4 }}>
                  清空下拉再点＝把选中的改回「未分类」。已经出过文案的素材重新归类，
                  <strong>不会回写</strong>已经出的候选文案。
                </div>
              </div>
            }
          >
            <Space.Compact>
              <CategorySelect
                items={cats.activeItems}
                value={assignTo}
                onChange={setAssignTo}
                width={210}
                placeholder="点原型"
              />
              <Button loading={assignBusy} disabled={!ids.length} onClick={applyCategory}>
                应用（{ids.length}）
              </Button>
            </Space.Compact>
          </Tooltip>
          <Text type="secondary" style={{ fontSize: 12 }}>
            先勾行再点原型；原型只是结构层标记，不填照样走完全链。
          </Text>
        </Space>
      )}
      <Table<AssetItem>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1380 }}
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
        title={`批量读视频详规（${ids.length} 条）`}
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
              <Text>视频时长上限（秒）：</Text>
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
              message="读详规按你选的时长上限扣费，不按视频实际时长"
              description={
                <span style={{ fontSize: 12 }}>
                  0.00054 元/秒 × 时长上限。600 秒档一条 0.324 元，180 秒档一条 0.0972 元——上限选大了，批次成本直接翻倍。
                  台账上记的是按时长上限推算的额度（对方服务不逐单回传金额），用来对账，别当精确值。
                </span>
              }
            />
            <Checkbox checked={retryFailed} onChange={(e) => setRetryFailed(e.target.checked)}>
              <Text style={{ fontSize: 12 }}>同时重跑读详规失败的素材（默认跳过已跑过的）</Text>
            </Checkbox>
          </Space>
        }
      />

      <CostConfirmModal
        open={resolveOpen}
        title={`查时长（${selected.filter((s) => s.source_kind === 'link').length} 条链接素材）`}
        preview={resolvePreview}
        previewLoading={previewLoading}
        loading={resolveBusy}
        needConfirm
        confirmed={resolveConfirmed}
        onConfirmChange={setResolveConfirmed}
        okText="确认查询（0.01 元/次）"
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
                拿到时长才能判断「这条能不能放进 180 秒档」，所以它是读详规之前的可选一步，不能替代读详规。
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
