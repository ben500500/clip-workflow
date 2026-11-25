import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Input, Modal, Radio, Segmented, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  DatabaseOutlined, DownloadOutlined, FolderOpenOutlined, PlusOutlined, ReloadOutlined, SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  assetApi, isAssetJobAck, waitForAssetJob,
  type AssetItem, type AssetOverlayParams, type AssetOverlayPreset, type AssetOverlayScope,
  type AssetOutput, type ComposeMaterialSource, type ComposeMatrixOrder, type ComposeMatrixRequest,
  type ComposeMatrixResult, type OverlayPresetListResult,
} from '../../../api/assets';
import { variantsApi, type SliceOutputListItem } from '../../../api/variants';
import { nudgeAssetJobBanner } from '../AssetJobBanner';
import {
  OverlayParamsEditor, emptyOverlay, overlayBriefText, overlayIsEmpty,
} from '../AssetOverlayBits';
import AssetOverlayPresetDrawer from '../AssetOverlayPresetDrawer';
import { HelpDot, MonoText, durationText } from '../AssetBits';

const { Text } = Typography;

/**
 * ⚠️ 本卡**当前没有挂载**（2026-11-24 用户反馈：「你的什么组合出片、什么行列写在那里，谁看得懂？
 * 我要的那个拼接是最后一步，你可以先不做，到时候直接把短剧切片中的那个功能搬过来就可以了」）。
 *
 * `SimpleLibrary` 已改回分步页签 ①导稿／②脚本库／③投豆包／④看成片，这一屏从界面上撤了。
 * 保留文件**不删**的理由：它的调用合同（矩阵入参、叠加预设、0 元口径、超 20 条的分两次话术）
 * 都测过、也还在后端，等把短剧切片那套拼接功能搬过来时按新交互重写，比从零想口径省一轮。
 * 后端 `POST /assets/compose/matrix`＋`/assets/overlay-presets` 与 pytest 用例**一律没动**。
 * 相应地 `frontend/evidence/shoot-compose-matrix*.mjs` 两道 UI 门随界面一起暂停（拼接的
 * 逻辑覆盖仍由后端用例兜着）。
 */

interface Props {
  /** 组合导出要花钱吗？不要——但开单职能照样是门槛（后端 require_roles(*_PROD_ROLES)） */
  canProduce: boolean;
  isAdmin: boolean;
  /** 落新产物后通知外层（极简主视图重拉、成片墙计数） */
  onDone?: () => void;
  onOpenFullTab: (tab: string) => void;
}

/**
 * 单次格数上限。与后端 `settings.ASSET_COMPOSE_MAX_PER_CALL` 同默认值（20）。
 *
 * 这里只是**提前预告**，真正的拦在后端（超了它回一句「这不是钱的事…请分两次点」）。
 * 和 `SimpleLibrary` 里 `BOARD_TOTAL_MAX` 一个做法：界面先把数字摆明，别让人点了才撞 400；
 * 改了那个旋钮要记得同步这里——两处不同步的后果只是「预告晚了」，不会放行错的东西。
 */
const COMPOSE_MAX_PER_CALL = 20;
/** 一屏拉多少候选：后端 list 封顶 300，200 够一线按最新挑 */
const PICK_SIZE = 200;

/** 叠加三档：与后端「预设与现场二选一、都不给＝不叠加」严格同构（不存在第四种） */
type OverlayMode = 'none' | 'preset' | 'custom';

const KIND_LABEL: Record<string, string> = { doubao_raw: '豆包成片', composed: '已拼成片' };

/**
 * 屏 3 · 组合导出（11-24 需求三 S4）。
 *
 * 用户口径：「多选钩子成片 × 多选正片 ＝ 组合投放素材；角标／警示语／剧名／片尾」。
 * 后端口是 `POST /assets/compose/matrix`（S3，misc.py:13120），这一屏只做它的形状。
 *
 * 六个界面决定，每一个都对着后端的一条闸：
 *
 * 1. **钩子那一侧只列 `doubao_raw` / `composed`，且不带试产片**。`_load_matrix_hooks`
 *    认这两种 kind，别的是 zip 和 txt（选了报「第1段探不出视频流」那种看不懂的错）；
 *    试产片是审核证据、不许当原料。所以我按 kind 各拉一次再合并，而不是拉全量自己挑——
 *    让界面根本选不出会被拒的行，比选了再拒好。
 * 2. **正片只列视频**。图片段后端当场 400（`_resolve_concat_input`）。
 * 3. **0 元，界面不许出现「花费 N 元/确认提交」**（11-12 钱面下架口径）：纯本机 ffmpeg，
 *    不投板、不占号池、不进预算闸门。
 * 4. **超上限是「分两次点」，不是 admin 强行放行**：多出来的格子不会更值钱，只会让这次
 *    请求把服务器压满。主按钮直接置灰＋一行话说清哪两个数相乘超了。
 * 5. **默认排后台**（D-1 口径）：一格 2~3 次转码，20 格真能吃满一次同步等待。
 *    提交即回任务号，所以必须 `nudgeAssetJobBanner()`——只靠定点轮询的话任务进不了
 *    `openBefore`、`onSettled` 永不触发，跑完了界面也不刷（批 C 踩实过）。
 * 6. **出包不另造口**：结果区那句「打包这 N 条」调的还是成片墙同一个
 *    `POST /assets/outputs/package`，交付包格式只有一套。
 *
 * 校验顺序照后端抄（去重→格数→钩子kind→正片文件→片尾不重复→叠加可用性→角标图），
 * 因为后端把全部校验排在 `_start_asset_job` **之前**：拦下来台账一行不留。
 * 界面先拦一遍不是为了省一个请求，是为了不让一线看到「组合导出 失败」这种半截话。
 */
const SimpleComposeCard: React.FC<Props> = ({ canProduce, isAdmin, onDone, onOpenFullTab }) => {
  // ── 行：钩子成片 ──
  const [hooks, setHooks] = useState<AssetOutput[]>([]);
  const [hookLoading, setHookLoading] = useState(false);
  const [hookIds, setHookIds] = useState<string[]>([]);

  // ── 列：正片（素材库片段 / 现网切片产物）──
  const [source, setSource] = useState<ComposeMaterialSource>('asset');
  const [assetRows, setAssetRows] = useState<AssetItem[]>([]);
  const [sliceRows, setSliceRows] = useState<SliceOutputListItem[]>([]);
  const [matLoading, setMatLoading] = useState(false);
  const [matIds, setMatIds] = useState<string[]>([]);
  const [kwInput, setKwInput] = useState('');
  const [kw, setKw] = useState('');

  // ── 片尾（恒在最后，只能从素材库挑）──
  const [tailRows, setTailRows] = useState<AssetItem[]>([]);
  const [tailId, setTailId] = useState<string | null>(null);

  const [order, setOrder] = useState<ComposeMatrixOrder>('hook_first');
  const [prefix, setPrefix] = useState('');

  // ── 叠加 ──
  const [presets, setPresets] = useState<AssetOverlayPreset[]>([]);
  const [meta, setMeta] = useState<OverlayPresetListResult | null>(null);
  const [overlayMode, setOverlayMode] = useState<OverlayMode>('none');
  const [presetId, setPresetId] = useState<string | null>(null);
  const [custom, setCustom] = useState<AssetOverlayParams>(emptyOverlay());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saveForm, setSaveForm] = useState<{ open: boolean; name: string; note: string; scope: AssetOverlayScope }>(
    { open: false, name: '', note: '', scope: 'user' },
  );

  // ── 提交与结果 ──
  const [busy, setBusy] = useState('');
  const [phase, setPhase] = useState('');
  const [result, setResult] = useState<ComposeMatrixResult | null>(null);
  const [packaging, setPackaging] = useState(false);

  const fetchHooks = useCallback(async () => {
    setHookLoading(true);
    try {
      // 两次按 kind 点名拉，而不是拉全量再挑：见头部注释第 1 条
      const [raw, composed] = await Promise.all([
        assetApi.listOutputs({ kind: 'doubao_raw', limit: PICK_SIZE }),
        assetApi.listOutputs({ kind: 'composed', limit: PICK_SIZE }),
      ]);
      const byId = new Map<string, AssetOutput>();
      [...(raw.items || []), ...(composed.items || [])].forEach((o) => {
        if (o.file_key) byId.set(o.id, o);
      });
      const rows = [...byId.values()].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
      setHooks(rows);
      // 已被删掉的勾选（别人在成片墙清了行）静默收掉，别让矩阵带着一张不存在的片子去撞 400
      setHookIds((prev) => prev.filter((id) => byId.has(id)));
    } catch (e) {
      message.error((e as Error).message || '钩子成片读取失败');
    } finally {
      setHookLoading(false);
    }
  }, []);

  const fetchMaterials = useCallback(async (keyword: string) => {
    setMatLoading(true);
    try {
      if (source === 'asset') {
        const res = await assetApi.listAssets({
          media_kind: 'video',
          keyword: keyword || undefined,
          sort: 'created_desc',
          page_size: PICK_SIZE,
        });
        setAssetRows(res.items || []);
      } else {
        const data = await variantsApi.listSliceOutputs({ keyword: keyword || undefined, page_size: 100 });
        setSliceRows(
          (data.groups || [])
            .flatMap((g) => g.episodes || [])
            .flatMap((ep) => ep.outputs || [])
            .filter((o) => !!o.file_key),
        );
      }
    } catch (e) {
      message.error((e as Error).message || '正片读取失败');
    } finally {
      setMatLoading(false);
    }
  }, [source]);

  const fetchTails = useCallback(async () => {
    try {
      const res = await assetApi.listAssets({ media_kind: 'video', sort: 'created_desc', page_size: PICK_SIZE });
      setTailRows((res.items || []).filter((i) => !!i.file_key));
    } catch {
      // 片尾是可选配件，拉不到不该打断这一屏；下拉空着时行内已说明「读不到」
      setTailRows([]);
    }
  }, []);

  const fetchPresets = useCallback(async () => {
    try {
      const res = await assetApi.listOverlayPresets(false);
      setPresets(res.items || []);
      setMeta(res);
      setPresetId((prev) => (prev && (res.items || []).some((p) => p.id === prev) ? prev : null));
    } catch (e) {
      message.error((e as Error).message || '叠加预设读取失败');
    }
  }, []);

  useEffect(() => {
    void fetchHooks();
    void fetchTails();
    void fetchPresets();
  }, [fetchHooks, fetchTails, fetchPresets]);
  // 换来源／改关键词才重拉正片（进页面只拉素材库那一侧，切片产物没人看就别白花一次请求）
  useEffect(() => { void fetchMaterials(kw); }, [fetchMaterials, kw]);

  const cells = hookIds.length * matIds.length;

  /** 勾选行对象：画幅预告和「片尾＝正片同文件」的本地拦都要拿真值 */
  const pickedHooks = useMemo(() => hooks.filter((h) => hookIds.includes(h.id)), [hooks, hookIds]);
  const pickedAssets = useMemo(() => assetRows.filter((a) => matIds.includes(a.id)), [assetRows, matIds]);
  const tailRow = useMemo(() => tailRows.find((t) => t.id === tailId) || null, [tailRows, tailId]);

  const firstSegResolution = useMemo(() => {
    if (order === 'hook_first') return pickedHooks[0]?.resolution || null;
    if (source === 'asset') return pickedAssets[0]?.resolution || null;
    const first = sliceRows.filter((s) => matIds.includes(s.id))[0];
    return first?.resolution || null;
  }, [order, pickedHooks, pickedAssets, sliceRows, matIds, source]);

  const activePreset = useMemo(() => presets.find((p) => p.id === presetId) || null, [presets, presetId]);

  const overlayText = overlayMode === 'none'
    ? '不叠加'
    : overlayMode === 'preset'
      ? (activePreset ? `${activePreset.name}：${activePreset.summary}` : '没选预设')
      : overlayBriefText(custom);

  /** 本地拦一遍：话术与后端同源，且**只拦后端一定会拒的**，不自加规矩 */
  const blockers = useMemo(() => {
    const out: string[] = [];
    if (!hookIds.length) out.push('先勾至少一支钩子成片');
    if (!matIds.length) out.push('先勾至少一条正片');
    if (hookIds.length && matIds.length && cells > COMPOSE_MAX_PER_CALL) {
      out.push(
        `${hookIds.length} 支钩子 × ${matIds.length} 条正片 ＝ ${cells} 条，超过单次上限 ${COMPOSE_MAX_PER_CALL} 条——`
        + '这不是钱的事（拼接 0 元），是一次压给服务器的转码量太大会挂，请分两次点',
      );
    }
    if (tailId && source === 'asset' && pickedAssets.some((a) => a.file_key && a.file_key === tailRow?.file_key)) {
      out.push('片尾和其中一条正片是同一个文件，拼出来是重复播放的废片，请换一个');
    }
    if (overlayMode === 'preset' && !presetId) out.push('叠加这一档还没选预设：选一套，或改回「不叠加」');
    if (overlayMode === 'custom' && overlayIsEmpty(custom)) out.push('现场调里什么都没叠：加个角标／文字，或选「不叠加」');
    return out;
  }, [hookIds, matIds, cells, tailId, source, pickedAssets, tailRow, overlayMode, presetId, custom]);

  const submit = async () => {
    if (blockers.length) {
      message.warning(blockers[0], 8);
      return;
    }
    const body: ComposeMatrixRequest = {
      hook_output_ids: hookIds,
      material_source: source,
      material_ids: matIds,
      tail_asset_id: tailId || null,
      order,
      overlay_preset_id: overlayMode === 'preset' ? presetId : null,
      overlay_params: overlayMode === 'custom' ? custom : null,
      async_mode: true,
      title_prefix: prefix.trim() || null,
    };
    setBusy('compose');
    setResult(null);
    setPhase('正在提交');
    try {
      const res = await assetApi.composeMatrix(body);
      // 提交即补查：任务横幅是唯一会把 job 放进 openBefore 的地方，漏了它跑完也不刷界面
      nudgeAssetJobBanner();
      let final: ComposeMatrixResult;
      if (isAssetJobAck(res)) {
        setPhase(res.message || '已排进后台，正在跑');
        const job = await waitForAssetJob(res.job_id, {
          intervalMs: 6000,
          timeoutMs: 30 * 60 * 1000,
          onTick: (j) => {
            const p = j.progress;
            setPhase(`${j.status_label}${p?.total ? `（已跑 ${p.done ?? 0}/${p.total} 格）` : ''}${p?.note ? `｜${p.note}` : ''}`);
          },
        });
        if (job.error) throw new Error(job.error);
        if (!job.result) throw new Error(`后台任务回的是「${job.status_label}」但没带清单，去任务台账看这条（任务号 ${job.id}）`);
        final = job.result as ComposeMatrixResult;
      } else {
        final = res;
      }
      setResult(final);
      setPhase(final.message || '');
      message.success(`组合导出跑完：成功 ${final.ok} 条、失败 ${final.failed} 条（0 元）`, 8);
      void fetchHooks();
      onDone?.();
    } catch (e) {
      // 后端话术原样显示：那都是白话（「第 1 个角标不是图片」「请分两次点」），改写只会更含糊
      message.error((e as Error).message || '组合导出失败', 10);
    } finally {
      setBusy('');
    }
  };

  const okIds = useMemo(
    () => (result?.results || []).filter((c) => c.ok && c.output_id).map((c) => c.output_id as string),
    [result],
  );

  /** 出包＝成片墙同一条口（POST /assets/outputs/package），不另造格式 */
  const packageOk = async () => {
    if (!okIds.length || packaging) return;
    setPackaging(true);
    try {
      const blob = await assetApi.packageOutputs(okIds);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'compose-package.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      message.success(`已发起 ${okIds.length} 条打包下载，浏览器右上角看进度`);
    } catch (e) {
      message.error((e as Error).message || '打包失败', 8);
    } finally {
      setPackaging(false);
    }
  };

  const savePreset = async () => {
    const name = saveForm.name.trim();
    if (!name) { message.warning('给这套起个名，下次才认得'); return; }
    if (overlayIsEmpty(custom)) { message.warning('空壳存不了：既没角标也没文字＝「不叠加」'); return; }
    try {
      const p = await assetApi.createOverlayPreset({
        name,
        scope: saveForm.scope,
        note: saveForm.note.trim() || undefined,
        params: custom,
      });
      setSaveForm({ open: false, name: '', note: '', scope: 'user' });
      message.success(`已存为预设「${p.name}」，这次就按它出片`);
      await fetchPresets();
      // 存完把这一屏切到「用预设」并选中它：现场调的参数已经进库，别再留两份真相
      setPresetId(p.id);
      setOverlayMode('preset');
    } catch (e) {
      message.error((e as Error).message || '存预设失败', 8);
    }
  };

  const hookColumns: ColumnsType<AssetOutput> = [
    {
      title: '钩子',
      dataIndex: 'hook_code',
      width: 104,
      render: (v: string | null) => (v ? <MonoText>{v}</MonoText> : <Text type="secondary">无号</Text>),
    },
    {
      title: '文件',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (v: string | null, row) => (
        <Space size={4}>
          <span>{v || row.asset_code || '（无名）'}</span>
          <Tag color={row.kind === 'composed' ? 'blue' : 'green'}>{KIND_LABEL[row.kind] || row.kind}</Tag>
        </Space>
      ),
    },
    { title: '时长', dataIndex: 'duration', width: 68, render: (v: number | null) => durationText(v) },
    { title: '画幅', dataIndex: 'resolution', width: 88, render: (v: string | null) => v || '-' },
  ];

  const assetColumns: ColumnsType<AssetItem> = [
    { title: '编号', dataIndex: 'code', width: 108, render: (v: string) => <MonoText>{v}</MonoText> },
    {
      title: '标题/文件',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string | null, row) => (
        <Space size={4}>
          <span>{v || row.file_name || '未命名'}</span>
          {!row.file_key && <Tag color="warning">无原片</Tag>}
        </Space>
      ),
    },
    { title: '时长', dataIndex: 'duration', width: 68, render: (v: number | null) => durationText(v) },
    { title: '画幅', dataIndex: 'resolution', width: 88, render: (v: string | null) => v || '-' },
  ];

  const sliceColumns: ColumnsType<SliceOutputListItem> = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (v: string | null) => v || <Text type="secondary">（无名）</Text>,
    },
    { title: '时长', dataIndex: 'duration', width: 68, render: (v: number | null) => durationText(v) },
    { title: '画幅', dataIndex: 'resolution', width: 88, render: (v: string | null) => v || '-' },
  ];

  return (
    <Card
      size="small"
      title={(
        <Space size={6}>
          组合出片
          <HelpDot
            text={(
              <span>
                勾几支豆包钩子成片 × 勾几条正片，一次出「支数×条数」条投放素材，可加片尾、叠角标／剧名／警示语。
                纯本机 ffmpeg：<b>0 元</b>、不投板、不占号池。排在<b>最前</b>那段决定画幅；
                一次最多 {COMPOSE_MAX_PER_CALL} 条，多了分两次点。产物一格一条，去成片墙勾选打包发。
              </span>
            )}
          />
        </Space>
      )}
      extra={(
        <Space size={8}>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => { void fetchHooks(); void fetchMaterials(kw); }}>
            重新取片
          </Button>
          <Button size="small" type="link" onClick={() => onOpenFullTab('outputs')}>去成片墙看片 →</Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap size={12} align="start">
          <div style={{ flex: '1 1 420px', minWidth: 320 }}>
            <Space size={6} style={{ marginBottom: 4 }}>
              <Text strong>钩子成片（行）</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>已选 {hookIds.length} 支</Text>
            </Space>
            <Table
              rowKey="id"
              size="small"
              loading={hookLoading}
              dataSource={hooks}
              columns={hookColumns}
              pagination={false}
              scroll={{ y: 200 }}
              locale={{ emptyText: '库里还没有豆包成片（先去「投豆包」出片并回收）' }}
              rowSelection={{
                selectedRowKeys: hookIds,
                preserveSelectedRowKeys: true,
                onChange: (keys) => setHookIds(keys.map(String)),
              }}
            />
          </div>
          <div style={{ flex: '1 1 420px', minWidth: 320 }}>
            <Space size={6} style={{ marginBottom: 4 }} wrap>
              <Text strong>正片（列）</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>已选 {matIds.length} 条</Text>
              <Segmented
                size="small"
                value={source}
                onChange={(v) => { setSource(v as ComposeMaterialSource); setMatIds([]); setKw(''); setKwInput(''); }}
                options={[
                  { label: '素材库片段', value: 'asset', icon: <DatabaseOutlined /> },
                  { label: '现网切片', value: 'slice', icon: <FolderOpenOutlined /> },
                ]}
              />
              <Input
                allowClear
                size="small"
                style={{ width: 150 }}
                placeholder="搜编号/文件名"
                value={kwInput}
                onChange={(e) => setKwInput(e.target.value)}
                onPressEnter={() => setKw(kwInput.trim())}
              />
            </Space>
            <Table
              rowKey="id"
              size="small"
              loading={matLoading}
              dataSource={source === 'asset' ? assetRows : sliceRows}
              columns={source === 'asset' ? assetColumns : sliceColumns}
              pagination={false}
              scroll={{ y: 200 }}
              rowSelection={{
                selectedRowKeys: matIds,
                preserveSelectedRowKeys: true,
                onChange: (keys) => setMatIds(keys.map(String)),
                getCheckboxProps: (row: any) => (source === 'asset' ? { disabled: !row.file_key } : {}),
              }}
            />
          </div>
        </Space>

        <Space wrap size={16}>
          <Space size={6}>
            <Text>顺序</Text>
            <Radio.Group
              size="small"
              value={order}
              onChange={(e) => setOrder(e.target.value as ComposeMatrixOrder)}
              options={[
                { label: '钩子在前', value: 'hook_first' },
                { label: '正片在前', value: 'material_first' },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              按最前那段出画幅{firstSegResolution ? `：${firstSegResolution}` : '（还没选，画幅待定）'}
            </Text>
          </Space>
          <Space size={6}>
            <Tooltip title="可选，恒拼在最后。只能从素材库挑视频。">
              <Text>片尾</Text>
            </Tooltip>
            <Select
              allowClear
              size="small"
              style={{ width: 240 }}
              placeholder={tailRows.length ? '不加片尾' : '正在读素材库…'}
              value={tailId || undefined}
              onChange={(v) => setTailId((v as string) || null)}
              options={tailRows.map((t) => ({
                value: t.id,
                label: `${t.code}·${(t.title || t.file_name || '未命名').slice(0, 18)}（${durationText(t.duration)}）`,
              }))}
            />
          </Space>
          <Space size={6}>
            <Text>产物名前缀</Text>
            <Input
              size="small"
              style={{ width: 180 }}
              maxLength={60}
              placeholder="默认按钩子号"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
            />
          </Space>
        </Space>

        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap size={10}>
            <Text strong>角标／文字</Text>
            <Segmented
              size="small"
              value={overlayMode}
              onChange={(v) => setOverlayMode(v as OverlayMode)}
              options={[{ label: '不叠加', value: 'none' }, { label: '用预设', value: 'preset' }, { label: '现场调', value: 'custom' }]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>这次：{overlayText}</Text>
          </Space>
          {overlayMode === 'preset' && (
            <Space wrap size={8}>
              <Select
                size="small"
                style={{ width: 300 }}
                placeholder="用哪套预设"
                value={presetId || undefined}
                onChange={(v) => setPresetId((v as string) || null)}
                options={presets.map((p) => ({
                  value: p.id,
                  label: `${p.name}（${p.scope === 'shared' ? '全员' : '我的'}）· ${p.summary}`,
                }))}
                notFoundContent="还没有预设：先在「管理预设」里存一套，或改选「现场调」"
              />
              <Button size="small" icon={<SettingOutlined />} onClick={() => setDrawerOpen(true)}>管理预设</Button>
              <Text type="secondary" style={{ fontSize: 12 }}>改预设不回改已出的片，历史片子认的是当时的参数。</Text>
            </Space>
          )}
          {overlayMode === 'custom' && (
            <>
              <OverlayParamsEditor
                active
                value={custom}
                onChange={setCustom}
                positions={meta?.positions}
                limits={{
                  maxBadges: meta?.max_badges ?? 6,
                  maxTexts: meta?.max_text_overlays ?? 6,
                  maxChars: meta?.max_text_chars ?? 30,
                }}
              />
              <Button
                size="small"
                icon={<PlusOutlined />}
                disabled={overlayIsEmpty(custom)}
                onClick={() => setSaveForm({ open: true, name: '', note: '', scope: 'user' })}
              >
                把这组叠法存成预设
              </Button>
            </>
          )}
        </Space>

        <Space wrap size={12} align="center">
          <Text>
            <Text strong>{hookIds.length}</Text> 支钩子 × <Text strong>{matIds.length}</Text> 条正片
            ＝ <Text strong>{cells}</Text> 条成片
            {tailId ? '（每条再拼片尾）' : ''}｜<Text strong>0 元</Text>
          </Text>
          <Tooltip title={blockers.length ? blockers.join('；') : '逐格本机 ffmpeg 拼接，排后台跑，跑完这里出清单'}>
            <Button
              type="primary"
              size="large"
              icon={<ThunderboltOutlined />}
              loading={busy === 'compose'}
              disabled={!canProduce || busy !== '' || blockers.length > 0}
              onClick={() => void submit()}
            >
              组合导出
            </Button>
          </Tooltip>
          {blockers.length > 0 && (
            <Text type="warning" style={{ fontSize: 12 }}>{blockers[0]}</Text>
          )}
        </Space>

        {busy === 'compose' && phase && (
          <Alert type="info" showIcon message="正在跑" description={<span style={{ fontSize: 12 }}>{phase}</span>} />
        )}

        {result && (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Alert
              type={result.failed ? 'warning' : 'success'}
              showIcon
              message={`成功 ${result.ok} 条／失败 ${result.failed} 条｜叠加：${result.overlay}｜耗时 ${result.elapsed_seconds}s｜0 元`}
              description={<span style={{ fontSize: 12 }}>{result.message}</span>}
            />
            <Table
              rowKey={(r) => `${r.hook_output_id}-${r.material}`}
              size="small"
              dataSource={result.results}
              pagination={false}
              scroll={{ y: 200 }}
              columns={[
                { title: '钩子', dataIndex: 'segments', width: 220, ellipsis: true, render: (v: string[]) => (v?.[0] || '-') },
                { title: '拼了什么', dataIndex: 'segments', ellipsis: true, render: (v: string[]) => (v || []).join(' + ') },
                {
                  title: '结果',
                  dataIndex: 'ok',
                  width: 220,
                  render: (_v: boolean, row) => (row.ok
                    ? <Text type="success">{row.file_name || '已入库'}（{durationText(row.duration)}）</Text>
                    : <Text type="danger">{(row.error || '失败').slice(0, 120)}</Text>),
                },
              ]}
            />
            <Space wrap size={8}>
              <Button
                icon={<DownloadOutlined />}
                loading={packaging}
                disabled={!okIds.length}
                onClick={() => void packageOk()}
              >
                打包这 {okIds.length} 条（zip）
              </Button>
              <Button type="link" onClick={() => onOpenFullTab('outputs')}>到成片墙挑着打包 →</Button>
            </Space>
          </Space>
        )}
      </Space>

      <AssetOverlayPresetDrawer
        open={drawerOpen}
        isAdmin={isAdmin}
        onClose={() => setDrawerOpen(false)}
        onPick={(p: AssetOverlayPreset) => {
          setPresetId(p.id);
          setOverlayMode('preset');
          setDrawerOpen(false);
        }}
      />

      <Modal
        open={saveForm.open}
        title="把这组叠法存成预设"
        okText="存下来"
        onOk={() => void savePreset()}
        onCancel={() => setSaveForm((s) => ({ ...s, open: false }))}
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Input
            placeholder="这套叫什么（同名会拒收）"
            maxLength={60}
            value={saveForm.name}
            onChange={(e) => setSaveForm((s) => ({ ...s, name: e.target.value }))}
          />
          <Input
            placeholder="备注：给谁用、什么时候用（可不填）"
            maxLength={200}
            value={saveForm.note}
            onChange={(e) => setSaveForm((s) => ({ ...s, note: e.target.value }))}
          />
          <Space size={6}>
            <Text>谁能用</Text>
            <Radio.Group
              size="small"
              value={saveForm.scope}
              onChange={(e) => setSaveForm((s) => ({ ...s, scope: e.target.value as AssetOverlayScope }))}
              options={[
                { label: '只我自己', value: 'user' },
                { label: isAdmin ? '全员可选' : '全员可选（仅管理员）', value: 'shared', disabled: !isAdmin },
              ]}
            />
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            这次要叠的：{overlayBriefText(custom)}。存完默认就按这套出片，下次直接选名字就行。
          </Text>
        </Space>
      </Modal>
    </Card>
  );
};

export default SimpleComposeCard;
