import React, { useMemo, useState } from 'react';
import {
  Alert, Button, Checkbox, Descriptions, Input, Modal, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { DEFAULT_TIER, assetApi } from '../../api/assets';
import type { AssetProduceResponse, AssetSummary } from '../../api/assets';
import { HOOK_CODE_RE, MonoText, parseHookCodes } from './AssetBits';

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
const ProduceOrderModal: React.FC<Props> = ({ open, summaries, isAdmin, onClose, onDone }) => {
  const [n, setN] = useState(3);
  const [boardTotal, setBoardTotal] = useState(1);
  const [accounts, setAccounts] = useState(1);
  const [titleCount, setTitleCount] = useState<number | undefined>(undefined);
  const [boardTag, setBoardTag] = useState('');
  const [cardKey, setCardKey] = useState('');
  const [codeText, setCodeText] = useState('');
  const [expand, setExpand] = useState(true);
  const [waiveReason, setWaiveReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssetProduceResponse | null>(null);

  const needCodes = summaries.length * n;
  const codes = useMemo(() => parseHookCodes(codeText), [codeText]);
  const badCodes = codes.filter((c) => !HOOK_CODE_RE.test(c));
  const dupCodes = codes.length !== new Set(codes).size;
  const plannedRows = summaries.length * n * boardTotal;

  const submit = async () => {
    if (!summaries.length) {
      message.warning('没有已过审的文案');
      return;
    }
    if (badCodes.length) {
      message.error(`钩子编号不合法：${badCodes.slice(0, 3).join('、')}（必须五位 0-9A-Z，来自 hook_id.py）`);
      return;
    }
    if (dupCodes) {
      message.error('钩子编号重复：一钩一号');
      return;
    }
    setBusy(true);
    try {
      const res = await assetApi.produce({
        summary_ids: summaries.map((s) => s.id),
        n,
        board_total: boardTotal,
        accounts,
        recommended_title_count: titleCount,
        board_tag: boardTag || undefined,
        character_card_key: cardKey || undefined,
        hook_codes: codes.length ? codes : undefined,
        expand,
        waive_reason: waiveReason || undefined,
      });
      setResult(res);
      message.success(res.message);
    } catch (e) {
      message.error((e as Error).message || '建单失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title={`投产 ${summaries.length} 条过审文案`}
      width={720}
      onCancel={() => {
        setResult(null);
        onClose();
      }}
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
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={busy} onClick={submit}>
              生成生产单（{plannedRows} 条投放）
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
            message={`已生成 ${result.created} 张生产单，本批真实投放 ${result.board.planned_rows} 条（任务 ${result.board.tasks} × 每任务 ${result.board.board_total} 版）`}
            description={result.message}
          />
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="通道">{result.board.channel}</Descriptions.Item>
            <Descriptions.Item label="板上 tag">{result.board.tag}</Descriptions.Item>
            <Descriptions.Item label="板上 date（后端生成）">{result.board.date}</Descriptions.Item>
            <Descriptions.Item label="出片规格">{result.board.output}</Descriptions.Item>
            <Descriptions.Item label="折算天数">
              {result.capacity_hint.days} 天（{result.capacity_hint.account_count} 号 × {result.capacity_hint.per_account_per_day} 条/日）
            </Descriptions.Item>
            <Descriptions.Item label="今日号池">
              {result.dispatch.today.board_rows} 条 / 软提示线 {result.dispatch.today.soft_cap}
              {result.dispatch.today.over_cap > 0 && <Tag color="red" style={{ marginLeft: 6 }}>超 {result.dispatch.today.over_cap}</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="今日成/败" span={2}>
              已投 {result.dispatch.today.dispatched}｜成功 {result.dispatch.today.succeeded}｜失败 {result.dispatch.today.failed}
              {result.dispatch.today.note && (
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                  {result.dispatch.today.note}
                </Text>
              )}
            </Descriptions.Item>
          </Descriptions>

          {!!result.recheck_failed?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.recheck_failed.length} 条被投产前复核拦下（没生成单，钩子编号没被烧掉，可原号重投）`}
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
              message={`${result.recheck_waived.length} 条经管理员豁免（已入 AuditLog，可抽检）`}
            />
          )}
          {!!result.drifted?.length && (
            <Alert
              type="error"
              showIcon
              message={`${result.drifted.length} 条「审的 ≠ 生产的」：展开后的提示词与过审文案不是同一条`}
              description={
                <Space direction="vertical" size={2}>
                  {result.drifted.slice(0, 8).map((d) => (
                    <Text key={`${d.summary_id}-${d.seq}`} style={{ fontSize: 12 }}>
                      {d.code} #{d.seq}：{d.reason || '漂移'}
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    单子照常生成、没静默丢弃，但别硬投——逐条改名或回审核台改文案。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.prompt_skeleton_gaps?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.prompt_skeleton_gaps.length} 条缺 11-02 骨架行（只警示不拦：缺「负面约束」会出怪片、缺「音频与字幕」会被加字幕）`}
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
                  <Paragraph style={{ marginBottom: 0, fontSize: 12 }} ellipsis={{ rows: 2, expandable: true }}>
                    {v}
                  </Paragraph>
                ),
              },
            ]}
          />
        </Space>
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions size="small" column={4} bordered>
            <Descriptions.Item label="文案">{summaries.length}</Descriptions.Item>
            <Descriptions.Item label="N（差异化份数）">{n}</Descriptions.Item>
            <Descriptions.Item label="board_total（每条几版）">{boardTotal}</Descriptions.Item>
            <Descriptions.Item label="投放量">
              <Text strong>{plannedRows} 条</Text>
            </Descriptions.Item>
          </Descriptions>

          <Space wrap size={16}>
            <span>
              <Text>N 每条文案派生份数：</Text>
              <Input type="number" min={1} max={10} style={{ width: 80, marginLeft: 6 }} value={n} onChange={(e) => setN(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
            </span>
            <Tooltip title="板上 total＝同一条提示词出几版（1..20）。与 N 是两个量，混用会白烧 N×total">
              <span>
                <Text>board_total：</Text>
                <Input type="number" min={1} max={20} style={{ width: 80, marginLeft: 6 }} value={boardTotal} onChange={(e) => setBoardTotal(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
              </span>
            </Tooltip>
            <span>
              <Text>豆包号数（折算天数）：</Text>
              <Input type="number" min={1} max={50} style={{ width: 80, marginLeft: 6 }} value={accounts} onChange={(e) => setAccounts(Math.max(1, Number(e.target.value) || 1))} />
            </span>
            <Tooltip title="K＝该剧发布号数，决定推荐视频标题条数（11-02 版不再固定 5 条）">
              <span>
                <Text>K 标题条数：</Text>
                <Input type="number" min={1} max={20} style={{ width: 80, marginLeft: 6 }} value={titleCount} onChange={(e) => setTitleCount(e.target.value ? Number(e.target.value) : undefined)} />
              </span>
            </Tooltip>
          </Space>

          <div>
            <Space style={{ marginBottom: 4 }}>
              <Text>钩子编号（选 {needCodes} 个，来自 hook_id.py）：</Text>
              {codes.length > 0 && (
                <Tag color={codes.length === needCodes && !badCodes.length && !dupCodes ? 'green' : 'orange'}>
                  已填 {codes.length}/{needCodes}
                </Tag>
              )}
            </Space>
            <Input.TextArea
              rows={2}
              placeholder="空格/逗号/换行分隔，例如：7C0B1 7C0B2 7C0B3 …（后端绝不编号，禁止手编）"
              value={codeText}
              onChange={(e) => setCodeText(e.target.value)}
            />
            {codes.length && codes.length < needCodes && (
              <Text type="warning" style={{ fontSize: 12 }}>
                还差 {needCodes - codes.length} 个：不足的会建单成功但被标「缺号」，导出 txt 时段头/推荐标题就没编号。
              </Text>
            )}
          </div>

          <Space wrap>
            <Input placeholder="板上 tag（留空用配置默认）" style={{ width: 220 }} value={boardTag} onChange={(e) => setBoardTag(e.target.value)} />
            <Tooltip title="角色卡在自有桶的 key → 板上 picDatas 来源（同剧同卡，按剧分组投）">
              <Input placeholder="角色卡 key（可选）" style={{ width: 260 }} value={cardKey} onChange={(e) => setCardKey(e.target.value)} />
            </Tooltip>
          </Space>

          <Checkbox checked={expand} onChange={(e) => setExpand(e.target.checked)}>
            调 AutoClip 按 11-02 权威模板展开成可投提示词
          </Checkbox>
          {!expand && (
            <Alert type="warning" showIcon message="不展开＝裸单：单子上只有过审文案本身，不许投放也不进导出正文" />
          )}

          {isAdmin && (
            <Input.TextArea
              rows={2}
              placeholder="（仅 admin）投产前复核未过仍要投递时的豁免理由——会逐条写进 AuditLog"
              value={waiveReason}
              onChange={(e) => setWaiveReason(e.target.value)}
            />
          )}

          <Alert
            type="info"
            showIcon
            message="出片恒 10.08s / 720×1280，板上没有时长与分辨率开关"
            description={
              <span style={{ fontSize: 12 }}>
                所以这里不填时长：内容更长只能拆上/下集两条各 10s，不是让板子变魔术。
                本批 {plannedRows} 条会占号池 {plannedRows} 条额度（实测 ≈120 条/日，不做硬限，只报数）。
                档位 {DEFAULT_TIER}s 只影响反推成本，与板无关。
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
