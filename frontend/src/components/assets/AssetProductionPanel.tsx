import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Col, Input, Modal, Radio, Row, Select, Space, Statistic, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { CloudUploadOutlined, CopyOutlined, DownloadOutlined, ExportOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  DISPATCH_REPORT_STATUSES, PRODUCTION_STATE_LABELS, assetApi, isAssetJobAck,
} from '../../api/assets';
import type {
  AssetDispatchAck, AssetDispatchResponse, AssetDispatchCounts, AssetExportJson, AssetExportPayload, AssetExportTxt,
  AssetProduction, DispatchReportStatus, ProductionState,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { nudgeAssetJobBanner } from './AssetJobBanner';
import { MonoText, ProductionStateTag, aspectShortText } from './AssetBits';

const { Text, Paragraph } = Typography;

interface Props {
  /** 投放结果登记与投产同侧：operator + admin */
  canWriteBack: boolean;
  /** 「带违禁词强行导出」只有 admin 能做（后端同一道闸，前端只决定按钮给不给） */
  isAdmin: boolean;
  batchId?: string;
  /** 后台投产任务收敛后自增（D-1）：生产单是后端建行的，只能重新拉才看得到 */
  reloadToken?: number;
}

const rate = (v: number | null | undefined) =>
  v === null || v === undefined ? '—（还没有终态样本）' : `${Math.round(v * 100)}%`;

/**
 * 生产单面板：台账 + 投递计数 + 导出 + **自动投板** + 人工回写投递态。
 *
 * 两个计数口径不能混（这是最容易看错的地方）：
 *  - `dispatch.by_status` 跟 batch_id/asset_id 走、**不跟 status= 走**：
 *    筛「失败」时如果 by_status 跟着筛，就变成「failed: 12」自己报自己，成功几条这个关键数消失了；
 *  - `dispatch.today.board_rows` = Σ board_total＝号池今天真吃进去的条数（软提示线比它，不是行数）；
 *    `board_capacity.already_today` 含未投单，两者不等价，别互相换算。
 *
 * 投递有**两个入口、一条交付线**（11-05 批 H）：
 *  - 「投上后台任务板」＝后端自己连板：建任务 → 轮询出片 → 把成片收进产物。拍板口径是
 *    「可自动投板，但**逐批人工确认**」，所以按钮必须勾了确认才点得动，且一次最多 20 张；
 *  - 「导出（板面七键）」→ 人去企微后台建任务 → 回来「回写投递态」记账。老路没断，
 *    没配板子凭据时后端会当场白话拒绝自动投板，这条就是唯一走法。
 * 两条路的闸门、payload、状态迁移共用后端同一套判据，前端不要自己复述规则数字。
 */
const AssetProductionPanel: React.FC<Props> = ({ canWriteBack, isAdmin, batchId, reloadToken }) => {
  const [items, setItems] = useState<AssetProduction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [loading, setLoading] = useState(false);
  const [dispatch, setDispatch] = useState<AssetDispatchCounts | null>(null);

  const [status, setStatus] = useState<string | undefined>();
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  const [assetFilter, setAssetFilter] = useState<string | undefined>();

  const [selected, setSelected] = useState<AssetProduction[]>([]);
  const [writeOpen, setWriteOpen] = useState(false);
  const [writeStatus, setWriteStatus] = useState<DispatchReportStatus>('queued');
  const [writeError, setWriteError] = useState('');
  const [writeTid, setWriteTid] = useState('');
  const [busy, setBusy] = useState(false);

  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<'json' | 'txt' | 'payload'>('txt');
  const [exportAccounts, setExportAccounts] = useState(1);
  const [exportOnlySelected, setExportOnlySelected] = useState(false);
  const [exportData, setExportData] = useState<AssetExportTxt | AssetExportPayload | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  // R-4：导出会按**当前**违禁词表重扫正文，命中的单子会被挡下。放行只有 admin，且必须写一句理由。
  const [exportForceRisk, setExportForceRisk] = useState(false);
  const [exportForceReason, setExportForceReason] = useState('');

  // 批 H：自动投板。同一个抽屉里两种动作——真投（要 confirm）/ 只回收（不花钱，不看 confirm）
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatchRecoverOnly, setDispatchRecoverOnly] = useState(false);
  const [dispatchConfirm, setDispatchConfirm] = useState(false);
  const [dispatchForceRisk, setDispatchForceRisk] = useState(false);
  const [dispatchForceReason, setDispatchForceReason] = useState('');
  const [dispatchBusy, setDispatchBusy] = useState(false);

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);

  /**
   * 选中的单子按状态分堆（**本地先给个预告**，真判据在后端闸门里）。
   * 后端 `_dispatch_gate` 会拦的条数里，有六条**行数据上就看得见**（状态、有没有 tid、
   * 漂移、没正文、没推荐标题、通道不对）——本地照同一套判。不这么做会出现在这里报
   * 「4 张新建」、提交完回执说「新建 1 张」的分叉，一线的第一反应是按钮吞了单子
   * （11-05 批 H 验收时抓出来的）。
   * 只有「按**当前**词表重扫风险词」这条本地判不了（词表在服务端），所以 `other`
   * 仍可能比后端 blocked 少：弹窗里那句"点了也不会投"说的是本地口径，真拦下几张以回执为准。
   */
  const canCreateLocally = (p: AssetProduction) =>
    p.status === 'order_ready' &&
    !p.board_tid &&
    !p.drift &&
    !!(p.prompt_text || '').trim() &&
    !!(p.board_name || '').trim() &&
    (!p.channel || p.channel === 'wework_aivideo');

  /**
   * 回收堆也要按闸门顺序判：`_dispatch_gate` 是**先挡** success/作废/failed，
   * 剩下的才看有没有 tid 进回收。所以"有 tid 的失败单"本地不许算成会回收——
   * 后端把它拦在 failed 那条里（失败重投与否要人判读，不在投递口自动做）。
   */
  const canRecoverLocally = (p: AssetProduction) =>
    !!p.board_tid &&
    p.status !== 'success' &&
    p.status !== 'failed' &&
    p.status !== 'superseded' &&
    p.status !== 'cancelled' &&
    p.status !== 'skipped';

  const dispatchPlan = useMemo(() => {
    const creating = selected.filter(canCreateLocally);
    const recovering = selected.filter(canRecoverLocally);
    const other = selected.length - creating.length - recovering.length;
    // 号池额度按 Σ board_total 算，不是张数（20 张 × total 3 是 60 条，不是 20 条）
    const rows = creating.reduce((acc, p) => acc + (p.board_total || 1), 0);
    return { willCreate: creating.length, willRecover: recovering.length, other, rows };
  }, [selected]);

  const fetchList = useCallback(
    async (p: number = page, ps: number = pageSize) => {
      setLoading(true);
      try {
        const res = await assetApi.listProductions({
          page: p,
          page_size: ps,
          status,
          batch_id: batchFilter,
          asset_id: assetFilter,
        });
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(res.page || p);
        setDispatch(res.dispatch || null);
      } catch (e) {
        message.error((e as Error).message || '加载生产单失败');
      } finally {
        setLoading(false);
      }
    },
    [status, batchFilter, assetFilter, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, batchFilter, assetFilter]);

  // 后台投产任务跑完（D-1）：生产单行是后端建的，只能重新拉
  useEffect(() => {
    if (!reloadToken) return;
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const submitWriteBack = async () => {
    if (!ids.length) return;
    if (writeStatus === 'failed' && !writeError.trim()) {
      message.warning('判失败必须写成因（板上失败行没有原因字段，这是我们的判读）');
      return;
    }
    if (writeTid && ids.length > 1) {
      message.warning('board_tid 是逐条钉的回读主键，多条时只能单选后逐条填');
      return;
    }
    setBusy(true);
    try {
      const res = await assetApi.updateProductionStatus({
        ids,
        status: writeStatus,
        error: writeError || undefined,
        board_tid: writeTid || undefined,
      });
      setDispatch(res.dispatch);
      Modal.info({
        title: res.message,
        width: 620,
        content: (
          <Space direction="vertical" style={{ width: '100%' }}>
            {!!res.unchanged?.length && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                同态幂等跳过 {res.unchanged.length} 条（已经报过这个态）
              </Text>
            )}
            {!!res.blocked?.length && (
              <Alert
                type="error"
                showIcon
                message={`${res.blocked.length} 条被迁移规则挡下`}
                description={
                  <Space direction="vertical" size={2}>
                    {res.blocked.slice(0, 8).map((b) => (
                      <Text key={b.id} style={{ fontSize: 12 }}>
                        {b.hook_code || b.id.slice(0, 8)}：{b.from} → {b.to}｜{b.reason}
                      </Text>
                    ))}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      允许的迁移：待投放→任意；已投→出片中/成功/失败；出片中→成功/失败；失败→重投或改判成功；成功→只允许改判失败（成片回收后发现不可用，必须写成因）。
                    </Text>
                  </Space>
                }
              />
            )}
          </Space>
        ),
      });
      setWriteOpen(false);
      setSelected([]);
      fetchList(page, pageSize);
    } catch (e) {
      message.error((e as Error).message || '回写失败');
    } finally {
      setBusy(false);
    }
  };

  const doExport = async (forceRisk = false) => {
    if (forceRisk && !exportForceReason.trim()) {
      message.warning('强行导出要写一句为什么（这句话会进审计，事后对账全靠它）');
      return;
    }
    setExportBusy(true);
    try {
      const res = await assetApi.exportProductions({
        batch_id: exportOnlySelected || !batchFilter ? undefined : batchFilter,
        asset_id: assetFilter,
        ids: exportOnlySelected && ids.length ? ids.join(',') : undefined,
        accounts: exportAccounts,
        format: exportFormat,
        force_risk: forceRisk || undefined,
        force_reason: forceRisk ? exportForceReason.trim() : undefined,
      });
      if (res.format === 'json') {
        setExportData(null);
        message.info('json 这种只给清单、不给正文：要粘进豆包的文本选 txt，要往企微后台建任务的参数选「板面七键」');
      } else {
        setExportData(res as AssetExportTxt | AssetExportPayload);
      }
    } catch (e) {
      message.error((e as Error).message || '导出失败');
    } finally {
      setExportBusy(false);
    }
  };

  /**
   * 提交投板（批 H）。三件事必须在这里做对，否则一线只会看到一个转圈的按钮：
   * ① 提交完**立刻** `nudgeAssetJobBanner()`——任务横幅按 8 秒定轮，不补查就会出现
   *    "任务已排上、横幅却不知道"→`onSettled` 永不触发→列表不刷新（11-04 批 C 实测 8/11→11/11）；
   * ② 回执按 `isAssetJobAck` 分岔，**不要**判 `results`（异步回执里故意没有它）；
   * ③ 闸门挡下的单子在 `precheck.blocked` 里逐条带原因，必须原文列出来——
   *    "投不了"却不告诉人为什么，下一步就是反复点同一个按钮。
   */
  const submitDispatch = async () => {
    if (!ids.length) return;
    if (!dispatchRecoverOnly && !dispatchConfirm) {
      message.warning('勾一下「我已逐批确认」：投出去吃的是当天号池额度，这一下只能由人点');
      return;
    }
    if (dispatchForceRisk && !dispatchForceReason.trim()) {
      message.warning('带高风险词强行投板要写一句为什么（这句话进审计，事后对账全靠它）');
      return;
    }
    setDispatchBusy(true);
    try {
      const res = await assetApi.dispatchProductions({
        ids,
        confirm: true,
        recover_only: dispatchRecoverOnly || undefined,
        force_risk: dispatchForceRisk || undefined,
        force_reason: dispatchForceRisk ? dispatchForceReason.trim() : undefined,
        async_mode: true,
      });
      setDispatchOpen(false);
      setDispatchConfirm(false);
      setDispatchRecoverOnly(false);
      setDispatchForceRisk(false);
      setDispatchForceReason('');
      setSelected([]);
      nudgeAssetJobBanner();
      fetchList(page, pageSize);
      if (isAssetJobAck(res)) {
        const ack = res as AssetDispatchAck;
        const pre = ack.precheck;
        Modal.success({
          title: ack.message,
          width: 700,
          content: (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Text>
                本批会新建 <Text strong>{pre.will_create}</Text> 张板任务、接续回收{' '}
                <Text strong>{pre.will_recover}</Text> 张；号池按条数记，本批加{' '}
                <Text strong>{pre.planned_board_rows}</Text> 条（不是一张一条，Σ board_total）。
              </Text>
              {!!pre.capacity?.advisory && (
                <Alert type="warning" showIcon message="号池余量（只提示不拦）"
                  description={<Text style={{ fontSize: 12 }}>{pre.capacity.advisory}</Text>} />
              )}
              {!!pre.blocked?.length && (
                <Alert
                  type="error"
                  showIcon
                  message={`${pre.blocked.length} 张过不了闸门，这次没投`}
                  description={
                    <Space direction="vertical" size={2}>
                      {pre.blocked.slice(0, 8).map((b) => (
                        <Text key={b.id} style={{ fontSize: 12 }}>
                          {b.hook_code || b.id.slice(0, 8)}：{b.reason}
                        </Text>
                      ))}
                      {pre.blocked.length > 8 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          另有 {pre.blocked.length - 8} 张，本条只列前 8 张
                        </Text>
                      )}
                    </Space>
                  }
                />
              )}
              {!!pre.card_warnings?.length && (
                <Alert
                  type="warning"
                  showIcon
                  message="角色卡有提醒（不影响投，但投出去的画面就是它）"
                  description={
                    <Space direction="vertical" size={2}>
                      {pre.card_warnings.map((c) => (
                        <Text key={c.id} style={{ fontSize: 12 }}>
                          {c.hook_code || c.id.slice(0, 8)}：{c.warnings.join('；')}
                        </Text>
                      ))}
                    </Space>
                  }
                />
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                {pre.note}投一条实测要 25 分钟起，整批排队更久——可以关页面，跑完在「任务台账」里看整份结果。
              </Text>
            </Space>
          ),
        });
      } else {
        const r = res as AssetDispatchResponse;
        Modal.info({
          title: r.message,
          width: 700,
          content: (
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              <Text style={{ fontSize: 12 }}>
                新建 {r.dispatched} 张、回收 {r.recovered} 张、到手 {r.succeeded ?? 0}／失败 {r.failed ?? 0}／还在板上 {r.still_running ?? 0}。
              </Text>
              {!!r.uncertain?.length && (
                <Alert
                  type="error"
                  showIcon
                  message={`${r.uncertain.length} 张状态未知：先别重投`}
                  description={
                    <Space direction="vertical" size={2}>
                      {r.uncertain.map((u) => (
                        <Text key={u.id} style={{ fontSize: 12 }}>{u.hook_code || u.id.slice(0, 8)}：{u.error}</Text>
                      ))}
                    </Space>
                  }
                />
              )}
            </Space>
          ),
        });
      }
    } catch (e) {
      message.error((e as Error).message || '投板失败');
    } finally {
      setDispatchBusy(false);
    }
  };

  const copyText = (text: string, label: string) => {    navigator.clipboard.writeText(text);
    message.success(`${label}已复制到剪贴板`);
  };

  const download = (name: string, text: string) => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: ColumnsType<AssetProduction> = [
    {
      title: '钩子号',
      dataIndex: 'hook_code',
      width: 96,
      render: (v: string | null) => (v ? <MonoText>{v}</MonoText> : <Tag color="orange">缺号</Tag>),
    },
    { title: '#', dataIndex: 'seq', width: 46 },
    {
      title: '板上 name / 素材',
      key: 'name',
      ellipsis: true,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text>{r.board_name || '（无推荐标题）'}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.asset_id.slice(0, 8)}｜变体：{r.variant_basis || '-'}
          </Text>
        </Space>
      ),
    },
    {
      title: '板面',
      key: 'board',
      width: 150,
      render: (_, r) => (
        <Tooltip title={`tag ${r.board_tag || '-'}｜date ${r.board_date || '-'}｜tid ${r.board_tid || '-'}`}>
          <Space size={2} wrap>
            <Tag>total {r.board_total}</Tag>
            {r.board_tid ? <Tag color="blue">有 tid</Tag> : <Tag>无 tid</Tag>}
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 108,
      render: (v: ProductionState) => <ProductionStateTag status={v} />,
    },
    {
      title: '投递',
      key: 'attempts',
      width: 130,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text>
            {r.attempts > 0 ? `投 ${r.attempts} 次` : '未投'}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.started_at ? `起 ${parseServerTime(r.started_at)?.format('MM-DD HH:mm')}` : ''}
            {r.completed_at ? `｜完 ${parseServerTime(r.completed_at)?.format('MM-DD HH:mm')}` : ''}
          </Text>
        </Space>
      ),
    },
    {
      title: '正文',
      dataIndex: 'prompt_text',
      width: 210,
      render: (v: string | null, r) =>
        v ? (
          <Space size={2}>
            {/* expandable: 'collapsible'（antd ≥5.18）——原来写 `expandable: true` 只能展开、
                点了「展开」之后那个按钮就没了，长正文收不回去，表格里一撑到底（11-04 用户反馈）。 */}
            <Paragraph
              style={{ marginBottom: 0, fontSize: 12 }}
              ellipsis={{ rows: 2, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
            >
              {v}
            </Paragraph>
            <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(v, '提示词')} />
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.error ? `（不外泄：${r.error}）` : '（裸单/未展开）'}
          </Text>
        ),
    },
    {
      title: '提醒',
      key: 'warn',
      width: 110,
      render: (_, r) => (
        <Space size={2} wrap>
          {r.drift && (
            <Tooltip title={r.drift_reason || ''}>
              <Tag color="red">漂移</Tag>
            </Tooltip>
          )}
          {r.error && (
            <Tooltip title={r.error}>
              <Tag color="volcano">有成因</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  const today = dispatch?.today;

  return (
    <Card size="small">
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Statistic title="生产单" value={dispatch?.total ?? 0} />
        </Col>
        <Col span={4}>
          <Statistic title="待投放" value={dispatch?.order_ready ?? 0} />
        </Col>
        <Col span={4}>
          <Statistic title="已投" value={dispatch?.dispatched ?? 0} />
        </Col>
        <Col span={4}>
          <Statistic title="成功" value={dispatch?.succeeded ?? 0} valueStyle={{ color: '#3f8600' }} />
        </Col>
        <Col span={4}>
          <Statistic title="失败" value={dispatch?.failed ?? 0} valueStyle={{ color: '#cf1322' }} />
        </Col>
        <Col span={4}>
          <Statistic title="成功率（只按终态）" value={rate(dispatch?.success_rate)} />
        </Col>
      </Row>

      {today && (
        <Alert
          type={today.over_cap > 0 ? 'error' : today.board_rows > today.soft_cap * 0.8 ? 'warning' : 'info'}
          showIcon
          style={{ marginBottom: 12 }}
          message={`${today.day} 号池：吃掉 ${today.board_rows} 条（Σ 板上 total）／软提示线 ${today.soft_cap} 条／板上任务 ${today.tasks} 行（按 board_date，还没投的单不在里面）；成功 ${today.succeeded}、失败 ${today.failed}${today.over_cap > 0 ? `；超线 ${today.over_cap} 条` : ''}`}
          description={
            <Space direction="vertical" size={2}>
              {today.note && <Text style={{ fontSize: 12 }}>{today.note}</Text>}
              <Text type="secondary" style={{ fontSize: 12 }}>
                {dispatch?.scope_note}｜产能不做硬限（11-03 拍板），这里只把数报清楚。
              </Text>
            </Space>
          }
        />
      )}

      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          value={status}
          onChange={setStatus}
          options={Object.entries(PRODUCTION_STATE_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Input
          placeholder="批次 ID"
          allowClear
          style={{ width: 170 }}
          value={batchFilter}
          onChange={(e) => setBatchFilter(e.target.value || undefined)}
        />
        <Input
          placeholder="素材 ID"
          allowClear
          style={{ width: 170 }}
          value={assetFilter}
          onChange={(e) => setAssetFilter(e.target.value || undefined)}
        />
        <Button icon={<ReloadOutlined />} onClick={() => fetchList(page, pageSize)}>
          刷新
        </Button>
        <Button icon={<ExportOutlined />} onClick={() => setExportOpen(true)}>
          导出（txt / 板面七键）
        </Button>
        {canWriteBack && (
          <Button
            type="primary"
            disabled={!ids.length}
            onClick={() => {
              setWriteStatus('queued');
              setWriteError('');
              setWriteTid('');
              setWriteOpen(true);
            }}
          >
            回写投递态（{ids.length}）
          </Button>
        )}
        {canWriteBack && (
          <Tooltip title="后端直接连企微后台任务板：建任务 → 等出片 → 把成片收进产物。一次最多 20 张，且必须逐批人工确认。">
            <Button
              danger
              type="primary"
              icon={<CloudUploadOutlined />}
              disabled={!ids.length}
              onClick={() => {
                setDispatchRecoverOnly(false);
                setDispatchConfirm(false);
                setDispatchForceRisk(false);
                setDispatchForceReason('');
                setDispatchOpen(true);
              }}
            >
              投上后台任务板（{ids.length}）
            </Button>
          </Tooltip>
        )}
      </Space>

      <Table<AssetProduction>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1250 }}
        rowSelection={
          canWriteBack
            ? {
                selectedRowKeys: ids,
                onChange: (_, rows) => {
                  setSelected(rows);
                  setExportOnlySelected(false);
                },
              }
            : undefined
        }
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 张单`,
          onChange: (p, ps) => {
            setPageSize(ps);
            fetchList(p, ps);
          },
        }}
      />

      <Modal
        open={writeOpen}
        title={`回写 ${ids.length} 张生产单的投递态`}
        onCancel={() => setWriteOpen(false)}
        onOk={submitWriteBack}
        confirmLoading={busy}
        okText="提交"
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Radio.Group
            value={writeStatus}
            onChange={(e) => setWriteStatus(e.target.value as DispatchReportStatus)}
            optionType="button"
            options={DISPATCH_REPORT_STATUSES.map((s) => ({ value: s, label: PRODUCTION_STATE_LABELS[s] }))}
          />
          {writeStatus === 'failed' && (
            <Input.TextArea
              rows={2}
              placeholder="失败成因（必填，我们侧判读；板上失败行没有原因字段）"
              value={writeError}
              onChange={(e) => setWriteError(e.target.value)}
            />
          )}
          <Input
            placeholder="board_tid（回读主键，多条时留空）"
            value={writeTid}
            disabled={ids.length > 1}
            onChange={(e) => setWriteTid(e.target.value)}
          />
          <Alert
            type="info"
            showIcon
            message="这里是「人工投板之后补账」：导出 payload → 人在企微后台建任务 → 回这里报结果"
            description={
              <span style={{ fontSize: 12 }}>
                同态重报幂等跳过；queued 每报一次 attempts +1（重投也计）。
                superseded/cancelled/skipped 是系统态，写不进来。
                11-05 起另一条入口是「投上后台任务板」（后端自己连板、自动回收成片），
                <b>两条路的闸门与状态迁移是同一套判据</b>，别在这里把机器投的结果再报一遍。
              </span>
            }
          />
        </Space>
      </Modal>

      <Modal
        open={dispatchOpen}
        title={`投上后台任务板（已选 ${ids.length} 张生产单）`}
        width={720}
        onCancel={() => setDispatchOpen(false)}
        onOk={submitDispatch}
        confirmLoading={dispatchBusy}
        okText={dispatchRecoverOnly ? '开始回收' : '确认投板'}
        okButtonProps={{
          danger: !dispatchRecoverOnly,
          disabled: !dispatchRecoverOnly && !dispatchConfirm,
        }}
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Row gutter={12}>
            <Col span={8}>
              <Statistic title="会新建板任务" value={dispatchPlan.willCreate} suffix="张" />
            </Col>
            <Col span={8}>
              <Statistic title="只回读回收（已有 tid）" value={dispatchPlan.willRecover} suffix="张" />
            </Col>
            <Col span={8}>
              <Statistic title="点了也不会投（会被挡）" value={dispatchPlan.other} suffix="张" />
            </Col>
          </Row>
          <Text type="secondary" style={{ fontSize: 12 }}>
            号池额度按<b>条数</b>算不按张数：本批 Σ board_total ≈{' '}
            <Text strong>{dispatchPlan.rows}</Text> 条；今天板上已经吃掉{' '}
            <Text strong>{dispatch?.today?.board_rows ?? 0}</Text> 条（软提示线 ≈
            {dispatch?.today?.soft_cap ?? '—'}，<b>只提示不拦</b>）。
            这个数只含素材库自己投的，与每日解压线共用同一个池，真实余量比它小。
          </Text>
          <Checkbox
            checked={dispatchRecoverOnly}
            onChange={(e) => setDispatchRecoverOnly(e.target.checked)}
          >
            只回收已投出去的片子（一个都不新建）
          </Checkbox>
          <Alert
            type={dispatchRecoverOnly ? 'success' : 'warning'}
            showIcon
            message={
              dispatchRecoverOnly
                ? '回收档不烧额度：只回读板面、把已经出好的成片取回来，所以不需要人工确认'
                : '这一步真占当天号池额度：一条投出去要 25 分钟起，失败行板上没有原因字段'
            }
            description={
              <span style={{ fontSize: 12 }}>
                {dispatchRecoverOnly
                  ? '进程重启把在等的任务带走之后（任务台账显示已中断），用它把片子取回来；同一条 outUrl 不会重复落产物。'
                  : '闸门与导出同一套：只投待投放的单、提示词必须与过审文案是同一条、作废单不投、正文含高风险词的按当前词表再扫一遍（admin 可带理由放行）。已拿到 board_tid 的单只回读不重建——再 POST 一次就是同一条烧两遍额度。'}
              </span>
            }
          />
          {!dispatchRecoverOnly && (
            <Checkbox checked={dispatchConfirm} onChange={(e) => setDispatchConfirm(e.target.checked)}>
              我已逐批确认这批要投出去（{dispatchPlan.willCreate} 张新建 · ≈{dispatchPlan.rows} 条额度）
            </Checkbox>
          )}
          {isAdmin && !dispatchRecoverOnly && (
            <>
              <Checkbox checked={dispatchForceRisk} onChange={(e) => setDispatchForceRisk(e.target.checked)}>
                带高风险词强行投板（仅 admin，和导出侧同一道闸）
              </Checkbox>
              {dispatchForceRisk && (
                <Input.TextArea
                  rows={2}
                  placeholder="强行投板的理由（必填，进审计）"
                  value={dispatchForceReason}
                  onChange={(e) => setDispatchForceReason(e.target.value)}
                />
              )}
            </>
          )}
        </Space>
      </Modal>

      <Modal
        open={exportOpen}
        title="导出提示词"
        width={860}
        onCancel={() => setExportOpen(false)}
        footer={
          exportData ? (
            <Space>
              <Button onClick={() => setExportData(null)}>重新选</Button>
              <Button
                icon={<DownloadOutlined />}
                onClick={() =>
                  download(
                    `生产单-${exportData.format}-${exportData.count}条.txt`,
                    exportData.format === 'txt'
                      ? exportData.export_text || ''
                      : JSON.stringify((exportData as AssetExportPayload).payloads || [], null, 2),
                  )
                }
              >
                下载
              </Button>
              <Button
                type="primary"
                onClick={() =>
                  copyText(
                    exportData.format === 'txt'
                      ? exportData.export_text || ''
                      : JSON.stringify((exportData as AssetExportPayload).payloads || [], null, 2),
                    exportData.format === 'txt' ? '文本' : '板面七键',
                  )
                }
              >
                复制
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={() => setExportOpen(false)}>关闭</Button>
              <Button type="primary" loading={exportBusy} onClick={() => doExport()}>
                生成
              </Button>
            </Space>
          )
        }
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Space wrap>
            <Radio.Group
              value={exportFormat}
              onChange={(e) => {
                setExportFormat(e.target.value);
                setExportData(null);
              }}
              optionType="button"
              options={[
                { value: 'json', label: 'json（只出清单，不给正文）' },
                { value: 'txt', label: 'txt（段头+正文+推荐标题，可粘豆包）' },
                { value: 'payload', label: '板面七键（企微后台建任务那七个字段）' },
              ]}
            />
            <span>
              <Text>豆包号数：</Text>
              <Input
                type="number"
                min={1}
                max={50}
                style={{ width: 70, marginLeft: 4 }}
                value={exportAccounts}
                onChange={(e) => setExportAccounts(Math.max(1, Number(e.target.value) || 1))}
              />
            </span>
            <Checkbox checked={exportOnlySelected} onChange={(e) => setExportOnlySelected(e.target.checked)}>
              只导选中的 {ids.length} 张
            </Checkbox>
          </Space>

          {exportData ? (
            <>
              <Alert
                type={exportData.blocked_count ? 'warning' : 'success'}
                showIcon
                message={`共 ${exportData.count} 张，可投 ${exportData.ready} 张，挡下 ${exportData.blocked_count} 张；按 ${exportData.capacity.account_count} 号折算 ${exportData.capacity.days} 天`}
                description={
                  <span style={{ fontSize: 12 }}>
                    {exportData.note}
                    {exportData.format === 'payload' && (exportData as AssetExportPayload).card_advisory
                      ? `｜${(exportData as AssetExportPayload).card_advisory}`
                      : ''}
                  </span>
                }
              />
              {/*
                批 G：卡是花钱传上来的生产输入，「建单时挑了卡、导出时图取不到」这种事的代价是
                板上 picDatas 空着、画中人全靠模型自由发挥，事后看不出来。所以这里把后端算好的
                缺卡计数照实说一遍（口径在后端 `_card_sources_for`，前端不自己判）。
              */}
              {exportData.format === 'payload' &&
                !!((exportData as AssetExportPayload).card_check?.rows_with_card_issues ?? 0) && (
                  <Alert
                    type="warning"
                    showIcon
                    message={`${(exportData as AssetExportPayload).card_check!.rows_with_card_issues} 张单在投板前有要先处理的事（缺卡／图取不到／横版／方向不一致／缺推荐标题），逐条点名在「角色卡」这列`}
                    description={
                      <Text style={{ fontSize: 12 }}>
                        {(exportData as AssetExportPayload).card_check!.note ||
                          '常见三种：素材行已删、桶里没有这个 key、旧单只有手填的单值 key。'}
                      </Text>
                    }
                  />
                )}
              {!!exportData.blocked?.length && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    被挡下的（状态照实回显、正文不外泄）：
                  </Text>
                  <Space wrap size={4} style={{ marginTop: 4 }}>
                    {exportData.blocked.slice(0, 20).map((b) => (
                      <Tooltip key={b.id} title={b.reason}>
                        {/* blocked 只有 id/seq/status/reason（后端不给正文），所以按单号点名 */}
                        <Tag color="red">
                          {b.id.slice(0, 8)}#{b.seq}（{PRODUCTION_STATE_LABELS[b.status]}）
                        </Tag>
                      </Tooltip>
                    ))}
                  </Space>
                </div>
              )}
              {/* R-4：导出前按当前违禁词表重扫——命中的一定是「过审之后运营才加的词」，
                  所以这里必须单独说清楚，不能混在「作废/失败」那堆里让一线以为是单子坏了。 */}
              {!!(exportData as AssetExportJson).risk_recheck?.hit_count && (
                <Alert
                  type={(exportData as AssetExportJson).risk_recheck?.blocked?.length ? 'error' : 'warning'}
                  showIcon
                  message={
                    `${(exportData as AssetExportJson).risk_recheck!.hit_count} 张单的正文里有现在不许用的词：`
                    + `${(exportData as AssetExportJson).risk_recheck!.blocked.length} 张已挡下`
                    + ((exportData as AssetExportJson).risk_recheck!.forced?.length
                      ? `、${(exportData as AssetExportJson).risk_recheck!.forced.length} 张由管理员放行`
                      : '')
                  }
                  description={
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Text style={{ fontSize: 12 }}>
                        {(exportData as AssetExportJson).risk_recheck!.note}
                      </Text>
                      <Space wrap size={4}>
                        {(exportData as AssetExportJson).items
                          .filter((i) => i.risk_hits?.length)
                          .map((i) => (
                            <Tag key={i.id} color={i.risk_forced ? 'orange' : 'red'}>
                              {i.hook_code || i.id.slice(0, 8)}#{i.seq}：
                              {i.risk_hits!.map((x) => x.word).join('、')}
                              {i.risk_forced ? '（已放行）' : ''}
                            </Tag>
                          ))}
                      </Space>
                      {isAdmin
                        && (exportData as AssetExportJson).risk_recheck!.blocked.length > 0 && (
                        <Space wrap>
                          <Input
                            style={{ width: 320 }}
                            placeholder="写一句为什么这些词在这批里没问题（会进审计）"
                            value={exportForceReason}
                            onChange={(e) => setExportForceReason(e.target.value)}
                          />
                          <Button size="small" loading={exportBusy} onClick={() => doExport(true)}>
                            管理员：带理由强行导出
                          </Button>
                        </Space>
                      )}
                      {!isAdmin && (exportData as AssetExportJson).risk_recheck!.blocked.length > 0 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          要放行得找管理员（谁能导、谁不能导是审核口径定的，不是投放这边自己判）；
                          或者回去改文案、重新投产。
                        </Text>
                      )}
                    </Space>
                  }
                />
              )}
              {exportData.format === 'txt' ? (
                <Paragraph>
                  <pre style={{ maxHeight: 420, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap' }}>
                    {exportData.export_text || '（没有可交付的正文）'}
                  </pre>
                </Paragraph>
              ) : (
                <Table
                  size="small"
                  rowKey={(r) => r.id}
                  dataSource={(exportData as AssetExportPayload).payloads || []}
                  pagination={{ pageSize: 5 }}
                  columns={[
                    { title: '编号', dataIndex: 'hook_code', width: 90, render: (v: string | null) => v || '-' },
                    { title: '素材', dataIndex: 'asset_code', width: 100 },
                    {
                      // 批 G：板侧按数组顺序认主次，所以这里必须**按顺序**摊开，并说清每张会出什么画幅
                      // （实测口径：成片画幅由角色卡的宽高比决定，提示词写 9:16 压不住横版卡）。
                      // 后端逐条算好的 warnings 以前只是躺在响应里没人渲染——投板前最后一屏就该看见它。
                      title: '角色卡（顺序＝板上的图序）',
                      key: 'cards',
                      width: 300,
                      render: (_, r: AssetExportPayload['payloads'][number]) => (
                        <Space direction="vertical" size={0} style={{ width: '100%' }}>
                          {(r.cards || []).length === 0 ? (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              这单没挑卡
                            </Text>
                          ) : (
                            (r.cards || []).map((c, i) => (
                              <Space key={`${c.asset_id || c.key}-${i}`} size={4} wrap>
                                <Text style={{ fontSize: 12 }}>
                                  {i + 1}. {c.label}
                                </Text>
                                {c.loaded === false && <Tag color="red">图取不到</Tag>}
                                {c.legacy && <Tag>旧口径单值</Tag>}
                                {!c.legacy && c.loaded !== false && (
                                  <Tag
                                    color={
                                      c.orientation === 'landscape'
                                        ? 'red'
                                        : c.orientation
                                          ? 'default'
                                          : 'orange'
                                    }
                                  >
                                    {aspectShortText({
                                      width: null,
                                      height: null,
                                      ratio: c.ratio ?? null,
                                      orientation: c.orientation ?? null,
                                    })}
                                  </Tag>
                                )}
                              </Space>
                            ))
                          )}
                          {(r.warnings || []).map((w, i) => (
                            <Text key={`w-${i}`} type="danger" style={{ fontSize: 12 }}>
                              {w}
                            </Text>
                          ))}
                        </Space>
                      ),
                    },
                    {
                      title: '七键',
                      key: 'p',
                      render: (_, r: AssetExportPayload['payloads'][number]) => (
                        <Space size={2} wrap>
                          {Object.keys(r.payload).map((k) => (
                            <Tag key={k}>{k}</Tag>
                          ))}
                        </Space>
                      ),
                    },
                    {
                      title: '',
                      key: 'copy',
                      width: 90,
                      render: (_, r: AssetExportPayload['payloads'][number]) => (
                        <Button size="small" onClick={() => copyText(JSON.stringify(r.payload), '这单的板面七键')}>
                          复制
                        </Button>
                      ),
                    },
                  ]}
                />
              )}
            </>
          ) : (
            <Text type="secondary">
              选一种形态再点「生成」。txt 每条是「段头（五位编号）+ 正文 + 推荐标题（编号在尾）」一整块，末尾接这一批的产出清单，复制进豆包就能用；
              板面七键每条是企微后台「创建AI视频」要收的那七个字段，复制过去直接建任务。
            </Text>
          )}
        </Space>
      </Modal>
    </Card>
  );
};

export default AssetProductionPanel;
