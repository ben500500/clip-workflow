import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Descriptions, Divider, Drawer, Empty, List, Modal, Space, Spin, Tabs, Tag, Tooltip, Typography, message,
} from 'antd';
import { CopyOutlined, DownloadOutlined, MergeCellsOutlined, ReloadOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetDetailResponse, AssetOutput, AssetSourceDownloadResult } from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import {
  AssetStatusTag, AuditStatusTag, MediaKindTag, ProductionStateTag, RiskTags, StageTags, MonoText,
  aspectShortText, durationText, isImageAsset, yuan,
} from './AssetBits';
import AssetComposeModal from './AssetComposeModal';
import { withCrossPersonConfirm } from './crossPerson';
import {
  CategorySelect, CategoryTag, invalidateAssetCategories, useAssetCategories,
} from './AssetCategoryBits';
import { HOOK_STYLE_LABELS } from '../../api/assets';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  assetId: string | null;
  onClose: () => void;
  /** 抽屉里收敛了反推任务或回源解析后，通知列表重取 */
  onChanged?: () => void;
  /** 只有 material/operator/admin 才显示「回源解析」按钮；后端仍按角色拦 */
  canProduce?: boolean;
}

/** style_tag 后端是自由文本（截 20 字），管线会写入历史标记；这里给老标记一句人话解释，没命中就悬停不弹 */
const STYLE_TAG_GLOSS: Record<string, string> = {
  导读文单拼: '导读文＋单条拼接：成片由「导读文」开头段和单条正文直接拼接出来',
};

/**
 * 备注是追加式的：后端每次反推失败都往尾上拼一行（`\n反推失败：{task.error}`），
 * 重试再败就会同一条失败信息出现两遍——渲染时按整行去重，只显示第一次。
 */
const dedupeNoteLines = (note: string): string => {
  const seen = new Set<string>();
  return note
    .split('\n')
    .filter((line) => {
      const key = line.trim();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .join('\n');
};

/**
 * 素材详情抽屉：一条素材的全链路状态 + 候选文案 + 生产单 + 反推文案稿。
 *
 * 一个 `GET /assets/{id}` 就把这四块带回来（详情与列表共用同一套计数字段），
 * 所以这里不必再发三次请求、也不必判 nil。
 */
const AssetDetailDrawer: React.FC<Props> = ({ open, assetId, onClose, onChanged, canProduce }) => {
  const [data, setData] = useState<AssetDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resolveBusy, setResolveBusy] = useState(false);
  /** 拼接产物：`GET /assets/{id}` 不带 outputs，所以单独取一次 */
  const [outputs, setOutputs] = useState<AssetOutput[]>([]);
  const [composeOpen, setComposeOpen] = useState(false);
  /** 钩子原型（11-04 拍板①）：抽屉里就地改，改完把新值并回本地 data，不整块重拉 */
  const cats = useAssetCategories();
  const [catBusy, setCatBusy] = useState(false);

  /**
   * 上栏播放器（批 E）：一条素材一个播放器，原片和拼接产物都往这里换源。
   *
   * 为什么之前"播不了"：旧接口 presign 时带了 `response-content-disposition=attachment`，
   * 浏览器拿到一律当附件存盘，`<video src>` 挂上去就是黑屏——所以这里必须走
   * `source-preview` / `preview` 两个**内联**口，不能复用 `source-download`。
   * 拖进度条的 Range 由对象存储直接响应，前端不管，也不占后端连接。
   */
  const [player, setPlayer] = useState<{
    url: string;
    label: string;
    /** 播放器上方那排角标：时长／画幅／来路，都跟着"当前在播的这一段"走 */
    duration?: number | null;
    resolution?: string | null;
    platform?: string | null;
    /** 验收结论：failed 的产物照样能看（看一眼为什么废），但要在播放器上方标红 */
    qc?: string | null;
    qcNote?: string | null;
  } | null>(null);
  const [playerBusy, setPlayerBusy] = useState(false);
  /** 播放器自己报的错（直链过期、混合内容、网络不通都长这样） */
  const [playerErr, setPlayerErr] = useState<string | null>(null);

  const loadSourcePreview = useCallback(async (id: string) => {
    setPlayerBusy(true);
    setPlayerErr(null);
    try {
      const res = await assetApi.previewAssetSource(id);
      // 链接素材没有内联源：不报错，交给下面的占位区说明怎么办
      setPlayer(
        res.url
          ? {
              url: res.url,
              label: res.file_name || res.asset_code,
              duration: res.duration,
              resolution: res.resolution,
              platform: res.platform,
            }
          : null,
      );
    } catch (e) {
      setPlayerErr((e as Error).message || '取预览地址失败');
    } finally {
      setPlayerBusy(false);
    }
  }, []);

  const previewProduct = async (o: AssetOutput) => {
    setPlayerBusy(true);
    setPlayerErr(null);
    try {
      const res = await assetApi.previewOutput(o.id);
      setPlayer({
        url: res.url,
        label: res.file_name || '拼接产物',
        duration: res.duration,
        resolution: res.resolution,
        qc: res.qc_status,
        qcNote: res.qc_note,
      });
    } catch (e) {
      setPlayerErr((e as Error).message || '取产物预览失败');
    } finally {
      setPlayerBusy(false);
    }
  };

  /**
   * 链接素材想播只能现取时效直链：走 `POST /assets/resolve`，**0.01 元/次**、计入批次
   * 成本，所以这是人手点的动作，绝不在打开抽屉时自动发起（取片和取时长是两笔钱）。
   */
  const playLinkSource = async () => {
    if (!assetId) return;
    setPlayerBusy(true);
    setPlayerErr(null);
    try {
      const res = await withCrossPersonConfirm((c) =>
        assetApi.resolveAssets({ asset_ids: [assetId], cross_person_confirm: c }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做
      const item = res.results?.[0];
      if (item?.ok && item.play_url) {
        setPlayer({ url: item.play_url, label: '原站时效直链（约 6 小时内有效）', duration: item.duration });
        message.success(`已取到直链播放（本条实扣 ${yuan(item.charged)}，计入批次成本）`);
      } else {
        setPlayerErr(item?.error || item?.note || res.message || '没取到直链，这条暂时播不了');
      }
      await fetchDetail(assetId);
      onChanged?.();
    } catch (e) {
      setPlayerErr((e as Error).message || '取直链失败');
    } finally {
      setPlayerBusy(false);
    }
  };

  const fetchOutputs = useCallback(async (id: string) => {
    try {
      const res = await assetApi.listOutputs({ asset_id: id });
      setOutputs(res.items || []);
    } catch {
      // 产物列表失败不该把整个抽屉判成打不开：详情是主链路，产物是附属信息
      setOutputs([]);
    }
  }, []);

  const fetchDetail = useCallback(async (id: string) => {
    setLoading(true);
    try {
      setData(await assetApi.getAsset(id));
    } catch (e) {
      message.error((e as Error).message || '加载素材详情失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && assetId) {
      fetchDetail(assetId);
      fetchOutputs(assetId);
      // 播放器每次开抽屉都从"没源"开始，否则会看到上一条素材的画面
      setPlayer(null);
      setPlayerErr(null);
      loadSourcePreview(assetId);
    }
    if (!open) {
      setData(null);
      setOutputs([]);
      setPlayer(null);
      setPlayerErr(null);
    }
  }, [open, assetId, fetchDetail, fetchOutputs, loadSourcePreview]);

  /**
   * 就地改这条素材的钩子原型。留空提交＝清成未分类（后端 `category_id=null` 的语义）。
   * 改成功只把 `category_id/category_name` 并回本地 data：抽屉里其余四块（文案/生产单/反推文案稿）
   * 和这次改动无关，整块重拉会让人看到一次白屏。
   */
  const assignCategory = async (next?: string) => {
    if (!assetId) return;
    setCatBusy(true);
    try {
      const res = await assetApi.assignCategory({ asset_ids: [assetId], category_id: next || null });
      if (res.not_found?.length) {
        message.error('这条素材库里已经查不到，分类没改成');
        return;
      }
      const name = next ? cats.byId[next]?.name || null : null;
      setData((prev) =>
        prev
          ? { ...prev, asset: { ...prev.asset, category_id: next || null, category_name: name } }
          : prev,
      );
      (res.notes || []).forEach((n) => message.info(n));
      message.success(
        res.asset_changed ? `原型已改成「${name || '未分类'}」（改动留档）` : '原型没有变化',
      );
      invalidateAssetCategories();
      onChanged?.();
    } catch (e) {
      message.error((e as Error).message || '改原型失败');
    } finally {
      setCatBusy(false);
    }
  };

  const refreshPrompt = async () => {
    if (!assetId) return;
    setBusy(true);
    try {
      const res = await assetApi.refreshAssetPrompt(assetId);
      setData((prev) => (prev ? { ...prev, asset: res.asset, prompt_task: res.prompt_task } : prev));
      message.success(res.duration_note || '已更新视频读取进度');
      onChanged?.();
    } catch (e) {
      message.error((e as Error).message || '更新失败（该素材可能还没有反推文案任务）');
    } finally {
      setBusy(false);
    }
  };

  /** 单条查时长：0.01 元/次，是「想知道这条到底多长」的唯一显式口子 */
  const resolveOne = async () => {
    if (!assetId) return;
    setResolveBusy(true);
    try {
      const res = await withCrossPersonConfirm((c) =>
        assetApi.resolveAssets({ asset_ids: [assetId], cross_person_confirm: c }),
      );
      if (!res) return; // 取消了「替他人批次」确认：什么都不做
      const item = res.results?.[0];
      if (!item) {
        message.info(res.message);
      } else if (item.ok) {
        Modal.info({
          title: `查时长完成（本条实扣 ${yuan(item.charged)}）`,
          width: 580,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>时长：{item.duration ? `${Math.round(item.duration)}s` : '仍未取到'}</Text>
              <Text>渠道：{item.channel || '-'}</Text>
              {item.title && <Text>标题：{item.title}</Text>}
              {item.note && <Alert type="warning" showIcon message={item.note} />}
              {item.play_url && (
                <Paragraph copyable={{ text: item.play_url }} ellipsis={{ rows: 2 }}>
                  <MonoText>{item.play_url}</MonoText>
                </Paragraph>
              )}
            </Space>
          ),
        });
      } else {
        message.error(item.error || item.note || '查时长没拿到结果');
      }
      await fetchDetail(assetId);
      onChanged?.();
    } catch (e) {
      message.error((e as Error).message || '查时长失败');
    } finally {
      setResolveBusy(false);
    }
  };

  /** 拼接产物下载：presigned 外链（后端对验收 failed 的会 409 挡下，不静默交付） */
  const downloadProduct = async (o: AssetOutput) => {
    try {
      const res = await assetApi.downloadOutput(o.id);
      window.open(res.url, '_blank');
      message.success(`已打开 ${res.file_name || o.file_name || '产物'}`);
    } catch (e) {
      message.error((e as Error).message || '取产物链接失败');
    }
  };

  const showSource = async () => {
    if (!assetId) return;
    try {
      const res: AssetSourceDownloadResult = await assetApi.downloadAssetSource(assetId);
      if (res.url) {
        window.open(res.url, '_blank');
        message.success(`已打开原片直链（${res.expires_in ?? 3600}s 内有效）`);
      } else {
        Modal.info({
          title: '这条素材不在自有桶',
          width: 580,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>{res.note}</Text>
              {res.source_url && (
                <Paragraph copyable={{ text: res.source_url }}>
                  <MonoText>{res.source_url}</MonoText>
                </Paragraph>
              )}
            </Space>
          ),
        });
      }
    } catch (e) {
      message.error((e as Error).message || '取原片链接失败');
    }
  };

  const asset = data?.asset;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={880}
      title={
        asset ? (
          <Space>
            <MonoText>{asset.code}</MonoText>
            <AssetStatusTag status={asset.status} />
            <StageTags asset={asset} />
          </Space>
        ) : (
          '素材详情'
        )
      }
      extra={
        <Space>
          <Button icon={<DownloadOutlined />} onClick={showSource} disabled={!asset}>
            原片
          </Button>
          {canProduce && asset && !isImageAsset(asset) && (
            <Tooltip title="两段直拼（再选一条素材／切片／本地文件，可选谁在前）：0 元，不调模型">
              <Button icon={<MergeCellsOutlined />} onClick={() => setComposeOpen(true)}>
                拼接
              </Button>
            </Tooltip>
          )}
          {/* 批 G：图片不给拼接入口（后端也会 400：ffmpeg 拿一张 jpg 当一段会在解码时炸） */}
          {asset?.stage_prompt === 'running' && (
            <Button icon={<ReloadOutlined />} loading={busy} onClick={refreshPrompt}>
              更新读取进度
            </Button>
          )}
          {canProduce && asset?.source_kind === 'link' && asset?.duration === null && (
            <Tooltip title="去原链接查时长：每次 0.01 元，会计入批次成本">
              <Button loading={resolveBusy} onClick={resolveOne}>
                查视频时长
              </Button>
            </Tooltip>
          )}
        </Space>
      }
    >
      {loading && !asset ? (
        <Spin style={{ display: 'block', margin: '60px auto' }} />
      ) : !asset ? (
        <Empty description="没有详情" />
      ) : (
        <>
          {/*
            上栏＝播放器（批 E）。放在详情表之前是有意的：一线开抽屉八成先要"看一眼这条是什么片子"，
            再看字段和候选。产物列表里的「预览」也是把源换到这里，不开第二个播放器。
          */}
          <div style={{ marginBottom: 12 }}>
            {player ? (
              <>
                {isImageAsset(asset) ? (
                  /*
                    批 G：图片素材走这一支。播放器对一张 jpg 是黑屏（`<video>` 解不了静态图），
                    而"这张卡长什么样、是竖版还是横版"恰恰是开抽屉最想确认的事——
                    原图直接摆出来，画幅角标写在下面。
                  */
                  <img
                    key={player.url}
                    src={player.url}
                    alt={player.label || asset.code || '角色卡原图'}
                    onError={() =>
                      setPlayerErr(
                        '这张原图没取到：直链可能过期或对象存储不可达。点右上角「原片」存盘看看，或重新入库。',
                      )
                    }
                    style={{
                      display: 'block',
                      maxWidth: '100%',
                      maxHeight: 360,
                      margin: '0 auto',
                      background: '#000',
                      borderRadius: 6,
                    }}
                  />
                ) : (
                  <video
                    key={player.url}
                    controls
                    preload="metadata"
                    style={{ width: '100%', maxHeight: 360, background: '#000', borderRadius: 6 }}
                    onError={() =>
                      setPlayerErr(
                        '这一段放不出来：直链可能已过期（时效链接约 6 小时），或浏览器不允许本页播外部地址。' +
                          '要留存请点右上角「原片」存盘。',
                      )
                    }
                    src={player.url}
                  />
                )}
                <Space wrap size={4} style={{ marginTop: 6 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {isImageAsset(asset) ? '正在看原图：' : '正在预览：'}
                    {player.label}
                  </Text>
                  {isImageAsset(asset) ? (
                    <>
                      <Tag color={asset.aspect?.orientation === 'landscape' ? 'red' : 'purple'}>
                        {aspectShortText(asset.aspect)}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        投产时它在「生成生产单」弹窗里被挑成角色卡
                      </Text>
                    </>
                  ) : (
                    <>
                      <Tag>{durationText(player.duration)}</Tag>
                      {player.resolution && <Tag>{player.resolution}</Tag>}
                      {player.platform && <Tag>{player.platform}</Tag>}
                      {asset.source_kind === 'link' && <Tag color="orange">原站时效直链</Tag>}
                    </>
                  )}
                </Space>
                {isImageAsset(asset) && asset.aspect?.orientation === 'landscape' && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginTop: 6 }}
                    message="这张是横版卡：画幅由角色卡宽高比决定，提示词写 9:16 也压不住，投出去会是横屏"
                    description="要竖屏就换一张竖版定妆照（720×1280 一类）；确实要做横版则不用动，知道这条就行。"
                  />
                )}
                {player.qc === 'failed' && (
                  <Alert
                    type="error"
                    showIcon
                    style={{ marginTop: 6 }}
                    message={`这条产物验收判的是不合格${player.qcNote ? `：${player.qcNote}` : ''}`}
                    description="不合格的不给下载、也不给投出去；这里能播是为了让你看清废在哪。"
                  />
                )}
              </>
            ) : (
              <div
                style={{
                  border: '1px dashed #d9d9d9',
                  borderRadius: 6,
                  padding: '18px 16px',
                  background: '#fafafa',
                  textAlign: 'center',
                }}
              >
                {playerErr && (
                  <Alert type="warning" showIcon style={{ marginBottom: 10, textAlign: 'left' }} message={playerErr} />
                )}
                {asset.source_kind === 'file' ? (
                  <>
                    <Text type="secondary">这条的文件预览没取到（可能上传没落成功）。</Text>
                    <div style={{ marginTop: 8 }}>
                      <Button size="small" loading={playerBusy} onClick={() => loadSourcePreview(assetId!)}>
                        重新取预览
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <Text type="secondary">
                      链接素材我们桶里没有原片，不能直接播——想在这儿看画面，得花 <strong>0.01 元</strong>
                      回源取一条时效直链（约 6 小时过期，计入批次成本）。
                    </Text>
                    <div style={{ marginTop: 8 }}>
                      <Button
                        size="small"
                        type="primary"
                        ghost
                        loading={playerBusy}
                        disabled={!canProduce}
                        onClick={playLinkSource}
                      >
                        取直链并播放（0.01 元）
                      </Button>
                      {!canProduce && (
                        <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                          当前角色只读，回源解析要素材专员或运营来做
                        </Text>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="标题" span={2}>
              {asset.title || <Text type="secondary">（还没有标题：反推文案成功后系统会试着从文案稿起一个；起不出来就留空，不瞎编）</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="来路">
              <Tag>{asset.source_kind === 'link' ? '链接' : '文件'}</Tag>
              {asset.platform || '-'}
            </Descriptions.Item>
            {/* 批 G：类型写在字段表里（不只列表那列）——抽屉是核对这张卡能不能用的地方，
                画幅／尺寸／超限提醒都要在这儿看得见，不用回列表悬浮取 tooltip */}
            <Descriptions.Item label="类型">
              <MediaKindTag asset={asset} />
              {isImageAsset(asset) && (
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                  生产输入（角色卡）
                </Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="钩子原型" span={2}>
              <Space wrap align="center">
                <CategoryTag categoryId={asset.category_id} categoryName={asset.category_name} />
                {canProduce && (
                  <>
                    <CategorySelect
                      items={cats.activeItems}
                      value={asset.category_id || undefined}
                      onChange={(v) => assignCategory(v)}
                      width={240}
                      size="small"
                      loading={cats.loading || catBusy}
                      placeholder="选原型（清空＝改成未分类）"
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      开头套路的标记，不填照样走完全链；改了只影响这条素材，
                      <strong>不回写</strong>已经出的候选文案。
                    </Text>
                  </>
                )}
              </Space>
              {asset.category_id && cats.byId[asset.category_id]?.note && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {cats.byId[asset.category_id]?.note}
                  </Text>
                </div>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="时长">
              {isImageAsset(asset) ? '—（图片没有时长）' : durationText(asset.duration)}
            </Descriptions.Item>
            <Descriptions.Item label="分辨率">
              {asset.resolution || '-'}
              {isImageAsset(asset) && (
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                  {aspectShortText(asset.aspect)}
                </Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="视频时长上限">
              {isImageAsset(asset)
                ? '不适用（图片不反推文案）'
                : asset.prompt_max_duration
                  ? `${asset.prompt_max_duration}s`
                  : '未定'}
            </Descriptions.Item>
            <Descriptions.Item label="文件">{asset.file_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="大小">
              {asset.file_size ? `${(asset.file_size / 1024 / 1024).toFixed(1)} MB` : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="成本" span={2}>
              {isImageAsset(asset) ? (
                <Text type="secondary">
                  0 元：图片不反推文案、不查时长，也不计入批次预估——它只在投产时当角色卡带上。
                </Text>
              ) : (
                <>
                  反推文案 {yuan(asset.cost_prompt)} ｜ 查时长 {yuan(asset.cost_parse)}
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                    （生产这一环的花费现在不记账、恒为 0，是留给后续版本的口子，别当预算看）
                  </Text>
                </>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="导入时间">
              {parseServerTime(asset.created_at)?.format('YYYY-MM-DD HH:mm') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="反推文案任务">
              {/* 后端这三个状态码是 processing/success/failed，直接 String() 出来一线看不懂
                  （11-04 抽屉截图上就是裸的「success」），这里翻成人话 */}
              {data?.prompt_task
                ? { processing: '还在读（稍等刷新）', success: '读完了', failed: '读失败' }[
                    String(data.prompt_task.status)
                  ] || String(data.prompt_task.status)
                : '未提交'}
            </Descriptions.Item>
            <Descriptions.Item label="来源链接" span={2}>
              {asset.source_url ? (
                <Paragraph copyable={{ text: asset.source_url }} style={{ marginBottom: 0 }}>
                  <a href={asset.source_url} target="_blank" rel="noreferrer">
                    <MonoText>{asset.source_url}</MonoText>
                  </a>
                </Paragraph>
              ) : (
                '-'
              )}
            </Descriptions.Item>
            {asset.note && (
              <Descriptions.Item label="备注" span={2}>
                <Text style={{ whiteSpace: 'pre-wrap' }}>{dedupeNoteLines(asset.note)}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>

          {/*
            批 G：图片走的是另一条路。反推文案稿／文案／生产单／拼接产物这四页对图片**永远为空**
            （后端四个口都按 media_kind 明确拒绝图片入参），留着只会让人按提示去点「反推文案」
            ——那是一次白扣钱的反推。所以这几页整块换成一句白话说明。
          */}
          {isImageAsset(asset) ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message="这张图只当角色卡，不走反推文案 → 出文案 → 审核 → 生产单那四步"
              description="它不反推文案、不出钩子文案、不生成生产单、也没有拼接产物（这四页对图片永远是空的，所以这里不摆出来）。真正用它的地方在「生成生产单」弹窗：把要用的卡按顺序挑进来，第 1 张就是板上的主形象；成片挂在被投产的那条视频素材名下，不在这里。"
            />
          ) : (
          <Tabs
            style={{ marginTop: 16 }}
            items={[
              {
                key: 'script',
                label: `反推文案稿${data?.prompt_script ? '' : '（还没出）'}`,
                children: data?.prompt_script ? (
                  <>
                    {/*
                      拍板②（11-04）：本期**不动闸门**，只在这一处加一行不拦人的提醒。
                      残留风险要说白：这段是模型自己看片子写的、没人核对过，文案是照它出的；
                      它读歪了的话一致性检查也判不出来（两边都歪就"对得上"），最后一道刹车是人的眼睛。
                    */}
                    <Alert
                      type="warning"
                      showIcon
                      style={{ marginBottom: 8 }}
                      message="这段是 AI 看片子写出来的，没经过人工核对；下面的钩子文案就是照它写的。"
                      description="觉得它读歪了（人物认错、情节说反、台词串了），直接驳回对应文案，或回列表对这条重做一遍反推文案再出文案。这一行只提醒、不拦任何步骤。"
                    />
                    <Space style={{ marginBottom: 8 }}>
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => {
                          navigator.clipboard.writeText(data.prompt_script || '');
                          message.success('已复制反推文案稿');
                        }}
                      >
                        复制
                      </Button>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        出文案的输入就是这段；审核时怀疑文案编造，回来对这里
                      </Text>
                    </Space>
                    <Paragraph
                      style={{
                        whiteSpace: 'pre-wrap',
                        background: '#fafafa',
                        padding: 12,
                        borderRadius: 6,
                        maxHeight: 460,
                        overflow: 'auto',
                        fontSize: 12,
                      }}
                    >
                      {data.prompt_script}
                    </Paragraph>
                  </>
                ) : (
                  <Empty description="还没有反推文案稿（先在列表页点「反推文案」）" />
                ),
              },
              {
                key: 'summaries',
                label: `候选文案（${data?.summaries?.length ?? 0}）`,
                children: (
                  <List
                    size="small"
                    dataSource={data?.summaries || []}
                    locale={{ emptyText: '还没有候选文案' }}
                    renderItem={(s) => (
                      <List.Item key={s.id}>
                        <Space direction="vertical" size={2} style={{ width: '100%' }}>
                          <Space wrap>
                            <Tag>#{s.seq}</Tag>
                            <AuditStatusTag status={s.audit_status} />
                            {s.is_recommended && <Tag color="green">推荐</Tag>}
                            {s.style_tag && (
                              <Tooltip title={STYLE_TAG_GLOSS[s.style_tag] || ''}>
                                <Tag>{HOOK_STYLE_LABELS[s.style_tag] || s.style_tag}</Tag>
                              </Tooltip>
                            )}
                            {s.formula_tag && <Tag color="geekblue">{s.formula_tag}</Tag>}
                            <Text type="secondary">{s.word_count ?? '-'} 字</Text>
                            <RiskTags riskHit={s.risk_hit} />
                          </Space>
                          <Paragraph
                            style={{ marginBottom: 0 }}
                            ellipsis={{ rows: 4, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
                          >
                            {s.text}
                          </Paragraph>
                          {s.consistency_ok === false && s.consistency_note && (
                            <Text type="warning" style={{ fontSize: 12 }}>
                              和原视频对不上：{s.consistency_note}
                            </Text>
                          )}
                          {s.reject_reason && (
                            <Text type="danger" style={{ fontSize: 12 }}>
                              理由：{s.reject_reason}
                            </Text>
                          )}
                          {s.text_before_edit && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              改前：{s.text_before_edit.slice(0, 60)}…
                            </Text>
                          )}
                          {/* 批 J：提示词预览（过审后系统自动备好）。预览≠投产稿要写在标题里，
                              否则会有人拿这段直接贴给豆包——它缺钩子编号和角色卡信息。 */}
                          {s.prompt_preview ? (
                            <Space direction="vertical" size={2} style={{ width: '100%' }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                豆包提示词预览（给人看的样稿，投产时会重新展开）：
                              </Text>
                              <Paragraph
                                style={{ marginBottom: 0, fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4 }}
                                ellipsis={{ rows: 6, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
                              >
                                {s.prompt_preview}
                              </Paragraph>
                            </Space>
                          ) : (s.audit_status === 'approved' || s.audit_status === 'passed_edited') ? (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              提示词预览还没生成出来（过审后系统自动备，备不出来不影响投产——投产时会重新展开）
                            </Text>
                          ) : null}
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
              {
                key: 'productions',
                label: `生产单（${data?.productions?.length ?? 0}）`,
                children: (
                  <List
                    size="small"
                    dataSource={data?.productions || []}
                    locale={{ emptyText: '还没有生产单' }}
                    renderItem={(p) => (
                      <List.Item key={p.id}>
                        <Space direction="vertical" size={2} style={{ width: '100%' }}>
                          <Space wrap>
                            <MonoText>{p.hook_code || '（没编号）'}</MonoText>
                            <Text>#{p.seq}</Text>
                            <ProductionStateTag status={p.status} />
                            <Text type="secondary">
                              板上的任务名 {p.board_name || '-'}｜一条出 {p.board_total} 版｜投了 {p.attempts} 次
                            </Text>
                            {p.drift && (
                              <Tag color="warning">正文对不上{p.drift_reason ? `：${p.drift_reason}` : '（展开后的提示词和过审文案不是同一条）'}</Tag>
                            )}
                          </Space>
                          <Paragraph
                            type="secondary"
                            style={{ marginBottom: 0, fontSize: 12 }}
                            ellipsis={{ rows: 2, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
                          >
                            {p.prompt_text || '（正文为空：已作废或投放失败的单，不提供正文）'}
                          </Paragraph>
                          {p.dispatch_note && (
                            // 不再自己加「投放要求：」前缀——存进来的正文第一句本就是
                            // 「投放要求（只给人看，不贴进豆包也不进 payload）：」，两处都写会读成
                            // 「投放要求：投放要求（…）：」这种叠字（11-03 抽屉截图上就是这样）
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {p.dispatch_note}
                            </Text>
                          )}
                          {p.error && (
                            <Text type="danger" style={{ fontSize: 12 }}>
                              {p.error}
                            </Text>
                          )}
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
              {
                key: 'outputs',
                label: `拼接产物（${outputs.length}）`,
                children: (
                  <List
                    size="small"
                    dataSource={outputs}
                    locale={{ emptyText: '还没有拼接产物（点右上角「拼接」，两段直拼、可选谁在前）' }}
                    renderItem={(o) => (
                      <List.Item
                        actions={[
                          <Button
                            key="p"
                            size="small"
                            type="link"
                            loading={playerBusy}
                            onClick={() => previewProduct(o)}
                          >
                            预览
                          </Button>,
                          <Button key="d" size="small" icon={<DownloadOutlined />} onClick={() => downloadProduct(o)}>
                            下载
                          </Button>,
                        ]}
                      >
                        <Space direction="vertical" size={2} style={{ width: '100%' }}>
                          <Space wrap>
                            <Text>{o.file_name || o.file_key || '（无名）'}</Text>
                            <Tag color={o.kind === 'composed' ? 'blue' : 'default'}>
                              {o.kind === 'composed' ? '拼接' : o.kind}
                            </Tag>
                            <Text type="secondary">
                              {o.resolution || '画幅未知'}｜{durationText(o.duration)}｜
                              {o.file_size ? `${(o.file_size / 1024 / 1024).toFixed(1)} MB` : '-'}
                            </Text>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {parseServerTime(o.created_at)?.format('MM-DD HH:mm') || '-'}
                            </Text>
                          </Space>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {o.production_id ? `挂生产单 ${o.production_id.slice(0, 8)}…` : '未挂生产单（拼接不强制）'}
                            {o.qc_status && `｜验收 ${o.qc_status}`}
                            {o.qc_note && `：${o.qc_note}`}
                          </Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
            ]}
          />
          )}
          <Divider style={{ margin: '12px 0' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {isImageAsset(asset)
              ? '图片的链路：导入（拖进上传面板）→ 量尺寸定画幅 → 入库（图片已入库）→ 在「生成生产单」里被挑成角色卡 → 随那条视频一起出片。画幅由这张卡的宽高比决定，提示词写 9:16 也压不住横版卡。'
              : '链路：导入 → 把视频反推成文案稿 → 出钩子文案 → 人工审核 → 生成生产单（把过审文案变成要投出去的一条条提示词）' +
                ' → 导出提示词 txt 或建板参数（七项）→（人把提示词放进企微后台任务板后，回来登记投放结果）→ 拼接产物（两段直拼，0 元）。' +
                '钩子编号是五位编号，投放和回收都靠它对上。'}
          </Text>
          <AssetComposeModal
            open={composeOpen}
            asset={asset}
            onClose={() => setComposeOpen(false)}
            onDone={async () => {
              if (assetId) {
                await Promise.all([fetchDetail(assetId), fetchOutputs(assetId)]);
              }
              onChanged?.();
            }}
          />
        </>
      )}
    </Drawer>
  );
};

/** 生产单状态标签（与生产单面板同一套色，两处显示不能打架） */

export default AssetDetailDrawer;
