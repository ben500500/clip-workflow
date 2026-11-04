import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Space, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetJobInfo } from '../../api/assets';
import { parseServerTime } from '../../utils/format';

const { Text } = Typography;

/** 轮询间隔：8s。出文案单条 ~95s、投产一批几分钟，8s 足够跟手又不刷爆接口。 */
const POLL_MS = 8000;

/**
 * 挂着的横幅（页面里只有一枚，但用 Set 以防哪天多处复用）。
 *
 * 为什么要这个口子：**只靠 8 秒定轮的话，刚点完"出文案/生成生产单"最长有 8 秒界面一片安静**，
 * 一线看到的和以前"转圈等"一样是"没反应"，只会再点一次；更要命的是横幅没在 `openBefore`
 * 里登记过这条任务，它终态时就不会回调 `onSettled` ⟶ 列表永远不刷新、结果没人接。
 * 台账行在接口返回**之前**就已 commit（后端 `_start_asset_job` 的顺序是硬的），
 * 所以拿到回执那一刻补查一次必然命中。
 */
const bannerNudges = new Set<() => void>();

/** 提交拿到任务号后叫一声：让横幅立刻补查一次（见上方注释） */
export const nudgeAssetJobBanner = () => {
  bannerNudges.forEach((fn) => fn());
};

/**
 * 后台任务横幅（D-1）。
 *
 * 存在的理由：出文案/投产改成「提交即回」以后，界面必须回答一线必然要问的那句
 * ——「我刚才点的那批现在在哪？还要不要我再点一次？」答案在台账里，不在这个组件里，
 * 所以刷新页面、换浏览器、切到别的标签都还在跑；组件只负责把「还在跑的」摊开来。
 *
 * 四条口径是硬的：
 *  - **没有活就不渲染**：常驻一条「一切正常」的绿条会让人以为这模块永远没事，反而没人看；
 *  - 任务从「在跑」变成终态时回调一次（`onSettled`），父层用它刷新列表——
 *    靠定时器去猜"大概 3 分钟了该刷新了"是假刷新，真跑完才刷；
 *  - **刚提交完立刻补查**（`nudgeAssetJobBanner`）：不然提交后最长 8 秒没人知道自己点了什么；
 *  - 「已中断」不当成功也不当失败，是**我们没跑完**：结果不可信，必须让人重新提交。
 */
const AssetJobBanner: React.FC<{ onSettled?: (job: AssetJobInfo) => void }> = ({ onSettled }) => {
  const [jobs, setJobs] = useState<AssetJobInfo[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  // 上一轮还在跑的 job id：这一轮少了哪个，就说明它终态了，去把它捞出来回调一次
  const openBefore = useRef<Set<string>>(new Set());
  // 已经回调过终态的 id：定轮和"提交后补查"可能撞车，同一条只让父层刷一次
  const settledOnce = useRef<Set<string>>(new Set());
  const settledCb = useRef(onSettled);
  settledCb.current = onSettled;

  const tick = useCallback(async () => {
    try {
      const res = await assetApi.listAssetJobs({ only_open: true, limit: 20 });
      const now = res.items || [];
      const nowIds = new Set(now.map((j) => j.id));
      const gone = [...openBefore.current].filter((id) => !nowIds.has(id));
      setJobs(now);
      openBefore.current = nowIds;
      for (const id of gone) {
        // 定轮和"刚提交补查"可能撞在同一秒：同一条终态只让父层刷一次，不然连弹两条 toast
        if (settledOnce.current.has(id)) continue;
        settledOnce.current.add(id);
        // 捞终态用单独一次 GET：列表口只给未结束的，终态明细（result/error）在这里
        const job = await assetApi.getAssetJob(id);
        settledCb.current?.(job);
      }
    } catch {
      // 轮询失败不弹错：台账还在，下一轮自然补上。这里报错只会把一线刷屏。
    }
  }, []);

  useEffect(() => {
    void tick();
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => clearInterval(timer);
  }, [tick]);

  // 提交拿到任务号 ⟶ 立刻补查一次（见 nudgeAssetJobBanner 上方注释）
  useEffect(() => {
    const fn = () => void tick();
    bannerNudges.add(fn);
    return () => {
      bannerNudges.delete(fn);
    };
  }, [tick]);

  if (!jobs.length) return null;

  return (
    <Alert
      type="info"
      showIcon
      message={
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Text strong>
            后台有 {jobs.length} 件事还在跑——不用守着页面，跑完这一条会自己消失（也可以直接刷新列表）
          </Text>
          {!collapsed &&
            jobs.map((j) => {
              const done = j.progress?.done ?? null;
              const totalUnits = j.planned_units ?? j.progress?.total ?? null;
              const started = j.created_at ? parseServerTime(j.created_at)?.format('HH:mm:ss') : '';
              return (
                <Text key={j.id} style={{ fontSize: 12 }}>
                  「{j.kind_label}」{j.status_label}
                  {done !== null && totalUnits !== null ? `（已收敛 ${done}/${totalUnits} 条）` : ''}
                  {started ? ` · ${started} 提交` : ''}
                  {j.status === 'interrupted' ? ' · 这条的结果不可信，需要重新提交' : ''}
                </Text>
              );
            })}
        </Space>
      }
      action={
        <Space size={4}>
          <Button size="small" type="text" icon={<ReloadOutlined />} onClick={() => void tick()}>
            刷新
          </Button>
          <Button size="small" type="text" onClick={() => setCollapsed((c) => !c)}>
            {collapsed ? `展开(${jobs.length})` : '收起'}
          </Button>
        </Space>
      }
    />
  );
};

export default AssetJobBanner;
