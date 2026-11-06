import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Checkbox, Descriptions, Input, Modal, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { DEFAULT_TIER, RECHECK_CODE_LABELS, assetApi, isAssetJobAck, waitForAssetJob } from '../../api/assets';
import type { AssetProduceResponse, AssetSummary } from '../../api/assets';
import { HOOK_CODE_RE, MonoText, parseHookCodes } from './AssetBits';
import AssetCardPicker from './AssetCardPicker';
import { nudgeAssetJobBanner } from './AssetJobBanner';
import { withCrossPersonConfirm } from './crossPerson';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  /** 只有「已过审 / 改后通过」的文案能进这里（后端也会挡） */
  summaries: AssetSummary[];
  isAdmin: boolean;
  onClose: () => void;
  /** 建单成功后回主面板（切到生产单页签）。produce 的响应里**没有**新单 id 列表
   *  （只有 created/results），所以只能让父面板自己去列表。 */
  onDone: () => void;
  /**
   * 批 L：就地上传角色卡挂的批次（=被投产素材所在批次）。可选——
   * 生产单页「全部」视图开单时拿不到，就由上传口新建小批次。
   */
  batchId?: string;
}

/**
 * 投产：过审文案 → N 条差异化提示词（生产单）。
 *
 * 三个量必须分开，混了就白烧号池：
 *  - `n`：一条文案派生几份**差异化**提示词（＝几个任务）；
 *  - `board_total`：板上 total＝同一条提示词出几版；
 *  - 真实投放量 = 文案数 × n × board_total。
 * 号池实测 ≈120 条/日，产能不做硬限（11-03 拍板），但建单当场就把「今天已经吃掉多少」摆出来。
 * 钩子编号只能从 hook_id.py 取号带进来，前端不生成、后端不编号。
 */
const ProduceOrderModal: React.FC<Props> = ({ open, summaries, isAdmin, onClose, onDone, batchId }) => {
  const [n, setN] = useState(3);
  const [boardTotal, setBoardTotal] = useState(1);
  const [accounts, setAccounts] = useState(1);
  const [titleCount, setTitleCount] = useState<number | undefined>(undefined);
  const [boardTag, setBoardTag] = useState('');
  /**
   * 批 G：角色卡改成「从素材库挑」，这里存的是 asset_items.id 数组，
   * **顺序＝板上 picDatas 顺序**。旧的那个手填 MinIO key 的框已经删掉——
   * 那个值被后端原样当 key 用，打错一个字符照样建单，只是投出去是一条没卡的片。
   */
  const [cardIds, setCardIds] = useState<string[]>([]);
  const [dramaAbbr, setDramaAbbr] = useState('');
  const [codeText, setCodeText] = useState('');
  /**
   * 11-06 拍板③：填了号就查哪些已经被钉在生产单上（GET /assets/hook-codes/used）。
   * 回显是软提醒（打字过程中尽力而为），提交时后端还有一道硬查重兜底——
   * 号一发就烧掉，作废单也不复用，所以这里查到的直接拦提交。
   */
  const [usedCodes, setUsedCodes] = useState<
    { code: string; asset_code: string; seq: number; status: string }[]
  >([]);
  const usedReqRef = useRef(0);
  const [expand, setExpand] = useState(true);
  const [waiveReason, setWaiveReason] = useState('');
  /**
   * R-6 分粒度：上一次自动检查拦下的问题类型（union）。管理员默认全放行＝整条放过，
   * 想只放一类（例如只放字数、把违禁词继续卡住）就取消勾选。空列表＝这次不放行任何一类，
   * 所以提交时不带 waive_codes（后端把留空当整条放过，绝不能由「全取消」误触发）。
   */
  const [waiveCodes, setWaiveCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssetProduceResponse | null>(null);
  /**
   * D-1：投产（expand=true）要按 n 逐条调模型，一批几分钟到十几分钟，
   * 同步等会一路撞上浏览器/nginx 超时。现在提交即回任务号，这里**边轮询边把状态显示出来**；
   * 人中途关掉窗口也安全——任务在后台照跑，顶部横幅和生产单列表会接住结果。
   */
  const [jobHint, setJobHint] = useState<string | null>(null);
  const giveUpRef = useRef(false);

  // 批 I（链路收敛）：投产成功后顺势投板——不用再回生产单列表勾一遍。
  // 逐批人工确认的口径不放松：这里也要勾一下确认才投得出去。
  const [followupConfirm, setFollowupConfirm] = useState(false);
  const [followupBusy, setFollowupBusy] = useState(false);

  const dispatchFollowup = async () => {
    const ids = (result?.production_ids || []).filter(Boolean);
    if (!ids.length) return;
    if (!followupConfirm) {
      message.warning('勾一下确认：投出去吃的是当天号池额度，这一下只能由人点');
      return;
    }
    setFollowupBusy(true);
    try {
      const res = await withCrossPersonConfirm((c) =>
        assetApi.dispatchProductions({
          ids,
          confirm: true,
          async_mode: true,
          cross_person_confirm: c,
        }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做
      nudgeAssetJobBanner();
      if (isAssetJobAck(res)) {
        const pre = (res as { precheck?: { will_create: number; will_recover: number; blocked?: unknown[]; planned_board_rows: number } }).precheck;
        Modal.success({
          title: '已经排上：机器去企微后台建任务出片',
          content: (
            <Text style={{ fontSize: 12 }}>
              新建 {pre?.will_create ?? '—'} 张、回收 {pre?.will_recover ?? 0} 张（≈{pre?.planned_board_rows ?? '—'} 条额度）
              {pre?.blocked?.length ? `；${pre.blocked.length} 张被闸门挡下没投` : ''}。
              出好的片子自动回到生产单页各单的「成片」列，可以关页面去干别的。
            </Text>
          ),
        });
      } else {
        message.success('已经排上：机器去企微后台建任务出片，成片自动回「成片」列');
      }
      setResult(null);
      onDone();
    } catch (e) {
      // 没配凭据/闸门拦截等，后端给的是白话 detail，原样亮出来
      message.error((e as Error).message || '投板失败', 8);
    } finally {
      setFollowupBusy(false);
    }
  };

  const needCodes = summaries.length * n;
  const codes = useMemo(() => parseHookCodes(codeText), [codeText]);
  const badCodes = codes.filter((c) => !HOOK_CODE_RE.test(c));
  const dupCodes = codes.length !== new Set(codes).size;
  const plannedRows = summaries.length * n * boardTotal;

  // 11-06 拍板③：500ms 防抖查已用号（不逐键打接口）；请求序号防乱序回包。
  // 回显失败静默——提交时后端硬查重还在，别因为一个回显口把填单卡死。
  useEffect(() => {
    if (!open || !codes.length) {
      setUsedCodes([]);
      return;
    }
    const reqId = ++usedReqRef.current;
    const timer = setTimeout(async () => {
      try {
        const res = await assetApi.hookCodesUsed(codes);
        if (usedReqRef.current === reqId) setUsedCodes(res.used);
      } catch {
        /* 尽力而为 */
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [open, codes]);

  /** 自动检查拦下的问题类型回填到表单，回到表单就能按类只放行一部分（R-6 分粒度） */
  const collectRecheckCodes = (res: AssetProduceResponse) => {
    const seen: string[] = [];
    (res.recheck_failed || []).forEach((f) =>
      (f.problems || []).forEach((p) => !seen.includes(p.code) && seen.push(p.code)),
    );
    if (seen.length) setWaiveCodes(seen);
  };

  const submit = async () => {
    if (!summaries.length) {
      message.warning('没有已过审的文案');
      return;
    }
    if (badCodes.length) {
      message.error(`钩子编号不对：${badCodes.slice(0, 3).join('、')}（必须是五位 0-9/A-Z，从取号工具 hook_id.py 拿，不能自己编）`);
      return;
    }
    if (dupCodes) {
      message.error('钩子编号重复：一个编号只能用在一条上');
      return;
    }
    if (usedCodes.length) {
      message.error(
        `这些编号已经被用掉了：${usedCodes.slice(0, 3).map((u) => u.code).join('、')}（一钩一号，回 hook_id.py 重新取号）`,
        8,
      );
      return;
    }
    setBusy(true);
    giveUpRef.current = false;
    try {
      const res = await assetApi.produce({
        summary_ids: summaries.map((s) => s.id),
        n,
        board_total: boardTotal,
        accounts,
        recommended_title_count: titleCount,
        board_tag: boardTag || undefined,
        card_asset_ids: cardIds.length ? cardIds : undefined,
        drama_abbr: dramaAbbr.trim() || undefined,
        hook_codes: codes.length ? codes : undefined,
        expand,
        waive_reason: waiveReason || undefined,
        waive_codes: waiveCodes.length ? waiveCodes : undefined,
        async_mode: true,
      });
      if (isAssetJobAck(res)) {
        // 叫一声让顶部横幅立刻登记这条活：人中途关窗后由横幅接住结果
        nudgeAssetJobBanner();
        setJobHint(res.message);
        const job = await waitForAssetJob(res.job_id, {
          onTick: (j) => {
            if (giveUpRef.current) return;
            const p = j.progress;
            setJobHint(
              `「${j.kind_label}」${j.status_label}` +
                (p?.done !== null && p?.done !== undefined && j.planned_units
                  ? `（已收敛 ${p.done}/${j.planned_units} 条）`
                  : '') +
                '——嫌慢可以关掉窗口，任务在后台照跑，跑完在顶部横幅和生产单列表里都能看到',
            );
          },
        });
        // 人已经关掉了窗口：结果交给顶部横幅接住，这里不再往已卸载的组件里塞状态
        if (giveUpRef.current) return;
        setJobHint(null);
        if (job.status !== 'succeeded') {
          message.error(job.error || `后台任务${job.status_label}，生产单没建成（任务号 ${job.id}）`, 8);
          return;
        }
        setResult(job.result as AssetProduceResponse);
        collectRecheckCodes(job.result as AssetProduceResponse);
        return;
      }
      setResult(res);
      collectRecheckCodes(res);
      message.success(res.message);
    } catch (e) {
      message.error((e as Error).message || '生成生产单失败');
    } finally {
      setBusy(false);
    }
  };

  // 关掉窗口 = 放弃在这里看结果，**不是**取消任务（后台照跑，横幅接住）。
  // 必须先置 giveUp 再关：轮询回来后靠它决定要不要往已卸载的组件里塞状态。
  const closeAndGiveUp = () => {
    giveUpRef.current = true;
    setJobHint(null);
    setResult(null);
    onClose();
  };

  return (
    <Modal
      open={open}
      title={`生成生产单：${summaries.length} 条过审文案`}
      width={720}
      onCancel={closeAndGiveUp}
      footer={
        result ? (
          <Space>
            <Button onClick={() => setResult(null)}>回到表单</Button>
            <Button type="primary" onClick={() => { setResult(null); onDone(); }}>
              去生产单列表
            </Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={closeAndGiveUp}>{busy ? '先关掉，后台继续跑' : '取消'}</Button>
            <Button type="primary" loading={busy} onClick={submit}>
              生成生产单（要投 {plannedRows} 条）
            </Button>
          </Space>
        )
      }
      destroyOnClose
    >
      {result ? (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Alert
            type={result.created ? 'success' : 'error'}
            showIcon
            message={`已生成 ${result.created} 张生产单，本批要投 ${result.board.planned_rows} 条（${result.board.tasks} 个任务 × 每个任务出 ${result.board.board_total} 版）`}
            description={result.message}
          />
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="投放渠道">
              {result.board.channel === 'wework_aivideo' ? '企微后台「创建AI视频」任务板' : result.board.channel}
            </Descriptions.Item>
            <Descriptions.Item label="板上的归属标记">{result.board.tag}</Descriptions.Item>
            <Descriptions.Item label="板上的建任务时间（系统生成）">{result.board.date}</Descriptions.Item>
            <Descriptions.Item label="出片规格">{result.board.output}</Descriptions.Item>
            <Descriptions.Item label="预计要跑几天">
              {result.capacity_hint.days} 天（{result.capacity_hint.account_count} 个号 × 每号每日 {result.capacity_hint.per_account_per_day} 条）
            </Descriptions.Item>
            <Descriptions.Item label="当日投放量">
              今天已排 {result.dispatch.today.board_rows} 条 / 提示线 {result.dispatch.today.soft_cap}
              {result.dispatch.today.over_cap > 0 && <Tag color="red" style={{ marginLeft: 6 }}>超出 {result.dispatch.today.over_cap} 条</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="今天投放情况" span={2}>
              已投出 {result.dispatch.today.dispatched} 条｜成功 {result.dispatch.today.succeeded} 条｜失败 {result.dispatch.today.failed} 条
              {result.dispatch.today.note && (
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                  {result.dispatch.today.note}
                </Text>
              )}
            </Descriptions.Item>
          </Descriptions>

          {/* 批 I（链路收敛）：单子建好了顺势问一句投不投——不用回列表再勾一遍。
              逐批人工确认不放松：还是要点一下勾，但不用换页面。 */}
          {!!result.production_ids?.length && result.board.channel === 'wework_aivideo' && (
            <div>
              <Checkbox
                checked={followupConfirm}
                onChange={(e) => setFollowupConfirm(e.target.checked)}
              >
                确认把这 {result.production_ids.length} 张新单投去 AI 出片（≈{result.board.planned_rows} 条额度，一条 25 分钟起）
              </Checkbox>
              <Space style={{ marginTop: 8 }}>
                <Button
                  type="primary"
                  danger
                  loading={followupBusy}
                  disabled={!followupConfirm}
                  onClick={dispatchFollowup}
                >
                  投去出片
                </Button>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  先不投就点「去生产单列表」，以后随时在生产单页投。
                </Text>
              </Space>
            </div>
          )}

          {!!result.recheck_failed?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.recheck_failed.length} 条在出生产单前的自动检查没通过（没生成单，钩子编号还能原号重投）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.recheck_failed.slice(0, 8).map((f) => (
                    <Text key={f.summary_id} style={{ fontSize: 12 }}>
                      {f.code}：{f.problems.map((p) => p.message).join('；')}
                    </Text>
                  ))}
                </Space>
              }
            />
          )}
          {!!result.recheck_waived?.length && isAdmin && (
            <Alert
              type="info"
              showIcon
              message={`${result.recheck_waived.length} 条由管理员带理由放行（已留档，可抽查）`}
            />
          )}
          {!!result.drifted?.length && (
            <Alert
              type="error"
              showIcon
              message={`${result.drifted.length} 条正文对不上：展开后的提示词和过审文案不是同一条`}
              description={
                <Space direction="vertical" size={2}>
                  {result.drifted.slice(0, 8).map((d) => (
                    <Text key={`${d.summary_id}-${d.seq}`} style={{ fontSize: 12 }}>
                      {d.code} #{d.seq}：{d.reason || '对不上'}
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    单子照常生成、没有偷偷丢掉，但别直接投——逐条改名或回审核台改文案。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.prompt_skeleton_gaps?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.prompt_skeleton_gaps.length} 条缺十行模板必须有的行（只提醒不拦：缺「负面约束」会出怪片、缺「音频与字幕」会被加字幕）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.prompt_skeleton_gaps.slice(0, 6).map((g, i) => (
                    <Text key={`${g.code}-${g.seq}-${i}`} style={{ fontSize: 12 }}>
                      {g.code} #{g.seq}：缺 {g.missing.join('、')}
                    </Text>
                  ))}
                </Space>
              }
            />
          )}
          {!!result.title_warnings?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.title_warnings.length} 条推荐标题正文超预算（只提醒：单子已建好、不拦出生产单，请把标题改短再投）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.title_warnings.slice(0, 8).map((w, i) => (
                    <Text key={`${w.asset_code}-${w.seq}-${i}`} style={{ fontSize: 12 }}>
                      {w.asset_code} #{w.seq}：「{w.title}」实测 {w.chars} 字 / 上限 {w.limit} 字
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    报表/任务板的标题列只显示前 22 字（发布侧补 4 字【账号】前缀，正文 ≤18）：
                    超了的那条会被截断、回收改名对不上。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.cards?.length && (
            <Alert
              type={result.cards.some((c) => c.orientation === 'landscape') ? 'warning' : 'info'}
              showIcon
              message={`这批带上的角色卡 ${result.cards.length} 张（第 1 张＝板上的第 1 张图＝主形象）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.cards.map((c, i) => (
                    <Text key={`${c.asset_id}-${i}`} style={{ fontSize: 12 }}>
                      {i + 1}. {c.code || (c.asset_id || '').slice(0, 8)}｜{c.hint}
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    导出任务文件时还会逐张核对能不能读到；画幅不合就现在回去换卡，别等投上板。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.warnings?.length && (
            <Alert
              type="info"
              showIcon
              message={`提醒 ${result.warnings.length} 条`}
              description={
                <Space direction="vertical" size={2}>
                  {result.warnings.slice(0, 10).map((w, i) => (
                    <Text key={i} style={{ fontSize: 12 }}>
                      {w}
                    </Text>
                  ))}
                </Space>
              }
            />
          )}
          <Table<AssetSummary>
            size="small"
            rowKey="id"
            dataSource={summaries}
            pagination={false}
            columns={[
              { title: '素材', dataIndex: 'asset_code', width: 110, render: (v?: string) => v || '-' },
              { title: '候选', key: 'seq', width: 70, render: (_, r) => `#${r.seq}${r.is_recommended ? ' 推荐' : ''}` },
              {
                title: '过审文案',
                dataIndex: 'text',
                render: (v: string) => (
                  <Paragraph
                    style={{ marginBottom: 0, fontSize: 12 }}
                    ellipsis={{ rows: 2, expandable: 'collapsible', symbol: (expanded: boolean) => (expanded ? '收起' : '展开') }}
                  >
                    {v}
                  </Paragraph>
                ),
              },
            ]}
          />
        </Space>
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {jobHint && (
            <Alert
              type="info"
              showIcon
              message={jobHint}
              description={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  这一步慢是在等模型逐条展开提示词（一条几十秒），不是在卡住；
                  重复点「生成」不会跑得更快，只会白烧一次模型费用。
                </Text>
              }
            />
          )}
          <Descriptions size="small" column={4} bordered>
            <Descriptions.Item label="文案">{summaries.length}</Descriptions.Item>
            <Descriptions.Item label="每条出几份不同写法（N）">{n}</Descriptions.Item>
            <Descriptions.Item label="每份出几版">{boardTotal}</Descriptions.Item>
            <Descriptions.Item label="要投多少条">
              <Text strong>{plannedRows} 条</Text>
            </Descriptions.Item>
          </Descriptions>

          <Space wrap size={16}>
            <span>
              <Text>N 每条文案派生份数：</Text>
              <Input type="number" min={1} max={10} style={{ width: 80, marginLeft: 6 }} value={n} onChange={(e) => setN(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
            </span>
            <Tooltip title="板上的 total＝同一条提示词出几版（1..20）。和 N 是两回事，弄混会白花 N×total 的量">
              <span>
                <Text>每份出几版：</Text>
                <Input type="number" min={1} max={20} style={{ width: 80, marginLeft: 6 }} value={boardTotal} onChange={(e) => setBoardTotal(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
              </span>
            </Tooltip>
            <span>
              <Text>豆包号数（折算天数）：</Text>
              <Input type="number" min={1} max={50} style={{ width: 80, marginLeft: 6 }} value={accounts} onChange={(e) => setAccounts(Math.max(1, Number(e.target.value) || 1))} />
            </span>
            <Tooltip title="K＝这部剧发布账号的数量，决定推荐视频标题给几条（现在不再固定 5 条）">
              <span>
                <Text>推荐标题条数（K）：</Text>
                <Input type="number" min={1} max={20} style={{ width: 80, marginLeft: 6 }} value={titleCount} onChange={(e) => setTitleCount(e.target.value ? Number(e.target.value) : undefined)} />
              </span>
            </Tooltip>
          </Space>

          <div>
            <Space style={{ marginBottom: 4 }}>
              <Text>钩子编号（要填 {needCodes} 个）：</Text>
              {codes.length > 0 && (
                <Tag color={codes.length === needCodes && !badCodes.length && !dupCodes && !usedCodes.length ? 'green' : 'orange'}>
                  已填 {codes.length}/{needCodes}
                </Tag>
              )}
            </Space>
            <div style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                取号：在服务器跑 hook_id.py 取五位编号（投放和回收靠它对上）。
              </Text>
            </div>
            <Input.TextArea
              rows={2}
              placeholder="空格/逗号/换行分隔，如：7C0B1 7C0B2（五位编号，不能自己编）"
              value={codeText}
              onChange={(e) => setCodeText(e.target.value)}
            />
            {codes.length && codes.length < needCodes && (
              <Text type="warning" style={{ fontSize: 12 }}>
                还差 {needCodes - codes.length} 个：缺了照样能建单，但导出内容带不上编号。
              </Text>
            )}
            {!!usedCodes.length && (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 6 }}
                message={`${usedCodes.length} 个编号已经被用掉了，提交会被拦`}
                description={
                  <div style={{ fontSize: 12 }}>
                    {usedCodes.slice(0, 8).map((u) => (
                      <div key={u.code}>{u.code}（已钉在素材 {u.asset_code} 的第 {u.seq} 张单上）</div>
                    ))}
                    {usedCodes.length > 8 && <div>另有 {usedCodes.length - 8} 个没列出</div>}
                    <div>一钩一号：号一发就烧掉，作废的单也不复用，回 hook_id.py 重新取号再投产。</div>
                  </div>
                }
              />
            )}
          </div>

          <Space wrap>
            <Input placeholder="板上的归属标记（留空用默认）" style={{ width: 220 }} value={boardTag} onChange={(e) => setBoardTag(e.target.value)} />
            <Tooltip title="剧名缩写要用 NAS《剧名缩写表.json》里的，禁止临时造；留空标题降级为「编号·精简钩子」，偏差说明记缺剧缩。">
              <Input
                placeholder="剧名缩写（可选，如 救总裁）"
                style={{ width: 200 }}
                maxLength={12}
                value={dramaAbbr}
                onChange={(e) => setDramaAbbr(e.target.value)}
              />
            </Tooltip>
          </Space>

          <AssetCardPicker active={open} value={cardIds} onChange={setCardIds} batchId={batchId} />

          <Checkbox checked={expand} onChange={(e) => setExpand(e.target.checked)}>
            让 AI 按标准模板把文案展开成能直接投的提示词
          </Checkbox>
          {!expand && (
            <Alert type="warning" showIcon message="不展开就是没正文的单：上面只有过审文案本身，不能投放，导出也不带正文" />
          )}

          {isAdmin && (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Input.TextArea
                rows={2}
                placeholder="（仅管理员）自动检查没过仍要坚持出生产单时的放行理由——会逐条留档"
                value={waiveReason}
                onChange={(e) => setWaiveReason(e.target.value)}
              />
              {!!waiveCodes.length && (
                <>
                  <Text style={{ fontSize: 12 }}>上一次拦下的问题类型，这次放行哪几类（不勾的那类仍然拦着）：</Text>
                  <Checkbox.Group
                    value={waiveCodes}
                    onChange={(v) => setWaiveCodes(v as string[])}
                    options={waiveCodes.map((c) => ({ label: RECHECK_CODE_LABELS[c] || c, value: c }))}
                  />
                </>
              )}
            </Space>
          )}

          <Alert
            type="info"
            showIcon
            message="出片恒 10.08s / 720×1280，任务板上没有时长与分辨率开关"
            description={
              <span style={{ fontSize: 12 }}>
                所以这里不填时长：内容更长只能拆成上/下集两条各 10 秒。
                本批 {plannedRows} 条会算进当日投放量 {plannedRows} 条（实测约 120 条/日，不做硬限，只报数）。
                视频时长上限 {DEFAULT_TIER}s 只影响反推文案的成本，跟任务板无关。
              </span>
            }
          />
          <MonoText>{summaries.map((s) => s.asset_code || s.id.slice(0, 8)).join(' · ')}</MonoText>
        </Space>
      )}
    </Modal>
  );
};

export default ProduceOrderModal;
