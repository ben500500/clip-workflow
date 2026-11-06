import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Input, Modal, Popover, Segmented, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined,
  ReloadOutlined, SafetyCertificateOutlined, SendOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { AUDIT_STATUS_LABELS, RECHECK_CODE_LABELS, assetApi } from '../../api/assets';
import type {
  AssetBatch, AssetReviewAction, AssetReviewResultItem, AssetSummary, AssetSummaryListResult,
} from '../../api/assets';
import {
  CategorySelect, invalidateAssetCategories, useAssetCategories,
} from './AssetCategoryBits';
import { useAssetFrames } from './AssetFrameBits';
import AssetReviewCard from './AssetReviewCard';
import ProduceOrderModal from './ProduceOrderModal';
import RiskLexiconDrawer from './RiskLexiconDrawer';

const { Text } = Typography;

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
  isAdmin: boolean;
  batchId?: string;
  /** 后台出文案任务收敛后自增（D-1）：新候选是后端落库的，只能重新拉一次才看得到 */
  reloadToken?: number;
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
const AssetReviewPanel: React.FC<Props> = ({ canReview, isAdmin, batchId, reloadToken }) => {
  const [data, setData] = useState<AssetSummaryListResult | null>(null);
  const [items, setItems] = useState<AssetSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const [auditStatus, setAuditStatus] = useState<string | undefined>('pending');
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

  const fetchList = useCallback(
    async (p: number = page, ps: number = pageSize) => {
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
        });
        setData(res);
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(res.page || p);
      } catch (e) {
        message.error((e as Error).message || '加载审核队列失败');
      } finally {
        setLoading(false);
      }
    },
    [auditStatus, recommendedOnly, onlyRisk, onlyInconsistent, onlyMine, batchFilter, categoryFilter, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditStatus, recommendedOnly, onlyRisk, onlyInconsistent, onlyMine, batchFilter, categoryFilter]);

  // 后台出文案任务跑完（D-1）：新候选不在前端内存里，只能重新拉
  useEffect(() => {
    if (!reloadToken) return;
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

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
  ) => {
    const targetIds = opts.summaryIds || ids;
    if (!targetIds.length) {
      message.warning('先勾选要处理的文案');
      return;
    }
    if ((action === 'reject' || action === 'need_rewrite') && !(opts.reason || '').trim()) {
      message.warning('驳回 / 要求改写必须填理由');
      return;
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
                常见原因：写文案的人不能审自己写的文案（管理员除外）、同一批被别人抢先处理了、素材已归档。
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
      fetchList(1, pageSize);
    } catch (e) {
      message.error((e as Error).message || '审核提交失败');
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

  const askReason = (action: 'reject' | 'need_rewrite') => {
    if (!ids.length) {
      message.warning('先勾选要处理的文案');
      return;
    }
    let reason = '';
    Modal.confirm({
      title: action === 'reject' ? `驳回 ${ids.length} 条（必填理由）` : `标记 ${ids.length} 条要求改写（必填理由）`,
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
        return runReview(action, { reason: reason.trim() });
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
    await runReview('pass_edited', { summaryIds: [editing.id], new_text: editText.trim() });
    // 分类是另一件事：过审若被复核拦下会弹窗，那时不顺手改分类，避免「以为过了其实没」
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
            setSelected([row]);
            askReason('reject');
          }}
          onResubmit={(row) => {
            setResubmitFor(row);
            setResubmitText(row.text);
            setResubmitNote('');
          }}
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
                <strong>过审</strong>：这条就是要拿去投放的文案。过审前会先自动查一遍（超字数／命中违禁词／和原视频对不上都会被拦），
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
        <Button icon={<ReloadOutlined />} onClick={() => fetchList(page, pageSize)}>
          刷新
        </Button>
      </Space>
      {/* ② 批量动作行：勾选后的审核动作都在这一行，位置固定不随筛选换行跳动 */}
      {canReview ? (
        <Space wrap size={8} style={{ marginBottom: 12 }}>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={busy}
            disabled={!ids.length}
            onClick={() => runReview('approve')}
          >
            批量通过（{ids.length}）
          </Button>
          <Button icon={<CloseCircleOutlined />} disabled={!ids.length} onClick={() => askReason('reject')}>
            驳回（{ids.length}）
          </Button>
          <Button disabled={!ids.length} onClick={() => askReason('need_rewrite')}>
            要求改写（{ids.length}）
          </Button>
          {canReview && (
            <Tooltip title="把过审文案变成一条条要投的提示词（括号只算已过审的）；素材专员不能开单。">
              <Button
                icon={<ThunderboltOutlined />}
                disabled={!approvedSelected.length}
                onClick={() => setProduceOpen(true)}
              >
                生成生产单（{approvedSelected.length}）· 即投产
              </Button>
            </Tooltip>
          )}
          {canReview && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              N 只数已过审/改后通过的条；勾了待审核的数字不变
            </Text>
          )}
        </Space>
      ) : (
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          当前角色只读：审核与生成生产单需要运营或管理员
        </Text>
      )}
      {!!data && recommendedOnly && auditStatus === 'pending' && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message="默认只列每条素材的推荐候选"
          description="一条素材默认只出 1 条候选；出了多条时通常只有一条能钩人，全勾一遍等于没审。要看对照请把筛选切到「全部」。"
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
          <Text type="secondary" style={{ fontSize: 12 }}>
            文案侧还有 {cats.unclassified.copy_count} 条没点原型；出稿时本来会从素材继承，这里只补漏。
          </Text>
        </Space>
      )}
      <Table<AssetSummary>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
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

      <ProduceOrderModal
        open={produceOpen}
        summaries={approvedSelected}
        onClose={() => setProduceOpen(false)}
        isAdmin={isAdmin}
        onDone={() => {
          setProduceOpen(false);
          setSelected([]);
          fetchList(page, pageSize);
        }}
      />

      <RiskLexiconDrawer open={lexiconOpen} onClose={() => setLexiconOpen(false)} />
    </Card>
  );
};

export default AssetReviewPanel;
