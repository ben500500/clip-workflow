import React, { useCallback, useMemo, useState } from 'react';
import { Button, Card, Modal, Space, Tabs, Tag, Typography, message } from 'antd';
import { ApartmentOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import AssetListPanel from '../components/assets/AssetListPanel';
import AssetJobsPanel from '../components/assets/AssetJobsPanel';
import AssetImportPanel from '../components/assets/AssetImportPanel';
import AssetReviewPanel from '../components/assets/AssetReviewPanel';
import AssetProductionPanel from '../components/assets/AssetProductionPanel';
import AssetJobBanner from '../components/assets/AssetJobBanner';
import AssetCategoryDrawer from '../components/assets/AssetCategoryDrawer';
import type { AssetJobInfo } from '../api/assets';

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
 *
 * 出文案/投产是「提交即回 + 后台跑」（D-1）：任务状态挂在顶部横幅上（`AssetJobBanner`
 * 每 8 秒查一次台账），跑完那一刻才把 `reloadToken` +1 让三个面板重拉列表。
 * 所以**关掉页面不影响任务**，重进来看的还是同一张台账——前端没有任何"必须守着"的状态。
 */
const AssetLibrary: React.FC = () => {
  const { user } = useAuth();
  const [batchId, setBatchId] = useState<string | undefined>();
  /**
   * 后台任务收敛一次就 +1（D-1）。三个面板各自拉自己的列表，靠这个数触发重拉——
   * 不用定时器猜"跑了三分钟应该好了"，只有横幅确认任务真到终态才刷。
   */
  const [reloadToken, setReloadToken] = useState(0);
  /**
   * 钩子原型字典抽屉：入口只在这张顶部卡片放**一处**（四个页签都看得到），
   * 面板里只做筛选和点原型，不再各挂一份抽屉——两处入口迟早变成一个新版本一个旧版本。
   */
  const [catOpen, setCatOpen] = useState(false);

  const onJobSettled = useCallback((job: AssetJobInfo) => {
    setReloadToken((t) => t + 1);
    // 11-06 承诺审计③：后端把逐条 note/error 都备在 job.result.results 里，此前前端
    // 从不读——「逐条成败看 result.results」是空头承诺。这里把它摆出来（截前 6 条）。
    const rows: Array<{ code?: string; error?: string; note?: string }> =
      ((job.result as { results?: unknown[] } | null)?.results as
        | Array<{ code?: string; error?: string; note?: string }>
        | undefined) ?? [];
    const bad = rows.filter((r) => r.error || r.note);
    if (job.status === 'succeeded') {
      if (bad.length) {
        Modal.warning({
          title: `「${job.kind_label}」跑完了，但有 ${bad.length} 条要留意`,
          width: 560,
          content: (
            <div style={{ maxHeight: 300, overflow: 'auto' }}>
              {bad.slice(0, 8).map((r, i) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  {r.code ? `${r.code}：` : ''}
                  {r.error || r.note}
                </div>
              ))}
              {bad.length > 8 && <div style={{ color: '#999' }}>…其余 {bad.length - 8} 条类似</div>}
            </div>
          ),
        });
      } else {
        message.success(`「${job.kind_label}」后台跑完了，列表已刷新（任务号 ${job.id.slice(0, 8)}）`, 6);
      }
    } else if (job.status === 'interrupted') {
      message.warning(`「${job.kind_label}」被服务重启打断，结果不可信，需要重新提交`, 8);
    } else {
      message.error(
        `「${job.kind_label}」没跑成：${job.error || '逐条原因看素材行上的阶段标签（红＝失败，可重试）'}（任务号 ${job.id.slice(0, 8)}）`,
        8,
      );
    }
  }, []);

  const role = user?.role;
  const isAdmin = role === 'admin';
  const canProduce = role === 'admin' || role === 'operator' || role === 'material';
  const canReview = role === 'admin' || role === 'operator';

  const roleHint = useMemo(() => {
    if (!role) return null;
    if (isAdmin) return <Tag color="red">管理员：全部操作都能做，包括余额不够时强行提交、检查不过时带理由放行</Tag>;
    if (role === 'operator') return <Tag color="orange">运营：可导入、可反推文案、可审核过审、可出生产单与登记投放结果</Tag>;
    return <Tag color="blue">素材专员：可导入/读视频/出文案，不能审自己写的文案、不能出生产单（审核台与生产单只读）</Tag>;
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
          reloadToken={reloadToken}
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
          reloadToken={reloadToken}
        />
      ),
    },
    {
      key: 'jobs',
      label: '后台任务',
      children: <AssetJobsPanel />,
    },
    {
      key: 'production',
      label: '生产单与投放',
      children: (
        <AssetProductionPanel
          key={`prod-${batchId ?? 'all'}`}
          canWriteBack={canReview}
          isAdmin={isAdmin}
          batchId={batchId}
          reloadToken={reloadToken}
        />
      ),
    },
  ];

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small">
        <Paragraph style={{ marginBottom: 6 }}>
          <Text strong>素材库 P0</Text>
          ：批量导入（分享链接 / 视频文件）→ 反推文案 → AI 出钩子文案候选 → 人工审核 →
          生成生产单（把过审文案变成要投出去的一条条提示词）→{' '}
          <Text strong>投去 AI 出片</Text>
          ：机器去企微后台「创建AI视频」任务板建任务、等出片、把成片自动收进各单的「成片」列
          （逐批人工确认后才投；想自己投就导出任务文件手工投完，回来「补记手工投板结果」记账）。
        </Paragraph>
        <Space size={8} wrap>
          {roleHint}
          {batchId && (
            <Tag closable onClose={() => setBatchId(undefined)} color="geekblue">
              当前批次筛选：{batchId.slice(0, 8)}
            </Tag>
          )}
          <Button size="small" icon={<ApartmentOutlined />} onClick={() => setCatOpen(true)}>
            钩子原型字典
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            原型（A–G）＝开头套路的标记：全员可看、管理员可改；不点也能走完全链，过审与投产都不看它。
          </Text>
        </Space>
      </Card>

      <AssetJobBanner onSettled={onJobSettled} />

      <Tabs items={items} />

      <AssetCategoryDrawer open={catOpen} onClose={() => setCatOpen(false)} />
    </Space>
  );
};

export default AssetLibrary;
