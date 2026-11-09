import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Button, Card, Modal, Popover, Space, Tabs, Tag, Tooltip, Typography, message } from 'antd';
import { ApartmentOutlined, BellOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import AssetListPanel from '../components/assets/AssetListPanel';
import AssetJobsPanel from '../components/assets/AssetJobsPanel';
import AssetImportPanel from '../components/assets/AssetImportPanel';
import AssetReviewPanel from '../components/assets/AssetReviewPanel';
import AssetProductionPanel from '../components/assets/AssetProductionPanel';
import AssetOutputWall from '../components/assets/AssetOutputWall';
import AssetJobBanner from '../components/assets/AssetJobBanner';
import AssetCategoryDrawer from '../components/assets/AssetCategoryDrawer';
import {
  deskNotifyState,
  deskNotifySupported,
  toggleDeskNotify,
  type DeskNotifyState,
} from '../components/assets/deskNotify';
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
   * 批 N（评审二·P0-2）：页签受控。投产成功后「去生产单列表」按钮承诺了带人过去，
   * 就得真能切过去——审核台（批 N）与素材列表（批 M「投去 AI 生成」）的投产弹窗
   * onDone 都会调 onGoToProduction 切到本页签。
   */
  // A′（2026-11-08 定稿）：页签角色化默认着陆（material→导入、operator→审核台、admin→素材列表）
  // ＋记住上次页签（首次访问按角色、之后 localStorage 记忆）。
  const defaultTab = useMemo(() => {
    const saved = localStorage.getItem('asset-library-tab');
    if (saved) return saved;
    const r = user?.role;
    if (r === 'material') return 'import';
    if (r === 'operator') return 'review';
    return 'assets';
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [activeTab, setActiveTabState] = useState<string>(defaultTab);
  const setActiveTab = useCallback((k: string) => {
    setActiveTabState(k);
    localStorage.setItem('asset-library-tab', k);
  }, []);
  /**
   * 钩子原型字典抽屉：入口只在这张顶部卡片放**一处**（四个页签都看得到），
   * 面板里只做筛选和点原型，不再各挂一份抽屉——两处入口迟早变成一个新版本一个旧版本。
   */
  const [catOpen, setCatOpen] = useState(false);
  // 桌面通知开关（用户口径 2026-11-09）：后台任务完成时提醒，页面在后台也能收到
  const [deskNotify, setDeskNotify] = useState<DeskNotifyState>(() => deskNotifyState());
  const [notifyHelpOpen, setNotifyHelpOpen] = useState(false);
  const doToggleDeskNotify = async () => {
    const next = await toggleDeskNotify();
    setDeskNotify(next);
    if (next === 'on') message.success('桌面通知已开启：后台任务完成时会提醒你', 4);
    else if (next === 'denied')
      message.warning('浏览器拒绝了通知权限——点地址栏左侧的锁图标，把「通知」改成允许后再试', 8);
    else if (next === 'insecure')
      message.warning('当前是内网 HTTP 访问，浏览器不允许开通知——点「桌面通知」看解决步骤', 8);
    else if (next === 'unsupported') message.info('当前浏览器不支持桌面通知，页内提示仍然有效');
  };

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
      // 批 N（评审二 P1-6）：不只说"需要重新提交"，把去哪重提说清（横幅行上也有跳转按钮）
      const tabHint =
        job.kind === 'summary_generate'
          ? '去「素材列表」重新出'
          : job.kind === 'produce' || job.kind === 'dispatch'
            ? '去「生产单与投板」页签重新点'
            : '去对应页签重新提交';
      message.warning(`「${job.kind_label}」被服务重启打断，结果不可信——${tabHint}（任务号 ${job.id.slice(0, 8)}）`, 10);
    } else {
      message.error(
        `「${job.kind_label}」没跑成：${job.error || '逐条原因看素材行上的阶段标签（红＝失败，可重试）'}（任务号 ${job.id.slice(0, 8)}）`,
        8,
      );
    }
  }, []);

  const role = user?.role;
  // A′：页签待办计数（轻量 total 探针；40s 一轮，够跟手不刷爆）
  const [badges, setBadges] = useState<{ review?: number; ready?: number }>({});
  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const H = { Authorization: `Bearer ${localStorage.getItem('token') ?? ''}` };
        const [r1, r2] = await Promise.all([
          fetch('/api/assets/summaries?audit_status=pending&page_size=1', { headers: H }).then((r) => r.json()),
          fetch(`/api/assets/productions?status=order_ready&owner=${role === 'operator' ? 'me' : 'all'}&page_size=1`, { headers: H }).then((r) => r.json()),
        ]);
        if (alive) setBadges({ review: r1.total ?? 0, ready: r2.total ?? 0 });
      } catch {
        /* 计数失败静默 */
      }
    };
    void pull();
    const t = setInterval(pull, 40000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [role, reloadToken]);
  const isAdmin = role === 'admin';
  const canProduce = role === 'admin' || role === 'operator' || role === 'material';
  const canReview = role === 'admin' || role === 'operator';

  const roleHint = useMemo(() => {
    if (!role) return null;
    if (isAdmin) return <Tag color="red">管理员：全部操作都能做，包括余额不够时强行提交、检查不过时带理由放行</Tag>;
    if (role === 'operator') return <Tag color="orange">运营：可导入、可反推文案、可审核过审、可出生产单与登记投板结果</Tag>;
    return <Tag color="blue">素材专员：可导入/读视频/出文案，不能审自己写的文案、不能出生产单（审核台与生产单只读）</Tag>;
  }, [isAdmin, role]);

  // 用户口径 2026-11-09：页签按**业务流程顺序**排列并加编号——
  // ① 导入 → ② 素材与文案（反推/出文案）→ ③ 审核 → ④ 生产与投板 → ⑤ 成片墙；
  // 后台任务是公共辅助（不属流程步骤），放末尾不编号。
  const items = [
    {
      key: 'import',
      label: '① 导入',
      children: (
        <AssetImportPanel
          canProduce={canProduce}
          onSelectBatch={(bid) => {
            setBatchId(bid);
            setActiveTab('assets'); // 批次码一键跳转到素材列表（带批次筛选）
          }}
          active={activeTab === 'import'}
        />
      ),
    },
    {
      key: 'assets',
      label: '② 素材与文案',
      children: (
        <AssetListPanel
          key={`assets-${batchId ?? 'all'}`}
          canProduce={canProduce}
          isAdmin={isAdmin}
          batchId={batchId}
          reloadToken={reloadToken}
          onGoToProduction={() => setActiveTab('production')}
          active={activeTab === 'assets'}
        />
      ),
    },
    {
      key: 'review',
      label: (
        <Space size={6}>
          ③ 文案审核
          {!!badges.review && <Badge count={badges.review} color="orange" title="等审核的候选数（共享池）" />}
        </Space>
      ),
      children: (
        <AssetReviewPanel
          key={`review-${batchId ?? 'all'}`}
          canReview={canReview}
          isAdmin={isAdmin}
          batchId={batchId}
          reloadToken={reloadToken}
          onGoToProduction={() => setActiveTab('production')}
          active={activeTab === 'review'}
        />
      ),
    },
    {
      key: 'production',
      label: (
        <Space size={6}>
          ④ 生产与投板
          {!!badges.ready && <Badge count={badges.ready} color="blue" title="还没投的生产单数" />}
        </Space>
      ),
      children: (
        <AssetProductionPanel
          key={`prod-${batchId ?? 'all'}`}
          canWriteBack={canReview}
          isAdmin={isAdmin}
          batchId={batchId}
          reloadToken={reloadToken}
          active={activeTab === 'production'}
        />
      ),
    },
    {
      // 批 K（成片素材墙）：链路终点。回收回来的片子按缩略图一面墙摆开，
      // 点开就播、勾选多选下载——最终用户「挑片子」就在这一屏，不用去生产单行里翻。
      key: 'outputs',
      label: '⑤ 成片墙',
      children: (
        <AssetOutputWall
          key={`outputs-${batchId ?? 'all'}`}
          batchId={batchId}
          reloadToken={reloadToken}
          ownerDefault={canReview && !isAdmin ? 'me' : 'all'}
          ownerSwitchable={canReview}
          active={activeTab === 'outputs'}
        />
      ),
    },
    {
      // 公共辅助（不属流程步骤）：所有后台任务的台账回看
      key: 'jobs',
      label: '后台任务',
      children: <AssetJobsPanel onGoToTab={setActiveTab} active={activeTab === 'jobs'} />,
    },
  ];

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small">
        <Space size={8} wrap>
          <Text strong>素材库</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            导入 → 出文案 → 审核 → 开单 → 投板出片 → 成片墙挑片
          </Text>
          <Popover
            placement="bottomLeft"
            title="素材库怎么用"
            content={
              <div style={{ maxWidth: 420, fontSize: 12 }}>
                <p style={{ marginBottom: 6 }}>
                  链路：批量导入（分享链接/视频文件）→ 反推文案 → AI 出钩子文案候选 → 人工审核 →
                  生成生产单（过审文案变成一条条要投的提示词）→ <b>投去 AI 出片</b>
                  （机器去企微后台任务板建任务，成片自动收进各单「成片」列，逐批人工确认后才投）。
                </p>
                <p style={{ marginBottom: 6 }}>
                  想自己投就导出任务文件手工投完，回来「补记手工投板结果」记账；
                  收回来的片子到「成片素材墙」挑：缩略图扫、点开播、多选下载。
                </p>
                <p style={{ marginBottom: 0 }}>
                  钩子原型（A–G）＝开头套路的标记：全员可看、管理员可改；不点也能走完全链。
                </p>
              </div>
            }
          >
            <Button type="link" size="small" style={{ padding: 0 }}>
              怎么用 <QuestionCircleOutlined />
            </Button>
          </Popover>
          {roleHint}
          {batchId && (
            <Tag closable onClose={() => setBatchId(undefined)} color="geekblue">
              批次：{batchId.slice(0, 8)}
            </Tag>
          )}
          <Button size="small" icon={<ApartmentOutlined />} onClick={() => setCatOpen(true)}>
            钩子原型字典
          </Button>
          {deskNotifySupported() && (
            <Tooltip
              title={
                deskNotify === 'on'
                  ? '已开启：后台任务完成/失败时弹桌面通知（页面切到后台也收得到）——点一下关闭'
                  : deskNotify === 'denied'
                    ? '浏览器已禁止通知：点地址栏左侧锁图标 → 通知 → 允许，再点这里开启'
                    : '开启后，后台任务完成/失败会弹桌面通知，切到别的页面也能收到'
              }
            >
              <Button
                size="small"
                type={deskNotify === 'on' ? 'primary' : 'default'}
                danger={deskNotify === 'denied' || deskNotify === 'insecure'}
                icon={<BellOutlined />}
                onClick={() => setNotifyHelpOpen(true)}
              >
                桌面通知{deskNotify === 'on' ? '：开' : ''}
              </Button>
            </Tooltip>
          )}
        </Space>
      </Card>

      <AssetJobBanner onSettled={onJobSettled} onGoToTab={setActiveTab} />

      <Tabs items={items} activeKey={activeTab} onChange={setActiveTab} />

      {/* 桌面通知说明弹窗（用户口径 2026-11-09）：权限怎么开、为什么点不动，一次说清 */}
      <Modal
        open={notifyHelpOpen}
        title="开启桌面通知"
        width={620}
        onCancel={() => setNotifyHelpOpen(false)}
        footer={
          deskNotify === 'on' ? (
            <Space>
              <Button onClick={() => setNotifyHelpOpen(false)}>保留开启</Button>
              <Button danger onClick={async () => { await doToggleDeskNotify(); setNotifyHelpOpen(false); }}>
                关闭桌面通知
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={() => setNotifyHelpOpen(false)}>暂不开启</Button>
              <Button
                type="primary"
                disabled={deskNotify === 'insecure' || deskNotify === 'unsupported'}
                onClick={async () => { await doToggleDeskNotify(); }}
              >
                {deskNotify === 'denied' ? '重新尝试授权' : '授权并开启'}
              </Button>
            </Space>
          )
        }
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Text>
            开启后，后台任务（出文案／开单／投板／反推）**完成、失败或被打断**时会弹一条系统
            桌面通知——切到别的页面、最小化窗口都能收到；失败/打断的通知不会自动消失，点一下跳回本页。
          </Text>

          {deskNotify === 'insecure' && (
            <Alert
              type="warning"
              showIcon
              message="当前访问地址不是 HTTPS，浏览器不允许开通知"
              description={
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <Text style={{ fontSize: 12 }}>
                    浏览器安全策略：只有 <b>HTTPS</b> 或 <b>localhost</b> 页面能申请通知权限。
                    你现在用的是内网 HTTP（如 http://192.168.x.x），所以点了没反应。
                  </Text>
                  <Text strong style={{ fontSize: 12 }}>三条路，任选其一：</Text>
                  <Text style={{ fontSize: 12 }}>
                    ① <b>推荐</b>：让运维给 163 的 nginx 配上 HTTPS 证书（自签也行，浏览器信任一次即可），
                    之后用 https:// 访问本系统。
                  </Text>
                  <Text style={{ fontSize: 12 }}>
                    ② <b>临时绕过</b>（仅 Chrome/Edge）：地址栏打开{' '}
                    <Text code style={{ fontSize: 12 }}>chrome://flags/#unsafely-treat-insecure-origin-as-secure</Text>
                    ，把本系统地址（含端口，如 http://192.168.1.163）填进来源列表，选 Enabled，重启浏览器后再来开启。
                  </Text>
                  <Text style={{ fontSize: 12 }}>
                    ③ <b>先不折腾</b>：页内提示照旧有效——顶部任务横幅 + 「后台任务」页签能看到每件活的终态。
                  </Text>
                </Space>
              }
            />
          )}

          {deskNotify === 'denied' && (
            <Alert
              type="warning"
              showIcon
              message="浏览器之前拒绝过通知，需要手动改回来"
              description={
                <span style={{ fontSize: 12 }}>
                  点地址栏左侧的<b>锁图标（或设置图标）→ 通知 → 允许</b>，然后刷新本页再点
                  「重新尝试授权」。如果锁图标里没有「通知」项，到浏览器的
                  设置 → 隐私和安全 → 网站设置 → 通知里，把本系统地址从「不允许」列表移除。
                </span>
              }
            />
          )}

          {deskNotify === 'unsupported' && (
            <Alert
              type="info"
              showIcon
              message="当前浏览器不支持桌面通知"
              description={<span style={{ fontSize: 12 }}>建议换用最新版 Chrome / Edge；页内提示不受影响。</span>}
            />
          )}

          {(deskNotify === 'off' || deskNotify === 'on') && (
            <Alert
              type="info"
              showIcon
              message="点「授权并开启」后，浏览器顶部会弹一个权限询问——选「允许」"
              description={
                <span style={{ fontSize: 12 }}>
                  如果误点了「阻止」：点地址栏左侧锁图标 → 通知 → 改为允许，再回来重新开启即可。
                  开启后会立刻收到一条测试通知，确认通路正常。
                </span>
              }
            />
          )}
        </Space>
      </Modal>

      <AssetCategoryDrawer open={catOpen} onClose={() => setCatOpen(false)} />
    </Space>
  );
};

export default AssetLibrary;
