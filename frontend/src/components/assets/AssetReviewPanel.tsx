import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Drawer, Input, Modal, Popover, Segmented, Select, Space, Spin, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined,
  ReloadOutlined, SafetyCertificateOutlined, SendOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { AUDIT_STATUS_LABELS, RECHECK_CODE_LABELS, assetApi } from '../../api/assets';
import type {
  AssetBatch, AssetDetailResponse, AssetReviewAction, AssetReviewResultItem, AssetSummary, AssetSummaryListResult,
} from '../../api/assets';
import {
  CategorySelect, invalidateAssetCategories, useAssetCategories,
} from './AssetCategoryBits';
import { useAssetFrames } from './AssetFrameBits';
import AssetReviewCard from './AssetReviewCard';
import ProduceOrderModal from './ProduceOrderModal';
import RiskLexiconDrawer from './RiskLexiconDrawer';
import TrialProduceGuide from './TrialProduceGuide';
import { ReviewGuide } from './PanelGuides';

const { Text, Paragraph } = Typography;

/**
 * 一条被拦结果里「可以按类放行」的问题类型。
 * 后端回 `waivable_codes`；老响应没有就从 `problems` 兜底，别让弹窗空转到永远点不动。
 */
const waivableCodesOf = (w: AssetReviewResultItem): string[] => {
  const src = w.waivable_codes && w.waivable_codes.length ? w.waivable_codes : (w.problems || []).map((p) => p.code);
  return Array.from(new Set(src));
};

/** 批量审核时，把多条结果的可放行类型并成一组复选框 */
const unionCodes = (list: AssetReviewResultItem[]): string[] => {
  const acc: string[] = [];
  list.forEach((w) => waivableCodesOf(w).forEach((c) => !acc.includes(c) && acc.push(c)));
  return acc;
};

interface Props {
  /** operator + admin 才能审；素材专员只读（后端还会挡「生产者不得自审」） */
  canReview: boolean;
  /** 2026-11-11 评审：审核台里也有「生成生产单」入口，投产职能被关的人不能看到它 */
  canProduce: boolean;
  isAdmin: boolean;
  batchId?: string;
  /** 后台出文案任务收敛后自增（D-1）：新候选是后端落库的，只能重新拉一次才看得到 */
  reloadToken?: number;
  /** A′ UX：页签切回来自动刷新 */
  active?: boolean;
  /**
   * 批 N（评审二·P0-2）：投产成功后「去生产单列表」要真能带人过去——
   * 由页面层（AssetLibrary）传页签切换回调进来。
   */
  onGoToProduction?: () => void;
  /**
   * 11-10「一屏到底」：建完单不当场投时，把新单 ID 交给页面层带进 ④ 的投板弹窗。
   * 没传（页面层还没接）就退回原来的 onDone 路径。
   */
  onProduced?: (ids: string[], notes: string[]) => void;
}

/**
 * 文案审核台。
 *
 * 默认勾「只看推荐条」是方案 §七 的防橡皮章设计：出了多条候选时通常只有一条能钩人，
 * 全勾一遍＝把审核变成点按钮。复核真正拦人的只有两件事：**字数/断句超限**和**违禁词**；
 * 「和原视频对不上」是预警（列里标红给你看，但不卡你过审）。
 * admin 可以带 `waive_reason` 豁免拦点，还能用 `waive_codes` 只放其中一类——
 * 豁免的每一条都进 AuditLog，可抽检。
 * 撤销过审会连带作废这条文案下**还没投出去**的生产单，所以撤销动作单独走一次确认。
 * 「原型」那一列是结构层人工标记（11-04 拍板①）：出稿时从素材继承，可以就地改、也可以不点，
 * 它不参与过审判定，所以既不在四个互斥范围里，也不做任何拦截。
 *
 * **11-05 批 F：一行从"表格列"改成一张卡片**——左＝原片三帧（点开九宫格）、
 * 中＝素材与文案、右＝徽标（命中违禁词／和原视频对不上／已产 N 条）+ 操作。
 * 表格外壳留着只是为了 rowSelection 和分页，列定义合成一格。
 * 帧是纯呈现层：`GET /assets/frames` 拉不到就当没图，审核动作照点。
 */
const AssetReviewPanel: React.FC<Props> = ({ canReview, canProduce, isAdmin, batchId, reloadToken, onGoToProduction, onProduced, active = true }) => {
  const [data, setData] = useState<AssetSummaryListResult | null>(null);
  const [items, setItems] = useState<AssetSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const [auditStatus, setAuditStatus] = useState<string | undefined>('pending');
  /**
   * 批 N（评审二 P1）：关键词搜索（正文/素材码，后端 ILIKE）。与其它筛选叠加。
   */
  const [keyword, setKeyword] = useState('');
  /**
   * A′ 按运营隔离（2026-11-07）：owner=me 已过审区只显自己过审的，pending 共享。
   * 默认矩阵：operator=我的、admin=全部；纯查询偏好，「全部」是只读全量。
   */
  const [ownerView, setOwnerView] = useState<'me' | 'all'>(isAdmin ? 'all' : 'me');
  /**
   * 三个筛选项**互斥**（11-04 用户纠正）：一次只看一类。
   * 之前是三个独立勾选框，能同时勾，勾出来的是「推荐条 且 命中违禁词 且 和原视频对不上」
   * 的交集——又窄又没人看得懂。现在用单选：
   *   recommended 只看推荐条（默认，防橡皮章）／risk 只看命中违禁词／
   *   inconsistent 只看和原视频对不上／all 全部候选都列出来
   */
  const [scope, setScope] = useState<'recommended' | 'risk' | 'inconsistent' | 'all'>('recommended');
  const recommendedOnly = scope === 'recommended';
  const onlyRisk = scope === 'risk';
  const onlyInconsistent = scope === 'inconsistent';
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  /** 「等我改的」：只看被驳回/需改写、且轮到我改的条目（驳回闭环的入口） */
  const [onlyMine, setOnlyMine] = useState(false);
  /**
   * 钩子原型筛选（11-04 拍板①）。和上面那四个互斥范围是**两个轴**：
   * 范围管「看哪一类候选」，原型管「看哪一类结构」，可以叠加。
   * 筛的是文案自己那一列（出稿时从素材继承，之后素材重新归类不回写）。
   */
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  /** 批量点原型（文案侧） */
  const [assignTo, setAssignTo] = useState<string | undefined>();
  const cats = useAssetCategories();

  const [selected, setSelected] = useState<AssetSummary[]>([]);
  const [editing, setEditing] = useState<AssetSummary | null>(null);
  const [editText, setEditText] = useState('');
  /** 改后通过弹窗里顺带改的原型（留空提交＝没动，不是清成未分类） */
  const [editCat, setEditCat] = useState<string | undefined>();

  // 改后重新提审（驳回后由文案作者改完交回队列）
  const [resubmitFor, setResubmitFor] = useState<AssetSummary | null>(null);
  const [resubmitText, setResubmitText] = useState('');
  const [resubmitNote, setResubmitNote] = useState('');

  // 复核拦下后的豁免弹窗
  const [waiveFor, setWaiveFor] = useState<AssetReviewResultItem[] | null>(null);
  const [waiveReason, setWaiveReason] = useState('');
  /**
   * R-6 分粒度豁免：弹窗里默认全勾＝整条放过（老行为）；
   * 取消某一类，那类拦点就仍然拦着——防止「一句理由把违禁词也一起带走」。
   */
  const [waiveCodes, setWaiveCodes] = useState<string[]>([]);

  // 投产弹窗
  const [produceOpen, setProduceOpen] = useState(false);
  // ── 试产（2026-11-12 用户口径）：审核员改提示词投豆包验证预期，不打回采集人 ──
  // 11-13 用户提「流程很多人看不懂」：六步动画引导，工具条与试产弹窗双入口
  const [guideOpen, setGuideOpen] = useState(false);
  const [howOpen, setHowOpen] = useState(false);
  const [trialFor, setTrialFor] = useState<AssetSummary | null>(null);
  const [trialPrompt, setTrialPrompt] = useState('');
  const [trialBusy, setTrialBusy] = useState(false);
  const [trialStep, setTrialStep] = useState('');
  // 当前页候选名下的试产单（summary_id → 单列表）：卡上显示「试产中/样片待判定」
  const [trialProds, setTrialProds] = useState<
    Record<string, { id: string; status: string; error?: string | null }[]>
  >({});
  // P1（评审定稿⑨）：一致性核验抽屉（原片播放＋反推脚本全文）
  const [inspecting, setInspecting] = useState<AssetSummary | null>(null);
  const [inspectData, setInspectData] = useState<AssetDetailResponse | null>(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  // 原片可播直链：走「素材原文件」口（自有桶 presigned）——share 页链接（weixin.qq.com/sph/…）
  // 直接喂 <video> 是黑屏，这就是上一版"原片无法播放"的原因
  const [inspectPlayUrl, setInspectPlayUrl] = useState<string | null>(null);
  const [inspectPlayNote, setInspectPlayNote] = useState<string | null>(null);
  const openInspect = async (row: AssetSummary) => {
    setInspecting(row);
    setInspectData(null);
    setInspectPlayUrl(null);
    setInspectPlayNote(null);
    setInspectLoading(true);
    try {
      const [detail, src] = await Promise.all([
        assetApi.getAsset(row.asset_id),
        assetApi.downloadAssetSource(row.asset_id).catch(() => null),
      ]);
      setInspectData(detail);
      if (src?.url) {
        setInspectPlayUrl(src.url);
      } else {
        setInspectPlayNote(
          src?.note
            ? `${src.note}。本条没有可播的原片：纯文案导入无原片（凭文案形态与风险词判定即可），外链素材可去「② 素材与文案」的详情抽屉里看原片`
            : '这条素材不在自有桶（外链导入），拿不到可播直链——核验凭文案与详情页信息判断即可',
        );
      }
    } catch (e) {
      message.error((e as Error).message || '取素材详情失败');
    } finally {
      setInspectLoading(false);
    }
  };

  // 批次下拉：原来只有一个「批次 ID」输入框，要手填 UUID，填 AB- 编号会一条都查不到
  const [batches, setBatches] = useState<AssetBatch[]>([]);
  // 风险词库抽屉
  const [lexiconOpen, setLexiconOpen] = useState(false);

  const loadBatches = useCallback(async () => {
    try {
      const res = await assetApi.listBatches({ limit: 100 });
      setBatches(res.items || []);
    } catch {
      /* 批次下拉拿不到不影响审核，忽略 */
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  // 批 M（评审一·P1-3）：fetchList 请求序号守卫——筛选变更与 reloadToken 重拉并发时，
  // 慢的新筛选回包可能被旧的覆盖。与生产单面板同一套模式（模块级自增序号）。
  const listReqRef = React.useRef(0);
  // 拉当前页候选的试产单（试产角标＋判定按钮的数据源）
  const fetchTrialProds = useCallback(async (summaryIds: string[]) => {
    if (!summaryIds.length) {
      setTrialProds({});
      return;
    }
    try {
      const res = await assetApi.listProductions({ summary_ids: summaryIds.join(','), page_size: 100 });
      const bySummary: Record<string, { id: string; status: string; error?: string | null }[]> = {};
      (res.items || []).forEach((p) => {
        if (!p.is_trial) return;
        (bySummary[p.summary_id] = bySummary[p.summary_id] || []).push({
          id: p.id, status: p.status, error: p.error,
        });
      });
      setTrialProds(bySummary);
    } catch {
      /* 试产角标失败静默——主列表不因此卡住 */
    }
  }, []);

  const fetchList = useCallback(
    async (p: number = page, ps: number = pageSize) => {
      const reqId = ++listReqRef.current;
      setLoading(true);
      try {
        const res = await assetApi.listSummaries({
          page: p,
          page_size: ps,
          audit_status: auditStatus,
          recommended_only: recommendedOnly,
          only_risk: onlyRisk,
          only_inconsistent: onlyInconsistent,
          only_resubmittable: onlyMine,
          batch_id: batchFilter,
          category_id: categoryFilter,
          q: keyword.trim() || undefined,
          owner: ownerView,
        });
        if (reqId !== listReqRef.current) return; // 已有更新的请求在途，旧回包作废
        setData(res);
        void fetchTrialProds((res.items || []).map((s) => s.id));
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(res.page || p);
      } catch (e) {
        if (reqId === listReqRef.current) message.error((e as Error).message || '加载审核队列失败');
      } finally {
        if (reqId === listReqRef.current) setLoading(false);
      }
    },
    [auditStatus, recommendedOnly, onlyRisk, onlyInconsistent, onlyMine, batchFilter, categoryFilter, keyword, ownerView, page, pageSize],
  );

  // 2026-11-13 流畅性席 P0：搜索框逐键触发全量重拉（每键 2 请求+表格闪一次）。
  // 输入态即时、查询态 400ms 防抖。
  const [keywordInput, setKeywordInput] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setKeyword(keywordInput.trim()), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keywordInput]);

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditStatus, recommendedOnly, onlyRisk, onlyInconsistent, onlyMine, batchFilter, categoryFilter, keyword, ownerView]);

  // 后台出文案任务跑完（D-1）：新候选不在前端内存里，只能重新拉
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

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);

  /**
   * 卡片左边的三帧（批 F）：整页素材一次批量取，同素材的多条候选共用一份。
   * 直链 1 小时过期，所以跟着列表走——不缓存翻页前的旧直链。
   */
  const itemAssetIds = useMemo(() => items.map((i) => i.asset_id), [items]);
  const { slots: frameSlots, loading: framesLoading } = useAssetFrames(itemAssetIds);

  /** 批次下拉选项：编号 + 名称 + 条数，比让人手填 UUID 强得多。 */
  const batchOptions = useMemo(() => {
    const opts = batches.map((b) => ({
      value: b.id,
      label: `${b.code} · ${b.name || '未命名'}（${b.item_count ?? 0} 条）`,
    }));
    // 从别处带进来的批次 id（可能已超出最近 100 批）：补一条，别在下拉里显示成一串裸 uuid
    if (batchFilter && !opts.some((o) => o.value === batchFilter)) {
      opts.unshift({ value: batchFilter, label: `当前批次 ${batchFilter.slice(0, 8)}…` });
    }
    return opts;
  }, [batches, batchFilter]);

  /**
   * 提交一次审核动作。
   * `suppressWaive` 是豁免重放时用的：那一次已经把拦下原因展示过了，不必再弹窗。
   */
  const runReview = async (
    action: AssetReviewAction,
    opts: {
      reason?: string;
      new_text?: string;
      waive_reason?: string;
      waive_codes?: string[];
      summaryIds?: string[];
    } = {},
    // 2026-11-11 评审（前端席 P1）：调用方需要知道审核**到底成没成**——submitEdited
    // 原来 await 完就顺手改分类+报成功，复核被拦时「文案没过、原型已改、提示说都提交了」。
    // 返回 {ok, blocked}；早退（没选条/缺理由）与抛错回 null。
  ): Promise<{ ok: number; blocked: number } | null> => {
    const targetIds = opts.summaryIds || ids;
    if (!targetIds.length) {
      message.warning('先勾选要处理的文案');
      return null;
    }
    if ((action === 'reject' || action === 'need_rewrite') && !(opts.reason || '').trim()) {
      message.warning('驳回 / 要求改写必须填理由');
      return null;
    }
    setBusy(true);
    try {
      const res = await assetApi.reviewSummaries({
        summary_ids: targetIds,
        action,
        reason: opts.reason,
        new_text: opts.new_text,
        waive_reason: opts.waive_reason,
        waive_codes: opts.waive_codes,
      });
      const blocked = (res.results || []).filter(
        (r) => !r.ok && r.error_code === 'ASSET_RECHECK_FAILED',
      );
      const failed = (res.results || []).filter((r) => !r.ok && r.error_code !== 'ASSET_RECHECK_FAILED');
      if (blocked.length && !opts.waive_reason) {
        setWaiveFor(blocked);
        setWaiveReason('');
        // 默认全勾＝整条放过（老行为）；管理员想只放一部分就取消勾选
        setWaiveCodes(unionCodes(blocked));
      }
      if (failed.length) {
        Modal.warning({
          title: `${failed.length} 条没改动成功`,
          width: 620,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              {failed.slice(0, 12).map((f) => (
                <Text key={f.summary_id} style={{ fontSize: 12 }}>
                  {f.code || f.summary_id.slice(0, 8)}：{f.error}
                </Text>
              ))}
              <Text type="secondary" style={{ fontSize: 12 }}>
                常见原因：写文案的人不能审自己写的文案（管理员除外）、这条已被别人过审（要同素材请重出文案）、素材已归档。
              </Text>
            </Space>
          ),
        });
      }
      // R-6：「和原视频对不上」不拦过审，但要**看得见**——过审成功也弹黄色提示，
      // 否则留痕列变红却没人解释，反而更像出故障。
      const warned = (res.results || []).filter((r) => r.ok && (r.warnings || []).length);
      if (!failed.length && !blocked.length && !warned.length) message.success(res.message);
      else if (!blocked.length) message.warning(res.message, 8);
      // 11-05 易操作性评估 P0-2：审完的条目会**从当前视图消失**——状态筛选还停在
      // 「等审核」，卡片一刷新就不见了；过审的还是非推荐条时，「推荐条」范围会把它
      // 二次藏住（实测要把状态和范围两个筛选都切过才找得回来）。这里只在「当前筛选
      // 确实会把刚处理的条藏掉」时补一句去哪了，平时不加噪音。
      const okCount = (res.results || []).filter((r) => r.ok).length;
      const afterStatus: Record<string, string> = {
        approve: 'approved',
        reject: 'rejected',
        need_rewrite: 'need_rewrite',
        pass_edited: 'passed_edited',
      };
      const target = afterStatus[action];
      // AUDIT_STATUS_LABELS 的键类型是 AuditStatus，这里 action 已映射成合法值；
      // 放宽成 Record<string,string> 取标签，免得 string 索引过不了 tsc -b。
      const labelMap = AUDIT_STATUS_LABELS as Record<string, string>;
      const targetLabel = labelMap[target] ?? target;
      const hints: string[] = [];
      if (okCount > 0 && target && auditStatus && auditStatus !== target) {
        hints.push(
          `这 ${okCount} 条现在已是「${targetLabel}」，会被当前状态筛选藏住——状态切到「${targetLabel}」能再看到`,
        );
      }
      if (action === 'approve' && scope === 'recommended') {
        // 11-06 P2：非推荐统计改吃**审核响应逐条带回的 is_recommended**（后端真话），
        // 不再数当前页 items——豁免重放时目标行可能已经不在当前页（fetchList 回第 1 页
        // 或状态筛选藏掉），按当前页数会漏报「其实会被藏住」。
        const nonRec = (res.results || []).filter(
          (r) => r.ok && r.is_recommended === false,
        ).length;
        if (nonRec) {
          hints.push(
            `其中 ${nonRec} 条不是推荐条，「推荐条」范围也会把它们藏住——范围切「全部」才看得到`,
          );
        }
      }
      if (hints.length) message.info(hints.join('；'), 10);
      setSelected([]);
      // 2026-11-13 流畅性席 P2：审完停在当前页——翻到第 3 页审完弹回第 1 页很烦人
      fetchList(page, pageSize);
      // 2026-11-11 评审（审核席 P1）：审完角标立即重拉，别等 20s 轮询跳变
      window.dispatchEvent(new Event('asset-badges-refresh'));
      return { ok: okCount, blocked: blocked.length };
    } catch (e) {
      message.error((e as Error).message || '审核提交失败');
      return null;
    } finally {
      setBusy(false);
    }
  };

  /**
   * 批量给勾选的文案点钩子原型（0 元、不花钱，所以不过成本确认单）。
   * 留空提交＝清成未分类；后端如实回 not_found，这里必须念出来，
   * 不能让人以为「点了 5 条都改好了」其实库里只剩 3 条。
   */
  const applyCategory = async () => {
    if (!ids.length) {
      message.warning('先勾选要点原型的文案');
      return;
    }
    setBusy(true);
    try {
      const res = await assetApi.assignCategory({ summary_ids: ids, category_id: assignTo || null });
      const name = assignTo ? cats.byId[assignTo]?.name || '该原型' : '未分类';
      (res.notes || []).forEach((n) => message.info(n));
      if (res.not_found?.length) {
        Modal.warning({
          title: `有 ${res.not_found.length} 条没点到「${name}」`,
          width: 600,
          content: (
            <Space direction="vertical" size={4}>
              <Text>改成功 {res.summary_changed} 条；下面这些 id 库里查不到（可能被撤审重出时作废了），没有被改动：</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {res.not_found.slice(0, 12).join('，')}
                {res.not_found.length > 12 ? ` 等 ${res.not_found.length} 条` : ''}
              </Text>
            </Space>
          ),
        });
      } else {
        message.success(
          res.summary_changed
            ? `已把 ${res.summary_changed} 条文案点成「${name}」`
            : `勾选的文案本来就是「${name}」，没有改动`,
        );
      }
      invalidateAssetCategories();
      setSelected([]);
      fetchList(page, pageSize);
    } catch (e) {
      message.error((e as Error).message || '点原型失败');
    } finally {
      setBusy(false);
    }
  };

  /**
   * 批 N（评审二 P2）：单卡驳回不再悄悄清空批量勾选——原来先 setSelected([row])
   * 再走批量通道，用户勾好的一批被静默替换掉。这里把目标行**显式传参**，勾选不动。
   */
  const askReason = (action: 'reject' | 'need_rewrite', rows?: AssetSummary[]) => {
    const target = rows ?? selected;
    const targetIds = target.map((s) => s.id);
    if (!targetIds.length) {
      message.warning('先勾选要处理的文案');
      return;
    }
    let reason = '';
    Modal.confirm({
      title:
        action === 'reject'
          ? `驳回 ${targetIds.length} 条（必填理由）`
          : `标记 ${targetIds.length} 条要求改写（必填理由）`,
      width: 520,
      content: (
        <Input.TextArea
          rows={3}
          placeholder="写清楚为什么不行：钩子不成立 / 与画面不符 / 风险表述…（驳回理由会显示给写文案的人）"
          onChange={(e) => {
            reason = e.target.value;
          }}
        />
      ),
      okText: '提交',
      onOk: () => {
        if (!reason.trim()) {
          message.warning('理由不能为空');
          return Promise.reject();
        }
        return runReview(action, { reason: reason.trim(), summaryIds: targetIds });
      },
    });
  };

  // ── 试产（2026-11-12 用户口径）：改提示词投豆包 → 看片 → 定稿/废片，不打回采集 ──
  // 2026-11-13 修正（用户质询「审核时都没预览，试产意义何在」）：prompt_preview 是
  // 过审后才备的，待审条目正是试产的主角——当场走 prompt-web 起草（该口不看审核态，
  // 一次模型调用、费用自动记账），起草完回填可编辑；绝不支人先去点「过」。
  const [trialDrafting, setTrialDrafting] = useState('');
  // ── 试产对比判定视图（2026-11-13 用户质询「试产回来的素材怎么展现、和原片怎么对比」）：
  // 左＝原片（一致性对照），右＝试产片，下＝所用提示词＋候选文案，底部＝定稿/废片
  const [trialView, setTrialView] = useState<{
    prodId: string; row: AssetSummary; promptText?: string | null;
  } | null>(null);
  const [trialVideoUrl, setTrialVideoUrl] = useState('');
  const [trialSourceUrl, setTrialSourceUrl] = useState('');
  const [trialViewNote, setTrialViewNote] = useState('');
  const [trialViewBusy, setTrialViewBusy] = useState(false);
  const openTrial = async (row: AssetSummary) => {
    setTrialFor(row);
    setTrialPrompt('');
    const pre = (row as unknown as { prompt_preview?: string | null }).prompt_preview
      || (row as unknown as { doubao_prompt?: string | null }).doubao_prompt || '';
    if (pre.trim()) {
      setTrialPrompt(pre);
      setTrialDrafting('');
      return;
    }
    setTrialDrafting('正在按稿子起草豆包提示词（一次模型调用，费用自动记账）…');
    try {
      const res = await assetApi.promptWebSummaries({ summary_ids: [row.id] });
      const r0 = (res.results || [])[0] as { error?: string } | undefined;
      if (r0?.error) {
        setTrialDrafting(`起草被拦：${r0.error}——可直接在框里手写`);
        return;
      }
      const fresh = await assetApi.listSummaries({ ids: row.id, page_size: 1 });
      const s0 = (fresh.items || [])[0];
      const text = s0?.doubao_prompt || s0?.prompt_preview || '';
      if (text.trim()) {
        setTrialPrompt(text);
        setTrialDrafting('');
        // 回写本地行：卡片上的「提示词未备」下次也拿得到
        setData((prev) =>
          prev ? { ...prev, items: prev.items.map((x) => (x.id === row.id ? { ...x, doubao_prompt: text } : x)) } : prev,
        );
      } else {
        setTrialDrafting('没起草出来（模型没回可用正文）——可直接在框里手写');
      }
    } catch (e) {
      setTrialDrafting(`起草失败：${(e as Error).message}——可直接在框里手写`);
    }
  };

  const openTrialView = async (prodId: string, row: AssetSummary, promptText?: string | null) => {
    setTrialView({ prodId, row, promptText });
    setTrialVideoUrl('');
    setTrialSourceUrl('');
    setTrialViewNote('');
    setTrialViewBusy(true);
    try {
      const [outs, srcRes] = await Promise.all([
        assetApi.listOutputs({ production_id: prodId, limit: 5 }),
        assetApi.downloadAssetSource(row.asset_id).catch(() => null),
      ]);
      const o = (outs.items || [])[0];
      if (o) {
        const pv = await assetApi.previewOutput(o.id);
        setTrialVideoUrl(pv.url);
      } else {
        setTrialViewNote('试产片还没回收到：板上还在出（任务条报进度），回收后这里就能播');
      }
      if (srcRes?.url) setTrialSourceUrl(srcRes.url);
      else if (srcRes?.note) setTrialViewNote((n) => (n ? n + '；' : '') + `原片取不到直链：${srcRes.note}`);
    } catch (e) {
      setTrialViewNote(`打开失败：${(e as Error).message}`);
    } finally {
      setTrialViewBusy(false);
    }
  };

  const submitTrial = async () => {
    if (!trialFor) return;
    if (!trialPrompt.trim()) {
      message.warning('提示词不能为空——试产投的就是这一段');
      return;
    }
    setTrialBusy(true);
    setTrialStep('① 建单中（复核＋取号，几秒）…');
    try {
      // ① 建单：走正常投产口（async_mode=false 拿同步回执拿 ids），1 条 × 1 版
      const res = await assetApi.produce({
        summary_ids: [trialFor.id],
        trial: true,
        // 投给豆包的就是这一段（审核员改过的），行上落 prompt_text 供判定与再迭代
        prompt_text: trialPrompt.trim(),
        n: 1,
        board_total: 1,
        hook_codes: [],
        async_mode: false,
      });
      const pr = res as { production_ids?: string[]; results?: Array<{ ok?: boolean; error?: string | null }>;
        recheck_failed?: Array<{ error?: string }>; warnings?: string[] };
      const pid = (pr.production_ids || [])[0];
      if (!pid) {
        const why = pr.recheck_failed?.[0]?.error || pr.results?.[0]?.error || pr.warnings?.[0]
          || '建单没成功（回包里没有生产单 id）';
        message.error(`试产建单被拦：${why}`, 8);
        return;
      }
      // ② 投板：trial_only=true（成片只回审核台）；提示词已在建单时落行
      setTrialStep('② 投板上板中…');
      const ack = await assetApi.dispatchProductions({
        ids: [pid],
        confirm: true,
        async_mode: true,
        trial_only: true,
      });
      // 2026-11-13 用户口径「任务发出去之后就把对话框关掉，别一直转圈」：
      // ack＝任务已受理，窗口立刻缩掉；卡片状态由下方乐观插入＋fetchList 接管
      const ackJob = (ack as { job_id?: string }).job_id;
      setTrialProds((prev) => ({
        ...prev,
        [trialFor.id]: [
          ...(prev[trialFor.id] || []),
          { id: pid, status: 'queued', error: null, prompt_text: trialPrompt.trim() },
        ],
      }));
      setTrialFor(null);
      message.success(
        `试产已投出去${ackJob ? '（任务受理）' : ''}：豆包出片约 25 分钟——这条卡上会亮「试产中」，片回来自动变判定按钮`,
        10,
      );
      void fetchTrialProds([trialFor.id]);
    } catch (e) {
      message.error((e as Error).message || '试产没投出去（原因见报错）', 8);
    } finally {
      setTrialBusy(false);
      setTrialStep('');
    }
  };

  const submitVerdict = (productionId: string, verdict: 'pass' | 'fail') => {
    let note = '';
    Modal.confirm({
      title: verdict === 'pass' ? '定稿：这条文案过审？' : '记废片：提示词没达预期？',
      width: 560,
      content: (
        <Input.TextArea
          rows={2}
          placeholder={verdict === 'pass' ? '判定说明（可选）' : '差在哪（建议写清：节奏/画面/换词没生效…会进审计）'}
          onChange={(e) => { note = e.target.value; }}
        />
      ),
      okText: verdict === 'pass' ? '定稿过审' : '记废片',
      okType: verdict === 'pass' ? 'primary' : 'danger',
      onOk: async () => {
        try {
          const res = await assetApi.trialVerdict(productionId, verdict, note.trim() || undefined);
          message.success(res.message, 8);
          fetchList(page, pageSize);
        } catch (e) {
          message.error((e as Error).message || '判定没成功');
        }
      },
    });
  };

  const submitEdited = async () => {
    if (!editing) return;
    if (!editText.trim()) {
      message.warning('改后文案不能为空');
      return;
    }
    const target = editCat || null;
    const changedCat = target !== (editing.category_id || null);
    const r = await runReview('pass_edited', { summaryIds: [editing.id], new_text: editText.trim() });
    // 分类是另一件事：过审若被复核拦下会弹窗，那时不顺手改分类，避免「以为过了其实没」
    // 2026-11-11 评审（前端席 P1）：这里真的接住返回值——原来 await 完无条件改分类，
    // 拦下时库里状态没动、原型却改了，提示还说「文字与原型都已提交」。
    if (r === null || r.blocked > 0) {
      if (changedCat) {
        message.warning(
          r === null
            ? '这次「改后过」没提交成功，文字与原型都未改动'
            : '复核被拦，文字按拦下结果处理、分类未动',
        );
      }
      setEditing(null);
      setEditCat(undefined);
      return;
    }
    if (changedCat) {
      try {
        const res = await assetApi.assignCategory({ summary_ids: [editing.id], category_id: target });
        if (res.not_found?.length) message.warning('文字已提交，但这条文案已不在库里，分类没改成');
        else if (!res.summary_changed) message.info('文字已提交；分类没有变化');
        else message.success('文字与原型都已提交（原型改动留档）');
        invalidateAssetCategories();
      } catch (e) {
        message.error(`文字已按上面结果处理，但改原型失败：${(e as Error).message}`);
      }
    }
    setEditing(null);
    setEditCat(undefined);
  };

  /**
   * 改后重新提审：驳回/需改写之后，文案作者（素材负责人）把文案改了交回待审队列。
   * 与「改后过」的区别：**改后过是审核人自己改、自己过**（一步到位）；
   * 这里是**作者改、审核人再审一遍**（两方都在场，留痕进审计）。
   */
  const submitResubmit = async () => {
    if (!resubmitFor) return;
    if (!resubmitText.trim()) {
      message.warning('文案不能为空');
      return;
    }
    setBusy(true);
    try {
      const res = await assetApi.resubmitSummaries({
        summary_ids: [resubmitFor.id],
        new_text: resubmitText.trim(),
        note: resubmitNote.trim() || null,
      });
      const failed = (res.results || []).filter((r) => !r.ok);
      if (failed.length) {
        Modal.error({
          title: '没能重新提审',
          content: (
            <Space direction="vertical" size={4}>
              {failed.map((f) => (
                <div key={f.summary_id}>
                  {f.code ? `${f.code}：` : ''}
                  {f.error}
                  {(f.problems || []).length > 0 && (
                    <Space wrap size={4} style={{ marginTop: 4 }}>
                      {(f.problems || []).map((p, i) => (
                        <Tag key={`${p.code}-${i}`}>
                          {RECHECK_CODE_LABELS[p.code] || p.code}｜{p.message}
                        </Tag>
                      ))}
                    </Space>
                  )}
                </div>
              ))}
            </Space>
          ),
        });
        return;
      }
      // R-6：提审成功但带预警（和原视频对不上）时说人话给人听，别让人以为已经全绿
      const warn = (res.results || []).find((r) => r.ok && (r.warnings || []).length);
      message.success(
        warn
          ? `已交回待审队列。提示：${warn.warnings?.map((p) => p.message).join('；')}——不拦提审，但审核人会看到`
          : '已交回待审队列，等审核人再过一遍',
        warn ? 8 : 3,
      );
      setResubmitFor(null);
      setResubmitText('');
      setResubmitNote('');
      fetchList(1, pageSize);
    } catch (e) {
      message.error((e as Error).message || '重新提审失败');
    } finally {
      setBusy(false);
    }
  };

  const columns: ColumnsType<AssetSummary> = [
    {
      // 批 F：一行＝一张卡片（左三帧｜中文案｜右徽标+操作）。
      // 表格列还留着——rowSelection / 分页 / loading 都靠它，只把"列"合成一格。
      key: 'card',
      render: (_, r) => (
        <AssetReviewCard
          row={r}
          slot={frameSlots[r.asset_id]}
          framesLoading={framesLoading}
          canReview={canReview}
          busy={busy}
          onApprove={(row) => runReview('approve', { summaryIds: [row.id] })}
          onEdit={(row) => {
            setEditing(row);
            setEditText(row.text);
            setEditCat(row.category_id || undefined);
          }}
          onReject={(row) => {
            // 批 N（评审二 P2）：显式传行，不动批量勾选（原实现会 setSelected([row]) 清掉整批）
            askReason('reject', [row]);
          }}
          onResubmit={(row) => {
            setResubmitFor(row);
            setResubmitText(row.text);
            setResubmitNote('');
          }}
          onInspect={(row) => void openInspect(row)}
          onTrial={canReview ? (row) => void openTrial(row) : undefined}
          trialProds={trialProds[r.id]}
          onVerdict={canReview ? submitVerdict : undefined}
          onCompare={canReview ? (pid, r2, pt) => void openTrialView(pid, r2, pt) : undefined}
        />
      ),
    },
  ];

  const approvedSelected = selected.filter((s) => s.audit_status === 'approved' || s.audit_status === 'passed_edited');

  return (
    /*
      排版口径（#110）：筛选行与批量按钮行**都放卡片体里全宽分行**，
      不再塞 Card 的 title/extra——卡片头是同行 flex，title 被按钮列挤窄后
      Segmented 会折到「怎么用」底下重叠。行序固定：
      ① 筛选行（怎么用＋全部筛器） ② 批量动作行 ③ 欠账提示 ④ 点原型行 ⑤ 卡片列表。
    */
    <Card size="small">
      {/* ① 筛选行：高频与低频筛器合一整行，放不下整行顺延换行 */}
      <Space wrap size={8} style={{ marginBottom: 12 }}>
        <Popover
          placement="bottomLeft"
          title="审核台怎么用"
          content={
            <div style={{ maxWidth: 380 }}>
              <p style={{ marginBottom: 6 }}>
                一条素材默认只出 <strong>1 条</strong>候选文案（浓缩一句话）。出多条时模型会标 1 条推荐，
                审核台默认只把推荐条摆到你面前——多条全勾一遍过，等于没审。
              </p>
              <p style={{ marginBottom: 6 }}>
                <strong>卡片左边</strong>是这条原片抽的三帧（第 10%／45%／80%，不取第一帧：开头常是黑边或台标），
                点一下看九宫格。图由后台抽帧任务补，<strong>没图不影响审核</strong>，也不参与任何判定。
              </p>
              <p style={{ marginBottom: 6 }}>
                <strong>过审</strong>：这条就是要拿去投板的文案。过审前会先自动查一遍（超字数／命中违禁词／和原视频对不上都会被拦），
                拦下时可让管理员带理由放行，放行记录会留档。
              </p>
              <p style={{ marginBottom: 6 }}>
                <strong>驳回／要求改写</strong>：必须写理由，理由会显示给写文案的人。
              </p>
              <p style={{ marginBottom: 6 }}>
                <strong>驳回之后怎么办</strong>：写文案的人（这条素材的负责人）在行上点
                <strong>「改后重提」</strong>，把文案改了交回待审队列，审核人再过一遍——
                改前改后都留档。审核人也可以自己点<strong>「改后过」</strong>直接改直接过（一步到位）。
              </p>
              <p style={{ marginBottom: 6 }}>
                <strong>生成生产单</strong>：只认已过审的文案，把过审文案变成要投出去的一条条提示词，一条派生几条不同写法。
              </p>
              <p style={{ marginBottom: 0 }}>各筛选项的说明在它们右边的问号里。</p>
            </div>
          }
        >
          <Button type="link" size="small" style={{ padding: 0 }}>
            怎么用 <QuestionCircleOutlined />
          </Button>
        </Popover>
        <Tooltip title="按审核状态筛：等审核／已过审／已驳回／要求改写／改后通过。清空＝所有状态都列出来。">
          <span>
            <Select
              style={{ width: 130 }}
              placeholder="审核状态"
              allowClear
              value={auditStatus}
              onChange={setAuditStatus}
              options={Object.entries(AUDIT_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
            />
            <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
          </span>
        </Tooltip>
        <Tooltip
          title={
            <div style={{ maxWidth: 340 }}>
              <div><strong>推荐条</strong>：出了多条候选时，模型标 1 条推荐。默认只看它，是为了防止全部勾一遍走过场。</div>
              <div><strong>命中违禁词</strong>：命中违禁词的候选。红色「不许用」＝过不了审、也出不了生产单；橙色「要注意」＝只留个提醒。</div>
              <div><strong>和原视频对不上</strong>：文案里的人物/场景/事件在反推文案稿里找不到的候选，通常要人工改或重新出。</div>
              <div><strong>全部</strong>：所有候选都列出来，用来看对照。</div>
              <div style={{ marginTop: 4 }}>这四个是互斥的：一次只看一类。</div>
            </div>
          }
        >
          <span>
            <Segmented
              size="small"
              value={scope}
              onChange={(v) => setScope(v as typeof scope)}
              options={[
                { label: '推荐条', value: 'recommended' },
                { label: '命中违禁词', value: 'risk' },
                { label: '和原视频对不上', value: 'inconsistent' },
                { label: '全部', value: 'all' },
              ]}
            />
            <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
          </span>
        </Tooltip>
        <Tooltip title="被驳回/要求改写且我负责的素材；开启会清掉「审核状态」筛选。">
          <span>
            <Button
              size="small"
              type={onlyMine ? 'primary' : 'default'}
              icon={<SendOutlined />}
              onClick={() => {
                const next = !onlyMine;
                setOnlyMine(next);
                if (next) setAuditStatus(undefined);
              }}
            >
              等我改的
            </Button>
            <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
          </span>
        </Tooltip>
        <Tooltip title="按导入批次筛选。选批次即可，会显示批次编号、名称和条数。">
          <span>
            <Select
              style={{ width: 220 }}
              placeholder="批次（可选）"
              popupMatchSelectWidth={false}
              allowClear
              showSearch
              optionFilterProp="label"
              value={batchFilter}
              onChange={setBatchFilter}
              options={batchOptions}
            />
            <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
          </span>
        </Tooltip>
        <Tooltip
          title={
            <div style={{ maxWidth: 340 }}>
              <div>
                <strong>钩子原型</strong>＝这条文案的开头套路（A–G，名字照《钩子模版换皮参数设定.docx》）。
                出稿时从素材继承，之后素材重新归类<strong>不会回写</strong>已出的候选。
              </div>
              <div style={{ marginTop: 4 }}>
                它和上面那四个范围（推荐条／命中违禁词／和原视频对不上／全部）是两个轴，可以叠加：
                比如「推荐条 + 原型 A」。
              </div>
              <div style={{ marginTop: 4 }}>
                「未分类」是清欠账用的：现在文案侧还有 {cats.unclassified.copy_count} 条没点原型。
                字典本身的名称与说明在页面顶部「钩子原型字典」里改（仅管理员）。
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
        <Tooltip title="查看／修改违禁词表（审核台「自动检查」列那些标签的来源）。只有管理员能改。">
          <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => setLexiconOpen(true)}>
            违禁词表
          </Button>
        </Tooltip>
        {/* A′ 按运营隔离：纯查询偏好——me=已过审区只显自己过审的，pending 照旧共享 */}
        {canReview && (
          <Segmented
            size="small"
            value={ownerView}
            onChange={(v) => setOwnerView(v as 'me' | 'all')}
            options={[
              { label: '我质检的', value: 'me' },
              { label: '全部', value: 'all' },
            ]}
          />
        )}
        {/* 批 N（评审二 P1）：关键词搜索（正文/素材码）——筛出空集时有自己找回目标的正路 */}
        <Tooltip title="按正文或素材码搜（子串匹配，与其它筛选叠加）。清空＝不限。">
          <Input.Search
            placeholder="搜正文/素材码"
            allowClear
            style={{ width: 190 }}
            value={keyword}
            onChange={(e) => setKeywordInput(e.target.value)}
          />
        </Tooltip>
        <Button icon={<ReloadOutlined />} onClick={() => fetchList(page, pageSize)}>
          刷新
        </Button>
        {/* 11-13 用户口径「流程很多人看不懂」：试产六步动画引导，常驻入口 */}
        <Tooltip title="60 秒动画：试产怎么发起、窗口为什么自己关、片回来在哪看、怎么定稿/废片">
          <Button icon={<ThunderboltOutlined style={{ color: '#722ed1' }} />} onClick={() => setGuideOpen(true)}>
            试产怎么用
          </Button>
        </Tooltip>
        <Tooltip title="60 秒动画：只看推荐条防橡皮章、判定标签怎么读、过/改后过/驳、撤销的连带影响">
          <Button icon={<QuestionCircleOutlined style={{ color: '#722ed1' }} />} onClick={() => setHowOpen(true)}>
            审核怎么用
          </Button>
        </Tooltip>
      </Space>
      {/* ② 批量动作行：勾选后的审核动作都在这一行，位置固定不随筛选换行跳动 */}
      {canReview ? (
        <Space wrap size={8} style={{ marginBottom: 12 }}>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={busy}
            disabled={!ids.length}
            onClick={() => {
              // 批 N（评审二·P1-3）：批量过审加确认预告——几十条一把过、误触即成事实，
              // 撤销过审还要连带作废未投的生产单。单卡的「过」保持一步到位不设卡。
              if (ids.length > 1) {
                Modal.confirm({
                  title: `批量通过 ${ids.length} 条？`,
                  width: 520,
                  content: '自动检查会先拦一道（超字数/违禁词/对不上）；过审后要撤销会连带作废未投的生产单。',
                  
                  okText: `通过这 ${ids.length} 条`,
                  cancelText: '再看看',
                  onOk: () => runReview('approve'),
                });
              } else {
                runReview('approve');
              }
            }}
          >
            批量通过（{ids.length}）
          </Button>
          <Button icon={<CloseCircleOutlined />} disabled={!ids.length} onClick={() => askReason('reject')}>
            驳回（{ids.length}）
          </Button>
          <Button disabled={!ids.length} onClick={() => askReason('need_rewrite')}>
            要求改写（{ids.length}）
          </Button>
          {canReview && canProduce && (
            <Tooltip title="把过审文案变成一条条要投的提示词；括号只算已过审/改后通过的条，勾了待审核数字不变；素材专员不能开单。">
              <Button
                icon={<ThunderboltOutlined />}
                disabled={!approvedSelected.length}
                onClick={() => setProduceOpen(true)}
              >
                生成生产单（{approvedSelected.length}）· 即投产
              </Button>
            </Tooltip>
          )}
        </Space>
      ) : (
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          当前账号不能审核：需要运营/管理员角色、且审核（质检）职能已开启——职能被关的找管理员在用户管理里开通
        </Text>
      )}
      {!!data && recommendedOnly && auditStatus === 'pending' && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message="默认只列推荐条——全勾一遍等于没审；要看对照切「全部」"
        />
      )}
      {/* 同素材列表：批量点原型放表头上方，别挤 Card 的 extra，否则那一排筛选会换行 */}
      {canReview && (
        <Space size={8} wrap style={{ marginBottom: 8 }}>
          <Tooltip
            title={
              <div style={{ maxWidth: 320 }}>
                <div>给勾选的文案点钩子原型（开头套路标记，0 元，不拦过审也不拦任何步骤）。</div>
                <div style={{ marginTop: 4 }}>
                  下拉清空再应用＝把选中的改回「未分类」。已经开过生产单的文案改原型<strong>不会</strong>改动已生成的提示词。
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
                loading={cats.loading}
              />
              <Button loading={busy} disabled={!ids.length} onClick={applyCategory}>
                应用（{ids.length}）
              </Button>
            </Space.Compact>
          </Tooltip>
          {cats.unclassified.copy_count > 0 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {cats.unclassified.copy_count} 条未点原型
            </Text>
          )}
        </Space>
      )}
      <Table<AssetSummary>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        // 批 N（评审二 P1）：空集必须给指路——原来只画「暂无数据」，一线只能对着空表
        // 猜是筛选配错了还是真没活。
        locale={{
          emptyText: (
            <div style={{ padding: '24px 0', textAlign: 'center', color: '#666', fontSize: 12 }}>
              筛得太窄就清一清上面的筛器（或切「全部」）；还没出文案就回「素材列表」点「出钩子文案」。
            </div>
          ),
        }}
        // 卡片行不需要表头解释自己：一行就是一张卡，列名反而成了噪声（徽标含义在「怎么用」里）
        showHeader={false}
        rowSelection={
          canReview
            ? { selectedRowKeys: ids, onChange: (_, rows) => setSelected(rows) }
            : undefined
        }
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条候选`,
          onChange: (p, ps) => {
            setPageSize(ps);
            fetchList(p, ps);
          },
        }}
      />

      <Modal
        open={!!editing}
        title="改后通过（改前原文会留档，管理员可抽查）"
        onCancel={() => setEditing(null)}
        onOk={submitEdited}
        okText="提交改后通过"
        confirmLoading={busy}
        width={680}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            改后的文案就是最终投出去的那一条：你在这里审的是文字，生产单用的也是这段文字，别在这里换内容。
          </Text>
          <Input.TextArea rows={8} value={editText} onChange={(e) => setEditText(e.target.value)} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {editText.trim().length} 字
          </Text>
          <Space align="center" wrap>
            <Text style={{ fontSize: 12 }}>钩子原型：</Text>
            <CategorySelect
              items={cats.activeItems}
              value={editCat}
              onChange={setEditCat}
              width={230}
              loading={cats.loading}
              placeholder="选原型（清空＝改成未分类）"
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              打开时已带出出稿时继承的原型，<strong>和它不一样才会提交改动</strong>；改完留档。原型本身不拦过审。
            </Text>
          </Space>
        </Space>
      </Modal>

      <Modal
        open={!!resubmitFor}
        title="改后重新提审（交回待审队列）"
        onCancel={() => setResubmitFor(null)}
        onOk={submitResubmit}
        okText="交回待审"
        confirmLoading={busy}
        width={680}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {resubmitFor?.reject_reason && (
            <Alert
              type="warning"
              showIcon
              message="审核人给的驳回理由"
              description={resubmitFor.reject_reason}
            />
          )}
          <Text type="secondary" style={{ fontSize: 12 }}>
            改完点「交回待审」，这条就回到待审队列，审核人会再过一遍。
            改前原文和改后文案都会留档，管理员可抽查。
            超字数、命中违禁词（不许用）的文案当场就提不上去，先改干净。
          </Text>
          <Input.TextArea rows={8} value={resubmitText} onChange={(e) => setResubmitText(e.target.value)} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {resubmitText.trim().length} 字
          </Text>
          <Input
            placeholder="给审核人的说明（可选，会留档）：比如「按建议把钩子改成疑问句」"
            value={resubmitNote}
            onChange={(e) => setResubmitNote(e.target.value)}
          />
        </Space>
      </Modal>

      <Modal
        open={!!waiveFor}
        title="自动检查没通过"
        onCancel={() => setWaiveFor(null)}
        okText={isAdmin ? '带放行理由通过' : '知道了'}
        // 至少要放行一类：全取消勾选＝一类都不放，那这次放行没有意义，
        // 而且空数组会被后端当成「整条全放过」（兼容旧行为），绝不能由误操作触发
        okButtonProps={{ disabled: !isAdmin || !waiveReason.trim() || !waiveCodes.length }}
        onOk={async () => {
          if (!isAdmin || !waiveFor) return;
          const targetIds = waiveFor.map((w) => w.summary_id);
          setWaiveFor(null);
          await runReview('approve', {
            summaryIds: targetIds,
            waive_reason: waiveReason.trim(),
            waive_codes: waiveCodes,
          });
        }}
        width={640}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {(waiveFor || []).slice(0, 10).map((w) => (
            <Alert
              key={w.summary_id}
              type="warning"
              showIcon
              message={`${w.code || w.summary_id.slice(0, 8)}：${w.error}`}
              description={
                <Space wrap size={4}>
                  {(w.problems || []).map((p, i) => (
                    <Tag key={`${p.code}-${i}`}>
                      {RECHECK_CODE_LABELS[p.code] || p.code}｜{p.message}
                    </Tag>
                  ))}
                </Space>
              }
            />
          ))}
          {isAdmin ? (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>
                管理员放行 = 你确认这些拦点是误报或可以接受。理由会逐条留档，可事后抽查追溯。
              </Text>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Text style={{ fontSize: 12 }}>这次放行哪几类问题（不放行的那类仍然拦着）：</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  想只放掉字数、把违禁词继续卡住，就取消对应的勾——一句理由全放行的老做法会连真违禁词一起带走。
                </Text>
                <Checkbox.Group
                  value={waiveCodes}
                  onChange={(v) => setWaiveCodes(v as string[])}
                  options={unionCodes(waiveFor || []).map((c) => ({
                    label: RECHECK_CODE_LABELS[c] || c,
                    value: c,
                  }))}
                />
              </Space>
              <Input.TextArea
                rows={3}
                placeholder="放行理由（必填）"
                value={waiveReason}
                onChange={(e) => setWaiveReason(e.target.value)}
              />
            </>
          ) : (
            <Alert type="info" showIcon message="只有管理员可以为检查不过的文案放行" />
          )}
        </Space>
      </Modal>

      {/* ── 试产弹窗（2026-11-12 用户口径）：改提示词 → 投豆包 → 看片定稿，不打回采集 ── */}
      <Modal
        open={!!trialFor}
        title={`试产：${trialFor?.asset_code || ''}（第 ${trialFor?.seq ?? 1} 条候选）`}
        width={720}
        confirmLoading={trialBusy}
        onCancel={() => { if (!trialBusy) setTrialFor(null); }}
        okText="投豆包试产（占 1 个号池额度）"
        okButtonProps={{ disabled: !!trialDrafting.startsWith('正在') }}
        onOk={submitTrial}
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="下面这一段就是要投给豆包的提示词——直接改，改完点确认投出去。成片约 25 分钟回到这条卡上，看完「定稿」（文案过审）或「废片」（文案留原态，改词再来一轮），不用打回采集人重提。"
            description={
              <Button type="link" size="small" style={{ padding: 0, height: 'auto' }} onClick={() => setGuideOpen(true)}>
                ▶ 没试过？看 60 秒动画「试产怎么用」
              </Button>
            }
          />
          {!!trialDrafting && (
            <Alert
              type={trialDrafting.startsWith('正在') ? 'info' : 'warning'}
              showIcon
              message={trialDrafting}
            />
          )}
          {!trialPrompt.trim() && !trialDrafting && (
            <Alert
              type="warning"
              showIcon
              message="框里现在是空的：可直接手写，或关掉重开一次（会重新起草）。"
            />
          )}
          {trialStep && (
            <Alert type="info" showIcon message={trialStep} />
          )}
          <Input.TextArea
            rows={10}
            value={trialPrompt}
            onChange={(e) => setTrialPrompt(e.target.value)}
            placeholder="投给豆包的提示词（可自由编辑）"
            style={{ fontFamily: 'monospace', fontSize: 12 }}
          />
        </Space>
      </Modal>

      {/* ── 试产对比判定视图（2026-11-13）：左原片｜右试产片｜下提示词与判定 ── */}
      <Modal
        open={!!trialView}
        title={`试产判定：${trialView?.row.asset_code || ''}（第 ${trialView?.row.seq ?? 1} 条候选）`}
        width={1080}
        footer={[
          <Button key="close" onClick={() => setTrialView(null)}>关闭</Button>,
          <Button key="fail" danger onClick={() => { const t = trialView; setTrialView(null); if (t) submitVerdict(t.prodId, 'fail'); }}>
            废片（改词再试一轮）
          </Button>,
          <Button key="pass" type="primary" onClick={() => { const t = trialView; setTrialView(null); if (t) submitVerdict(t.prodId, 'pass'); }}>
            定稿（文案过审）
          </Button>,
        ]}
        onCancel={() => setTrialView(null)}
      >
        {trialView && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {trialViewBusy && <Alert type="info" showIcon message="正在取片…" />}
            {!!trialViewNote && <Alert type="warning" showIcon message={trialViewNote} />}
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text strong style={{ fontSize: 12 }}>原片（一致性对照）</Text>
                {trialSourceUrl ? (
                  <video src={trialSourceUrl} controls preload="metadata"
                    style={{ width: '100%', maxHeight: 380, background: '#000', borderRadius: 8, marginTop: 4 }} />
                ) : (
                  <div style={{ width: '100%', height: 200, background: '#f5f5f5', borderRadius: 8, marginTop: 4,
                    display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {(trialView.row as unknown as { stage_import?: string }).stage_import === 'skipped'
                        ? '贴文案导入无原片'
                        : '原片直链没取到（过期关掉重开会续）'}
                    </Text>
                  </div>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text strong style={{ fontSize: 12 }}>试产片（本轮提示词的产出）</Text>
                {trialVideoUrl ? (
                  <video src={trialVideoUrl} controls autoPlay preload="metadata"
                    style={{ width: '100%', maxHeight: 380, background: '#000', borderRadius: 8, marginTop: 4 }} />
                ) : (
                  <div style={{ width: '100%', height: 200, background: '#f5f5f5', borderRadius: 8, marginTop: 4,
                    display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {trialViewNote.includes('还没回收') ? '等回收后重开' : '取片中…'}
                    </Text>
                  </div>
                )}
              </div>
            </div>
            {!!trialView.promptText && (
              <Card size="small" title="本轮投给豆包的提示词（改词再试时以此为基础）">
                <Paragraph style={{ marginBottom: 0, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 160, overflow: 'auto' }}>
                  {trialView.promptText}
                </Paragraph>
              </Card>
            )}
            <Card size="small" title="候选文案（第 1 手素材，对照画面是否拍出了钩子）">
              <Paragraph style={{ marginBottom: 0, fontSize: 13, whiteSpace: 'pre-wrap' }}>
                {trialView.row.text}
              </Paragraph>
            </Card>
          </Space>
        )}
      </Modal>

      <ProduceOrderModal
        open={produceOpen}
        summaries={approvedSelected}
        onClose={() => setProduceOpen(false)}
        isAdmin={isAdmin}
        batchId={batchId}
        onDone={() => {
          setProduceOpen(false);
          setSelected([]);
          fetchList(page, pageSize);
          // 批 N（评审二·P0-2）：按钮叫「去生产单列表」就得真带人过去——
          // 原来只关弹窗刷自己，新单在哪要用户自己猜。
          onGoToProduction?.();
        }}
        onProduced={
          onProduced
            ? (ids, notes) => {
                // 11-10 一屏到底：建完单直接把人带到 ④ 的「投去 AI 出片」那一屏
                setProduceOpen(false);
                setSelected([]);
                fetchList(page, pageSize);
                onProduced(ids, notes);
              }
            : undefined
        }
      />

      {/* P1（评审定稿⑨）：一致性核验抽屉——签字依据给足：原片播放＋反推脚本全文 */}
      <Drawer
        title={inspecting ? `核验：${inspecting.asset_code || inspecting.asset_id.slice(0, 8)}` : ''}
        width={720}
        open={!!inspecting}
        onClose={() => setInspecting(null)}
      >
        {inspecting && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {/* 2026-11-11 评审（前端席 P2）：抽屉原来一上来就是原片＋反推稿，
                「正在审的到底是哪句」要滚回卡片去看。这里把候选文案钉在顶部（只读，
                改动仍在卡片上做），对照着核才不用两头翻页。 */}
            <Card
              size="small"
              title={`正在核验的候选文案（第 ${inspecting.seq} 条，只读）`}
              style={{ background: '#f6ffed', borderColor: '#b7eb8f' }}
            >
              <Paragraph style={{ marginBottom: 0, fontSize: 13, whiteSpace: 'pre-wrap' }}>
                {inspecting.text}
              </Paragraph>
            </Card>
            {inspectPlayUrl ? (
              <video
                src={inspectPlayUrl}
                controls
                autoPlay
                preload="metadata"
                style={{ width: '100%', maxHeight: 380, background: '#000', borderRadius: 8 }}
                onError={() =>
                  setInspectPlayNote('这一段放不出来：直链可能已过期（时效链接约 1 小时），关掉重开即可续期')
                }
              />
            ) : inspectPlayNote ? (
              <Alert type="info" showIcon message={inspectPlayNote} />
            ) : null}
            {inspectLoading ? (
              <div style={{ padding: 24, textAlign: 'center' }}>
                <Spin />
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    正在取反推文案稿…
                  </Text>
                </div>
              </div>
            ) : inspectData?.prompt_script ? (
              <Card size="small" title="反推文案稿">
                <Paragraph
                  style={{ marginBottom: 0, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 360, overflow: 'auto' }}
                >
                  {inspectData.prompt_script}
                </Paragraph>
              </Card>
            ) : (
              <Text type="secondary">还没有反推文案稿。</Text>
            )}
          </Space>
        )}
      </Drawer>
      <RiskLexiconDrawer open={lexiconOpen} onClose={() => setLexiconOpen(false)} />
      {/* 11-13：试产六步动画引导（从工具条按钮或试产弹窗内链接打开） */}
      <TrialProduceGuide open={guideOpen} onClose={() => setGuideOpen(false)} />
      <ReviewGuide open={howOpen} onClose={() => setHowOpen(false)} />
    </Card>
  );
};

export default AssetReviewPanel;
