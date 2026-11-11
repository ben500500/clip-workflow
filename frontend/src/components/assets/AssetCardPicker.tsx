import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Select, Space, Spin, Tag, Tooltip, Typography, Upload, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetItem } from '../../api/assets';
import { aspectShortText } from './AssetBits';

const { Text } = Typography;

/** 一次拉多少张：后端 page_size 封顶 200，角色卡是「一剧几张」的量级，200 足够覆盖在用剧 */
const LOAD_SIZE = 200;

interface Props {
  /** 已选卡 id，**数组顺序＝板上 picDatas 顺序**（第一张＝主形象） */
  value: string[];
  onChange: (ids: string[]) => void;
  /** 弹窗开着才拉：库里的图随时有人在传，进页面缓存一次会让新卡看不见 */
  active: boolean;
  /**
   * 批 L：就地上传的卡挂到这个批次名下（=被投产素材所在批次，账面干净）。
   * 不传（生产单页「全部」视图开单）就新建一个独立小批次，名字自动带「角色卡」。
   */
  batchId?: string;
}

/**
 * 批 G：投产时的「从素材库挑角色卡」。
 *
 * 为什么不是当初那个手填框：那个框里的字符串被后端**原样当 MinIO key 用**，
 * 打错一个字符照样建单成功，只是投出去是一条没有卡的片——静默、事后查不到成因。
 * 这里改成只给「库里真实存在的图片」选，id 由列表带回来，选不到不存在的卡；
 * 多张卡按点选顺序排，界面上一眼能看到谁是第 1 张（＝板上第 1 张 picData＝主形象）。
 *
 * 画幅提醒为什么放在挑卡这一屏：**画幅由角色卡宽高比决定**（实测口径，
 * 提示词写 9:16 压不住一张横版三视图卡）。投产后再说「这支出横屏了」已经花过钱了。
 */
const AssetCardPicker: React.FC<Props> = ({ value, onChange, active, batchId }) => {
  const [cards, setCards] = useState<AssetItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [covers, setCovers] = useState<Record<string, string | null>>({});
  // 批 L：就地上传。串行链防并发建批——第一张没建上批次第二张就发出，会裂成两个批次
  const [uploading, setUploading] = useState(false);
  const chainRef = useRef<Promise<unknown>>(Promise.resolve());
  // 批 M（评审二·P2）：排队的上传张数。原来每段 .finally 都 setUploading(false)——
  // 第二张还在传时第一张完成就把 loading 灯提前熄了，看起来像传完其实没有。
  const pendingUploads = useRef(0);
  // 2026-11-11 评审（前端席 P1）：就地传卡链内记住第一张新建的批次 id——
  // 原来每张都各自建批（batch_id=undefined），拖 5 张卡裂 5 个批次，台账对账废掉
  const createdBatchIdRef = useRef<string | undefined>(undefined);
  const valueRef = useRef(value);
  valueRef.current = value;
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    assetApi
      .listAssets({ media_kind: 'image', page_size: LOAD_SIZE, sort: 'created_desc' })
      .then((res) => {
        if (cancelled) return;
        setCards(res.items || []);
        setTotal(res.total || 0);
        const ids = (res.items || []).map((a) => a.id);
        if (!ids.length) {
          setCovers({});
          return null;
        }
        // 缩略图走封面直链（图片入库时 cover_image_key＝原图 key，不抽帧也是这张）
        return assetApi
          .framesForAssets(ids)
          .then((f) => {
            if (!cancelled) setCovers(f.cover_url || {});
          })
          .catch(() => {
            // 直链拉不到只影响看图，不影响选卡：留白 + 名字照样能选
            if (!cancelled) setCovers({});
          });
      })
      .catch((e) => {
        if (!cancelled) setLoadError((e as Error).message || '角色卡列表拉不到');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active, reloadTick]);

  const byId = useMemo(() => {
    const m: Record<string, AssetItem> = {};
    cards.forEach((a) => {
      m[a.id] = a;
    });
    return m;
  }, [cards]);

  /** 已选但这次没在列表里的 id（多半是那张卡刚被删）：不静默丢掉，点名让人重选 */
  const missingSelected = useMemo(() => value.filter((id) => !byId[id]), [value, byId]);

  const options = useMemo(
    () =>
      cards.map((a) => {
        const noFile = !a.file_key;
        return {
          value: a.id,
          // 没文件的行后端会 400（「桶里没有文件…先重新入库再投产」），这里直接不给选
          disabled: noFile,
          label: `${a.code || a.id.slice(0, 8)} · ${a.file_name || '未命名'} · ${aspectShortText(a.aspect)}${
            noFile ? ' · 桶里没文件，不能投' : ''
          }`,
        };
      }),
    [cards],
  );

  /**
   * 顺序由我们维护，不指望组件给的数组顺序：
   * 保留原有顺序、新增的排在后面，删掉谁都不补位——「第几张卡」必须和屏幕上看到的一致。
   */
  const onPick = (picked: string[]) => {
    const kept = value.filter((id) => picked.includes(id));
    const added = picked.filter((id) => !value.includes(id));
    onChange([...kept, ...added]);
  };

  const move = (index: number, delta: number) => {
    const next = [...value];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const selected = value.map((id) => byId[id]).filter(Boolean) as AssetItem[];
  const orientations = Array.from(
    new Set(selected.map((a) => a.aspect?.orientation || 'unknown')),
  );
  const landscape = selected.filter((a) => a.aspect?.orientation === 'landscape');
  const unknownSize = selected.filter((a) => !a.aspect?.ratio);

  /** 批 L：就地上传角色卡。逐张串行（没有 batch_id 时第一张要先建上批次，
   *  并发第二张会裂成两个批次）；成功即入库＋自动排进已选卡末尾＋刷新列表。
   *  2026-11-11 评审（前端席 P1）：链内记住第一张新建的 batch_id 传给后续。 */
  const uploadCard = (file: File) => {
    pendingUploads.current += 1;
    setUploading(true);
    chainRef.current = chainRef.current
      .then(() => {
        const bid = createdBatchIdRef.current ?? batchId ?? undefined;
        return assetApi.uploadBatch({
          files: [file],
          batch_id: bid,
          name: bid ? undefined : '角色卡（投产时就地传）',
        });
      })
      .then((res) => {
        if (!createdBatchIdRef.current && res.batch_id) createdBatchIdRef.current = res.batch_id;
        const ok = res.items || [];
        if (ok.length) {
          onChange([...valueRef.current, ...ok.map((a) => a.id)]);
          setReloadTick((t) => t + 1);
          message.success(`已入库并选上：${ok.map((a) => a.file_name || a.code).join('、')}`);
          // 画幅提醒跟着走：横版卡会出横屏片（提示词写 9:16 压不住），必须传完当场说
          const warns = (res.image_notes || []).filter((n) => n.notes?.length);
          if (warns.length) {
            message.warning(
              warns.map((n) => `${n.file_name || '图片'}：${n.notes.join('；')}`).join(' ｜ '),
              8,
            );
          }
        }
        (res.failed || []).forEach((f) => message.error(`${f.file_name} 没传上：${f.error}`));
      })
      .catch((e) => message.error((e as Error).message || '角色卡上传失败'))
      .finally(() => {
        // 只有整条链都排空了才熄灯（评审二·P2：否则排队中的第二张会没灯）
        pendingUploads.current -= 1;
        if (pendingUploads.current <= 0) {
          pendingUploads.current = 0;
          setUploading(false);
        }
      });
  };

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <Tooltip title="顺序＝板上的图片顺序，第 1 张＝主形象；同一部剧请用同一批卡（「上下集换装」就是卡没锁住导致的）">
        <Text style={{ fontSize: 12 }}>人物卡（三视图等，可多张）</Text>
      </Tooltip>

      {/*
        批 M（11-09 用户口径）：就地传卡从「点按钮选文件」升级成**可拖拽区**——
        手上有三视图的人通常是文件夹里拖一把过来，而不是在文件选择器里翻目录。
        行为一点没变：仍是 beforeUpload 返回 false 自己接管上传、逐张串行、
        传完自动选上并刷新列表（并发拆批的坑见 uploadCard 那段注释）。
      */}
      <Upload.Dragger
        accept="image/jpeg,image/png,image/webp"
        multiple
        showUploadList={false}
        disabled={!active || uploading}
        // 压矮一点：这块是在投产弹窗里，默认 48px 图标 + 16px 内边距会把卡片列表顶出屏
        style={{ padding: '6px 12px' }}
        beforeUpload={(f) => {
          uploadCard(f as unknown as File);
          return false;
        }}
      >
        <p className="ant-upload-drag-icon" style={{ marginBottom: 2 }}>
          {/* 尺寸写在内层：antd 的 .ant-upload-drag-icon .anticon{font-size:48px} 会盖掉父级字号 */}
          <InboxOutlined style={{ fontSize: 22 }} />
        </p>
        <p className="ant-upload-text" style={{ fontSize: 13, marginBottom: 2 }}>
          {uploading ? '正在上传（传完自动选上）…' : '把人物三视图拖进来，或点击选择（jpg/png，可多张）'}
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12, marginBottom: 0 }}>
          {batchId ? '传的卡挂在当前批次名下' : '当前没锁批次：传的卡会单独建一个小批次'}
        </p>
      </Upload.Dragger>

      {loading && !cards.length ? (
        <Spin size="small" />
      ) : loadError ? (
        <Alert type="warning" showIcon message={`角色卡列表拉不到：${loadError}`} />
      ) : !cards.length ? (
        <Alert
          type="info"
          showIcon
          message="素材库里还没有图片素材"
          description={
            <Text type="secondary" style={{ fontSize: 12 }}>
              把定妆照/三视图 jpg·png 直接拖进上面那块区域（或点它选文件），传完自动选上。
              图片只作生产输入，不参与读视频、出文案、拼接，也不计费。
              不挂卡也能建单，只是成片人物形象由模型自己发挥。
            </Text>
          }
        />
      ) : (
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="从素材库挑角色卡（可按编号/文件名搜）"
          value={value}
          onChange={onPick}
          options={options}
          optionFilterProp="label"
          maxTagCount="responsive"
          allowClear
        />
      )}

      {total > cards.length && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          库里共 {total} 张图，这里只列最近 {cards.length} 张（按入库时间倒序）——
          找不到说明那张太早，去素材列表按编号搜出来再看要不要重传。
        </Text>
      )}

      {!!missingSelected.length && (
        <Alert
          type="warning"
          showIcon
          message={`有 ${missingSelected.length} 张已选的卡不在当前列表里（多半刚被删）：${missingSelected
            .map((x) => x.slice(0, 8))
            .join('、')}——提交会被后端点名拒掉，重新挑一次，别拿旧快照投产`}
        />
      )}

      {!!selected.length && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {selected.map((a, i) => {
            const url = covers[a.id];
            const land = a.aspect?.orientation === 'landscape';
            return (
              <div
                key={a.id}
                style={{
                  width: 122,
                  border: `1px solid ${land ? '#ffa39e' : '#d9d9d9'}`,
                  borderRadius: 4,
                  padding: 4,
                  background: '#fff',
                }}
              >
                <div style={{ position: 'relative' }}>
                  {url ? (
                    <img
                      src={url}
                      alt={a.code || a.file_name || '角色卡'}
                      style={{
                        width: '100%',
                        height: 96,
                        objectFit: 'contain',
                        display: 'block',
                        background: '#fafafa',
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: '100%',
                        height: 96,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        border: '1px dashed #d9d9d9',
                        color: '#bfbfbf',
                        fontSize: 11,
                      }}
                    >
                      图打不开
                    </div>
                  )}
                  <Tag color="blue" style={{ position: 'absolute', left: 2, top: 2, marginInlineEnd: 0 }}>
                    {i + 1}
                  </Tag>
                </div>
                <div style={{ fontSize: 11, lineHeight: '16px' }}>
                  <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {a.code || a.id.slice(0, 8)}
                  </div>
                  <Tooltip title={a.file_name || ''}>
                    <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: '#8c8c8c' }}>
                      {a.file_name || '未命名'}
                    </div>
                  </Tooltip>
                  <Tag color={land ? 'red' : a.aspect?.ratio ? 'green' : 'orange'} style={{ marginTop: 2 }}>
                    {aspectShortText(a.aspect)}
                  </Tag>
                </div>
                <Space size={2} style={{ marginTop: 2 }}>
                  <Button size="small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="往前挪">
                    ↑
                  </Button>
                  <Button size="small" disabled={i === selected.length - 1} onClick={() => move(i, 1)} aria-label="往后挪">
                    ↓
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() => onChange(value.filter((_, idx) => idx !== i))}
                    aria-label="移除这张卡"
                  >
                    去
                  </Button>
                </Space>
              </div>
            );
          })}
        </div>
      )}

      {!!landscape.length && (
        <Alert
          type="error"
          showIcon
          message={`${landscape.length} 张是横版卡：画幅由角色卡宽高比决定，提示词写 9:16 也压不住，投出去会是横屏`}
          description={
            <Text type="secondary" style={{ fontSize: 12 }}>
              {landscape.map((a) => `${a.code || a.id.slice(0, 8)}（${aspectShortText(a.aspect)}）`).join('、')}
              ——真想横版就别动；想要竖屏换竖版卡（720×1280 一类）。
            </Text>
          }
        />
      )}
      {orientations.length > 1 && (
        <Alert
          type="warning"
          showIcon
          message={`这批卡方向不一致（${orientations
            .map((o) => (o === 'unknown' ? '量不到' : o === 'landscape' ? '横版' : o === 'square' ? '方图' : '竖屏'))
            .join('、')}）：同一支片里换画幅，成片两头不靠`}
        />
      )}
      {!!unknownSize.length && (
        <Alert
          type="warning"
          showIcon
          message={`${unknownSize.length} 张量不到尺寸（${unknownSize
            .map((a) => a.code || a.id.slice(0, 8))
            .join('、')}）：画幅按模型默认走，投产前自己看一眼原图`}
        />
      )}
    </Space>
  );
};

export default AssetCardPicker;
