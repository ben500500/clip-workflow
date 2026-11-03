import React, { useMemo, useState } from 'react';
import { Card, Space, Tabs, Tag, Typography } from 'antd';
import { useAuth } from '../contexts/AuthContext';
import AssetListPanel from '../components/assets/AssetListPanel';
import AssetImportPanel from '../components/assets/AssetImportPanel';
import AssetReviewPanel from '../components/assets/AssetReviewPanel';
import AssetProductionPanel from '../components/assets/AssetProductionPanel';

const { Text, Paragraph } = Typography;

/**
 * 素材库 P0 工作台：导入 → 反推 → 出文案 → 审核 → 投产 → 导出/回写。
 *
 * 权限不是前端装饰，是把后端 403 提前挡掉：
 *  - 导入/反推/出文案/回源解析 = material + operator + admin（`_PROD_ROLES`）；
 *  - 审核过审、投产、投递态回写 = operator + admin（`_REVIEW_ROLES`）；
 *  - 素材内容**全量可见**，不按人隔离（P0 口径），所以列表/详情没有归属过滤。
 *
 * batchId 只在各面板挂载时作初值（面板内部 useState 接），所以点批次跳转时靠
 * `key={batchId}` 强制重挂，而不是指望 props 变化自己重新筛。
 */
const AssetLibrary: React.FC = () => {
  const { user } = useAuth();
  const [batchId, setBatchId] = useState<string | undefined>();

  const role = user?.role;
  const isAdmin = role === 'admin';
  const canProduce = role === 'admin' || role === 'operator' || role === 'material';
  const canReview = role === 'admin' || role === 'operator';

  const roleHint = useMemo(() => {
    if (!role) return null;
    if (isAdmin) return <Tag color="red">管理员：全部动作可做，含 blocked 闸门强提与审核豁免</Tag>;
    if (role === 'operator') return <Tag color="orange">运营：可导入反推、可审核过审、可投产与回写投递态</Tag>;
    return <Tag color="blue">素材专员：可导入/反推/出文案，不能自审、不能投产（审核台与生产单只读）</Tag>;
  }, [isAdmin, role]);

  const items = [
    {
      key: 'assets',
      label: '素材列表',
      children: (
        <AssetListPanel
          key={`assets-${batchId ?? 'all'}`}
          canProduce={canProduce}
          isAdmin={isAdmin}
          batchId={batchId}
        />
      ),
    },
    {
      key: 'import',
      label: '导入与批次',
      children: <AssetImportPanel canProduce={canProduce} onSelectBatch={setBatchId} />,
    },
    {
      key: 'review',
      label: '文案审核台',
      children: (
        <AssetReviewPanel
          key={`review-${batchId ?? 'all'}`}
          canReview={canReview}
          isAdmin={isAdmin}
          batchId={batchId}
        />
      ),
    },
    {
      key: 'production',
      label: '生产单与投递',
      children: (
        <AssetProductionPanel key={`prod-${batchId ?? 'all'}`} canWriteBack={canReview} batchId={batchId} />
      ),
    },
  ];

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small">
        <Paragraph style={{ marginBottom: 6 }}>
          <Text strong>素材库 P0</Text>
          ：批量导入（分享链接 / 视频文件）→ 反推提示词 → 钩子文案候选 → 人工审核 → 过审文案派生 N 条差异化生产单
          → 导出板面 payload。P0 <Text strong>不自动投递</Text>：导出后由人在企微后台建任务，回到本页回写
          queued / running / success / failed。
        </Paragraph>
        <Space size={8} wrap>
          {roleHint}
          {batchId && (
            <Tag closable onClose={() => setBatchId(undefined)} color="geekblue">
              当前批次筛选：{batchId.slice(0, 8)}
            </Tag>
          )}
        </Space>
      </Card>

      <Tabs items={items} />
    </Space>
  );
};

export default AssetLibrary;
