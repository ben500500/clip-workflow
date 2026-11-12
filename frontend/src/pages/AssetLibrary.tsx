import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Drawer, Modal, Popover, Space, Table, Tabs, Tag, Tooltip, Typography, message, notification } from 'antd';
import { ApartmentOutlined, BellOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import AssetListPanel from '../components/assets/AssetListPanel';
import AssetJobsPanel from '../components/assets/AssetJobsPanel';
import AssetImportPanel from '../components/assets/AssetImportPanel';
import AssetReviewPanel from '../components/assets/AssetReviewPanel';
import AssetProductionPanel from '../components/assets/AssetProductionPanel';
import AssetOutputWall from '../components/assets/AssetOutputWall';
import AssetJobBanner, { RESUBMIT_TARGET } from '../components/assets/AssetJobBanner';
import AssetCategoryDrawer from '../components/assets/AssetCategoryDrawer';
import { publishApi } from '../api/publish';
import {
  deskNotifyState,
  toggleDeskNotify,
  type DeskNotifyState,
} from '../components/assets/deskNotify';
import type { AssetJobInfo } from '../api/assets';

const { Text, Paragraph } = Typography;

/**
 * 11-10 用户口径③「刚才投出去的那条生产单显示完成，成片墙还是看不到…能改得简单一点吗」：
 * 每一种后台任务跑完，除了后端那句 `done_note`（做了什么、下一步在哪），界面还要给
 * **一跳直达的页签**——只说"去看成片墙"却让人自己找页签，等于没说。
 * 键是后端 `AssetJobKind`；没列在里面的（抽帧／备提示词这类）就不给跳转，只说那句话。
 */
const JOB_DONE_TARGET: Partial<Record<AssetJobInfo['kind'], { tab: string; label: string }>> = {
  summary_generate: { tab: 'review', label: '去审核台看文案' },
  produce: { tab: 'production', label: '去生产单页投板' },
  dispatch: { tab: 'production', label: '去看这几张单的进度' },
  analyze: { tab: 'assets', label: '去看反推回来的稿子' },
};

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
  // 2026-11-11 评审（素材席 R2 P0）：默认 tab 的记忆键原来是全局一个——上一任使用者
  // （或同一浏览器另一账号）留下的「④ 生产与投板」会让素材专员登录就落到一个恒 0 的页。
  // 键按用户隔离；首次访问按角色落位（素材→①导入，运营→③审核）。
  const defaultTab = useMemo(() => {
    const saved = user ? localStorage.getItem(`asset-library-tab:${user.id}`) : null;
    if (saved) return saved;
    const r = user?.role;
    if (r === 'material') return 'import';
    if (r === 'operator') return 'review';
    return 'assets';
  }, [user]);
  const [activeTab, setActiveTabState] = useState<string>(defaultTab);
  const setActiveTab = useCallback((k: string) => {
    setActiveTabState(k);
    if (user) localStorage.setItem(`asset-library-tab:${user.id}`, k);
  }, [user]);
  /**
   * 钩子原型字典抽屉：入口只在这张顶部卡片放**一处**（四个页签都看得到），
   * 面板里只做筛选和点原型，不再各挂一份抽屉——两处入口迟早变成一个新版本一个旧版本。
   */
  const [catOpen, setCatOpen] = useState(false);
  // 2026-11-11 评审（管理员席 P0）：跨人投产/取号/审核的审计一直只写不读——
  // 管理员在界面上找不到入口。给 admin 一颗「审计」按钮＋抽屉表（动作发生地就在这页）。
  const [auditOpen, setAuditOpen] = useState(false);
  // 2026-11-11 评审（素材席 R2 P1）：批次筛选 chip 原来只露 UUID——和回执/下拉的
  // 「AB 码·名称」对不上。这里拉一次批次表把 chip 换成人话；失败就退回短码。
  const [batchNames, setBatchNames] = useState<Record<string, string>>({});
  useEffect(() => {
    import('../api/assets').then(({ assetApi }) =>
      assetApi.listBatches({ limit: 100 }).then((res) => {
        const m: Record<string, string> = {};
        (res.items || []).forEach((b) => {
          m[b.id] = `${b.code} · ${b.name || '未命名'}`;
        });
        setBatchNames(m);
      }).catch(() => undefined),
    );
  }, [reloadToken]);
  const [auditRows, setAuditRows] = useState<Record<string, unknown>[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const openAuditDrawer = async () => {
    setAuditOpen(true);
    setAuditLoading(true);
    try {
      const res = await publishApi.getAuditLogs({ kind: 'asset', limit: 200 });
      setAuditRows((res.items ?? []) as unknown as Record<string, unknown>[]);
    } catch (e) {
      message.error((e as Error).message || '审计读取失败');
    } finally {
      setAuditLoading(false);
    }
  };
  /**
   * 11-10「一屏到底」：②③④ 任一处建完生产单并点了「投去出片」，就把新单 ID 交到这儿，
   * 页面层切到 ④ 并让生产单面板直接弹出投板确认窗——省掉「回列表、勾行、再点按钮」三段路。
   * ④ 认领后立刻调 `onDispatchConsumed` 清空：同一批 ID 二次点提交不该再弹窗。
   */
  const [dispatchIds, setDispatchIds] = useState<string[] | null>(null);
  const [dispatchNotes, setDispatchNotes] = useState<string[]>([]);
  const handoffToDispatch = useCallback((ids: string[], notes: string[] = []) => {
    setActiveTab('production');
    setDispatchNotes(notes);
    setDispatchIds(ids);
  }, [setActiveTab]);
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
    // 2026-11-11 评审（审核席 P1）：任务收尾（开单/出文案等）角标立即重拉
    window.dispatchEvent(new Event('asset-badges-refresh'));
    // 2026-11-13 流畅性席 P1：试产任务终态要把人带到看得到片的地方——
    // 试产片不在 ④（is_trial 被成片链路过滤），判定按钮在 ③ 的卡片试产区。
    if (job.kind === 'dispatch' && job.status === 'succeeded') {
      const raw = (job.result as { results?: unknown } | null)?.results;
      const isTrial = (() => {
        if (Array.isArray(raw)) return raw.some((x) => (x as { trial?: boolean })?.trial);
        if (raw && typeof raw === 'object') {
          return Object.values(raw as Record<string, { trial?: boolean }>).some((x) => x?.trial);
        }
        return false;
      })();
      if (isTrial) {
        setActiveTab('review');
      }
    }
    // 11-06 承诺审计③：后端把逐条 note/error 都备在 job.result.results 里，此前前端
    // 从不读——「逐条成败看 result.results」是空头承诺。这里把它摆出来（截前 6 条）。
    //
    // 11-10 修：`results` 有两种形状——出文案/开单/下载是**数组**（逐条 push），
    // 投板是**字典**（`outcome["summary"]` 按生产单 id 索引，见后端 `_execute_dispatch`）。
    // 老写法直接 `.filter`，投板那一支 `{}` 上没这方法 → TypeError 被 AssetJobBanner
    // 的 try/catch 吞掉 → onSettled 回调没跑完 → done_note 消息条**永远不弹**、
    // 一跳直达按钮也没了（用户口径③「投出去的那条生产单显示完成，成片墙还是看不到」
    // 的现场证据就是这么丢的）。这里统一拍平成数组，判"要不要留意"只看 `error`——
    // 投板的 `note` 是"还在板上跑，不判失败"这类正常状态说明，不是警告。
    const rawResults = (job.result as { results?: unknown } | null)?.results;
    const rows: Array<{ code?: string; error?: string; note?: string }> = Array.isArray(rawResults)
      ? (rawResults as Array<{ code?: string; error?: string; note?: string }>)
      : rawResults && typeof rawResults === 'object'
        ? Object.values(rawResults as Record<string, { code?: string; error?: string; note?: string }>)
        : [];
    const bad = rows.filter((r) => r.error);
    if (job.status === 'succeeded') {
      // 11-10 口径③「投出去的那条生产单显示完成，成片墙还是看不到」：话术权威在后端
      // `ASSET_JOB_DONE_NOTES`（`done_note`），这里只负责把它摆出来＋给一跳直达的页签。
      // 「已完成」只等于**这个动作**跑完：投板跑完＝挂上板，片子还在豆包那边出；
      // 开单跑完＝单建好，还没投。不写这一句，一线就只能自己猜"完成"完成了什么。
      const note = job.done_note || '';
      const target = JOB_DONE_TARGET[job.kind];
      if (bad.length) {
        Modal.warning({
          title: `「${job.kind_label}」跑完了，但有 ${bad.length} 条要留意`,
          width: 560,
          content: (
            <>
              <div style={{ maxHeight: 300, overflow: 'auto' }}>
                {bad.slice(0, 8).map((r, i) => (
                  <div key={i} style={{ marginBottom: 4 }}>
                    {r.code ? `${r.code}：` : ''}
                    {r.error || r.note}
                  </div>
                ))}
                {bad.length > 8 && <div style={{ color: '#999' }}>…其余 {bad.length - 8} 条类似</div>}
              </div>
              {!!note && (
                <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
                  这一步做到了哪一步：{note}
                  {target && (
                    <Button
                      size="small"
                      type="link"
                      style={{ padding: '0 0 0 6px', fontSize: 12 }}
                      onClick={() => setActiveTab(target.tab)}
                    >
                      {target.label} →
                    </Button>
                  )}
                </div>
              )}
            </>
          ),
        });
      } else if (note) {
        notification.success({
          key: `asset-job-done-${job.id}`,
          message: `「${job.kind_label}」这个动作跑完了（任务号 ${job.id.slice(0, 8)}）`,
          // 挂久一点：这条正是"下一步去哪看"的指路牌，1.5 秒闪过等于没说
          duration: target ? 0 : 10,
          style: { width: 520 },
          description: (
            <Space direction="vertical" size={4}>
              <Text style={{ fontSize: 12 }}>{note}</Text>
              {target && (
                <Button
                  size="small"
                  type="link"
                  style={{ padding: 0, fontSize: 12 }}
                  onClick={() => {
                    setActiveTab(target.tab);
                    notification.destroy(`asset-job-done-${job.id}`);
                  }}
                >
                  {target.label} →
                </Button>
              )}
            </Space>
          ),
        });
      } else {
        message.success(`「${job.kind_label}」后台跑完了，列表已刷新（任务号 ${job.id.slice(0, 8)}）`, 6);
      }
    } else if (job.status === 'interrupted') {
      // 批 N（评审二 P1-6）：不只说"需要重新提交"，把去哪重提说清（横幅行上也有跳转按钮）。
      // 11-10：话直接从横幅那张跳转表里取，别再在这里写一套 switch——两套必然分叉，
      // 之前「反推」就只在这套里漏了（横幅有按钮、toast 只会说"去对应页签"）。
      const resub = RESUBMIT_TARGET[job.kind];
      message.warning(
        `「${job.kind_label}」被服务重启打断，结果不可信——${resub ? resub.label : '去对应页签重新提交'}（任务号 ${job.id.slice(0, 8)}）`,
        10,
      );
    } else {
      message.error(
        `「${job.kind_label}」没跑成：${job.error || '逐条原因看素材行上的阶段标签（红＝失败，可重试）'}（任务号 ${job.id.slice(0, 8)}）`,
        8,
      );
    }
  }, [setActiveTab]);

  const role = user?.role;
  // A′：页签待办计数（轻量 total 探针；20s 一轮＋动作后事件触发，够跟手不刷爆）
  const [badges, setBadges] = useState<{ review?: number; ready?: number }>({});
  const badgePullRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        // 2026-11-11 评审（前端席 P0）：键名写错成 'token'——全站 token 存的是
        // 'auth_token'（AuthContext/client.ts），Authorization 恒为空 → 两个计数口
        // 每 40s 各 401 一次，「等审核/待投单」角标整体静默死亡。
        const H = { Authorization: `Bearer ${localStorage.getItem('auth_token') ?? ''}` };
        const [r1, r2] = await Promise.all([
          fetch('/api/assets/summaries?audit_status=pending&page_size=1', { headers: H }).then((r) => r.json()),
          fetch(`/api/assets/productions?status=order_ready&owner=${role === 'operator' ? 'me' : 'all'}&page_size=1`, { headers: H }).then((r) => r.json()),
        ]);
        if (alive) setBadges({ review: r1.total ?? 0, ready: r2.total ?? 0 });
      } catch {
        /* 计数失败静默 */
      }
    };
    badgePullRef.current = pull;
    void pull();
    const t = setInterval(pull, 20000);
    // 2026-11-11 评审（审核席 P1）：审完一条角标要 40s 才动，91→89→88 跳变像坏了。
    // 面板动作完成后 dispatch 这个事件，角标立即重拉。
    const onRefresh = () => void pull();
    window.addEventListener('asset-badges-refresh', onRefresh);
    return () => {
      alive = false;
      clearInterval(t);
      window.removeEventListener('asset-badges-refresh', onRefresh);
    };
  }, [role, reloadToken]);
  const isAdmin = role === 'admin';
  // 2026-11-11 评审（审核/投放席 P0）：光看角色不够——管理员可以按人关掉审核/投产职能
  //（users.can_review / can_produce，/auth/me 已返回）。职能关了按钮必须真的不可用，
  // 否则一线点进去被后端 403，还以为系统坏了。旧缓存没有这两个字段时按开（后端兜底）。
  const fnReview = user?.can_review !== false;
  const fnProduce = user?.can_produce !== false;
  const canProduce = fnProduce && (role === 'admin' || role === 'operator' || role === 'material');
  const canReview = fnReview && (role === 'admin' || role === 'operator');

  const roleHint = useMemo(() => {
    if (!role) return null;
    if (isAdmin) return <Tag color="red">管理员：全部操作都能做，包括余额不够时强行提交、检查不过时带理由放行</Tag>;
    if (role === 'operator') {
      if (!fnReview) return <Tag color="orange">运营（审核职能已关）：不能审核——要审文案找管理员在用户管理里开通</Tag>;
      if (!fnProduce) return <Tag color="orange">运营（投产职能已关）：不能开单投板——要投产找管理员在用户管理里开通</Tag>;
      return <Tag color="orange">运营：可导入、可反推文案、可审核过审、可出生产单与登记投板结果</Tag>;
    }
    return <Tag color="blue">素材专员：可导入/读视频/出文案，不能审自己写的文案、不能出生产单（审核台与生产单只读）</Tag>;
  }, [fnProduce, fnReview, isAdmin, role]);

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
          onProduced={handoffToDispatch}
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
          canProduce={canProduce}
          isAdmin={isAdmin}
          batchId={batchId}
          reloadToken={reloadToken}
          onGoToProduction={() => setActiveTab('production')}
          onProduced={handoffToDispatch}
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
          canWriteBack={canProduce}
          isAdmin={isAdmin}
          batchId={batchId}
          reloadToken={reloadToken}
          dispatchIds={dispatchIds}
          dispatchNotes={dispatchNotes}
          onGoToOutputs={() => setActiveTab('outputs')}
          onDispatchConsumed={() => {
            setDispatchIds(null);
            setDispatchNotes([]);
          }}
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
          onGoToProduction={() => setActiveTab('production')}
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
                  （机器去企微后台任务板建任务，你点「确认投去出片」那一下就是人工确认，投完窗口当场缩掉、成片自动收进各单「成片」列）。
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
              批次：{batchNames[batchId] || batchId.slice(0, 8)}
            </Tag>
          )}
          <Button size="small" icon={<ApartmentOutlined />} onClick={() => setCatOpen(true)}>
            钩子原型字典
          </Button>
          {isAdmin && (
            <Tooltip title="跨人投产、取号、钉号、审核、交付包的留痕——谁在什么时候动了什么">
              <Button size="small" onClick={() => void openAuditDrawer()}>
                审计
              </Button>
            </Tooltip>
          )}
          {/* 2026-11-11 评审（前端席 P1）：原来用 deskNotifySupported() 当渲染条件——
              它要求安全上下文，内网 HTTP 下按钮整个消失，写好的诊断弹窗永远打不开。
              改成「Notification API 存在就显示」：HTTP 下也能点开看解决步骤。 */}
          {deskNotify !== 'unsupported' && (
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
            开启后，后台任务（出文案／开单／投板／反推）完成、失败或被打断时，会弹一条系统
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
      <Drawer
        title="素材库审计流水（最近 200 条）"
        width={860}
        open={auditOpen}
        onClose={() => setAuditOpen(false)}
      >
        <Table
          size="small"
          rowKey="id"
          loading={auditLoading}
          dataSource={auditRows}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => (v || '').replace('T', ' ').slice(0, 19) },
            { title: '操作人', dataIndex: 'operator_name', width: 110 },
            { title: '动作', dataIndex: 'action', width: 210 },
            { title: '对象', key: 'target', width: 170, render: (_: unknown, r: Record<string, unknown>) => `${r.target_type ?? ''} ${(r.target_id as string ?? '').slice(0, 13)}` },
            { title: '变更', key: 'brief', ellipsis: true, render: (_: unknown, r: Record<string, unknown>) => (r.after_brief as string) || (r.before_brief as string) || '' },
            { title: 'IP', dataIndex: 'ip_address', width: 110 },
          ]}
        />
      </Drawer>
    </Space>
  );
};

export default AssetLibrary;
