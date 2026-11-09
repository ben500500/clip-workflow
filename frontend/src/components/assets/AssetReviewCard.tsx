import React from 'react';
import { Button, Popover, Space, Tag, Tooltip, Typography, message } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, EditOutlined, FileSearchOutlined, SendOutlined } from '@ant-design/icons';
import { HOOK_STYLE_LABELS, type AssetFrameSlot, type AssetSummary } from '../../api/assets';
import { AuditStatusTag, RiskTags } from './AssetBits';
import { CategoryTag } from './AssetCategoryBits';
import { FrameStrip } from './AssetFrameBits';
import { parseServerTime } from '../../utils/format';

const { Paragraph, Text } = Typography;

/**
 * 批 N（评审二·P1-4）：风险词落在正文里。原来命中词只在右列标签堆、正文纯文本，
 * 人要自己在句子里把那个词找出来。这里把命中的词就地高亮（红底加重），
 * 与右列 RiskTags 同一份 risk_hit（word|level 逗号串），长词优先避免被短词拆碎。
 */
const highlightRisk = (text: string, riskHit: string | null | undefined): React.ReactNode => {
  const words = Array.from(
    new Set(
      (riskHit || '')
        .split(',')
        .map((s) => s.trim().split('|')[0])
        .filter(Boolean),
    ),
  ).sort((a, b) => b.length - a.length);
  if (!words.length) return text;
  const re = new RegExp(
    `(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'gi',
  );
  return text.split(re).map((seg, i) => {
    const hit = words.some((w) => seg.toLowerCase() === w.toLowerCase());
    return hit ? (
      <Text key={i} type="danger" strong style={{ background: '#fff1f0' }}>
        {seg}
      </Text>
    ) : (
      <React.Fragment key={i}>{seg}</React.Fragment>
    );
  });
};

interface Props {
  row: AssetSummary;
  /** 这条素材的卡片图（同素材的多条候选共用一份） */
  slot?: AssetFrameSlot;
  framesLoading?: boolean;
  canReview: boolean;
  busy?: boolean;
  onApprove: (row: AssetSummary) => void;
  onEdit: (row: AssetSummary) => void;
  onReject: (row: AssetSummary) => void;
  onResubmit: (row: AssetSummary) => void;
  /** P1（评审定稿⑨）：一致性核验入口——弹出原片播放+反推脚本全文 */
  onInspect?: (row: AssetSummary) => void;
}

/**
 * 审核台的一行＝一张卡片（批 F，11-06 重排）。
 *
 * 为什么从表格式改成卡片：审核真正要比的是**画面和文字对不对得上**，
 * 而表格里的「素材」列只有 AS 码和标题，眼睛还得再回详情页开视频。卡片左边直接摆
 * 原片抽的三帧（10%／45%／80%，刻意不取 t=0——首帧常是黑边或台标），点开是九宫格。
 *
 * 排版三层（11-06 用户反馈「看着不舒服、不明确」后重排）：
 *   头行   —— 素材是谁＋第几候选＋审核状态（12px 灰字，扫一眼定位）
 *   正文   —— 文案本体 16px 加重，这张卡的绝对主角、眼睛的落点
 *   元信息 —— 字数/句式/基因/原型/提示词入口（12px 灰字，不跟正文抢）
 * 右列上下分区：判定徽标（对得上/违禁词/已产）在上，操作按钮钉在下沿，
 * 每行卡片的按钮位置恒定，不用在标签堆里找「过」。
 * 图是纯呈现层：没图（老素材、链接素材、整集片）不拦任何审核动作，右边照样能点。
 */
const AssetReviewCard: React.FC<Props> = ({
  row,
  slot,
  framesLoading,
  canReview,
  busy,
  onApprove,
  onEdit,
  onReject,
  onResubmit,
  onInspect,
}) => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
    {/* 左：三帧横排，点开九宫格 */}
    <FrameStrip slot={slot} loading={framesLoading} assetId={row.asset_id} />

    {/* 中：头行（小）→ 文案正文（大）→ 元信息（小） */}
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
      <Space size={6} wrap style={{ marginBottom: 4 }}>
        <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
          {row.asset_code || row.asset_id.slice(0, 8)}｜{row.asset_title || '（无标题）'}
        </Text>
        <Tooltip title={`同一素材出的第 ${row.seq} 条候选；一条素材默认只出 1 条，多出的场合默认只把推荐条摆出来，切「全部」能看对照`}>
          <Text strong style={{ fontSize: 12 }}>
            候选 #{row.seq}
          </Text>
        </Tooltip>
        {row.is_recommended && <Tag color="green">推荐</Tag>}
        <Tooltip title={row.reject_reason ? `理由：${row.reject_reason}` : undefined}>
          <span>
            <AuditStatusTag status={row.audit_status} />
          </span>
        </Tooltip>
      </Space>

      <Paragraph
        style={{ fontSize: 16, fontWeight: 500, lineHeight: 1.6, margin: '0 0 8px' }}
        ellipsis={{ rows: 3, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
      >
        {highlightRisk(row.text, row.risk_hit)}
      </Paragraph>

      <Space size={6} wrap>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {row.word_count ?? '-'} 字
        </Text>
        {/* 批 N（评审二·P1-4）：一致性判读取前 20 字平铺——原来整条藏在 Tooltip 里，
            不悬停根本看不见。全量判读仍在右列徽标的悬停里。 */}
        {row.consistency_ok === false && (row.consistency_note || '').trim() && (
          <Tooltip title={`完整判读：${row.consistency_note}`}>
            <Text type="warning" style={{ fontSize: 12 }}>
              判读：{row.consistency_note!.slice(0, 20)}
              {(row.consistency_note || '').length > 20 ? '…' : ''}
            </Text>
          </Tooltip>
        )}

        {row.style_tag && <Tag>{HOOK_STYLE_LABELS[row.style_tag] || row.style_tag}</Tag>}
        {row.formula_tag && <Tag color="geekblue">{row.formula_tag}</Tag>}
        <CategoryTag categoryId={row.category_id} categoryName={row.category_name} />
        {/* 批 N（11-09 用户口径「文案都去取一个编号放着」）：这条名下揣着一个**还没用掉**的
            钩子编号——开单时后端自动顶上缺号槽位，顶掉就清。别和 ④ 生产单行上那个编号混：
            那是已经烧掉的号，这是备用的号。 */}
        {row.hook_code && (
          <Tooltip title="这条文案名下预取好的钩子编号：开单时自动顶到缺号的槽位上，用掉就清（一钩一号，不会重复投）。要看已经投出去的编号请去 ④ 生产单。">
            <Tag color="purple">已备号 {row.hook_code}</Tag>
          </Tooltip>
        )}
        {/* A′（2026-11-08 定稿）：过审＝质检记录（灰字）；挑选与生产归属在投产人（生产单/成片墙"投：X"） */}
        {row.audit_status !== 'pending' && row.reviewed_by_name && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            质检：{row.reviewed_by_name}
          </Text>
        )}
        {row.text_before_edit && (
          <Tooltip
            title={
              '改前原文：' + (row.text_before_edit || '')
              + (row.resubmit_note ? `

作者说明：${row.resubmit_note}` : '')
            }
          >
            <Tag color={row.audit_status === 'passed_edited' ? 'cyan' : 'geekblue'}>
              {row.audit_status === 'passed_edited'
                ? '审核人改后通过'
                : row.audit_status === 'approved'
                  ? '作者重提后过审'
                  : '改过并重提'}
            </Tag>
          </Tooltip>
        )}
        {/* 批 J：过审即自动备好豆包提示词预览。收进一行点开看——整段提示词几百字，
            平铺在卡片里会把每行撑到一屏高。「预览≠投产稿」必须跟着标题走。 */}
        {row.prompt_preview && (
          <Popover
            trigger="click"
            title="豆包提示词预览（给人看的样稿，投产时会重新展开）"
            content={
              <div
                style={{
                  maxWidth: 480,
                  maxHeight: 320,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  fontSize: 12,
                  lineHeight: 1.6,
                }}
              >
                {row.prompt_preview}
              </div>
            }
          >
            <a style={{ fontSize: 12 }}>提示词已备好·查看</a>
          </Popover>
        )}
        {/* 11-06 双产出：出文案时同步生成的豆包网页版完整提示词（复制整段去
            doubao.com 对话框直接生成，与上面任务板预览是两条通道）。 */}
        {row.doubao_prompt && (
          <Popover
            trigger="click"
            title="豆包网页版提示词（复制整段去豆包对话框直接生成）"
            content={
              <div style={{ maxWidth: 480 }}>
                <div style={{ textAlign: 'right', marginBottom: 8 }}>
                  <Button
                    size="small"
                    type="primary"
                    onClick={() => {
                      navigator.clipboard.writeText(row.doubao_prompt || '');
                      message.success('已复制网页版提示词，去豆包对话框粘贴即可');
                    }}
                  >
                    复制
                  </Button>
                </div>
                <div
                  style={{
                    maxHeight: 360,
                    overflow: 'auto',
                    whiteSpace: 'pre-wrap',
                    fontSize: 12,
                    lineHeight: 1.6,
                  }}
                >
                  {row.doubao_prompt}
                </div>
              </div>
            }
          >
            <a style={{ fontSize: 12 }}>网页版提示词·复制</a>
          </Popover>
        )}
      </Space>
    </div>

    {/* 右：上＝判定徽标堆，下＝操作按钮（位置恒定，不用在标签堆里找「过」） */}
    <div
      style={{
        width: 210,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 8,
      }}
    >
      <Space size={4} wrap style={{ justifyContent: 'flex-end' }}>
        <RiskTags riskHit={row.risk_hit} />
        {row.consistency_ok === false ? (
          <Tooltip title={row.consistency_note || ''}>
            <Tag color="orange">和原视频对不上</Tag>
          </Tooltip>
        ) : row.consistency_ok === true ? (
          <Tag color="green">和原视频对得上</Tag>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            还没校验
          </Text>
        )}
        {/* 「已产 N 条」只有列表口带这个数（详情口不查＝键不存在，宁可不画也不报 0） */}
        {typeof row.output_count === 'number' && (
          <Tooltip title="这条过审文案派生的生产单已经产出几条视频（交付包与文案文件不算）">
            <Tag color={row.output_count ? 'blue' : 'default'}>已产 {row.output_count} 条</Tag>
          </Tooltip>
        )}
      </Space>

      {/* P1（评审定稿⑨）：核验是一个重要功能——做成独立按钮，放右侧操作区顶部 */}
      {onInspect && (
        <Tooltip title="核验签字依据：看原片 + 反推文案稿全文（一致性比对的事实来源）">
          <Button
            size="middle"
            block
            icon={<FileSearchOutlined />}
            onClick={() => onInspect(row)}
          >
            核验原片/脚本
          </Button>
        </Tooltip>
      )}

      <Space size={4}>
        {row.can_resubmit && (
          <Tooltip title="把文案改了交回待审队列，等审核人再过一遍（改前改后都留档）">
            <Button size="small" icon={<SendOutlined />} loading={busy} onClick={() => onResubmit(row)}>
              改后重提
            </Button>
          </Tooltip>
        )}
        {canReview && row.audit_status !== 'approved' && row.audit_status !== 'passed_edited' && (
          <>
            <Tooltip title="写文案的人不能审自己写的文案（管理员除外）">
              <Button
                size="small"
                type="primary"
                icon={<CheckCircleOutlined />}
                loading={busy}
                onClick={() => onApprove(row)}
              >
                过
              </Button>
            </Tooltip>
            <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(row)}>
              改后过
            </Button>
            <Button size="small" icon={<CloseCircleOutlined />} onClick={() => onReject(row)}>
              驳
            </Button>
          </>
        )}
        {/* 批 N（评审二·P1-5）：终态卡（已过审/改后通过）不再挂可点的「过/改后过/驳」——
            误点只会换来后端 400 报错噪音（迁移校验兜底）。按钮收起来，留判定时间。 */}
        {canReview && (row.audit_status === 'approved' || row.audit_status === 'passed_edited') && (
          <Tooltip title="这条已经是终态：要回炉先撤销过审（会连带作废未投的生产单）。不挂动作按钮就是防误点。">
            <Text type="secondary" style={{ fontSize: 12 }}>
              {row.reviewed_at ? `${parseServerTime(row.reviewed_at)?.format('MM-DD HH:mm')} 判定` : '已判定'}
            </Text>
          </Tooltip>
        )}
      </Space>
    </div>
  </div>
);

export default AssetReviewCard;
