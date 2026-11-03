import React from 'react';
import { Alert, Checkbox, Descriptions, Modal, Space, Tag, Typography } from 'antd';
import { GateLine, yuan } from './AssetBits';
import type { AssetCostEstimateResponse } from '../../api/assets';

const { Text } = Typography;

interface Props {
  open: boolean;
  title: string;
  /** 花钱的动作提交前必须先拿这个：预估 + 余额 + 闸门结论 */
  preview: AssetCostEstimateResponse | null;
  loading?: boolean;
  previewLoading?: boolean;
  /** 需要勾选确认才允许提交（后端对 need_approval / ≥2 条回源解析会硬卡 confirmed） */
  needConfirm?: boolean;
  confirmed?: boolean;
  onConfirmChange?: (v: boolean) => void;
  /** 业务侧控件：反推的档位选择、出文案的条数等 */
  extra?: React.ReactNode;
  /** 仅 admin：blocked 时可强行提交（余额接口有波动） */
  allowForce?: boolean;
  force?: boolean;
  onForceChange?: (v: boolean) => void;
  okText?: string;
  onOk: () => void;
  onCancel: () => void;
}

/**
 * 成本确认单。
 *
 * 存在的原因是反推按**计时上限**扣费、不按视频实际时长（600 档一条 0.324 元），
 * 回源解析按次 0.01 元 —— 都是真金白银，所以「点批量」这一步必须先把数摆清楚。
 * 余额查不到时闸门仍放行，但 `balance_note` 一定显示出来，别让人以为有钱。
 */
const CostConfirmModal: React.FC<Props> = ({
  open,
  title,
  preview,
  loading,
  previewLoading,
  needConfirm,
  confirmed,
  onConfirmChange,
  extra,
  allowForce,
  force,
  onForceChange,
  okText = '确认并提交',
  onOk,
  onCancel,
}) => {
  const blocked = preview?.gate?.level === 'blocked';
  // blocked 时只有「管理员 + 勾了强行提交」才允许点确认：非 admin 根本没这个口子，
  // admin 不勾就得回去充值或拆批——闸门不能变成一个看得见就能按的按钮。
  const okDisabled =
    !!previewLoading ||
    !preview ||
    (blocked && !(allowForce && force)) ||
    (!!needConfirm && !confirmed);

  return (
    <Modal
      open={open}
      title={title}
      onCancel={onCancel}
      onOk={onOk}
      okText={okText}
      confirmLoading={loading}
      okButtonProps={{ disabled: okDisabled }}
      width={620}
      destroyOnClose
    >
      {preview ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="条数">{preview.count}</Descriptions.Item>
            <Descriptions.Item label="计时上限档位">{preview.prompt_max_duration}s</Descriptions.Item>
            <Descriptions.Item label="单条预估">{yuan(preview.unit_cost)}</Descriptions.Item>
            <Descriptions.Item label="本批预估">
              <Text strong>{yuan(preview.total_cost)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="反推">
              {yuan(preview.breakdown.prompt)}
            </Descriptions.Item>
            <Descriptions.Item label="回源解析">
              {yuan(preview.breakdown.parse)}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Text type="secondary">智令余额：</Text>
            {preview.balance === null || preview.balance === undefined ? (
              <Text type="warning">未知</Text>
            ) : (
              <Text strong>
                {preview.balance}
                {preview.balance_unit || '元'}
              </Text>
            )}
            {preview.balance_note && (
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {preview.balance_note}
                </Text>
              </div>
            )}
          </div>

          <div>
            <Text type="secondary">闸门结论：</Text>
            <GateLine gate={preview.gate} />
          </div>

          {blocked && allowForce && (
            <Alert
              type="error"
              showIcon
              message="本批被余额闸门挡下"
              description={
                <Checkbox checked={!!force} onChange={(e) => onForceChange?.(e.target.checked)}>
                  我是管理员，确认强行提交（余额接口有波动，需事后对账）
                </Checkbox>
              }
            />
          )}

          {preview.gate?.level === 'need_approval' && (
            <Alert
              type="warning"
              showIcon
              message="超单批上限：本批需要勾选确认后才提交（或拆批 / 管理员放批）"
            />
          )}

          <div>
            <Text type="secondary">其他档位对比（同条数）：</Text>
            <div style={{ marginTop: 4 }}>
              {Object.entries(preview.tiers || {}).map(([t, cost]) => (
                <Tag key={t} style={{ marginBottom: 4 }}>
                  {t}s → {yuan(cost)}
                </Tag>
              ))}
            </div>
          </div>
        </Space>
      ) : (
        <Text type="secondary">{previewLoading ? '预估计算中…' : '暂无预估数据'}</Text>
      )}

      {extra && <div style={{ marginTop: 12 }}>{extra}</div>}

      {needConfirm && (
        <Checkbox
          style={{ marginTop: 12 }}
          checked={!!confirmed}
          onChange={(e) => onConfirmChange?.(e.target.checked)}
        >
          我已确认本批成本与档位，同意提交
        </Checkbox>
      )}
    </Modal>
  );
};

export default CostConfirmModal;
