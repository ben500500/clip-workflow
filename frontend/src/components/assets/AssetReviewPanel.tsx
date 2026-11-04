import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Input, Modal, Popover, Segmented, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, EditOutlined, QuestionCircleOutlined,
  ReloadOutlined, SafetyCertificateOutlined, SendOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { AUDIT_STATUS_LABELS, HOOK_STYLE_LABELS, assetApi } from '../../api/assets';
import type {
  AssetBatch, AssetReviewAction, AssetReviewResultItem, AssetSummary, AssetSummaryListResult,
} from '../../api/assets';
import { AuditStatusTag, RiskTags } from './AssetBits';
import ProduceOrderModal from './ProduceOrderModal';
import RiskLexiconDrawer from './RiskLexiconDrawer';

const { Text, Paragraph } = Typography;

interface Props {
  /** operator + admin 才能审；素材专员只读（后端还会挡「生产者不得自审」） */
  canReview: boolean;
  isAdmin: boolean;
  batchId?: string;
}

/**
 * 文案审核台。
 *
 * 默认勾「只看推荐条」是方案 §七 的防橡皮章设计：三条候选里通常只有一条能钩人，
 * 全勾一遍＝把审核变成点按钮。风险词（block 级）与一致性不过会被复核挡下，
 * admin 可以带 `waive_reason` 豁免——豁免的每一条都进 AuditLog，可抽检。
 * 撤销过审会连带作废这条文案下**还没投出去**的生产单，所以撤销动作单独走一次确认。
 */
const AssetReviewPanel: React.FC<Props> = ({ canReview, isAdmin, batchId }) => {
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
   * 之前是三个独立勾选框，能同时勾，勾出来的是「推荐条 且 命中风险词 且 一致性不过」
   * 的交集——又窄又没人看得懂。现在用单选：
   *   recommended 只看推荐条（默认，防橡皮章）／risk 只看命中风险词／
   *   inconsistent 只看一致性不过／all 全部候选都列出来
   */
  const [scope, setScope] = useState<'recommended' | 'risk' | 'inconsistent' | 'all'>('recommended');
  const recommendedOnly = scope === 'recommended';
  const onlyRisk = scope === 'risk';
  const onlyInconsistent = scope === 'inconsistent';
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  /** 「等我改的」：只看被驳回/需改写、且轮到我改的条目（驳回闭环的入口） */
  const [onlyMine, setOnlyMine] = useState(false);

  const [selected, setSelected] = useState<AssetSummary[]>([]);
  const [editing, setEditing] = useState<AssetSummary | null>(null);
  const [editText, setEditText] = useState('');

  // 改后重新提审（驳回后由文案作者改完交回队列）
  const [resubmitFor, setResubmitFor] = useState<AssetSummary | null>(null);
  const [resubmitText, setResubmitText] = useState('');
  const [resubmitNote, setResubmitNote] = useState('');

  // 复核拦下后的豁免弹窗
  const [waiveFor, setWaiveFor] = useState<AssetReviewResultItem[] | null>(null);
  const [waiveReason, setWaiveReason] = useState('');

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
    [auditStatus, recommendedOnly, onlyRisk, onlyInconsistent, onlyMine, batchFilter, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditStatus, recommendedOnly, onlyRisk, onlyInconsistent, onlyMine, batchFilter]);

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);

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
    opts: { reason?: string; new_text?: string; waive_reason?: string; summaryIds?: string[] } = {},
  ) => {
    const targetIds = opts.summaryIds || ids;
    if (!targetIds.length) {
      message.warning('先勾选要处理的文案');
      return;
    }
    if ((action === 'reject' || action === 'need_rewrite') && !(opts.reason || '').trim()) {
      message.warning('驳回 / 需改写必须填理由');
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
      });
      const blocked = (res.results || []).filter(
        (r) => !r.ok && r.error_code === 'ASSET_RECHECK_FAILED',
      );
      const failed = (res.results || []).filter((r) => !r.ok && r.error_code !== 'ASSET_RECHECK_FAILED');
      if (blocked.length && !opts.waive_reason) {
        setWaiveFor(blocked);
        setWaiveReason('');
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
                常见成因：生产者不能审自己产的东西（admin 除外）、并发下已被他人处理、素材已归档。
              </Text>
            </Space>
          ),
        });
      }
      if (!failed.length && !blocked.length) message.success(res.message);
      else if (!blocked.length) message.warning(res.message);
      setSelected([]);
      fetchList(1, pageSize);
    } catch (e) {
      message.error((e as Error).message || '审核提交失败');
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
      title: action === 'reject' ? `驳回 ${ids.length} 条（必填理由）` : `${ids.length} 条标记需改写（必填理由）`,
      width: 520,
      content: (
        <Input.TextArea
          rows={3}
          placeholder="写清楚为什么不行：钩子不成立 / 与画面不符 / 风险表述…（驳回理由会回显给生产者）"
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
    await runReview('pass_edited', { summaryIds: [editing.id], new_text: editText.trim() });
    setEditing(null);
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
                          {p.code}｜{p.message}
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
      message.success('已交回待审队列，等审核人再过一遍');
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
      title: '素材',
      key: 'asset',
      width: 180,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Tag>{r.asset_code || r.asset_id.slice(0, 8)}</Tag>
          <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
            {r.asset_title || '（无标题）'}
          </Text>
        </Space>
      ),
    },
    {
      title: '候选',
      key: 'seq',
      width: 70,
      render: (_, r) => (
        <Space size={2}>
          <Text>#{r.seq}</Text>
          {r.is_recommended && <Tag color="green">推荐</Tag>}
        </Space>
      ),
    },
    {
      title: '文案',
      dataIndex: 'text',
      render: (v: string, r) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>
            {v}
          </Paragraph>
          {r.text_before_edit && (
            <Tooltip title={`改前原文：${r.text_before_edit}`}>
              <Tag color="cyan">
                {r.audit_status === 'approved' || r.audit_status === 'passed_edited' ? '改后通过' : '改过并重提'}
              </Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '字数',
      dataIndex: 'word_count',
      width: 62,
      render: (v: number | null) => v ?? '-',
    },
    {
      title: '风格 / 公式',
      key: 'tags',
      width: 140,
      render: (_, r) => (
        <Space size={2} wrap>
          {r.style_tag && <Tag>{HOOK_STYLE_LABELS[r.style_tag] || r.style_tag}</Tag>}
          {r.formula_tag && <Tag color="geekblue">{r.formula_tag}</Tag>}
        </Space>
      ),
    },
    {
      title: '复核',
      key: 'check',
      width: 150,
      render: (_, r) => (
        <Space direction="vertical" size={2}>
          <RiskTags riskHit={r.risk_hit} />
          {r.consistency_ok === false ? (
            <Tooltip title={r.consistency_note || ''}>
              <Tag color="orange">一致性不过</Tag>
            </Tooltip>
          ) : r.consistency_ok === true ? (
            <Tag color="green">一致性 ok</Tag>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              未校验
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'audit_status',
      width: 92,
      render: (v: AssetSummary['audit_status'], r) => (
        <Tooltip title={r.reject_reason ? `理由：${r.reject_reason}` : undefined}>
          <span>
            <AuditStatusTag status={v} />
          </span>
        </Tooltip>
      ),
    },
    ...(canReview || items.some((r) => r.can_resubmit)
      ? [
          {
            title: '操作',
            key: 'op',
            width: 230,
            fixed: 'right' as const,
            render: (_: unknown, r: AssetSummary) => (
              <Space size={2}>
                {r.can_resubmit && (
                  <Tooltip title="把文案改了交回待审队列，等审核人再过一遍（改前改后都进审计）">
                    <Button
                      size="small"
                      icon={<SendOutlined />}
                      loading={busy}
                      onClick={() => {
                        setResubmitFor(r);
                        setResubmitText(r.text);
                        setResubmitNote('');
                      }}
                    >
                      改后重提
                    </Button>
                  </Tooltip>
                )}
                {canReview && (
                  <>
                    <Tooltip title="生产者不能审自己产的东西（admin 除外）">
                      <Button
                        size="small"
                        type="primary"
                        icon={<CheckCircleOutlined />}
                        loading={busy}
                        onClick={() => runReview('approve', { summaryIds: [r.id] })}
                      >
                        过
                      </Button>
                    </Tooltip>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => {
                        setEditing(r);
                        setEditText(r.text);
                      }}
                    >
                      改后过
                    </Button>
                    <Button size="small" icon={<CloseCircleOutlined />} onClick={() => {
                      setSelected([r]);
                      askReason('reject');
                    }}>
                      驳
                    </Button>
                  </>
                )}
              </Space>
            ),
          },
        ]
      : []),
  ];

  const approvedSelected = selected.filter((s) => s.audit_status === 'approved' || s.audit_status === 'passed_edited');

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <Popover
            placement="bottomLeft"
            title="审核台怎么用"
            content={
              <div style={{ maxWidth: 380 }}>
                <p style={{ marginBottom: 6 }}>
                  一条素材出 3 条候选文案，其中 1 条被模型标为推荐。审核台默认只把推荐条摆到你面前——
                  3 条全勾一遍过，等于没审。
                </p>
                <p style={{ marginBottom: 6 }}>
                  <strong>过审</strong>：这条就是要投豆包的那条。会先跑一遍复核（超字数／命中风险词／与详规对不上都会被拦），
                  拦下时可让管理员带理由豁免，豁免内容进审计。
                </p>
                <p style={{ marginBottom: 6 }}>
                  <strong>驳回／需改写</strong>：必须写理由，理由会回显给写文案的人。
                </p>
                <p style={{ marginBottom: 6 }}>
                  <strong>驳回之后怎么办</strong>：写文案的人（这条素材的负责人）在行上点
                  <strong>「改后重提」</strong>，把文案改了交回待审队列，审核人再过一遍——
                  改前改后都进审计。审核人也可以自己点<strong>「改后过」</strong>直接改直接过（一步到位）。
                </p>
                <p style={{ marginBottom: 6 }}>
                  <strong>投产</strong>：只吃已过审的文案，一条过审文案派生 N 条差异化提示词。
                </p>
                <p style={{ marginBottom: 0 }}>各筛选项的说明在它们右边的问号里。</p>
              </div>
            }
          >
            <Button type="link" size="small" style={{ padding: 0 }}>
              怎么用 <QuestionCircleOutlined />
            </Button>
          </Popover>
          <Tooltip title="按审核状态筛：待审／已过审／已驳回／需改写／改后通过。清空＝所有状态都列出来。">
            <span>
              <Select
                style={{ width: 130 }}
                placeholder="审核态"
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
                <div><strong>推荐条</strong>：每条素材出 3 条候选，模型标 1 条推荐。默认只看它，是为了防止 3 条全勾一遍走过场。</div>
                <div><strong>命中风险</strong>：命中风险词的候选。红色「拦」＝不许过审、不许投产；橙色「警」＝只留痕。</div>
                <div><strong>一致性不过</strong>：与反推详规对不上的候选（实体没命中），通常要人工改或重新出。</div>
                <div><strong>全部</strong>：3 条候选都列出来，用来看对照。</div>
                <div style={{ marginTop: 4 }}>这四个是**互斥**的：一次只看一类。</div>
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
                  { label: '命中风险', value: 'risk' },
                  { label: '一致性不过', value: 'inconsistent' },
                  { label: '全部', value: 'all' },
                ]}
              />
              <QuestionCircleOutlined style={{ marginLeft: 2, color: '#999' }} />
            </span>
          </Tooltip>
          <Tooltip title="只看轮到我改的：被驳回 / 需改写、且是我负责的素材。开启后会清掉「审核态」筛选（否则两边互相打架）。点行上的「改后重提」把文案改了交回待审队列。">
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
          <Tooltip title="查看／修改风险词库（审核台「复核」列那些标签的来源）。只有管理员能改。">
            <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => setLexiconOpen(true)}>
              风险词库
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => fetchList(page, pageSize)}>
            刷新
          </Button>
        </Space>
      }
      extra={
        canReview ? (
          <Space wrap>
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
              需改写（{ids.length}）
            </Button>
            {canReview && (
              <Tooltip title="过审文案 → N 条差异化提示词（投产与审核同侧：material 不能开单）。括号里的数字只算勾选行里已过审/改后通过的那些，待审的不算。">
                <Button
                  icon={<ThunderboltOutlined />}
                  disabled={!approvedSelected.length}
                  onClick={() => setProduceOpen(true)}
                >
                  投产（{approvedSelected.length}）
                </Button>
              </Tooltip>
            )}
          </Space>
        ) : (
          <Text type="secondary">当前角色只读：审核与投产需运营（operator）或管理员</Text>
        )
      }
    >
      {!!data && recommendedOnly && auditStatus === 'pending' && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message="默认只列每条素材的推荐候选"
          description="三条候选里通常只有一条能钩人，全勾一遍等于没审。要看对照请取消勾选「只看推荐条」。"
        />
      )}
      <Table<AssetSummary>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1250 }}
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
        title="改后通过（原文会留痕，admin 可抽检）"
        onCancel={() => setEditing(null)}
        onOk={submitEdited}
        okText="提交改后通过"
        confirmLoading={busy}
        width={680}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            改后的文案就是最终投产的那一条：审核的是文字，生产的也是文字，别在这里改口径。
          </Text>
          <Input.TextArea rows={8} value={editText} onChange={(e) => setEditText(e.target.value)} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {editText.trim().length} 字
          </Text>
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
            改前原文和改后文案都会进审计，admin 可抽检。
            超字数、命中拦级风险词的文案**当场就提不上去**，先改干净。
          </Text>
          <Input.TextArea rows={8} value={resubmitText} onChange={(e) => setResubmitText(e.target.value)} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {resubmitText.trim().length} 字
          </Text>
          <Input
            placeholder="给审核人的说明（可选，会进审计）：比如「按建议把钩子改成疑问句」"
            value={resubmitNote}
            onChange={(e) => setResubmitNote(e.target.value)}
          />
        </Space>
      </Modal>

      <Modal
        open={!!waiveFor}
        title="复核未过"
        onCancel={() => setWaiveFor(null)}
        okText={isAdmin ? '带豁免理由通过' : '知道了'}
        okButtonProps={{ disabled: !isAdmin || !waiveReason.trim() }}
        onOk={async () => {
          if (!isAdmin || !waiveFor) return;
          const targetIds = waiveFor.map((w) => w.summary_id);
          setWaiveFor(null);
          await runReview('approve', { summaryIds: targetIds, waive_reason: waiveReason.trim() });
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
                      {p.code}｜{p.message}
                    </Tag>
                  ))}
                </Space>
              }
            />
          ))}
          {isAdmin ? (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>
                豁免 = 你确认这些拦点是误报或可接受。理由会逐条写进 AuditLog，admin 可抽检回溯。
              </Text>
              <Input.TextArea
                rows={3}
                placeholder="豁免理由（必填）"
                value={waiveReason}
                onChange={(e) => setWaiveReason(e.target.value)}
              />
            </>
          ) : (
            <Alert type="info" showIcon message="只有管理员可以豁免复核不过的文案" />
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
