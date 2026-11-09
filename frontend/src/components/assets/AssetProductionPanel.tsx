import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Col, Dropdown, Input, Modal, Radio, Row, Segmented, Select, Space, Statistic, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  CloudUploadOutlined, CopyOutlined, DownloadOutlined, ExportOutlined, MoreOutlined, PlayCircleOutlined, ReloadOutlined, ThunderboltOutlined, VideoCameraOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  AUDIT_STATUS_LABELS, DISPATCH_REPORT_STATUSES, PRODUCTION_STATE_LABELS, assetApi, isAssetJobAck,
} from '../../api/assets';
import type {
  AssetBatch, AssetDispatchAck, AssetDispatchResponse, AssetDispatchCounts, AssetExportJson, AssetExportPayload, AssetExportTxt,
  AssetOutput, AssetOutputPreviewResult, AssetProduction, AssetSummary, DispatchReportStatus, ProductionState,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { nudgeAssetJobBanner } from './AssetJobBanner';
import { withCrossPersonConfirm } from './crossPerson';
import ProduceOrderModal from './ProduceOrderModal';
import AssetCardPicker from './AssetCardPicker';
import { MonoText, ProductionStateTag, aspectShortText } from './AssetBits';

const { Text, Paragraph } = Typography;

interface Props {
  /** 投板结果登记与投产同侧：operator + admin */
  canWriteBack: boolean;
  /** 「带违禁词强行导出」只有 admin 能做（后端同一道闸，前端只决定按钮给不给） */
  isAdmin: boolean;
  batchId?: string;
  /** 后台投产任务收敛后自增（D-1）：生产单是后端建行的，只能重新拉才看得到 */
  reloadToken?: number;
  /** A′ UX：页签切回来自动刷新 */
  active?: boolean;
}

const rate = (v: number | null | undefined) =>
  v === null || v === undefined ? '—（还没有终态样本）' : `${Math.round(v * 100)}%`;

/**
 * 批 M（评审一·P1-3）：fetchList 的请求序号守卫（模块级，两个面板同一套）。
 * 筛选变更和 10s 静默轮询并发时，慢的新筛选回包可能被旧的覆盖——表格与筛选条件
 * 持续对不上。同文件 hookCodesUsed 已经用 reqId 防乱序（本仓现成模式），fetchList 没跟上。
 */
let listReqSeq = 0;

/** 批 L：板面行状态 → 人话（board.readback 的 status 词直接透传，多版单会拼成「waiting/running」串） */
const BOARD_ROW_STATUS_TEXT: Record<string, string> = {
  waiting: '排队中',
  running: '出片中',
  succ: '已出片',
  fail: '板面失败',
};
const boardStatusText = (raw: string | null): string | null => {
  if (!raw) return null;
  return raw
    .split('/')
    .map((s) => BOARD_ROW_STATUS_TEXT[s.trim()] || s.trim())
    .join('·');
};

/**
 * 生产单面板：台账 + 投递计数 + 导出任务文件 + **自动投板（投去 AI 出片）** + 人工补账。
 *
 * 两个计数口径不能混（这是最容易看错的地方）：
 *  - `dispatch.by_status` 跟 batch_id/asset_id 走、**不跟 status= 走**：
 *    筛「失败」时如果 by_status 跟着筛，就变成「failed: 12」自己报自己，成功几条这个关键数消失了；
 *  - `dispatch.today.board_rows` = Σ board_total＝号池今天真吃进去的条数（软提示线比它，不是行数）；
 *    `board_capacity.already_today` 含未投单，两者不等价，别互相换算。
 *
 * 投递有**两个入口、一条交付线**（11-05 批 H）：
 *  - 「投去 AI 出片」＝后端自己连板：建任务 → 轮询出片 → 把成片收进产物。拍板口径是
 *    「可自动投板，但**逐批人工确认**」，所以按钮必须勾了确认才点得动，且一次最多 20 张；
 *  - 「导出任务文件（板面七键）」→ 人去企微后台建任务 → 回来「补记手工投板结果」记账。老路没断，
 *    没配板子凭据时后端会当场白话拒绝自动投板，这条就是唯一走法。
 * 两条路的闸门、payload、状态迁移共用后端同一套判据，前端不要自己复述规则数字。
 */
const AssetProductionPanel: React.FC<Props> = ({ canWriteBack, isAdmin, batchId, reloadToken, active = true }) => {
  const [items, setItems] = useState<AssetProduction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [loading, setLoading] = useState(false);
  const [dispatch, setDispatch] = useState<AssetDispatchCounts | null>(null);
  const [dispatch_all_, setDispatchAll] = useState<AssetDispatchCounts | null>(null);

  const [status, setStatus] = useState<string | undefined>();
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  const [assetFilter, setAssetFilter] = useState<string | undefined>();
  /**
   * A′ 按运营隔离（2026-11-07）：owner=me 只看自己投产的单（查询偏好）。
   * 默认矩阵：operator=我的、admin=全部；统计两行并排（我的／全站），号池一本账。
   */
  const [ownerView, setOwnerView] = useState<'me' | 'all'>(isAdmin ? 'all' : 'me');

  const [selected, setSelected] = useState<AssetProduction[]>([]);
  const [writeOpen, setWriteOpen] = useState(false);
  const [writeStatus, setWriteStatus] = useState<DispatchReportStatus>('queued');
  const [writeError, setWriteError] = useState('');
  const [writeTid, setWriteTid] = useState('');
  const [busy, setBusy] = useState(false);
  // 批 I（链路收敛）：行级「补记投递结果」记的是这一行，不是整页勾选；顶部批量入口还在，
  // 但降成普通按钮——它记的是账，不是又一次"投"，不能再跟投板按钮并排抢主位。
  const [writeTarget, setWriteTarget] = useState<AssetProduction[] | null>(null);

  // 批 I（链路收敛）：行上「成片」列点开的小窗——这一单收回来的片子，就地预览/下载，
  // 免得用户投完板还要自己去找"片子到底回哪了"。
  const [outFor, setOutFor] = useState<AssetProduction | null>(null);
  const [outItems, setOutItems] = useState<AssetOutput[]>([]);
  const [outLoading, setOutLoading] = useState(false);
  const [outPreview, setOutPreview] = useState<AssetOutputPreviewResult | null>(null);

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
  // 11-06 拍板：投递稿可改。只改**这一次投出去**的正文——生产单行的 prompt_text、
  // 过审文案、漂移判定都不动，下一次再投仍是原稿；后端会对改稿重扫风险词并逐条留审计。
  const [promptOverrides, setPromptOverrides] = useState<Record<string, string>>({});
  // 投板前统一挂卡（人物三视图）：给则覆盖本批要新建的单，空＝沿用各单已带的
  const [dispatchCardIds, setDispatchCardIds] = useState<string[]>([]);
  const [editPromptFor, setEditPromptFor] = useState<AssetProduction | null>(null);
  const [editPromptDraft, setEditPromptDraft] = useState('');

  // 批 L：生产单页自己开单——「从过审文案开单」。审核台是审核人员的地盘，
  // 投产这步不必绕回那边；审核台原入口保留（审完顺手投的快捷路径）。
  const [approvedOpen, setApprovedOpen] = useState(false);
  const [approvedRows, setApprovedRows] = useState<AssetSummary[]>([]);
  const [approvedLoading, setApprovedLoading] = useState(false);
  const [approvedSel, setApprovedSel] = useState<AssetSummary[]>([]);
  const [produceOpen, setProduceOpen] = useState(false);
  // 批 N（评审二·P1-2）：挑选器加批次筛选＋截断提示——原来只拉 approved/passed_edited
  // 各 300 条无翻页无提示，量大时找文案像翻相册。
  const [approvedBatch, setApprovedBatch] = useState<string | undefined>();
  const [approvedTotal, setApprovedTotal] = useState(0);
  const [approvedTruncated, setApprovedTruncated] = useState(false);
  const [batches, setBatches] = useState<AssetBatch[]>([]);

  useEffect(() => {
    // 批次下拉拿不到不影响开单，静默
    assetApi.listBatches({ limit: 100 }).then((r) => setBatches(r.items || [])).catch(() => {});
  }, []);

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

  const fetchApproved = useCallback(async (batch?: string) => {
    setApprovedLoading(true);
    try {
      const [a, b] = await Promise.all([
        assetApi.listSummaries({ audit_status: 'approved', page_size: 300, batch_id: batch }),
        assetApi.listSummaries({ audit_status: 'passed_edited', page_size: 300, batch_id: batch }),
      ]);
      const merged = [...(a.items || []), ...(b.items || [])].sort((x, y) =>
        (y.reviewed_at || '').localeCompare(x.reviewed_at || ''),
      );
      setApprovedRows(merged);
      setApprovedTotal((a.total || 0) + (b.total || 0));
      setApprovedTruncated(
        (a.total || 0) > (a.items?.length || 0) || (b.total || 0) > (b.items?.length || 0),
      );
    } catch (e) {
      message.error((e as Error).message || '过审文案列表拉不到');
    } finally {
      setApprovedLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!approvedOpen) return;
    void fetchApproved(approvedBatch);
  }, [approvedOpen, approvedBatch, fetchApproved]);

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
    // 批 L：silent=true＝进度轮询专用——不点 loading 灯，10 秒一刷不闪表格
    async (p: number = page, ps: number = pageSize, silent: boolean = false) => {
      const reqId = ++listReqSeq;
      if (!silent) setLoading(true);
      try {
        const res = await assetApi.listProductions({
          page: p,
          page_size: ps,
          status,
          batch_id: batchFilter,
          asset_id: assetFilter,
          owner: ownerView,
        });
        if (reqId !== listReqSeq) return; // 已有更新的请求在途，旧回包作废（评审一·P1-3）
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(res.page || p);
        setDispatch(res.dispatch || null);
        setDispatchAll(res.dispatch_all ?? null);
      } catch (e) {
        if (reqId === listReqSeq) message.error((e as Error).message || '加载生产单失败');
      } finally {
        if (reqId === listReqSeq) setLoading(false);
      }
    },
    [status, batchFilter, assetFilter, ownerView, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, batchFilter, assetFilter, ownerView]);

  // 后台投产任务跑完（D-1）：生产单行是后端建的，只能重新拉
  useEffect(() => {
    if (!reloadToken) return;
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  // A′ UX：切走再切回页签时自动刷新
  const wasActive = React.useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) fetchList(page, pageSize);
    wasActive.current = active;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // 批 L（投放进度可视化）：有「排队中/出片中」的单时每 10 秒静默刷新——
  // 投完板界面自己动起来，不用人手勤快去点刷新才能看到片子回来了没有。
  // 页面切到后台时暂停（document.hidden），回前台下一轮立即补上。
  useEffect(() => {
    const live = items.some((p) => p.status === 'queued' || p.status === 'running');
    if (!live) return;
    const t = window.setInterval(() => {
      if (!document.hidden) fetchList(page, pageSize, true);
    }, 10000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, page, pageSize]);

  // 批 I：补账对象＝行级入口点的那一行；顶部批量入口没指定就还是整页勾选
  const writeRows = writeTarget ?? selected;

  /**
   * 批 L：拉全部过审文案（approved + passed_edited 两态合并，按过审时间倒序）。
   * 批 N（评审二·P1-2）：拉取挪进 effect（随批次筛选重拉），这里只负责开窗。
   */
  const openApprovedPicker = () => {
    setApprovedOpen(true);
    setApprovedSel([]);
    setApprovedBatch(undefined);
  };

  /**
   * 批 N（评审二·P0-1）：失败单的活路——按同文案重开单。
   * 投板闸门拦 failed 是对的（重投与否要人判读，写进闸门的纪律），要修的是
   * 「失败行上没有任何指向」。失败单本身留档不动；文案已被撤审/驳回时如实拦下。
   */
  const reopenFromFailed = async (r: AssetProduction) => {
    try {
      const res = await assetApi.listSummaries({ asset_id: r.asset_id, page_size: 200 });
      const hit = (res.items || []).find((s) => s.id === r.summary_id);
      if (!hit) {
        message.warning('这条单的过审文案在库里找不到了（可能随素材删除），开不了单');
        return;
      }
      if (hit.audit_status !== 'approved' && hit.audit_status !== 'passed_edited') {
        message.warning(
          `这条文案现在是「${AUDIT_STATUS_LABELS[hit.audit_status]}」，不是过审态——先回审核台把它重新过审，再从这里开单`,
          8,
        );
        return;
      }
      setApprovedSel([hit]);
      setProduceOpen(true);
    } catch (e) {
      message.error((e as Error).message || '取原过审文案失败');
    }
  };

  const submitWriteBack = async () => {
    const rows = writeRows;
    if (!rows.length) return;
    const rowIds = rows.map((r) => r.id);
    if (writeStatus === 'failed' && !writeError.trim()) {
      message.warning('判失败必须写成因（板上失败行没有原因字段，这是我们的判读）');
      return;
    }
    if (writeTid && rowIds.length > 1) {
      message.warning('board_tid 是逐条钉的回读主键，多条时只能单选后逐条填');
      return;
    }
    setBusy(true);
    try {
      const res = await assetApi.updateProductionStatus({
        ids: rowIds,
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
                      允许的迁移：还没投→任意；已投→出片中/成功/失败；出片中→成功/失败；失败→重投或改判成功；成功→只允许改判失败（成片回收后发现不可用，必须写成因）。
                    </Text>
                  </Space>
                }
              />
            )}
          </Space>
        ),
      });
      setWriteOpen(false);
      // 批 M（评审一·P1-2）：成功后只清本次补账相关的勾选——行级补账（writeTarget）
      // 不该把整页勾选一并端掉；批量补账（没指定行）才清全部。
      if (writeTarget) {
        const target = writeTarget;
        setSelected((prev) => prev.filter((p) => !target.some((t) => t.id === p.id)));
        setWriteTarget(null);
      } else {
        setSelected([]);
      }
      fetchList(page, pageSize);
    } catch (e) {
      message.error((e as Error).message || '补记失败');
    } finally {
      setBusy(false);
    }
  };

  /** 批 I：行级「补记手工投板结果」——记住是哪一行，别把整页勾选一起写了 */
  const openWriteBackRow = (r: AssetProduction) => {
    setWriteTarget([r]);
    setWriteStatus('queued');
    setWriteError('');
    setWriteTid('');
    setWriteOpen(true);
  };

  /** 批 I：成片小窗——先列这一单的产物，预览按需取（presign 不带 attachment 才能内联播） */
  const openOutputs = async (r: AssetProduction) => {
    setOutFor(r);
    setOutItems([]);
    setOutPreview(null);
    setOutLoading(true);
    try {
      const res = await assetApi.listOutputs({ production_id: r.id });
      setOutItems(res.items || []);
      // 点开即自动挂第一段的预览（保留手动切换其它段）
      const first = (res.items || [])[0];
      if (first) previewOneOutput(first);
    } catch (e) {
      message.error((e as Error).message || '取成片列表失败');
      setOutFor(null);
    } finally {
      setOutLoading(false);
    }
  };

  const previewOneOutput = async (o: AssetOutput) => {
    setOutLoading(true);
    try {
      setOutPreview(await assetApi.previewOutput(o.id));
    } catch (e) {
      message.error((e as Error).message || '取预览失败');
    } finally {
      setOutLoading(false);
    }
  };

  const downloadOneOutput = async (o: AssetOutput) => {
    try {
      const d = await assetApi.downloadOutput(o.id);
      const a = document.createElement('a');
      a.href = d.url;
      a.download = d.file_name || o.file_name || '';
      a.target = '_blank';
      a.rel = 'noopener';
      a.click();
      message.success('下载链接已打开（一次性外链，链接受限请立刻保存）');
    } catch (e) {
      message.error((e as Error).message || '取下载链接失败');
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
      // 11-06：改过投递稿的带上去；只带非空的（空白＝照原稿投）
      const overrides: Record<string, string> = {};
      Object.entries(promptOverrides).forEach(([id, v]) => {
        if ((v || '').trim()) overrides[id] = v;
      });
      const res = await withCrossPersonConfirm((c) =>
        assetApi.dispatchProductions({
          ids,
          confirm: true,
          recover_only: dispatchRecoverOnly || undefined,
          force_risk: dispatchForceRisk || undefined,
          force_reason: dispatchForceRisk ? dispatchForceReason.trim() : undefined,
          async_mode: true,
          cross_person_confirm: c,
          prompt_overrides: Object.keys(overrides).length ? overrides : undefined,
          card_asset_ids: dispatchCardIds.length ? dispatchCardIds : undefined,
        }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做，弹窗留着
      setDispatchOpen(false);
      setDispatchConfirm(false);
      setDispatchRecoverOnly(false);
      setDispatchForceRisk(false);
      setDispatchForceReason('');
      setPromptOverrides({});
      setEditPromptFor(null);
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
              {!!pre.prompt_overrides?.length && (
                <Text type="warning" style={{ fontSize: 12 }}>
                  其中 {pre.prompt_overrides.length} 张投的是改过的投递稿（库里的原稿不动，改前改后进了审计）。
                </Text>
              )}
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
                接下来不用守着：机器去企微后台排队出片，一条 25 分钟起、整批更久。
                出好的片子自动回到本页各单的「成片」列（回来点「刷新」或看顶部任务横幅）；
                板上失败的会计成失败、在行上写清成因。{pre.note ? `｜${pre.note}` : ''}
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

  const copyText = async (text: string, label: string) => {
    // 批 M（评审二·P2）：原来不 await 也没 catch——失败照样喊「已复制」。
    try {
      await navigator.clipboard.writeText(text);
      message.success(`${label}已复制到剪贴板`);
    } catch {
      message.error(`${label}复制失败：浏览器没给剪贴板权限，请手动选择复制`);
    }
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
            {r.asset_id.slice(0, 8)}
            {r.owner_name ? `｜投：${r.owner_name}` : ''}
            ｜变体：{r.variant_basis || '-'}
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
      width: 130,
      render: (v: ProductionState, r) => (
        <Space direction="vertical" size={0}>
          <ProductionStateTag status={v} />
          {/* 批 L（投放进度可视化）：投板在跑的单子把板侧进度带出来——「排队中/出片中」
              是板面行状态的人话，检查时间是轮询活着的证据。终态后这两行自动消失。 */}
          {(v === 'queued' || v === 'running') && r.board_last_status && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {boardStatusText(r.board_last_status)}
              {r.board_last_check_at
                ? `·${parseServerTime(r.board_last_check_at)?.format('HH:mm')}查`
                : ''}
            </Text>
          )}
        </Space>
      ),
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
    {
      // 批 I（链路收敛）：「投完不知道去向」的正解——片子回来了就在这一列，
      // 点开就地预览/下载，不用再去别处找产物。
      title: '成片',
      key: 'outputs',
      width: 110,
      render: (_, r) =>
        (r.output_count ?? 0) > 0 ? (
          <Button size="small" icon={<VideoCameraOutlined />} onClick={() => openOutputs(r)}>
            已收 {r.output_count} 段
          </Button>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            还没收片
          </Text>
        ),
    },
    ...(canWriteBack
      ? [
          {
            title: '操作',
            key: 'ops',
            width: 84,
            render: (_: unknown, r: AssetProduction) => (
              <Dropdown
                menu={{
                  items: [
                    // 批 N（评审二·P0-1）：失败行的出路——同文案重开单（原单留档不动）
                    ...(r.status === 'failed'
                      ? [
                          {
                            key: 'reopen',
                            label: '按同文案重开单（原单留档不动）',
                            onClick: () => void reopenFromFailed(r),
                          },
                        ]
                      : []),
                    {
                      key: 'wb',
                      label: '补记手工投板结果',
                      onClick: () => openWriteBackRow(r),
                    },
                  ],
                }}
              >
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            ),
          } as ColumnsType<AssetProduction>[number],
        ]
      : []),
  ];

  const dispatch_all = dispatch_all_ ?? null;
  const today = dispatch?.today;

  return (
    <Card size="small">
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={3}>
          <Statistic title="生产单" value={dispatch?.total ?? 0} />
        </Col>
        <Col span={3}>
          <Statistic title="还没投" value={dispatch?.order_ready ?? 0} />
        </Col>
        <Col span={3}>
          <Statistic title="已投" value={dispatch?.dispatched ?? 0} />
        </Col>
        <Col span={3}>
          <Statistic title="成功" value={dispatch?.succeeded ?? 0} valueStyle={{ color: '#3f8600' }} />
        </Col>
        <Col span={3}>
          <Statistic title="失败" value={dispatch?.failed ?? 0} valueStyle={{ color: '#cf1322' }} />
        </Col>
        <Col span={3}>
          <Tooltip title="分母只算已终态（成功+失败），在投/出片中不进分母；没有终态时显示 —">
            <Statistic title="成功率" value={rate(dispatch?.success_rate)} />
          </Tooltip>
        </Col>
        {/* 用户口径 2026-11-09：号池折叠块删除，只留今日消耗统计 */}
        <Col span={6}>
          <Tooltip title="今天板上真吃掉的条数（Σ各单板上条数，不是行数）；与每日解压线共用同一池，只提示不拦。超线标红。">
            <Statistic
              title="今日消耗"
              value={today?.board_rows ?? 0}
              suffix={today ? `/ ${today.soft_cap}` : ''}
              valueStyle={
                today && today.over_cap > 0
                  ? { color: '#cf1322' }
                  : today && today.board_rows > today.soft_cap * 0.8
                    ? { color: '#d46b08' }
                    : undefined
              }
            />
          </Tooltip>
        </Col>
      </Row>

      {ownerView === 'me' && dispatch_all && (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          全站：成功 {dispatch_all.succeeded ?? 0} · 失败 {dispatch_all.failed ?? 0} · 已投{' '}
          {dispatch_all.dispatched ?? 0}（号池一本账，不分人）
        </Text>
      )}
      {/* A′（2026-11-08 定稿）：排版对齐 #110——①筛选行 ②动作行，不再混排 */}
      <Space wrap size={8} style={{ marginBottom: 8 }}>
        <Segmented
          size="small"
          value={ownerView}
          onChange={(v) => setOwnerView(v as 'me' | 'all')}
          options={[
            { label: '我的', value: 'me' },
            { label: '全部', value: 'all' },
          ]}
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          value={status}
          onChange={setStatus}
          options={Object.entries(PRODUCTION_STATE_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Tooltip title="按批次筛：下拉选（编号·名称·条数），也可直接粘贴批次 ID 原值回车">
          <Select
            showSearch
            allowClear
            style={{ width: 220 }}
            placeholder="批次（可选/可贴 ID）"
            value={batchFilter}
            onChange={setBatchFilter}
            options={batchOptions}
            optionFilterProp="label"
          />
        </Tooltip>
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
      </Space>
      <Space wrap size={8} style={{ marginBottom: 12 }}>
        {/* 批 L：开单入口收编到生产单页——审核台只管质检，投产不必绕回那边 */}
        {canWriteBack && (
          <Tooltip title="列出全部已过审的文案，勾选后生成生产单（一条文案派生 N 条差异化提示词）。审核台里的同名入口保留，两边走的是同一个投产弹窗。">
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={openApprovedPicker}
            >
              从过审文案开单
            </Button>
          </Tooltip>
        )}
        {canWriteBack && (
          <Tooltip title="机器去企微后台建任务 → 等出片 → 成片自动回到每张单的「成片」列。一次最多 20 张，逐批人工确认。">
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
                setPromptOverrides({});
                setEditPromptFor(null);
                setDispatchCardIds([]);
                setDispatchOpen(true);
              }}
            >
              投去 AI 出片（{ids.length}）
            </Button>
          </Tooltip>
        )}
        <Button icon={<ExportOutlined />} onClick={() => setExportOpen(true)}>
          导出任务文件（手工投）
        </Button>
        {canWriteBack && (
          <Tooltip title="自己上企微后台手工投的，回来在这里把结果记上账；机器投的不用记。">
            <Button
              disabled={!ids.length}
              onClick={() => {
                setWriteTarget(null);
                setWriteStatus('queued');
                setWriteError('');
                setWriteTid('');
                setWriteOpen(true);
              }}
            >
              补记手工投板结果（{ids.length}）
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
        // 批 N（评审二·P2）：1440 宽下「成片」列被视口截半——横向滚动给足，
        // 别让最后一列（成片/操作）永远探不进去。
        scroll={{ x: 1500 }}
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
        title={`补记手工投板结果（${writeRows.length} 张）`}
        onCancel={() => {
          setWriteOpen(false);
          setWriteTarget(null);
        }}
        onOk={submitWriteBack}
        confirmLoading={busy}
        okText="记账"
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
            // 批 M（评审一·P1-2）：禁用条件原来判整页勾选数（ids.length），而本弹窗
            // 的对象是 writeRows——勾了多行再走行级补账，单行补账的 tid 输入被错误禁用。
            disabled={writeRows.length > 1}
            onChange={(e) => setWriteTid(e.target.value)}
          />
          <Tooltip title="人工投的回来记账；机器投的别在这里重复报（两条路同一套判据）。同态重报幂等跳过；queued 每报一次 attempts +1">
            <Alert
              type="info"
              showIcon
              message="人工投的回来记账；机器投的别重复报"
            />
          </Tooltip>
        </Space>
      </Modal>

      {/* 批 I（链路收敛）：这一单收回来的片子，就地预览/下载——投完之后「片子在哪」的答案 */}
      <Modal
        open={!!outFor}
        title={outFor ? `成片（${outFor.hook_code || outFor.id.slice(0, 8)}）· 已收 ${outItems.length} 段` : '成片'}
        width={720}
        onCancel={() => {
          setOutFor(null);
          setOutPreview(null);
        }}
        footer={null}
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {outPreview && (
            <video
              src={outPreview.url}
              controls
              autoPlay
              style={{ width: '100%', maxHeight: 420, background: '#000' }}
            />
          )}
          {outItems.length === 0 && !outLoading && (
            <Text type="secondary">这一单还没有成片。投出去的等机器收回来；失败的单子看行上的成因。</Text>
          )}
          {outItems.map((o) => (
            <Space
              key={o.id}
              style={{ width: '100%', justifyContent: 'space-between' }}
            >
              <Space size={6} wrap>
                <PlayCircleOutlined />
                <Text style={{ fontSize: 12 }}>{o.file_name || o.id.slice(0, 8)}</Text>
                {o.resolution && <Tag style={{ fontSize: 11 }}>{o.resolution}</Tag>}
                {o.qc_status && (
                  <Tag color={o.qc_status === 'passed' ? 'green' : o.qc_status === 'failed' ? 'red' : 'default'} style={{ fontSize: 11 }}>
                    {o.qc_status === 'passed' ? '验收过' : o.qc_status === 'failed' ? '验收没过' : `验收 ${o.qc_status}`}
                  </Tag>
                )}
              </Space>
              <Space size={4}>
                <Button size="small" onClick={() => previewOneOutput(o)}>
                  预览
                </Button>
                <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadOneOutput(o)}>
                  下载
                </Button>
              </Space>
            </Space>
          ))}
        </Space>
      </Modal>

      <Modal
        open={dispatchOpen}
        title={`投去 AI 出片（已选 ${ids.length} 张生产单）`}
        width={720}
        onCancel={() => setDispatchOpen(false)}
        onOk={submitDispatch}
        confirmLoading={dispatchBusy}
        okText={dispatchRecoverOnly ? '开始回收' : '确认投去出片'}
        okButtonProps={{
          danger: !dispatchRecoverOnly,
          disabled: !dispatchRecoverOnly && !dispatchConfirm,
        }}
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Row gutter={12}>
            <Col span={6}>
              <Statistic title="会新建板任务" value={dispatchPlan.willCreate} suffix="张" />
            </Col>
            <Col span={6}>
              <Statistic title="只回收（已有 tid）" value={dispatchPlan.willRecover} suffix="张" />
            </Col>
            <Col span={6}>
              <Statistic title="点了也不投（会被挡）" value={dispatchPlan.other} suffix="张" />
            </Col>
            <Col span={6}>
              <Statistic
                title="新建里缺卡"
                value={selected.filter((p) => canCreateLocally(p) && !(p.card_asset_ids?.length ?? 0)).length}
                suffix="张"
                valueStyle={(dispatchPlan.willCreate ?? 0) > 0 && selected.some((p) => canCreateLocally(p) && !(p.card_asset_ids?.length ?? 0)) ? { color: '#d46b08' } : undefined}
              />
            </Col>
          </Row>
          <Tooltip title="出好的片子自动回「成片」列，可关页面去干别的；额度按条数算（Σ各单板上条数），只含素材库自己投的，与每日解压线共用同一个池">
            <Text type="secondary" style={{ fontSize: 12 }}>
              本批 ≈{dispatchPlan.rows} 条额度｜今天已 {dispatch?.today?.board_rows ?? 0}／提示线{' '}
              {dispatch?.today?.soft_cap ?? '—'}（只提示不拦）
            </Text>
          </Tooltip>
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
                ? '回收档不烧额度，不需要人工确认；进程重启后靠它把片子取回来'
                : '真占当天号池额度，一条 25 分钟起；闸门与导出同一套（状态/正文/风险词）'
            }
          />
          {/* 人物卡（三视图）：投板前统一挑/传，开窗第一屏就给它——缺卡的单在这里补上再走 */}
          {!dispatchRecoverOnly && dispatchPlan.willCreate > 0 && (
            <div>
              <Text strong style={{ fontSize: 12 }}>人物卡（三视图）</Text>
              <AssetCardPicker
                active={dispatchOpen}
                value={dispatchCardIds}
                onChange={setDispatchCardIds}
                batchId={batchFilter || batchId}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                选了会<b>覆盖</b>本批每张新单已带的卡；不选＝沿用各单自己的。
              </Text>
            </div>
          )}
          {!dispatchRecoverOnly && (
            <Checkbox checked={dispatchConfirm} onChange={(e) => setDispatchConfirm(e.target.checked)}>
              我已逐批确认这批要投出去（{dispatchPlan.willCreate} 张新建 · ≈{dispatchPlan.rows} 条额度）
            </Checkbox>
          )}
          {/* 11-06 拍板：投递稿可改。只改这次投出去的；改稿在后端照走风险词重扫并留审计 */}
          {!dispatchRecoverOnly && dispatchPlan.willCreate > 0 && (
            <div>
              <Tooltip title="只改这一次投出去的正文，库里的提示词不动；改稿会照过一遍高风险词">
                <Text strong style={{ fontSize: 12 }}>投递稿</Text>
              </Tooltip>
              <div style={{ marginTop: 4, maxHeight: 160, overflowY: 'auto' }}>
                {selected.filter(canCreateLocally).map((p) => (
                  <div
                    key={p.id}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}
                  >
                    <MonoText>{p.hook_code || p.id.slice(0, 8)}</MonoText>
                    <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                      {p.board_name || '（无推荐标题）'}
                    </Text>
                    {(p.card_asset_ids?.length ?? 0) > 0 ? (
                      <Tag style={{ fontSize: 11 }}>卡 {p.card_asset_ids!.length}</Tag>
                    ) : (
                      <Tag color="orange" style={{ fontSize: 11 }}>缺卡</Tag>
                    )}
                    {promptOverrides[p.id]?.trim() && <Tag color="orange">已改</Tag>}
                    <Button
                      size="small"
                      type="link"
                      style={{ marginLeft: 'auto', flexShrink: 0 }}
                      onClick={() => {
                        setEditPromptFor(p);
                        setEditPromptDraft(promptOverrides[p.id] ?? p.prompt_text ?? '');
                      }}
                    >
                      改稿
                    </Button>
                  </div>
                ))}
              </div>
            </div>
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
          {/* 批 I：手工投的退路还在，但从"三个按钮抢主位"降成一句链接 */}
          {!dispatchRecoverOnly && (
            <Button
              type="link"
              style={{ paddingLeft: 0 }}
              onClick={() => {
                setDispatchOpen(false);
                setExportOpen(true);
              }}
            >
              不想机器投？导出任务文件手工投，投完回来补记结果
            </Button>
          )}
        </Space>
      </Modal>

      {/* 11-06：单张投递稿编辑。预填当前正文（改过的预填改后的）；「还原」丢掉改稿照原稿投 */}
      <Modal
        open={!!editPromptFor}
        title={`编辑投递稿（${editPromptFor?.hook_code || editPromptFor?.id.slice(0, 8) || ''}）`}
        width={760}
        onCancel={() => setEditPromptFor(null)}
        onOk={() => {
          if (editPromptFor) {
            setPromptOverrides((m) => ({ ...m, [editPromptFor.id]: editPromptDraft }));
          }
          setEditPromptFor(null);
        }}
        okText="用这份投"
        cancelText="算了不改"
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="只改这一次投出去的正文"
            description={
              <span style={{ fontSize: 12 }}>
                库里的提示词、过审文案、漂移判定都不动，下一次再投仍是原稿。
                改后的稿子会照过一遍高风险词（命中会被拦，admin 可带理由放行）；改了哪张、改前是什么，进审计。
              </span>
            }
          />
          <Input.TextArea
            rows={14}
            value={editPromptDraft}
            onChange={(e) => setEditPromptDraft(e.target.value)}
            placeholder="这一次投出去的提示词正文（留空＝照原稿投）"
          />
          <Button
            size="small"
            onClick={() => {
              if (editPromptFor) {
                setEditPromptDraft(editPromptFor.prompt_text ?? '');
                setPromptOverrides((m) => {
                  const next = { ...m };
                  delete next[editPromptFor.id];
                  return next;
                });
              }
            }}
          >
            还原成原稿
          </Button>
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
                          要放行得找管理员（谁能导、谁不能导是审核口径定的，不是投板这边自己判）；
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

      {/* 批 L：过审文案挑选弹窗——勾好进投产弹窗（与审核台同一个） */}
      <Modal
        open={approvedOpen}
        title="从过审文案开单"
        width={760}
        onCancel={() => setApprovedOpen(false)}
        footer={
          <Space>
            <Button onClick={() => setApprovedOpen(false)}>取消</Button>
            <Button
              type="primary"
              disabled={!approvedSel.length}
              onClick={() => {
                setApprovedOpen(false);
                setProduceOpen(true);
              }}
            >
              去生成生产单（{approvedSel.length}）
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 8 }}>
          {/* 批 N（评审二·P1-2）：加批次筛选——量大时找文案不能靠翻相册 */}
          <Space wrap size={8}>
            <Select
              style={{ width: 260 }}
              placeholder="按批次筛选（可选）"
              allowClear
              showSearch
              optionFilterProp="label"
              value={approvedBatch}
              onChange={setApprovedBatch}
              loading={approvedLoading}
              options={batches.map((b) => ({
                value: b.id,
                label: `${b.code} · ${b.name || '未命名'}（${b.item_count ?? 0} 条）`,
              }))}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 {approvedTotal} 条过审文案
            </Text>
          </Space>
          {approvedTruncated && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 0 }}
              message="过审文案太多，这里只列最近的一部分（两态各 300 条）——用上面的批次筛选缩小范围，或回生产单页带批次条件开单"
            />
          )}
        </Space>
        <Table<AssetSummary>
          rowKey="id"
          size="small"
          loading={approvedLoading}
          dataSource={approvedRows}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          rowSelection={{
            selectedRowKeys: approvedSel.map((s) => s.id),
            onChange: (_, rows) => setApprovedSel(rows),
          }}
          columns={[
            {
              title: '文案',
              dataIndex: 'text',
              ellipsis: true,
              render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
            },
            { title: '字数', dataIndex: 'word_count', width: 56 },
            {
              title: '素材',
              dataIndex: 'asset_id',
              width: 100,
              render: (v: string) => <MonoText>{v.slice(0, 8)}</MonoText>,
            },
            {
              title: '过审时间',
              dataIndex: 'reviewed_at',
              width: 120,
              render: (v: string | null) =>
                v ? parseServerTime(v)?.format('MM-DD HH:mm') : '—',
            },
          ]}
        />
      </Modal>

      <ProduceOrderModal
        open={produceOpen}
        summaries={approvedSel}
        isAdmin={isAdmin}
        batchId={batchFilter || batchId}
        onClose={() => setProduceOpen(false)}
        onDone={() => {
          setProduceOpen(false);
          setApprovedSel([]);
          fetchList(page, pageSize);
        }}
      />
    </Card>
  );
};

export default AssetProductionPanel;
