import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Spin, Typography } from 'antd';
import type { AssetFrameItem, AssetFrameSlot } from '../../api/assets';
import { assetApi } from '../../api/assets';

const { Text } = Typography;

/**
 * 一页素材的卡片图（批 F）。
 *
 * 抽帧是后台任务，导入完不一定立刻有图；这里的口径和后端一致：
 * **拿图失败＝这条没预览**，不报错、不拦审核。
 * presign 直链 1 小时过期，所以每次列表翻页/换筛选都重新拉一次（不缓存旧直链）。
 */
export const useAssetFrames = (assetIds: string[]) => {
  const [slots, setSlots] = useState<Record<string, AssetFrameSlot>>({});
  const [loading, setLoading] = useState(false);
  // 依赖用排序后的 id 串，避免"同一页换个顺序"把请求再打一遍
  const key = useMemo(() => Array.from(new Set(assetIds.filter(Boolean))).sort().join(','), [assetIds]);

  useEffect(() => {
    if (!key) {
      setSlots({});
      return;
    }
    let cancelled = false;
    setLoading(true);
    assetApi
      .framesForAssets(key.split(','))
      .then((res) => {
        if (!cancelled) setSlots(res.by_asset || {});
      })
      .catch(() => {
        // 整批拉不到也不弹错：卡片自己画「没有预览图」
        if (!cancelled) setSlots({});
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  return { slots, loading };
};

/** 单张帧图：加载失败（直链过期/对象被清）要自己说"打不开"，不能留一个破图标让人以为坏了 */
const FrameImg: React.FC<{ frame: AssetFrameItem; height: number; onOpen?: () => void }> = ({
  frame,
  height,
  onOpen,
}) => {
  const [broken, setBroken] = useState(false);
  if (!frame.url || broken) {
    return (
      <div
        style={{
          height,
          width: Math.round(height * 0.5625),
          background: '#fafafa',
          border: '1px dashed #d9d9d9',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 11,
          color: '#bfbfbf',
          textAlign: 'center',
          padding: 2,
        }}
      >
        图打不开
      </div>
    );
  }
  return (
    <img
      src={frame.url}
      alt={`第 ${Math.round((frame.t_offset ?? 0) * 10) / 10} 秒`}
      onError={() => setBroken(true)}
      onClick={onOpen}
      style={{
        height,
        width: Math.round(height * 0.5625),
        objectFit: 'cover',
        display: 'block',
        cursor: onOpen ? 'zoom-in' : 'default',
        background: '#000',
      }}
    />
  );
};

/**
 * 卡片左侧的三帧横排（10%／45%／80%，不取 t=0）。点开＝九宫格一览。
 *
 * 三帧是**同一素材**的三帧，同素材的多条候选共用一份，所以这里只吃 slot 不吃 summary。
 */
export const FrameStrip: React.FC<{
  slot?: AssetFrameSlot;
  loading?: boolean;
  /** 窄卡片里用 78，详情抽屉里可以放大 */
  height?: number;
}> = ({ slot, loading, height = 78 }) => {
  const [gridOpen, setGridOpen] = useState(false);
  const thumbs = slot?.thumbs || [];
  const grid = slot?.grid || null;
  const boxWidth = Math.round(height * 0.5625) * 3 + 4;

  if (loading && !thumbs.length) {
    return (
      <div
        style={{
          width: boxWidth,
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '1px dashed #f0f0f0',
        }}
      >
        <Spin size="small" />
      </div>
    );
  }
  if (!thumbs.length && !grid) {
    return (
      <div
        style={{
          width: boxWidth,
          height,
          background: '#fafafa',
          border: '1px dashed #d9d9d9',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 2,
          fontSize: 11,
          color: '#bfbfbf',
          textAlign: 'center',
          padding: 4,
        }}
        title="这里没有图，是因为这条素材的原片还没下载到我们自己的桶里。在列表或抽屉里点「下载原片」，下载成功后系统会自动抽帧补上图；没图不影响审核与投产。"
      >
        <span>没有预览图</span>
        <span style={{ color: '#8c8c8c' }}>下载原片后自动补</span>
      </div>
    );
  }
  return (
    <>
      <div style={{ display: 'flex', gap: 2, cursor: 'pointer' }} onClick={() => setGridOpen(true)}>
        {(thumbs.length ? thumbs : []).slice(0, 3).map((f) => (
          <FrameImg key={f.id} frame={f} height={height} />
        ))}
      </div>
      <Modal
        open={gridOpen}
        onCancel={() => setGridOpen(false)}
        footer={null}
        width={grid ? 520 : 720}
        title={grid ? '九宫格：整片均匀取 9 帧' : '这条只有单帧，没有九宫格'}
      >
        {grid?.url ? (
          <img src={grid.url} alt="九宫格" style={{ width: '100%', display: 'block' }} />
        ) : (
          <div style={{ display: 'flex', gap: 4 }}>
            {thumbs.map((f) => (
              <FrameImg key={f.id} frame={f} height={300} />
            ))}
          </div>
        )}
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          帧是审核用的**呈现层**：抽自原片第 {thumbs.map((t) => Math.round((t.t_offset ?? 0) * 10) / 10).join(' / ') || '-'} 秒，
          不参与过审、投产、导出的任何判定。
        </Text>
      </Modal>
    </>
  );
};
