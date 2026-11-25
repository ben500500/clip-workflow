import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Spin, Typography } from 'antd';
import { assetApi, type AssetFrameSlot } from '../../../api/assets';

const { Text } = Typography;

/**
 * 极简模式的「看得见」部件（2026-11-24，用户原话：素材也没有预览）。
 *
 * 口径与审核台/成片墙一致，只是把同一套东西搬到极简这几屏：
 *  · 缩略图＝该素材已抽好的帧（批 F 的 `/assets/frames`），**没抽到＝没预览**，
 *    不报错、不拦任何一步（帧只是呈现层，不参与过审/投产判定）；
 *  · 点开＝内联播原片，走批 E 的 `source-preview`。这个口**不能**带
 *    `response-content-disposition=attachment`，带了浏览器只认下载、`<video>` 就是黑屏；
 *  · 图片素材（批 G 的角色卡那类）不能进播放器——`<video>` 解不了静态图，直接放图。
 */

/** 一页对象的封面图：按素材 id 批量取帧（50 一块已在上层函数里切好），拿不到就是没预览 */
export const useCoverMap = (assetIds: Array<string | null | undefined>) => {
  // 依赖用排序后的 id 串：同一页换个顺序不该把请求再打一遍
  const key = Array.from(new Set(assetIds.filter((x): x is string => !!x))).sort().join(',');
  const [slots, setSlots] = useState<Record<string, AssetFrameSlot>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!key) {
      setSlots({});
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    assetApi
      .framesForAssets(key.split(','))
      .then((res) => { if (!cancelled) setSlots(res.by_asset || {}); })
      .catch(() => { if (!cancelled) setSlots({}); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [key]);

  const cover = useMemo(() => {
    const out: Record<string, string | null> = {};
    key.split(',').filter(Boolean).forEach((id) => { out[id] = slots[id]?.thumbs?.[0]?.url || null; });
    return out;
  }, [key, slots]);

  return { cover, slots, loading };
};

/**
 * 一格缩略图（纯呈现，自带点击回调）。
 *
 * 列表里几百行时用这个 + 全组件共享一个 `VideoPreviewModal`：
 * 每行各自挂一个 Modal 组件树，200 行就是 200 个（哪怕没开），白烧渲染。
 */
export const ThumbCell: React.FC<{
  src?: string | null;
  /** 取帧请求还在路上 */
  loading?: boolean;
  title: string;
  height?: number;
  /** 不给＝这条没得播（原片不在库里），格子只表示"没预览" */
  onPlay?: () => void;
}> = ({ src, loading, title, height = 64, onPlay }) => {
  const boxWidth = Math.round(height * 0.5625);
  if (!src) {
    return (
      <div
        style={{
          height, width: boxWidth, background: '#fafafa', border: '1px dashed #d9d9d9',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, color: '#bfbfbf', textAlign: 'center', padding: 2, borderRadius: 2,
        }}
        title="原片还没下载到桶里，或抽帧没跑成——不影响改稿与投产"
      >
        {loading ? <Spin size="small" /> : '无图'}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={title}
      onClick={onPlay}
      style={{
        height, width: boxWidth, objectFit: 'cover', display: 'block',
        background: '#000', cursor: onPlay ? 'zoom-in' : 'default', borderRadius: 2,
      }}
    />
  );
};

/**
 * 点开后播这条素材的原片。
 *
 * `mode==='external'`（只有站外分享链、桶里没文件）后端给不出内联地址，
 * 这里就把 `note`／原始链摆出来说清"为什么播不了"，而不是给一个黑框。
 */
export const VideoPreviewModal: React.FC<{
  open: boolean;
  onClose: () => void;
  title: string;
  assetId: string | null;
  /** 图片素材：直接放大这张图，不进播放器 */
  imageUrl?: string | null;
  width?: number;
}> = ({ open, onClose, title, assetId, imageUrl, width = 520 }) => {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [url, setUrl] = useState<string | null>(null);
  const [note, setNote] = useState<string>('');

  useEffect(() => {
    if (!open) return;
    if (imageUrl) {
      setState('ready');
      setUrl(null);
      return;
    }
    if (!assetId) return;
    let cancelled = false;
    setState('loading');
    setUrl(null);
    setNote('');
    assetApi
      .previewAssetSource(assetId)
      .then((res) => {
        if (cancelled) return;
        setUrl(res.url);
        setNote(res.note || (res.mode === 'external' ? '这条只有站外链接，桶里没有文件，播不了。' : ''));
        setState(res.url ? 'ready' : 'error');
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setNote(e.message || '取预览地址失败');
        setState('error');
      });
    return () => { cancelled = true; };
  }, [open, assetId, imageUrl]);

  return (
    <Modal open={open} onCancel={onClose} footer={null} width={width} destroyOnClose title={title}>
      {imageUrl ? (
        <img src={imageUrl} alt={title} style={{ width: '100%', display: 'block', background: '#000' }} />
      ) : state === 'loading' ? (
        <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin tip="取播放地址…" />
        </div>
      ) : state === 'ready' && url ? (
        <video src={url} controls autoPlay preload="metadata" style={{ width: '100%', maxHeight: 480, background: '#000' }} />
      ) : (
        <div style={{ padding: '28px 12px', textAlign: 'center' }}>
          <Text type="secondary" style={{ fontSize: 13 }}>{note || '这条播不了（原片还没下载到桶里，或直链取不到）'}</Text>
        </div>
      )}
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        预览用的内联地址 1 小时过期，关掉重开就是新的。
      </Text>
    </Modal>
  );
};

/** 一格缩略图：有图给图、没图给占位，点一下就播（图片素材则放大看） */
export const ThumbPlay: React.FC<{
  assetId: string | null | undefined;
  cover?: string | null;
  loading?: boolean;
  title: string;
  /** 图片素材（角色卡）走这条：不进播放器 */
  imageUrl?: string | null;
  height?: number;
}> = ({ assetId, cover, loading, title, imageUrl, height = 64 }) => {
  const [open, setOpen] = useState(false);
  const boxWidth = Math.round(height * 0.5625);
  const src = imageUrl || cover || null;

  const cell = src ? (
    <img
      src={src}
      alt={title}
      onClick={() => assetId || imageUrl ? setOpen(true) : undefined}
      style={{
        height, width: boxWidth, objectFit: 'cover', display: 'block',
        background: '#000', cursor: 'zoom-in', borderRadius: 2,
      }}
    />
  ) : (
    <div
      style={{
        height, width: boxWidth, background: '#fafafa', border: '1px dashed #d9d9d9',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, color: '#bfbfbf', textAlign: 'center', padding: 2, borderRadius: 2,
      }}
      title="原片还没下载到桶里，或抽帧没跑成——不影响改稿与投产"
    >
      {loading ? <Spin size="small" /> : '无图'}
    </div>
  );

  return (
    <>
      {cell}
      <VideoPreviewModal
        open={open}
        onClose={() => setOpen(false)}
        title={title}
        assetId={open ? (assetId ?? null) : null}
        imageUrl={imageUrl}
      />
    </>
  );
};
