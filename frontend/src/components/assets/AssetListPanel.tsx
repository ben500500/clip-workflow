import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, DatePicker, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  BulbOutlined, CloudDownloadOutlined, DeleteOutlined, DownloadOutlined, FileTextOutlined, LoadingOutlined,
  MergeCellsOutlined, QuestionCircleOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  ASSET_STAGE_LABELS, ASSET_STATUS_LABELS, DEFAULT_TIER, DURATION_TIERS, assetApi, isAssetJobAck,
} from '../../api/assets';
import type {
  AssetItem, AssetAnalyzeResponse, AssetCostEstimateResponse, AssetMediaKind, AssetResolveResponse,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { AssetStatusTag, MediaKindTag, StageTags, aspectShortText, durationText, isImageAsset, yuan } from './AssetBits';
import {
  CategorySelect, CategoryTag, UNCLASSIFIED, invalidateAssetCategories, useAssetCategories,
} from './AssetCategoryBits';
import CostConfirmModal from './CostConfirmModal';
import AssetDetailDrawer from './AssetDetailDrawer';
import AssetComposeModal from './AssetComposeModal';
import { nudgeAssetJobBanner } from './AssetJobBanner';
import { withCrossPersonConfirm } from './crossPerson';

const { Text } = Typography;
const { RangePicker } = DatePicker;

/** 列宽拖拽的记忆键（批 J 列表列宽可拖，拖完存本地，下次进来保持） */
const COL_WIDTH_KEY = 'asset-list-col-widths-v1';

/** 来源链接太长截断成「域名+尾巴」，全文放 Tooltip（批 J：超长链接把列撑爆） */
const shortUrl = (u: string) => {
  try {
    const p = new URL(u);
    return `${p.host}/…${u.slice(-14)}`;
  } catch {
    return u.length > 40 ? `${u.slice(0, 40)}…` : u;
  }
};

/** 表头拖拽把手：盖住列分隔线 6px，按住左右拖改列宽（原生 pointer 事件，不引第三方库） */
const startResize = (
  e: React.PointerEvent,
  curWidth: number,
  onMove: (w: number) => void,
  onEnd: () => void,
) => {
  e.preventDefault();
  e.stopPropagation();
  const startX = e.clientX;
  const startW = curWidth;
  const move = (ev: PointerEvent) => onMove(Math.max(60, startW + ev.clientX - startX));
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    onEnd();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
};

/**
 * 表头单元格：只有 `onHeaderCell` 回了 width/handler 的列才渲染拖拽把手
 * （antd 把 `onHeaderCell` 的返回值当 props 传给这个单元格）。
 * 没配的列（勾选框、操作列）原样渲染，一个属性都不多。
 */
const ResizableHeaderCell: React.FC<{
  width?: number;
  onResizeStart?: (e: React.PointerEvent) => void;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  // 其余全是 antd 透传的 th 属性（className/colSpan/…）
  [key: string]: unknown;
}> = ({ width, onResizeStart, children, style, ...rest }) => {
  const thProps = rest as React.ThHTMLAttributes<HTMLTableCellElement>;
  if (!width || !onResizeStart) return <th style={style} {...thProps}>{children}</th>;
  return (
    <th style={{ ...style, position: 'relative' }} {...thProps}>
      {children}
      <span
        title=""
        onPointerDown={onResizeStart}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          bottom: 0,
          width: 7,
          cursor: 'col-resize',
          zIndex: 2,
        }}
      />
    </th>
  );
};


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
  /**
   * 批 G：按媒体类型筛。`image` 就是「只看角色卡」——投产前想核对库里有哪些卡、
   * 画幅对不对，靠这一筛，不用翻整页列表找扩展名。
   */
  const [mediaKind, setMediaKind] = useState<AssetMediaKind | undefined>();
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
  // 行级「重试反推」提交中（11-05：失败行的环节旁小图标）
  const [retryingId, setRetryingId] = useState<string | null>(null);
  // 行级「重试下载原片」提交中（批 J：下载失败的行就地重试）
  const [retryDlId, setRetryDlId] = useState<string | null>(null);
  /**
   * 批 J：反推时顺带把链接素材的原片下载进自有桶（用户口径：默认要下）。
   * 只对勾选里的链接视频成立；文件/图片后端本来就会跳过，勾不勾不影响。
   */
  const [withDownload, setWithDownload] = useState(true);
  // 批 J：列宽可拖（记忆在 localStorage）。key→宽度；没记过的列用定义里的默认宽
  const [colWidths, setColWidths] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(localStorage.getItem(COL_WIDTH_KEY) || '{}');
    } catch {
      return {};
    }
  });
  const colWidthsRef = useRef(colWidths);
  colWidthsRef.current = colWidths;

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
          media_kind: mediaKind,
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
    [keyword, status, sourceKind, mediaKind, stagePrompt, batchFilter, categoryFilter, dates, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, sourceKind, mediaKind, stagePrompt, batchFilter, categoryFilter, dates]);

  // 后台任务刚收敛完（横幅确认终态后 +1）：阶段标签和状态是后端算的，只能重新拉一次
  useEffect(() => {
    if (!reloadToken) return;
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);
  const runningCount = useMemo(() => items.filter((i) => i.stage_prompt === 'running').length, [items]);
  /**
   * 批 G：勾选里区分「视频」和「图片」。三个花钱按钮（反推文案／出文案／查时长）
   * 只对视频成立，所以**提交只给视频 id**、预估也只按视频条数算——
   * 把图片混进 count 里报钱，确认单上的数字会比实际扣的多，对账时说不清。
   * 后端那道口（逐条点名拒图）是第二道闸，不能反过来代替这里的分流。
   */
  const selectedVideoIds = useMemo(
    () => selected.filter((s) => !isImageAsset(s)).map((s) => s.id),
    [selected],
  );
  const selectedImageCount = useMemo(
    () => selected.filter((s) => isImageAsset(s)).length,
    [selected],
  );
  const selectedVideoCount = selectedVideoIds.length;

  // ── 反推文案（原「反推」）──
  const openAnalyze = async () => {
    if (!ids.length) {
      message.warning('先勾选要反推文案的素材');
      return;
    }
    // 批 G：一张视频都没选上（全是角色卡）时直接说清，不弹一张 0 条的成本确认单
    if (!selectedVideoCount) {
      message.warning(
        `选中的 ${ids.length} 条都是图片：图片只当投产用的角色卡，不反推文案（提交了也是白扣一次钱）`,
        8,
      );
      return;
    }
    setAnalyzeOpen(true);
    // 11-05 用户口径：反推是常规动作，进来就默认勾上「同意提交」——
    // 想反悔的人再点一下取消即可；确认单上的钱数照旧展示，闸门本身不放松
    setConfirmed(true);
    setForce(false);
    setPreviewLoading(true);
    try {
      setAnalyzePreview(await assetApi.estimateCost({ count: selectedVideoCount, max_duration: tier }));
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
      setAnalyzePreview(await assetApi.estimateCost({ count: selectedVideoCount, max_duration: nextTier }));
    } finally {
      setPreviewLoading(false);
    }
  };

  const submitAnalyze = async () => {
    setAnalyzeLoading(true);
    try {
      const res: AssetAnalyzeResponse | undefined = await withCrossPersonConfirm((c) =>
        assetApi.analyzeBatch({
          asset_ids: selectedVideoIds,
          max_duration: tier,
          confirmed: true,
          force,
          retry_failed: retryFailed,
          download: withDownload,
          cross_person_confirm: c,
        }),
      );
      if (!res) return; // 用户在「替他人批次」确认窗点了取消：什么都没动，留在弹窗里
      Modal.info({
        title: '反推文案已提交',
        width: 520,
        content: <Text>{res.message}</Text>,
      });
      setAnalyzeOpen(false);
      setSelected([]);
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '提交反推文案失败');
    } finally {
      setAnalyzeLoading(false);
    }
  };

  // ── 出文案（提交即回任务号，顶部横幅负责报"跑完了"）──
  const generateSummaries = async () => {
    // 11-05 修真 bug：原来按 `selected[i].stage_prompt` 判——那是**勾选那一刻的行快照**，
    // 反推在后台跑完、列表虽然刷新了，`selected` 里存的还是旧对象（stage_prompt 还是
    // running/未跑），于是「不刷新页面就选它出文案」永远提示"没有反推文案成功的"。
    // 改成按 id 回当前列表里取最新行：横幅一收敛 fetchList 过，这里看到的就是 success。
    const freshById = new Map(items.map((it) => [it.id, it]));
    const ok = ids.filter((id) => freshById.get(id)?.stage_prompt === 'success');
    if (!ok.length) {
      const waiting = ids.filter((id) => freshById.get(id)?.stage_prompt === 'running').length;
      message.warning(
        waiting
          ? `选中的素材里有 ${waiting} 条反推文案还在跑，跑完（顶部横幅会报）再出文案`
          : '选中的素材里没有「反推文案成功」的——文案是从反推文案稿里出的，得先反推一遍',
      );
      return;
    }
    // 11-06 承诺审计②：后端 note 说「重生成请勾选 overwrite」，但界面上从没有这个
    // 勾选框——承诺了一个无法执行的动作。现在勾了已有候选的素材时会真问一句。
    const hasCopies = ok.filter((id) => (freshById.get(id)?.summary_count ?? 0) > 0);
    if (hasCopies.length) {
      const run = (ids2: string[], overwrite: boolean) => doGenerateSummaries(ids2, overwrite);
      Modal.confirm({
        title: `选中的素材里 ${hasCopies.length} 条已经有候选文案`,
        content: (
          <div>
            <p style={{ marginBottom: 6 }}>「覆盖重出」会把这些旧候选删掉重新生成（已过审的会拦下，必须先撤审）；旧的留档按「只补」。</p>
          </div>
        ),
        okText: `覆盖重出（${hasCopies.length} 条旧的删掉）`,
        cancelText: '只补还没有文案的',
        onOk: () => run(ok, true),
        onCancel: () => {
          const onlyNew = ok.filter((id) => !hasCopies.includes(id));
          if (onlyNew.length) run(onlyNew, false);
          else message.info('选中的都有候选了，没有要补的');
        },
      });
      return;
    }
    await doGenerateSummaries(ok, false);
  };

  const doGenerateSummaries = async (ok: string[], overwrite: boolean) => {
    setGenBusy(true);
    try {
      const res = await withCrossPersonConfirm((c) =>
        assetApi.generateSummaries({ asset_ids: ok, async_mode: true, overwrite, cross_person_confirm: c }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做
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
      const res: AssetResolveResponse | undefined = await withCrossPersonConfirm((c) =>
        assetApi.resolveAssets({
          asset_ids: linkIds,
          confirmed: linkIds.length >= 2,
          cross_person_confirm: c,
        }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做
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
                message={`${notes.length} 条给了说明（有说明不等于失败：命中免费渠道时本来就不回时长）`}
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

  // ── 行级重试反推（11-05）：失败的行在环节旁给个 ⟳ 小图标，点了按默认档重跑这一条 ──
  const retryAnalyze = (row: AssetItem) => {
    const perCost = DEFAULT_TIER * 0.00054;
    Modal.confirm({
      title: `重试反推文案（${row.code}）`,
      width: 520,
      content: (
        <Text style={{ fontSize: 12 }}>
          按 {DEFAULT_TIER}s 默认档扣费，这条约 {yuan(perCost)}。只重跑这一条，不用回上面勾选再开弹窗；
          跑完列表自己刷新，失败原因看详情抽屉。
        </Text>
      ),
      okText: '重试',
      onOk: async () => {
        setRetryingId(row.id);
        try {
          const res: AssetAnalyzeResponse | undefined = await withCrossPersonConfirm((c) =>
            assetApi.analyzeBatch({
              asset_ids: [row.id],
              max_duration: DEFAULT_TIER,
              confirmed: true,
              retry_failed: true,
              cross_person_confirm: c,
            }),
          );
          if (!res) return; // 取消了「替他人批次」确认
          if (isAssetJobAck(res)) nudgeAssetJobBanner();
          message.success(res.message || '反推文案已重新提交', 8);
          fetchList();
        } catch (e) {
          message.error((e as Error).message || '重试提交失败');
        } finally {
          setRetryingId(null);
        }
      },
    });
  };

  /**
   * 批 J：行级「重试下载原片」。链接素材下载失败的行就地给红色小标，点了
   * 只重下这一条（已在桶里的后端会跳过并说明）。免费渠道 0 元；付费渠道一条
   * 0.01 元——失败那一次多半已把解析费记过账，重试可能再扣一次，话术里说清。
   */
  const retryDownload = async (row: AssetItem) => {
    setRetryDlId(row.id);
    try {
      const res = await withCrossPersonConfirm((c) =>
        assetApi.downloadSources({ asset_ids: [row.id], async_mode: true, cross_person_confirm: c }),
      );
      if (!res) return; // 取消了「替他人批次」确认
      if (isAssetJobAck(res)) {
        message.success(res.message || '已排上下载，跑完这行会变绿色', 6);
        nudgeAssetJobBanner();
      } else {
        message.success(res.message || '下载已提交', 6);
      }
      fetchList();
    } catch (e) {
      message.error((e as Error).message || '下载提交失败');
    } finally {
      setRetryDlId(null);
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

  // ── 删除（11-06）：行级垃圾桶 + 勾选后批量删。挂在谁头上谁确认，
  //    有文案/生产单/产物的后端会拒（409 的话术直接透出来），不在这里猜。
  const [delBusy, setDelBusy] = useState(false);
  const deleteRows = (rows: AssetItem[]) => {
    if (!rows.length || delBusy) return;
    Modal.confirm({
      title: `删除 ${rows.length} 条素材？`,
      content: (
        <div>
          <p style={{ marginBottom: 6 }}>
            删除后素材行和桶里的原片/抽帧图一起没了，<strong>恢复不了</strong>。
          </p>
          <p style={{ marginBottom: 0 }}>
            已经出过文案、建过生产单或拼过产物的会被拦下不让删（历史要留档）；
            确实要连历史一起删的得找管理员。
          </p>
        </div>
      ),
      okText: `删除（${rows.length} 条）`,
      okType: 'danger',
      cancelText: '先不删',
      onOk: async () => {
        setDelBusy(true);
        const failed: string[] = [];
        let done = 0;
        for (const row of rows) {
          try {
            await assetApi.deleteAsset(row.id);
            done += 1;
          } catch (e) {
            failed.push(`${row.code}：${(e as Error).message}`);
          }
        }
        setDelBusy(false);
        if (done) message.success(`已删除 ${done} 条`);
        failed.forEach((m) => message.error(m, 6));
        setSelected([]);
        fetchList();
      },
    });
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
      // 批 J：给个默认宽（没有 numeric width 的列不挂拖拽把手，被别的列拖挤到 50px 时
      // 用户连拽回来都做不到——截图验收里真发生了）
      width: 240,
      render: (v: string | null, row) => (
        // 批 J：全文挪进悬浮提示，列里只显示截断的链接（域名+尾巴），拖宽列也看得到全文
        <Tooltip
          title={
            <div style={{ maxWidth: 420, wordBreak: 'break-all' }}>
              {row.title && <div>{row.title}</div>}
              {row.source_url && <div style={{ marginTop: 2 }}>{row.source_url}</div>}
              {!row.title && !row.source_url && <div>（未取到标题）</div>}
            </div>
          }
        >
          <Space direction="vertical" size={0}>
            {/* 11-06 承诺审计①：88a7f67 后反推成功会自动回填标题，旧话术
                「链接素材：无标题，只有来源地址」与修复后的行为自相矛盾 */}
            <Text strong={!!v}>
              {v || (
                <Text type="secondary">
                  {row.source_url ? '（还没有标题：反推成功后自动起，取不到就留空）' : '（未取到标题）'}
                </Text>
              )}
            </Text>
            {row.source_url ? (
              <a href={row.source_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
                {shortUrl(row.source_url)}
              </a>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {row.file_name || '-'}
              </Text>
            )}
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '来路',
      dataIndex: 'source_kind',
      width: 96,
      render: (v: string, row) => (
        <Space direction="vertical" size={0}>
          <Tag>{v === 'link' ? row.platform || '链接' : '文件'}</Tag>
          {/* 批 J：链接素材的原片下载三态小标——下载是搭车动作，失败不拦流程，
              但得让人看得见、点得动重试，不能只藏在详情抽屉里 */}
          {!isImageAsset(row) && v === 'link' && (
            row.download_status === 'running' ? (
              <Tag icon={<LoadingOutlined spin />} color="processing" style={{ fontSize: 11, marginInlineEnd: 0 }}>
                原片下载中
              </Tag>
            ) : row.download_status === 'failed' ? (
              <Tooltip title="原片没下载下来，点这里重试（只重下这一条；走免费渠道不花钱，付费渠道一条 0.01 元）">
                <a onClick={() => retryDownload(row)}>
                  <Tag color="red" style={{ fontSize: 11, marginInlineEnd: 0 }}>
                    {retryDlId === row.id ? '提交中…' : '下载失败·点重试'}
                  </Tag>
                </a>
              </Tooltip>
            ) : row.file_key ? (
              <Tag color="green" style={{ fontSize: 11, marginInlineEnd: 0 }}>原片已下载</Tag>
            ) : (
              <Tooltip title="原片还在别人平台上，我们自己的存储里没有；反推文案时勾「顺带下载原片」就会存一份进来">
                <Text type="secondary" style={{ fontSize: 11 }}>原片未下载</Text>
              </Tooltip>
            )
          )}
        </Space>
      ),
    },
    {
      /**
       * 批 G：类型列。图片在这张表里**永远停在「图片已入库」**——它不走五个环节，
       * 所以把画幅直接写在列上（成片画幅跟卡走，横版卡要在投产前就被认出来）。
       */
      title: '类型',
      key: 'media_kind',
      width: 96,
      render: (_, row) =>
        isImageAsset(row) ? (
          <Space direction="vertical" size={0}>
            <MediaKindTag asset={row} />
            <Text type={row.aspect?.orientation === 'landscape' ? 'danger' : 'secondary'} style={{ fontSize: 11 }}>
              {aspectShortText(row.aspect)}
            </Text>
          </Space>
        ) : (
          <MediaKindTag asset={row} />
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
      render: (v: number | null, row) =>
        isImageAsset(row) ? (
          // 批 G：图片没有「时长」这回事，给个横杠而不是「未知」——
          // 「未知」在这里的含义是"链接素材还没回源查"，会让人以为点查时长能查出来
          <Text type="secondary">—</Text>
        ) : v === null || v === undefined ? (
          <Tooltip
            title={
              row.source_kind === 'link'
                ? '链接素材库里没存原片，反推文案也只回文字提示词。要看时长点「查时长」（0.01 元/次）'
                : '文件素材上传时本地探查没拿到时长（文件损坏或格式不识别）；本地重探不花钱，重传一次即可'
            }
          >
            <Text type="warning">未知</Text>
          </Tooltip>
        ) : (
          durationText(v)
        ),
    },
    {
      title: (
        <Tooltip
          title={
            <div>
              <div>五个字 = 这条素材走到哪一步了：<strong>导</strong>＝导入、<strong>读</strong>＝反推文案、<strong>文</strong>＝钩子文案、<strong>单</strong>＝生产单、<strong>拼</strong>＝拼接产物。</div>
              <div style={{ marginTop: 4 }}>灰＝没开始、蓝＝进行中、绿＝成功、红＝失败、黄＝跳过。悬停单个字看全称。</div>
            </div>
          }
        >
          <span>五个环节</span>
        </Tooltip>
      ),
      key: 'stages',
      width: 148,
      render: (_, row) => (
        <Space size={2}>
          <StageTags asset={row} />
          {/* 11-05：反推失败的行就地给个 ⟳——不用把这条重新勾一遍再开批量弹窗 */}
          {canProduce && !isImageAsset(row) && row.stage_prompt === 'failed' && (
            <Tooltip title="这条反推文案失败了，点重试（按默认时长档扣费）">
              <Button
                size="small"
                type="text"
                icon={<ReloadOutlined />}
                loading={retryingId === row.id}
                onClick={() => retryAnalyze(row)}
                style={{ width: 20, height: 20, marginLeft: 2 }}
              />
            </Tooltip>
          )}
        </Space>
      ),
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
        <Tooltip title={`反推文案 ${yuan(row.cost_prompt)}｜查时长 ${yuan(row.cost_parse)}`}>
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
          {canProduce && !isImageAsset(row) && (
            <Tooltip title="两段直拼：再选一条素材／一个切片／本地文件，选谁在前（0 元，不选点不剪切）">
              <Button size="small" icon={<MergeCellsOutlined />} onClick={() => setComposeAsset(row)} />
            </Tooltip>
          )}
          {/* 批 G：图片不给拼接入口——ffmpeg 拿一张 jpg 当一段会在解码时炸（后端也挡，
              但入口摆在那儿就是让人去撞 400）。它的下一步在「投产」弹窗里被挑成角色卡。 */}
          {canProduce && isImageAsset(row) && (
            <Tooltip title="图片只作生产输入：投产时在「生成生产单」弹窗里挑它当角色卡。不参与反推文案、出文案、拼接。">
              <Tag color="purple" style={{ marginLeft: 2 }}>当角色卡用</Tag>
            </Tooltip>
          )}
          {/* 11-06 删除：本人删自己的、admin 删任意；拦不拦得动由后端裁决（409 话术透传） */}
          <Tooltip title="删除这条素材（有文案/生产单/产物挂着的会被拦；误删恢复不了，删前会再确认一次）">
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => deleteRows([row])} />
          </Tooltip>
        </Space>
      ),
    },
  ];

  /**
   * 批 J：列宽可拖。把每列的默认宽换成「上次拖完记住的宽」，并在表头挂拖拽把手
   * （操作列是固定列，antd 会复制表头，拖拽把手对它不生效，跳过）。
   */
  const resizableColumns: ColumnsType<AssetItem> = columns.map((col) => {
    if (!('dataIndex' in col) && !col.key) return col;
    const rawKey: unknown = col.key ?? ('dataIndex' in col ? col.dataIndex : undefined);
    const key =
      typeof rawKey === 'string' ? rawKey : Array.isArray(rawKey) ? rawKey.join('.') : undefined;
    if (!key || col.fixed) return col;
    const defaultW = typeof col.width === 'number' ? col.width : undefined;
    const curW = colWidths[key] ?? defaultW;
    return {
      ...col,
      width: curW,
      onHeaderCell: () => ({
        width: curW,
        onResizeStart: (e: React.PointerEvent) =>
          startResize(
            e,
            curW ?? 120,
            (w) => setColWidths((prev) => ({ ...prev, [key]: w })),
            () => {
              try {
                localStorage.setItem(COL_WIDTH_KEY, JSON.stringify(colWidthsRef.current));
              } catch {
                /* 存不了就算了：本次会话内拖宽仍然生效 */
              }
            },
          ),
      }),
    };
  });

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
          <Select<AssetMediaKind>
            placeholder="类型"
            allowClear
            style={{ width: 120 }}
            value={mediaKind}
            onChange={setMediaKind}
            options={[
              { value: 'video', label: '视频素材' },
              { value: 'image', label: '图片（角色卡）' },
            ]}
          />
          <Select
            placeholder="反推文案环节"
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
                  钩子原型＝这条片子的<strong>开头套路</strong>（A–G，名字照《钩子模版换皮参数设定.docx》），
                  和句式标签、公式标签是三回事。
                </div>
                <div style={{ marginTop: 4 }}>
                  原型是<strong>人工点的，也可以不点</strong>——不点照常反推文案、出文案、投产。
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
            {/* 批 G：图片混在勾选里时先把它摘出来说一句——下面几个按钮只对视频成立 */}
            {!!selectedImageCount && (
              <Tooltip title="图片（角色卡）不反推文案、不出文案、不查时长：提交进去也只会逐条回「这是图片」。这几个按钮只动勾到的视频。">
                <Tag color="purple">另勾了 {selectedImageCount} 张图，不参与这几步</Tag>
              </Tooltip>
            )}
            <Button type="primary" icon={<FileTextOutlined />} onClick={openAnalyze} disabled={!ids.length}>
              反推文案（{selectedVideoCount}）
            </Button>
            {/*
              拍板②（11-04）：出文案没有确认弹窗（D-1 后是"提交即回"的后台任务），
              所以这句软提示挂在按钮悬浮上——正好在花钱那一下看得见，但不拦人。
            */}
            <Tooltip
              title={
                <div style={{ maxWidth: 320 }}>
                  <div>文案是从「反推文案稿」里出的，而那段是 AI 看片子自己写的、没经过人工核对。</div>
                  <div style={{ marginTop: 4 }}>
                    它读歪了，文案会照着歪着写，一致性检查也判不出来（两边都歪就对得上）。
                    <strong>这一行只提醒、不拦步骤</strong>：觉得歪了就在详情抽屉里驳回文案或重做反推文案。
                  </div>
                </div>
              }
            >
              <Button icon={<BulbOutlined />} loading={genBusy} onClick={generateSummaries} disabled={!ids.length}>
                出钩子文案（{selectedVideoCount}）
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
            <Tooltip title="删掉勾选的素材（含桶里的原片与抽帧图）；有文案/生产单/产物挂着的会被后端拦下">
              <Button danger icon={<DeleteOutlined />} loading={delBusy} onClick={() => deleteRows(selected)} disabled={!ids.length}>
                删除（{ids.length}）
              </Button>
            </Tooltip>
          </Space>
        ) : (
          <Text type="secondary">当前角色只读：导入、反推文案、出文案由素材专员或运营来做</Text>
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
        extra 里本来就有 4 个动作按钮（反推文案／出文案／收结果／查时长），再挤一个 260px 的下拉
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
            先勾行再点原型；原型只是开头套路的标记，不填照样走完全链。
          </Text>
        </Space>
      )}
      <Table<AssetItem>
        rowKey="id"
        size="small"
        loading={loading}
        columns={resizableColumns}
        dataSource={items}
        scroll={{ x: 1470 }}
        components={{ header: { cell: ResizableHeaderCell } }}
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
        title={`批量反推文案（${selectedVideoCount} 条${selectedImageCount ? `，另勾的 ${selectedImageCount} 张图不读、不计费` : ''}）`}
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
              message="反推文案按你选的时长上限扣费，不按视频实际时长"
              description={
                <span style={{ fontSize: 12 }}>
                  0.00054 元/秒 × 时长上限。600 秒档一条 0.324 元，180 秒档一条 0.0972 元——上限选大了，批次成本直接翻倍。
                  系统里记的是按时长上限推算的估算金额（对方服务不逐单回传金额），用来对账，别当精确值。
                </span>
              }
            />
            <Checkbox checked={withDownload} onChange={(e) => setWithDownload(e.target.checked)}>
              <Text style={{ fontSize: 12 }}>顺带把链接素材的原片下载到我们自己的存储（默认勾上）</Text>
            </Checkbox>
            <Text type="secondary" style={{ fontSize: 11 }}>
              下载好以后回看、拼接、做合成都不用再蹲原平台的临时链接。走付费渠道时一条加 0.01 元解析费；
              上传的文件和图片本来就在自己存储里，会自动跳过。原片会一直占存储，目前不自动清理。
            </Text>
            <Checkbox checked={retryFailed} onChange={(e) => setRetryFailed(e.target.checked)}>
              <Text style={{ fontSize: 12 }}>同时重跑反推文案失败的素材（默认跳过已跑过的）</Text>
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
                实际命中 yuanbao/preview 这些免费渠道时库里记 0，对账只会偏高不会偏低。
                拿到时长才能判断「这条能不能放进 180 秒档」，所以它是反推文案之前的可选一步，不能替代反推文案。
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
