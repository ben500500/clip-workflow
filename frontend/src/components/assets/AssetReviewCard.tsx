import React from 'react';
import { Button, Popover, Space, Tag, Tooltip, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, EditOutlined, SendOutlined } from '@ant-design/icons';
import { HOOK_STYLE_LABELS, type AssetFrameSlot, type AssetSummary } from '../../api/assets';
import { AuditStatusTag, RiskTags } from './AssetBits';
import { CategoryTag } from './AssetCategoryBits';
import { FrameStrip } from './AssetFrameBits';

const { Paragraph, Text } = Typography;

interface Props {
  row: AssetSummary;
  /** 这条素材的卡片图（同素材的 3 条候选共用一份） */
  slot?: AssetFrameSlot;
  framesLoading?: boolean;
  canReview: boolean;
  busy?: boolean;
  onApprove: (row: AssetSummary) => void;
  onEdit: (row: AssetSummary) => void;
  onReject: (row: AssetSummary) => void;
  onResubmit: (row: AssetSummary) => void;
}

/**
 * 审核台的一行＝一张卡片（批 F）。
 *
 * 为什么从表格式改成卡片：审核真正要比的是**画面和文字对不对得上**，
 * 而表格里的「素材」列只有 AS 码和标题，眼睛还得再回详情页开视频。卡片左边直接摆
 * 原片抽的三帧（10%／45%／80%，刻意不取 t=0——首帧常是黑边或台标），点开是九宫格。
 *
 * 三块：**左** 帧｜**中** 素材与文案｜**右** 判定徽标 + 操作。
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
}) => (
  <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
    {/* 左：三帧横排，点开九宫格 */}
    <FrameStrip slot={slot} loading={framesLoading} assetId={row.asset_id} />

    {/* 中：素材行 + 文案正文 */}
    <div style={{ flex: 1, minWidth: 0 }}>
      <Space size={4} wrap style={{ marginBottom: 2 }}>
        <Tag>{row.asset_code || row.asset_id.slice(0, 8)}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
          {row.asset_title || '（无标题）'}
        </Text>
        <Tooltip title={`同一素材出的第 ${row.seq} 条候选；一条素材通常出 3 条，默认只把推荐条摆出来，切「全部」能看 3 条对照`}>
          <Text strong style={{ fontSize: 12 }}>
            候选 #{row.seq}
          </Text>
        </Tooltip>
        {row.is_recommended && <Tag color="green">推荐</Tag>}
        <CategoryTag categoryId={row.category_id} categoryName={row.category_name} />
        <Tooltip title={row.reject_reason ? `理由：${row.reject_reason}` : undefined}>
          <span>
            <AuditStatusTag status={row.audit_status} />
          </span>
        </Tooltip>
      </Space>

      <Paragraph
        style={{ marginBottom: 2 }}
        ellipsis={{ rows: 3, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
      >
        {row.text}
      </Paragraph>

      <Space size={4} wrap>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {row.word_count ?? '-'} 字
        </Text>
        {row.style_tag && <Tag>{HOOK_STYLE_LABELS[row.style_tag] || row.style_tag}</Tag>}
        {row.formula_tag && <Tag color="geekblue">{row.formula_tag}</Tag>}
        {row.text_before_edit && (
          <Tooltip title={`改前原文：${row.text_before_edit}`}>
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
      </Space>
    </div>

    {/* 右：判定徽标 + 操作 */}
    <div style={{ width: 250, flexShrink: 0, textAlign: 'right' }}>
      <Space size={2} wrap style={{ justifyContent: 'flex-end' }}>
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

      <div style={{ marginTop: 4 }}>
        <Space size={2}>
          {row.can_resubmit && (
            <Tooltip title="把文案改了交回待审队列，等审核人再过一遍（改前改后都留档）">
              <Button size="small" icon={<SendOutlined />} loading={busy} onClick={() => onResubmit(row)}>
                改后重提
              </Button>
            </Tooltip>
          )}
          {canReview && (
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
        </Space>
      </div>
    </div>
  </div>
);

export default AssetReviewCard;
