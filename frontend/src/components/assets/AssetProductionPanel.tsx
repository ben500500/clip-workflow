import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Col, Dropdown, Input, Modal, Radio, Row, Segmented, Select, Space, Statistic, Table, Tag, Tooltip, Typography, message, notification,
} from 'antd';
import {
  CloudUploadOutlined, CopyOutlined, DownloadOutlined, ExportOutlined, MoreOutlined, PlayCircleOutlined, ReloadOutlined, ThunderboltOutlined, VideoCameraOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  AUDIT_STATUS_LABELS, DISPATCH_REPORT_STATUSES, PRODUCTION_STATE_LABELS, assetApi, isAssetJobAck,
} from '../../api/assets';
import type {
  AssetAutoConcatOrder, AssetBatch, AssetDispatchAck, AssetDispatchResponse, AssetDispatchCounts, AssetExportJson, AssetExportPayload, AssetExportTxt,
  AssetOutput, AssetOutputPreviewResult, AssetPromptElementFound, AssetPromptElementMark, AssetProduction, AssetSummary, DispatchReportStatus, ProductionState,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { nudgeAssetJobBanner } from './AssetJobBanner';
import { withCrossPersonConfirm } from './crossPerson';
import ProduceOrderModal from './ProduceOrderModal';
import ApprovedSummaryPickerModal from './ApprovedSummaryPickerModal';
import AssetCardPicker from './AssetCardPicker';
import AssetConcatPicker from './AssetConcatPicker';
import AssetPromptElementDrawer from './AssetPromptElementDrawer';
import { HelpDot, HighlightedPrompt, MonoText, ProductionStateTag, aspectShortText } from './AssetBits';

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
  /**
   * 11-10 一屏到底：别的页签（②③）里开单成功后，父层把刚建的那几张 id 交到这里，
   * 本页直接弹出「投去 AI 出片」确认窗（照旧能看全文／改投递稿／挑拼接素材）。
   * 消费完必须调 `onDispatchConsumed` 清空，否则下次切页签会重放同一个窗。
   */
  dispatchIds?: string[] | null;
  /** 开单那一屏没处说的提醒（漂移／自动检查没过／标题超字…），在确认窗里接着说 */
  dispatchNotes?: string[];
  onDispatchConsumed?: () => void;
  /**
   * 11-10 口径③：「出片成功」那一行给的一跳直达——片子真正在的地方是「成片墙」，
   * 以前只有本行「已收 N 段」那个抽屉口，人不知道还能整墙看、整墙挑。
   */
  onGoToOutputs?: () => void;
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
 * 11-10 用户口径③「投出去的那条生产单显示完成，成片墙还是看不到…我投去了、生产出来了就给我看」：
 * 状态标签那两个字（「已投上板」「出片成功」）说的是**台账里这一行**，不是**片子在哪**。
 * 一线真正想知道的是这四档各下一步谁做、在哪儿看到东西，所以标签下面固定补一句白话：
 *  1. 还没投 —— 建单不占号也不出片，下一步是**人**点「投去出片」；
 *  2. 已投上板 / 正在出片 —— 下一步是**机器**等豆包，几十分钟，人等着就行；
 *  3. 出片成功 —— 片子已经落到「成片墙」，给一跳直达；
 *  4. 投板失败 / 要求改写 —— 说清成因在哪看，别让"红色标签"自己猜。
 * `success` 但库里一段都没收到是真实存在的一种错位（人工回写成 success、或回收没落库），
 * 这一档单独说破——以前它和"真收到片"共用一句「已收 N 段」，正是"显示完成却看不到成片"的来源。
 */
const stateWhereabouts = (
  status: ProductionState,
  row: { output_count?: number | null },
): string | null => {
  const n = row.output_count ?? 0;
  if (status === 'order_ready') return '只建了单、还没投板：不占号也不出片，点「投去出片」才开始';
  if (status === 'queued' || status === 'running') return '已投上板，豆包在出片（几十分钟起）：这一段不用你盯，回来自动进成片墙';
  if (status === 'success') return n > 0 ? `片子已回收 ${n} 段：在「成片墙」和本行「成片」列都能看` : '记的是出片成功，但库里一段片子都没收到——多半是人工回写或回收没落库，成因看本行「提醒」';
  if (status === 'failed') return '没出成片：红标签旁的「有成因」写了为什么';
  if (status === 'awaiting_rewrite') return '等你回审核台改文案重提，改完才轮到重新开单';
  if (status === 'superseded') return '同文案重开单后这张作废：不用管它';
  return null;
};

/** 批 M：一条元素要换掉的原文（pattern 只换捕获组，literal/自定义＝整段逐字换） */
interface ElementEdit {
  key?: string;
  old?: string;
  new: string;
}

/**
 * 批 M：把「某个元素换成 X」翻成后端听得懂的一组替换项。
 *
 * - pattern 槽位 → **一条** `old:''` 的替换＝这个槽位的所有命中都换（换完仍然处处一致，
 *   时长那种「②⑦⑩⑬ 四处必须相同」的位置不会出现半条 10s 半条 15s）；
 * - literal 槽位 → 把这份稿子里认出的**每个词面**都换掉，长的先换（重叠命中不重复计数）。
 *   只换 `current` 那一个词面会留下「橘猫换了、猫没换」这种半拉子稿。
 */
const editsForSlot = (slot: AssetPromptElementFound, value: string): ElementEdit[] => {
  if (slot.mode === 'pattern') return [{ key: slot.key, old: '', new: value }];
  const faces = (slot.occurrences || [])
    .map((o) => (o.value || '').trim())
    .filter(Boolean);
  const uniqFaces = Array.from(new Set(faces.length ? faces : [(slot.current || '').trim()]));
  return uniqFaces
    .sort((a, b) => b.length - a.length)
    .map((face) => ({ key: slot.key, old: face, new: value }));
};

/** 批 M：候选下拉的选项＝字典里裂变的候选（推荐顺序）＋这份稿子里已认出的其它写法 */
const optionsForSlot = (slot: AssetPromptElementFound) => {
  const pool = (slot.pool || []).filter(Boolean);
  const seen = new Set(pool);
  const extra = (slot.occurrences || [])
    .map((o) => (o.value || '').trim())
    .filter((v) => v && !seen.has(v) && v !== (slot.current || '').trim());
  return [
    ...(pool.length
      ? [{ label: `字典候选（${pool.length} 选）`, options: pool.map((v) => ({ value: v, label: v })) }]
      : []),
    ...(extra.length
      ? [{ label: '这份稿子里的其它写法', options: extra.map((v) => ({ value: v, label: v })) }]
      : []),
  ];
};

/**
 * 「稿子里这句」在前端重算一份：后端 `context` 给的是**认出来那一刻**那一句，
 * 而「套用」之后那一行已经被换掉了（旧词面整篇没了，重新认也不命中，靠 carry 留行）。
 * carry 若继续沿用旧原句，界面上就会指着稿子里已经不存在的字说"原稿里这句"——
 * 所以这里按后端同一条口径（命中所在那一行、折行压平、截 160 字）从**新稿子**重算。
 */
const lineContextOf = (text: string, needle: string) => {
  if (!needle) return '';
  const line = String(text || '')
    .split('\n')
    .find((l) => l.includes(needle));
  if (!line) return '';
  const one = line.replace(/\s+/g, ' ').trim();
  return one.length > 160 ? `${one.slice(0, 160)}…` : one;
};

/**
 * 批 M：改稿弹窗里的一排元素行。
 *
 * 一行＝字典一行：显示「当前是什么／出现几处」，给候选下拉＋自定义输入，
 * 「套用」只改**这一次投出去的正文**（右边那份全文跟着变，仍可整段手改）。
 * 字典里 pool 留空的元素只有自定义输入框——功能不断档，等运营补候选就有得选。
 *
 * 11-10 用户口径「把原提示词中对应的内容也放出来，这样可以做一个对比」：
 * 每行下面把**这个元素在稿子里所在那一行**的原文摊出来（后端 `context`），
 * 换之前看得见原句，不用自己拿放大镜在正文里找词面对不对得上。
 */
const PromptElementRow: React.FC<{
  slot: AssetPromptElementFound;
  value: string;
  busy: boolean;
  otherCount: number;
  onValue: (v: string) => void;
  onApply: (slot: AssetPromptElementFound, v: string) => void;
  onApplyBatch: (slot: AssetPromptElementFound, v: string) => void;
}> = ({ slot, value, busy, otherCount, onValue, onApply, onApplyBatch }) => {
  const counts = (slot.occurrences || []).reduce((n, o) => n + (o.count || 0), 0);
  const opts = optionsForSlot(slot);
  return (
    <div style={{ padding: '4px 0', borderBottom: '1px dashed #f0f0f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', rowGap: 4 }}>
        <Tooltip title={slot.note || undefined}>
          <Text strong style={{ fontSize: 12, minWidth: 88 }}>
            {slot.label}
          </Text>
        </Tooltip>
        <Text type="secondary" style={{ fontSize: 12 }}>
          当前：<MonoText>{slot.current || '（没认出）'}</MonoText>
          {counts > 1 ? ` 出现 ${counts} 处` : ''}
        </Text>
        {opts.length > 0 && (
          <Select
            size="small"
            style={{ minWidth: 150 }}
            placeholder="选一个候选"
            value={opts.some((g) => g.options.some((o) => o.value === value)) ? value : undefined}
            options={opts}
            onChange={(v) => onValue(v)}
            disabled={busy}
          />
        )}
        <Input
          size="small"
          style={{ width: 170 }}
          placeholder={opts.length ? '或自己输入' : '自己输入换成什么'}
          value={value}
          onChange={(e) => onValue(e.target.value)}
          disabled={busy}
        />
        <Button
          size="small"
          type="primary"
          ghost
          disabled={busy || !value.trim()}
          onClick={() => onApply(slot, value.trim())}
        >
          套用
        </Button>
        {otherCount > 0 && (
          <Button
            size="small"
            disabled={busy || !value.trim()}
            onClick={() => onApplyBatch(slot, value.trim())}
          >
            同元素套用到本批另 {otherCount} 张
          </Button>
        )}
      </div>
      {!!slot.context && (
        <div style={{ marginTop: 2, paddingLeft: 96 }}>
          {/* 原句整行摊出来：词面一模一样才换得动，这里就是拿来核那一下的 */}
          <Text type="secondary" style={{ fontSize: 12, lineHeight: '18px' }}>
            稿子里这句：<span style={{ background: '#fffbe6', padding: '0 2px' }}>{slot.context}</span>
          </Text>
        </div>
      )}
    </div>
  );
};

/**
 * 11-10 用户口径「改了一个元素之后，那提示词在哪里呢？我怎么在投出去之前确认整套提示词是我想要的？」
 *
 * 两件事一起做：① 右边那份**全文**始终摆在眼前（改完立刻是最终稿）；② 加这块逐行对照，
 * 只把动过的那几行摊出来、改动的那一小段描红／描绿，没动的行折起来不占地方。
 * 稿子十几行、行结构不变（换词不改行），按行下标对齐足够，不必上 diff 库。
 */
const PromptDraftDiff: React.FC<{ before: string; after: string }> = ({ before, after }) => {
  const [showAll, setShowAll] = useState(false);
  const b = (before || '').split('\n');
  const a = (after || '').split('\n');
  const n = Math.max(b.length, a.length);
  const rows = Array.from({ length: n }, (_, i) => {
    const from = b[i] ?? '';
    const to = a[i] ?? '';
    return { i, from, to, changed: from !== to };
  });
  const changedCount = rows.filter((r) => r.changed).length;
  if (!changedCount) {
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        和原稿一模一样——这一张照原稿投。
      </Text>
    );
  }
  /**
   * 一行里公共前后缀之外的那一小段才是真改动，只给它上色，别把整行刷成一片红绿。
   * （元素替换都是原地换词、行结构不变，所以「前后缀」就是最贴实际的切法。）
   */
  const splitChanged = (from: string, to: string) => {
    const maxS = Math.min(from.length, to.length);
    let s = 0;
    while (s < maxS && from[s] === to[s]) s += 1;
    let e = 0;
    while (e < maxS - s && from[from.length - 1 - e] === to[to.length - 1 - e]) e += 1;
    return { head: from.slice(0, s), fromMid: from.slice(s, from.length - e), toMid: to.slice(s, to.length - e), tail: e ? from.slice(from.length - e) : '' };
  };
  const shown = showAll ? rows : rows.filter((r) => r.changed);
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space size={6} wrap>
        <Text strong style={{ fontSize: 12 }}>
          改了 {changedCount} 行
        </Text>
        <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setShowAll((v) => !v)}>
          {showAll ? '只看改动的行' : '看整段原稿对照'}
        </Button>
      </Space>
      <div
        style={{
          border: '1px solid #f0f0f0', borderRadius: 6, padding: '6px 8px',
          maxHeight: 210, overflowY: 'auto', background: '#fafafa',
        }}
      >
        {shown.map((r) => {
          const c = splitChanged(r.from, r.to);
          return (
            <div key={r.i} style={{ marginBottom: r.changed ? 4 : 0 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                第 {r.i + 1} 行
              </Text>
              {r.changed ? (
                <>
                  <div style={{ fontSize: 12, lineHeight: '18px', wordBreak: 'break-all' }}>
                    <span style={{ color: '#8c8c8c' }}>{c.head}</span>
                    {!!c.fromMid && (
                      <span style={{ background: '#fff1f0', color: '#cf1322', textDecoration: 'line-through' }}>
                        {c.fromMid}
                      </span>
                    )}
                    <span style={{ color: '#8c8c8c' }}>{c.tail}</span>
                  </div>
                  <div style={{ fontSize: 12, lineHeight: '18px', wordBreak: 'break-all', background: '#f6ffed', padding: '0 2px' }}>
                    <span style={{ color: '#389e0d' }}>↓ </span>
                    <span style={{ color: '#8c8c8c' }}>{c.head}</span>
                    <span style={{ background: '#b7eb8f' }}>{c.toMid}</span>
                    <span style={{ color: '#8c8c8c' }}>{c.tail}</span>
                  </div>
                </>
              ) : (
                <div style={{ fontSize: 12, lineHeight: '18px', color: '#8c8c8c', wordBreak: 'break-all' }}>
                  {r.to || '（空行）'}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Space>
  );
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
const AssetProductionPanel: React.FC<Props> = ({
  canWriteBack, isAdmin, batchId, reloadToken, active = true,
  dispatchIds, dispatchNotes, onDispatchConsumed, onGoToOutputs,
}) => {
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

  // 批 H：自动投板。同一个抽屉里两种动作——真投 / 只回收（不花钱）
  // 11-09 用户口径「确认步骤太多了」：原来这里还有一枚 `dispatchConfirm` 勾选态，
  // 不勾按钮就 disabled、点了静默无事——现网真有人以为已经投出去了。现在**点「确认投去出片」
  // 本身就是那一下人工确认**，勾掉了；接口照旧带 confirm=true（后端口径不变，防 API 侧裸投）。
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatchRecoverOnly, setDispatchRecoverOnly] = useState(false);
  const [dispatchForceRisk, setDispatchForceRisk] = useState(false);
  const [dispatchForceReason, setDispatchForceReason] = useState('');
  const [dispatchBusy, setDispatchBusy] = useState(false);
  /**
   * 11-10 一屏到底：开单那一屏上原来摆着的分项警示（正文漂移／自动检查没过／标题超字／
   * 卡是横版…）。窗口缩掉了这些话不能跟着消失——由 `onProduced` 带过来，在确认窗里接着说。
   */
  const [openNotes, setOpenNotes] = useState<string[]>([]);
  // 11-06 拍板：投递稿可改。只改**这一次投出去**的正文——生产单行的 prompt_text、
  // 过审文案、漂移判定都不动，下一次再投仍是原稿；后端会对改稿重扫风险词并逐条留审计。
  const [promptOverrides, setPromptOverrides] = useState<Record<string, string>>({});
  // 投板前统一挂卡（人物三视图）：给则覆盖本批要新建的单，空＝沿用各单已带的
  const [dispatchCardIds, setDispatchCardIds] = useState<string[]>([]);
  // 批 Q（需求⑤）：成片收回来以后自动和哪条拼。null＝这次不提要求（各行原来钉的照旧）；
  // `dispatchConcatClear` 是真要点名取消时才发的空串——后端把「没传」和「传空串」分得很开。
  const [dispatchConcatId, setDispatchConcatId] = useState<string | null>(null);
  const [dispatchConcatOrder, setDispatchConcatOrder] = useState<AssetAutoConcatOrder>('hook_first');
  const [dispatchConcatClear, setDispatchConcatClear] = useState(false);
  const [editPromptFor, setEditPromptFor] = useState<AssetProduction | null>(null);
  const [editPromptDraft, setEditPromptDraft] = useState('');
  // 批 M（11-10）：投产前「可替换元素裂变」。这一排元素来自后端那份元素字典
  // （system_config.asset_prompt_elements），开弹窗时在**当前这份投递稿正文**里认一遍：
  // 认出来的每个元素给几个候选（pool＝裂变）＋自定义输入，套用后把整段正文喂回下面那个
  // 仍可全文编辑的文本框。全程 0 元、不落库——改完仍是走 prompt_overrides 那一条通道。
  const [elementRows, setElementRows] = useState<AssetPromptElementFound[]>([]);
  const [elementChoice, setElementChoice] = useState<Record<string, string>>({});
  const [elementBusy, setElementBusy] = useState(false);
  const [elementNotes, setElementNotes] = useState<string[]>([]);
  const [elementBlocked, setElementBlocked] = useState(false);
  /**
   * 11-10 用户口径①「没有看到正文被替换的地方」：上一次「套用」换上的词**在正文哪一处**。
   * `marksText` 记住这套位置是按哪一版正文算的——人随后在文本框里手改过，坐标就作废，
   * 界面宁可说"位置对不上了"，也不许拿旧坐标描到新正文上（那才是真的误导）。
   */
  const [elementMarks, setElementMarks] = useState<AssetPromptElementMark[]>([]);
  const [marksText, setMarksText] = useState('');
  const [customOld, setCustomOld] = useState('');
  const [customNew, setCustomNew] = useState('');
  const [elementsOpen, setElementsOpen] = useState(false);

  /**
   * 批 M：这张单**这一次要投出去**的正文＝改过的用改后的，没改过的用库里的原稿。
   * 只读，不写回 `promptOverrides`（那是"改过了"的唯一标记）。
   */
  const currentDraftOf = (p: AssetProduction) => {
    const edited = (promptOverrides[p.id] ?? '').trim();
    return edited ? (promptOverrides[p.id] as string) : p.prompt_text ?? '';
  };

  /**
   * 批 M：在当前正文里认一遍可替换元素（纯文本进、纯文本出，0 元、不动任何库里的稿子）。
   * `category` 用这条单所属文案的**钩子原型名**——字典里 `categories` 非空的行只在那一类下出现。
   * 列表口没带原型（历史单/单行口）就不传，退化成"所有槽位都认"，不会因为缺这一列而看不见元素。
   *
   * `carry`＝刚被这次改动替换掉的那几行（CDP 实测出来的真问题）：把场景换成「老破小客厅」后，
   * 字典里的词面（现代咖啡厅落地窗／咖啡厅）在新稿里一处都不剩，重新认一遍就把这一行整行抹掉了——
   * 一线连着换第二个元素时找不到刚那行，会以为改动没生效。留着这行，「当前」显示我们刚替换进去的值
   * （这是事实，不是猜的），候选池还在，想换回来也还有入口。
   *
   * `keepChoice`＝套完之后**留着**刚选的那个候选：「重新认一遍」默认把选择清空（那是「照正文重认」的语义），
   * 但刚点完「套用」就清，会把下一步「同元素套用到本批另 N 张」的按钮一起置灰（CDP 实测 G2 空转的真原因），
   * 一线想「这个元素整批都换成它」就得重选一遍。
   */
  const extractElements = async (
    p: AssetProduction,
    text: string,
    carry: AssetPromptElementFound[] = [],
    keepChoice = false,
  ) => {
    if (!(text || '').trim()) {
      setElementRows([]);
      return;
    }
    setElementBusy(true);
    try {
      const res = await assetApi.extractPromptElements({
        texts: { [p.id]: text },
        category: p.category_name || undefined,
      });
      const fresh = res.items?.[p.id] || [];
      // 已经摆在界面上的行，只要它「当前」还在正文里就别因为这次重新认没命中就消失：
      // 换完场景再去换光线，场景那行不该跟着没了（一线看不到自己刚换的是什么、也换不回去）。
      // 出现几处按当前正文重新数，不沿用旧数字。
      const sticky = elementRows
        .filter((r) => r.key && r.current && !fresh.some((f) => f.key === r.key) && text.includes(r.current))
        .map((r) => ({
          ...r,
          occurrences: [{ value: r.current as string, count: text.split(r.current as string).length - 1 }],
          // 原句也从**当前正文**重算：上一行的编辑可能就动过这一句
          context: lineContextOf(text, (r.current || '').trim()) || r.context,
        }));
      const byKey = new Map<string, AssetPromptElementFound>();
      sticky.forEach((r) => byKey.set(r.key, r));
      carry.forEach((r) => byKey.set(r.key, r));
      const kept = [...byKey.values()].filter((k) => k.key && !fresh.some((f) => f.key === k.key));
      // 顺序按上一次的位置排（新出现的槽位排到最后）：不然刚套用的那行会跳到列表底部，
      // 一线一眼看去像「刚那行没了、下面冒出来一行新的」
      const prevIndex = new Map(elementRows.map((r, i) => [r.key, i] as const));
      const orderOf = (k: string) => (prevIndex.has(k) ? (prevIndex.get(k) as number) : Number.MAX_SAFE_INTEGER);
      setElementRows([...fresh, ...kept].sort((a, b) => orderOf(a.key) - orderOf(b.key)));
      if (!keepChoice) setElementChoice({});
    } catch (e) {
      message.error((e as Error).message || '认元素失败');
    } finally {
      setElementBusy(false);
    }
  };

  /** 批 M：打开「改稿」＝清掉上一张的元素态，再拿当前正文认一遍 */
  const openPromptEditor = (p: AssetProduction) => {
    const draft = currentDraftOf(p);
    setEditPromptFor(p);
    setEditPromptDraft(draft);
    setElementRows([]);
    setElementChoice({});
    setElementNotes([]);
    setElementBlocked(false);
    setElementMarks([]);
    setMarksText('');
    setCustomOld('');
    setCustomNew('');
    void extractElements(p, draft);
  };

  /**
   * 批 M：把一组替换套到**本批其它已选投递稿**上（每张稿内容不同，所以逐张各算一遍）。
   * 结果直接进 `promptOverrides`——也就是跟「改稿」同一通道，投出去才算数，库里不动。
   */
  const applyToOthers = async (edits: ElementEdit[], label: string) => {
    const others = selected.filter((p) => canCreateLocally(p) && p.id !== editPromptFor?.id);
    if (!others.length || !edits.length) return;
    setElementBusy(true);
    try {
      const next: Record<string, string> = {};
      const risky: string[] = [];
      for (const p of others) {
        const base = currentDraftOf(p);
        if (!base.trim()) continue;
        const res = await assetApi.applyPromptElements({ text: base, edits });
        next[p.id] = res.text;
        if (res.would_dispatch_block) risky.push(p.hook_code || p.id.slice(0, 8));
      }
      setPromptOverrides((m) => ({ ...m, ...next }));
      message.success(`「${label}」已套用到本批另 ${Object.keys(next).length} 张投递稿（仍只改这一次投出去的）`);
      if (risky.length) {
        message.warning(`${risky.length} 张换上这个词会被投板闸门拦下：${risky.join('、')}`);
      }
    } catch (e) {
      message.error((e as Error).message || '套用到本批失败');
    } finally {
      setElementBusy(false);
    }
  };

  /** 批 M：套到当前这一张（改完重新认一遍，「当前值／出现几处」跟着新正文走） */
  const applyToCurrent = async (edits: ElementEdit[], label: string) => {
    if (!editPromptFor || !edits.length) return;
    const beforeRows = elementRows;
    setElementBusy(true);
    try {
      const res = await assetApi.applyPromptElements({ text: editPromptDraft, edits });
      setEditPromptDraft(res.text);
      setElementMarks(res.marks || []);
      setMarksText(res.text);
      setElementNotes(res.notes || []);
      setElementBlocked(!!res.would_dispatch_block);
      // 这一批改动动过的槽位先攒成 carry 行：重新认一遍若不再命中字典词面（换掉场景后旧词面整篇没了），
      // 行也不许消失——当前值就用刚替换进去的这个，出现几处按新稿里数出来的算。
      const touched = new Map<string, string>();
      edits.forEach((e) => {
        if (e.key) touched.set(e.key, e.new);
      });
      const carry: AssetPromptElementFound[] = [];
      touched.forEach((to, key) => {
        const old = beforeRows.find((r) => r.key === key);
        if (!old || !to) return;
        const n = to ? res.text.split(to).length - 1 : 0;
        // 新稿里一处都没有（那次替换其实没落上）就别留行——留着只会报一个假的「当前」
        if (n <= 0) return;
        carry.push({
          ...old,
          current: to,
          occurrences: [{ value: to, count: n }],
          // 对照那句也跟着换到新稿子上：留旧原句＝界面指着一句稿子里已经不存在的话
          context: lineContextOf(res.text, to) || old.context,
        });
      });
      await extractElements(editPromptFor, res.text, carry, true);
    } catch (e) {
      message.error((e as Error).message || '套用失败');
    } finally {
      setElementBusy(false);
    }
  };

  const applySlot = (slot: AssetPromptElementFound, value: string) =>
    applyToCurrent(editsForSlot(slot, value), slot.label);

  /** 批 M：自定义替换（不带 key＝整段逐字换，不限于字典认出的元素） */
  const applyCustom = () => {
    const src = customOld.trim();
    const to = customNew.trim();
    if (!src || !to) {
      message.info('自定义替换要写清「换掉什么」和「换成什么」');
      return;
    }
    void applyToCurrent([{ old: src, new: to }], src);
  };

  // 批 L：生产单页自己开单——「从过审文案开单」。审核台是审核人员的地盘，
  // 投产这步不必绕回那边；审核台原入口保留（审完顺手投的快捷路径）。
  // 批 N（11-09 收「两套入口」）：挑选那一屏抽成 ②④ 共用组件 ApprovedSummaryPickerModal，
  // 拉数、批次筛选、截断提示都在那边，这里只留「开弹窗」＋「选完接投产弹窗」两根线。
  const [approvedOpen, setApprovedOpen] = useState(false);
  const [pickedSummaries, setPickedSummaries] = useState<AssetSummary[]>([]);
  const [produceOpen, setProduceOpen] = useState(false);
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

  // 2026-11-11 评审（投放席 P1）：「从过审文案开单」原来是裸按钮——投放专员不知道
  // 现在有多少过审候选等着开单，只能去审核台翻。这里给按钮挂上「待产」计数
  //（过审+改后过、还没建过生产单的条数；两个状态各拉一页 100，超出不追，角标足够指路）。
  const [approvedPendingCount, setApprovedPendingCount] = useState<number | null>(null);
  useEffect(() => {
    if (!active || !canWriteBack) return;
    let alive = true;
    (async () => {
      try {
        const [a, b] = await Promise.all([
          assetApi.listSummaries({ audit_status: 'approved', page_size: 100 }),
          assetApi.listSummaries({ audit_status: 'passed_edited', page_size: 100 }),
        ]);
        const cnt = [...(a.items || []), ...(b.items || [])].filter(
          (s) => !s.production_count,
        ).length;
        if (alive) setApprovedPendingCount(cnt);
      } catch {
        /* 计数失败静默——按钮不数也能点 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [active, canWriteBack, reloadToken]);

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
    // 批 Q：这次会**被写上新拼装要求**的行＝新建堆＋回收堆（后端 `to_create + to_recover` 同一套）
    const concatTargets = creating.length + recovering.length;
    // 这批里原来就钉过拼装要求的行数：不为 0 才给「取消这些单的自动拼接」那个勾——
    // 不传字段和传空串在后端是两件事（前者沿用、后者清空），界面也得把这两句话说清楚。
    const pinned = selected.filter((p) => !!p.concat_asset_id).length;
    return {
      willCreate: creating.length,
      willRecover: recovering.length,
      other,
      rows,
      concatTargets,
      pinnedConcat: pinned,
    };
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
   * 11-10 一屏到底：弹「投去 AI 出片」确认窗的**唯一入口**。
   * 顶部那颗按钮（勾着的这批）和「刚建完单直接顶进来」（点名这几张）两条路都走这里，
   * 免得两套预填口径对不上。进来一次就把上一批留下的选择归零：回收档、强行放行、
   * 投递稿改动、挑卡、挑拼装——这些都属于"那一批"，不跟着换批走。
   */
  const openDispatch = (rows: AssetProduction[], notes: string[] = []) => {
    setSelected(rows);
    setDispatchRecoverOnly(false);
    setDispatchForceRisk(false);
    setDispatchForceReason('');
    setPromptOverrides({});
    setEditPromptFor(null);
    setDispatchCardIds([]);
    setOpenNotes(notes);
    // 批 Q：这批单原来钉过拼装要求就把它带进选择器（看得见的才改得动）。
    // 只在**全批同一条**时预填——各单钉的不一样时不猜，留空但下面的
    // 「N 张已钉」那句话照样说清楚，免得界面显示的和实际投出去的两回事。
    const pinnedIds = Array.from(new Set(rows.map((p) => p.concat_asset_id || '')));
    const pinnedOrders = Array.from(new Set(rows.map((p) => p.concat_order || '')));
    setDispatchConcatId(pinnedIds.length === 1 && pinnedIds[0] ? pinnedIds[0] : null);
    setDispatchConcatOrder(
      pinnedOrders.length === 1 && pinnedOrders[0]
        ? (pinnedOrders[0] as AssetAutoConcatOrder)
        : 'hook_first',
    );
    setDispatchConcatClear(false);
    setDispatchOpen(true);
  };

  /**
   * 11-10 一屏到底：把「刚建的那几张」直接顶进确认窗。
   * 必须**按 id 现拉**（`GET /assets/productions?ids=`）——这一屏可能正筛着状态／批次／
   * 「我的」，新单不一定在表格里；拿不到行对象就等于开一个空选的窗（老结果屏那种"顺手投"
   * 是把 id 直接丢给接口，不挑界面，现在改成挑界面了就得先把行认全）。
   */
  const takeOverDispatch = useCallback(
    async (ids: string[], notes: string[] = []) => {
      if (!ids.length) return;
      try {
        const res = await assetApi.listProductions({ ids: ids.join(','), page_size: 300 });
        const rows = res.items || [];
        if (!rows.length) {
          message.warning('刚建的那几张单没抓到，请刷新后在生产单页勾上再点「投去 AI 出片」', 8);
        } else if (!canWriteBack) {
          message.warning('这批单建好了。投板要运营／管理员权限，你这一侧只能看不能投。', 8);
        } else {
          openDispatch(rows, notes);
        }
        void fetchList(1, pageSize);
      } catch (e) {
        message.error((e as Error).message || '取刚建的生产单失败', 8);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canWriteBack, pageSize],
  );

  // 别的页签（②③）里开完单交过来的那几张：接住→开窗→立刻清账（清早不清晚，
  // StrictMode 双跑／本页重挂都不会把同一个窗重放第二次）
  useEffect(() => {
    if (!dispatchIds?.length) return;
    const ids = dispatchIds;
    const notes = dispatchNotes || [];
    onDispatchConsumed?.();
    void takeOverDispatch(ids, notes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatchIds]);

  /**
   * 批 L：从这里只负责开窗。拉数（approved + passed_edited 两态一次取全）、
   * 批次筛选、截断提示都在 ②④ 共用的挑选弹窗里，不再在本页维护第二套状态。
   */
  const openApprovedPicker = () => setApprovedOpen(true);

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
      // 不经过挑选弹窗：直接把这一条文案送进投产弹窗（挑选弹窗自己会清空重选）
      setPickedSummaries([hit]);
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
   * 11-09 改：①「我已逐批确认」那枚勾选去掉（用户口径：确认步骤太多）；②结果**不再弹需要点掉的
   * 成功窗**，改用右上角自动收的消息条，弹窗提交完当场缩掉，任务在后台跑、进度看顶部横幅。
   * 但 ③ 的"闸门挡下"必须**留着不自动关**（duration 0）——那是"你以为投了其实没投"的唯一现场证据。
   */
  const submitDispatch = async () => {
    if (!ids.length) return;
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
          // 批 Q（需求⑤）：三种语义必须分开——
          //   勾了「取消」→ 空串（后端把这几张行上钉的要求清掉）
          //   挑了一条   → id ＋顺序
          //   什么都没动   → 字段不传（沿用各单行上原有的要求，不清空）
          concat_asset_id: dispatchConcatClear ? '' : dispatchConcatId || undefined,
          concat_order:
            !dispatchConcatClear && dispatchConcatId ? dispatchConcatOrder : undefined,
        }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做，弹窗留着
      setDispatchOpen(false);
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
        // 11-09 用户口径「确认后窗口就缩掉，让任务在后台跑着」：原来这里开的是
        // `Modal.success`——提交已经成功了，却还要人再点一下"知道了"才能关掉窗口。
        // 换成右上角消息条：正常回执 8 秒自动收；**只有闸门挡下**的那条不自动关
        // （duration 0），因为那是「你以为投出去了其实没投」的唯一现场证据。
        notification.open({
          key: 'asset-dispatch-ack',
          message: ack.message,
          placement: 'topRight',
          duration: pre.blocked?.length ? 0 : 8,
          style: { width: 520 },
          description: (
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
              {/* 批 Q：拼装要求投出去之前就得看得见——回收是几十分钟后另一个进程做的，
                  那时才发现"没钉上"就只能手工另拼一遍（需求⑤要消掉的正是这一步）。 */}
              {!!pre.concat && 'applied_to' in pre.concat && (
                <Text style={{ fontSize: 12 }}>
                  出片后每支自动和 <Text strong>{pre.concat.label}</Text> 拼一条
                  （{pre.concat.order === 'hook_first' ? '钩子片在前' : '片段在前'}），
                  拼成 0 元、只拼一次；要求钉在 {pre.concat.applied_to.length} 张单上，
                  进程重启后走「只回收」也照样拼。
                </Text>
              )}
              {!!pre.concat && 'cleared_for' in pre.concat && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已取消 {pre.concat.cleared_for.length} 张单的自动拼接（成片原样进产物，要拼去详情抽屉手工拼）。
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
        notification.open({
          key: 'asset-dispatch-ack',
          message: r.message,
          placement: 'topRight',
          duration: r.uncertain?.length ? 0 : 8,
          style: { width: 520 },
          description: (
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              <Text style={{ fontSize: 12 }}>
                新建 {r.dispatched} 张、回收 {r.recovered} 张、到手 {r.succeeded ?? 0}／失败 {r.failed ?? 0}／还在板上 {r.still_running ?? 0}。
              </Text>
              {/* 批 Q：同步档（脚本/用例走的这条）也把拼没拼说清楚；界面按钮走的是异步档，
                  真结果在任务台账里，行上的「拼没拼」列跟着刷新。 */}
              {!!r.concat?.note && (
                <Text type={(r.concat.failed ?? 0) > 0 ? 'warning' : 'secondary'} style={{ fontSize: 12 }}>
                  {r.concat.note}
                  {r.concat.failed > 0 && (
                    <>
                      （
                      {r.concat.results
                        .filter((x) => x.result === 'failed')
                        .slice(0, 3)
                        .map((x) => `${x.hook_code || x.production_id.slice(0, 8)}：${x.error}`)
                        .join('；')}
                      ——片子已进产物，去详情抽屉手工拼）
                    </>
                  )}
                </Text>
              )}
              {!!r.uncertain?.length && (
                <Alert
                  type="error"
                  showIcon
                  message={`${r.uncertain.length} 张状态未知：先别重投`}                  description={
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
      width: 150,
      render: (v: ProductionState, r) => (
        <Space direction="vertical" size={0}>
          <ProductionStateTag status={v} />
          {/* 11-10 口径③：这一行回答「这四档各下一步谁做、在哪儿看到东西」，
              标签只说台账，这句说去向——「显示完成却看不到成片」就是这两件事以前没分开。 */}
          {(() => {
            const where = stateWhereabouts(v, r);
            if (!where) return null;
            return (
              <div style={{ maxWidth: 148 }}>
                <Text type="secondary" style={{ fontSize: 12, lineHeight: '16px' }}>
                  {where}
                </Text>
                {v === 'success' && (r.output_count ?? 0) > 0 && onGoToOutputs && (
                  <Button
                    size="small"
                    type="link"
                    style={{ padding: 0, fontSize: 12, height: 18 }}
                    onClick={onGoToOutputs}
                  >
                    去成片墙看 →
                  </Button>
                )}
              </div>
            );
          })()}
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
          {/*
            批 Q（需求⑤）「拼没拼」：这一列只**报事实**，不参与任何判定。
            三种可见状态——钉了要求还没回收（待拼）、回收过（拼成/部分/失败/此前已拼）、
            没钉（不显示）。拼失败绝不代表回收失败：片子是真金白银收回来的，
            成因在 Tooltip 里，人可以去详情抽屉手工另拼。
          */}
          {!!r.concat_asset_id && !r.concat_last_result && (
            <Tooltip title={`已钉上自动拼接：收回来每支和 ${r.concat_asset_id.slice(0, 8)} 拼一条（${
              r.concat_order === 'material_first' ? '片段在前' : '钩子片在前'
            }），等回收`}
            >
              <Tag style={{ fontSize: 11 }}>待拼</Tag>
            </Tooltip>
          )}
          {!!r.concat_last_result && (
            <Tooltip
              title={[
                `拼成 ${r.concat_last_result.ok}／失败 ${r.concat_last_result.failed}／此前已拼 ${r.concat_last_result.already}`,
                `${r.concat_last_result.order === 'material_first' ? '片段在前' : '钩子片在前'}`,
                r.concat_last_result.last_error ? `成因：${r.concat_last_result.last_error}` : '',
                r.concat_last_result.at
                  ? `时间：${parseServerTime(r.concat_last_result.at)?.format('MM-DD HH:mm')}`
                  : '',
              ]
                .filter(Boolean)
                .join('｜')}
            >
              <Tag
                color={
                  r.concat_last_result.status === 'success'
                    ? 'green'
                    : r.concat_last_result.status === 'partial'
                      ? 'orange'
                      : r.concat_last_result.status === 'already'
                        ? 'blue'
                        : 'red'
                }
                style={{ fontSize: 11 }}
              >
                {
                  {
                    success: `拼成 ${r.concat_last_result.ok}`,
                    partial: `拼成 ${r.concat_last_result.ok}·失败 ${r.concat_last_result.failed}`,
                    failed: '没拼上',
                    already: '此前已拼',
                  }[r.concat_last_result.status]
                }
              </Tag>
            </Tooltip>
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
        {/* 用户口径 2026-11-09：号池折叠块删除，只留今日消耗统计；
            暂不设上限/预警（原来的软提示线 120 已从界面移除，后端仍只记数不拦） */}
        <Col span={6}>
          <Tooltip title="今天板上真吃掉的条数（Σ各单板上条数，不是行数）；与每日解压线共用同一池，只报数。">
            <Statistic title="今日消耗" value={today?.board_rows ?? 0} suffix="条" />
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
            popupMatchSelectWidth={false}
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
              从过审文案开单{approvedPendingCount ? `（${approvedPendingCount} 待产）` : ''}
            </Button>
          </Tooltip>
        )}
        {canWriteBack && (
          <Tooltip title="机器去企微后台建任务 → 等出片 → 成片自动回到每张单的「成片」列。一次最多 20 张；点「确认投去出片」那一下就是人工确认，投完窗口当场缩掉，进度看顶部横幅。">
            <Button
              danger
              type="primary"
              icon={<CloudUploadOutlined />}
              disabled={!ids.length}
              onClick={() => openDispatch(selected)}
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
        // 11-10 用户口径「不要点到旁边它就消失掉了，很容易误点」：这一屏勾了卡、点了改稿，
        // 误触遮罩等于整屏白填——遮罩不给关，只能走「取消 / 开始回收 / 确认投去出片」三个明确的口。
        maskClosable={false}
        onCancel={() => setDispatchOpen(false)}
        onOk={submitDispatch}
        confirmLoading={dispatchBusy}
        okText={dispatchRecoverOnly ? '开始回收' : '确认投去出片'}
        okButtonProps={{
          danger: !dispatchRecoverOnly,
        }}
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {/* 11-10 一屏到底：这批是**刚建完直接顶进来**的时候，开单那一屏上那些"先别投"的话
              在这里接着说（漂移/自动检查没过/标题超字/卡是横版…）。没带话＝从列表勾单投的，不占地方。 */}
          {!!openNotes.length && (
            <Alert
              type="warning"
              showIcon
              message={`开单时有 ${openNotes.length} 件事要看着办（这批单已经建好，投不投由你定）`}
              description={
                <Space direction="vertical" size={2}>
                  {openNotes.slice(0, 8).map((nx, i) => (
                    <Text key={i} style={{ fontSize: 12 }}>
                      {nx}
                    </Text>
                  ))}
                  {openNotes.length > 8 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      另有 {openNotes.length - 8} 条没列出
                    </Text>
                  )}
                </Space>
              }
            />
          )}
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
              本批 ≈{dispatchPlan.rows} 条额度｜今天已投 {dispatch?.today?.board_rows ?? 0} 条
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
                ? '回收档不烧额度、一个都不新建；进程重启后靠它把片子取回来'
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
          {/*
            批 Q（11-10，需求⑤「钩子成片生成出来以后，需要导入拼接视频自动拼接成可投放素材」）：
            第二段在这里点名，不等回收。判据（是不是图片、有没有文件）后端在**烧号池之前**跑，
            所以这里选不出拼不了的东西；真选的那条被人在回收前删了，也只是这一支拼失败，
            成片照样进产物（成因写进「拼没拼」那一列）。
          */}
          {dispatchPlan.concatTargets > 0 && (
            <div>
              <Tooltip title="片子收回来以后，每支自动和这条素材两段直拼成一条可投放素材：0 元、每支只拼一次、拼成后来源素材状态点亮成「可投放」。不选＝这次不提要求（各单行上原来钉的照旧）。">
                <Text strong style={{ fontSize: 12 }}>成片到手后自动拼接</Text>
              </Tooltip>
              <div style={{ marginTop: 4 }}>
                <AssetConcatPicker
                  active={dispatchOpen && !dispatchConcatClear}
                  value={dispatchConcatClear ? null : dispatchConcatId}
                  onChange={setDispatchConcatId}
                  order={dispatchConcatOrder}
                  onOrderChange={setDispatchConcatOrder}
                />
              </div>
              {!!dispatchPlan.pinnedConcat && (
                <Checkbox
                  checked={dispatchConcatClear}
                  onChange={(e) => setDispatchConcatClear(e.target.checked)}
                  style={{ marginTop: 6 }}
                >
                  取消这 {dispatchPlan.pinnedConcat} 张单已钉的自动拼接（投出去就不再自动拼，成片原样进产物）
                </Checkbox>
              )}
            </div>
          )}
          {/* 11-06 拍板：投递稿可改。只改这次投出去的；改稿在后端照走风险词重扫并留审计 */}
          {!dispatchRecoverOnly && dispatchPlan.willCreate > 0 && (
            <div>
              <Space size={6} align="center">
                <Tooltip title="只改这一次投出去的正文，库里的提示词不动；改稿会照过一遍高风险词">
                  <Text strong style={{ fontSize: 12 }}>投递稿</Text>
                </Tooltip>
                <Tooltip title="投产前把稿子里的元素（场景／动物／动物说的话…）换成别的说法：这里能看到都配了哪些、给哪几个候选（管理员可改）">
                  <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setElementsOpen(true)}>
                    可替换元素库
                  </Button>
                </Tooltip>
              </Space>
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
                      onClick={() => openPromptEditor(p)}
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

      {/*
        11-06 投递稿可改 ＋ 11-10 批 M 元素裂变 ＋ 11-10 下午用户五条口径：
        · 左边一排是「这份稿子里认出来的可替换元素」（候选＝字典里的 pool，也能自己输入），
          每行下面把**稿子里那一行的原句**摊出来做对照；
        · 右边那一大段是**这一次真正投出去的全文**——套完立刻能在眼前看到整份稿子，
          底下「改了 N 行」是把改前改后逐行描出来的地方，不用自己在几千字里找；
        · 窗口加宽＋点旁边不再关掉（原来误点遮罩整屏白改）；
        · 静态说明缩进「？」浮窗，只有会拦人的话（风险词）留在界面上。
        确认（「用这份投」）之后才进 payload。全程只改这一次投出去的，库里的提示词不动。
      */}
      <Modal
        open={!!editPromptFor}
        title={
          <Space size={6}>
            {`改投递稿（${editPromptFor?.hook_code || editPromptFor?.id.slice(0, 8) || ''}）`}
            <HelpDot text="只改这一次投出去的正文：库里的提示词、过审文案、漂移判定都不动，下一次再投仍是原稿。改后的稿子会照过一遍高风险词（命中会被拦，admin 可带理由放行）；改了哪张、改前是什么，进审计。">
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>（这份只投一次）</Text>
            </HelpDot>
          </Space>
        }
        width="min(1280px, 96vw)"
        maskClosable={false}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto', paddingRight: 6 } }}
        onCancel={() => {
          // 「点旁边就消失」＝改了半天一句话没存，加一道脏检查：真改了就先问一句
          const dirty = !!editPromptFor
            && editPromptDraft.trim() !== (promptOverrides[editPromptFor.id] ?? editPromptFor.prompt_text ?? '').trim();
          if (!dirty) {
            setEditPromptFor(null);
            return;
          }
          Modal.confirm({
            title: '这份改完还没点「用这份投」',
            content: '现在关掉，这次的改动就不算了（下一屏仍按没改过处理）。',
            okText: '继续留着改',
            cancelText: '丢掉这次改动',
            okCancel: true,
            onOk: () => undefined,
            onCancel: () => setEditPromptFor(null),
          });
        }}
        onOk={() => {
          if (editPromptFor) {
            const id = editPromptFor.id;
            // 「已改」这个标签要说真话：还原成原稿又点「用这份投」不算改过，
            // 留着 override 会让下一屏以为这张单被改过（导出/投板侧也是按这个键判的）。
            setPromptOverrides((m) => {
              const next = { ...m };
              if (editPromptDraft.trim() === (editPromptFor.prompt_text ?? '').trim()) delete next[id];
              else next[id] = editPromptDraft;
              return next;
            });
          }
          setEditPromptFor(null);
        }}
        okText="用这份投"
        cancelText="算了不改"
      >
        <Row gutter={16} align="top">
          <Col xs={24} xl={11}>
            <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: '10px 12px' }}>
              <Space size={6} align="center" wrap style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>可替换元素</Text>
                <HelpDot
                  text={
                    editPromptFor?.category_name
                      ? `这一屏只摆原型「${editPromptFor.category_name}」在字典里配的参数项。换词是在右边那份正文上做的字面替换，不花钱、不动库里的稿子。认得不准就点「重新认一遍」——字典是管理员随时在改的，改完这里立刻按新的认。`
                      : '这张单没带原型：限定原型的槽位不显示，只认通用那些。要让它按原型摆参数，回②素材与文案那边把钩子原型点上。'
                  }
                />
                <Button
                  size="small"
                  type="link"
                  style={{ padding: 0 }}
                  loading={elementBusy}
                  onClick={() => editPromptFor && extractElements(editPromptFor, editPromptDraft)}
                >
                  重新认一遍
                </Button>
                <Button
                  size="small"
                  type="link"
                  style={{ padding: 0 }}
                  onClick={() => setElementsOpen(true)}
                >
                  元素库（管理员可配）
                </Button>
              </Space>
              {elementRows.length === 0 && !elementBusy ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  这份稿子里没认出可替换元素——可能字典还没配这一类，也可能这份稿子不照模板写。
                  想直接改词，用下面那行「自定义替换」。
                </Text>
              ) : (
                <div>
                  {elementRows.map((slot) => (
                    <PromptElementRow
                      key={slot.key}
                      slot={slot}
                      value={elementChoice[slot.key] ?? ''}
                      busy={elementBusy}
                      otherCount={selected.filter((p) => canCreateLocally(p) && p.id !== editPromptFor?.id).length}
                      onValue={(v) => setElementChoice((m) => ({ ...m, [slot.key]: v }))}
                      onApply={(s, v) => void applySlot(s, v)}
                      onApplyBatch={(s, v) => void applyToOthers(editsForSlot(s, v), s.label)}
                    />
                  ))}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>自定义替换</Text>
                <HelpDot text="上面那些是字典认出来的元素；这一行不限字典——把稿子里那段原文照抄进第一个框（一字不差，多个字也行），第二个框写换成什么，点「套用」就整段逐字换掉。" />
                <Input
                  size="small"
                  style={{ width: 150 }}
                  placeholder="稿子里要换掉的那段原文"
                  value={customOld}
                  onChange={(e) => setCustomOld(e.target.value)}
                  disabled={elementBusy}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>换成</Text>
                <Input
                  size="small"
                  style={{ width: 150 }}
                  placeholder="换成什么"
                  value={customNew}
                  onChange={(e) => setCustomNew(e.target.value)}
                  disabled={elementBusy}
                />
                <Button size="small" disabled={elementBusy} onClick={applyCustom}>
                  套用
                </Button>
                {selected.filter((p) => canCreateLocally(p) && p.id !== editPromptFor?.id).length > 0 && (
                  <Button
                    size="small"
                    disabled={elementBusy}
                    onClick={() =>
                      customOld.trim() &&
                      customNew.trim() &&
                      void applyToOthers([{ old: customOld.trim(), new: customNew.trim() }], customOld.trim())
                    }
                  >
                    同文字套用到本批另 {selected.filter((p) => canCreateLocally(p) && p.id !== editPromptFor?.id).length} 张
                  </Button>
                )}
              </div>
              {elementNotes.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                  {elementNotes.map((n) => (
                    <li key={n}>
                      <Text type="secondary" style={{ fontSize: 12 }}>{n}</Text>
                    </li>
                  ))}
                </ul>
              )}
              {elementBlocked && (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginTop: 8 }}
                  message="换上这个词会被投板闸门拦下"
                  description={
                    <span style={{ fontSize: 12 }}>
                      现在还没拦你（这里只组稿），点「确认投去出片」时会被打回。
                      要么换个说法，要么让 admin 带理由强行放行。
                    </span>
                  }
                />
              )}
            </div>
          </Col>

          <Col xs={24} xl={13}>
            <Space size={6} align="center" wrap style={{ marginBottom: 4 }}>
              <Text strong style={{ fontSize: 12 }}>这一次投出去的全文</Text>
              <HelpDot text="左边每点一次「套用」，这里就是改完之后的整份稿子——投出去的就是这一段，一个字都不差。还能继续整段手改；点「用这份投」才算定稿，否则回上一屏仍是原稿。" />
              <Button
                size="small"
                type="link"
                style={{ padding: 0 }}
                onClick={() => {
                  if (editPromptFor) {
                    setEditPromptDraft(editPromptFor.prompt_text ?? '');
                    setElementNotes([]);
                    setElementBlocked(false);
                    setElementMarks([]);
                    setMarksText('');
                    void extractElements(editPromptFor, editPromptFor.prompt_text ?? '');
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
            <Input.TextArea
              rows={16}
              value={editPromptDraft}
              onChange={(e) => setEditPromptDraft(e.target.value)}
              placeholder="这一次投出去的提示词正文（留空＝照原稿投）"
            />
            {/*
              11-10 用户口径①「选了几个元素，但没看到正文被替换的地方」：
              TextArea 里是一整片同色字，换上的词藏在第 30 行就等于没换。这里补一块**只读稿纸**，
              把刚换上的词按后端给的坐标描绿并自动滚到第一处。位置只在「套完之后没再手改」时有效——
              marksText 和当前正文一旦不一致就改成一句话说明，绝不拿旧坐标描到新正文上。
              （下面的逐行对照回答的是另一问：改了哪几行、原稿那行写的什么。）
            */}
            {elementMarks.length > 0 && (
              marksText === editPromptDraft ? (
                <div style={{ marginTop: 8 }}>
                  <HighlightedPrompt
                    text={editPromptDraft}
                    marks={elementMarks}
                    maxHeight={220}
                    caption={`刚换上的 ${elementMarks.length} 处已标绿（投出去的就是这一段）`}
                  />
                </div>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  标绿的位置已作废——你在文本框里手改过正文，旧坐标不能再描到新稿上。要看落点就再点一次「套用」。
                </Text>
              )
            )}
            <div style={{ marginTop: 8 }}>
              <PromptDraftDiff before={editPromptFor?.prompt_text ?? ''} after={editPromptDraft} />
            </div>
          </Col>
        </Row>
      </Modal>

      {/* 批 M：可替换元素库（读全员、写仅 admin；改完下一次打开「改稿」立即按新的认） */}
      <AssetPromptElementDrawer open={elementsOpen} onClose={() => setElementsOpen(false)} />

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

      {/* 批 L：过审文案挑选弹窗；批 N 起与 ② 素材页共用同一个组件（同一套拉法、同一套话术） */}
      <ApprovedSummaryPickerModal
        open={approvedOpen}
        title="从过审文案开单"
        batchOptions={batchOptions}
        onCancel={() => setApprovedOpen(false)}
        onConfirm={(rows) => {
          setPickedSummaries(rows);
          setApprovedOpen(false);
          setProduceOpen(true);
        }}
      />

      <ProduceOrderModal
        open={produceOpen}
        summaries={pickedSummaries}
        isAdmin={isAdmin}
        batchId={batchFilter || batchId}
        onClose={() => setProduceOpen(false)}
        onDone={() => {
          setProduceOpen(false);
          setPickedSummaries([]);
          fetchList(page, pageSize);
        }}
        // 11-10 一屏到底：建完当场关窗（ProduceOrderModal 自己 onClose），这里直接
        // 把刚建的那几张顶进投板确认窗——不用再回列表勾一遍。
        onProduced={(ids, notes) => {
          setProduceOpen(false);
          setPickedSummaries([]);
          void takeOverDispatch(ids, notes);
        }}
      />
    </Card>
  );
};

export default AssetProductionPanel;
