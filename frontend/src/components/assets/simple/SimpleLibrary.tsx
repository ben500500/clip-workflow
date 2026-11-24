import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Badge, Button, Card, Input, InputNumber, Modal, Segmented, Space, Table, Tag, Tooltip,
  Typography, Upload, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  EditOutlined, LinkOutlined, QuestionCircleOutlined, StopOutlined, ThunderboltOutlined, UploadOutlined,
} from '@ant-design/icons';
import {
  ASSET_STAGE_LABELS, assetApi, isAssetJobAck,
  type AssetCategory, type AssetItem, type AssetScript, type AssetScriptVerdictItem,
} from '../../../api/assets';
import { CategorySelect, splitCategoryName, useAssetCategories } from '../AssetCategoryBits';
import AssetCardPicker from '../AssetCardPicker';
import { nudgeAssetJobBanner } from '../AssetJobBanner';
import { withCrossOwnerConfirm, withCrossPersonConfirm } from '../crossPerson';
import ScriptEditorDrawer, { type SaveKind } from './ScriptEditorDrawer';
import SimpleComposeCard from './SimpleComposeCard';
import { reportVerdict } from './scriptResult';

const { Text } = Typography;

/** 每个脚本出几版＝板上 total（1..ASSET_BOARD_TOTAL_MAX，与后端同上限） */
const BOARD_TOTAL_MAX = 20;
/** 反推计时档位：与系统默认档一致（ASSET_PROMPT_MAX_DURATION=180） */
const REVERSE_TIER = 180;
/** 反推在后台跑时，多久回看一次刚导入的那几条（任务横幅收敛时也会触发重拉） */
const HOOK_POLL_MS = 15000;

const PROD_STATUS: Record<string, string> = {
  order_ready: '待投', queued: '已上板', running: '出片中', success: '已成片',
  failed: '失败', superseded: '已作废', cancelled: '已取消', skipped: '跳过', awaiting_rewrite: '待改写',
};

const STAGE_COLOR: Record<string, string> = {
  success: 'green', failed: 'red', running: 'processing', pending: 'processing', skipped: 'default',
};

interface Props {
  /** 导入／反推／建稿（_PROD_ROLES） */
  canImport: boolean;
  /** 投产职能＋角色：建单、投板 */
  canProduce: boolean;
  /** 审核职能＋角色：轻量过审 */
  canReview: boolean;
  isAdmin: boolean;
  /** 用户 id：sessionStorage 的键按人隔离（上一任留下的记录不能冒出来） */
  userId: string | null;
  /** 后台任务收敛一次 +1：刚导入的那几条要重拉反推状态 */
  reloadToken: number;
  /** 跳到完整模式的某个页签（成片墙） */
  onOpenFullTab: (tab: string) => void;
}

/** 脚本在库里的「一句话状态」：待审/已过审跟着载体走（送审才有载体） */
const scriptStatus = (s: AssetScript): { text: string; color: string } => {
  if (s.state === 'retired') return { text: '已下架', color: 'default' };
  if (s.state === 'draft') return { text: '库稿', color: 'default' };
  if (!s.carrier) return { text: '可投稿', color: 'blue' };
  if (isApproved(s)) return { text: '已过审', color: 'green' };
  return { text: '待审', color: 'orange' };
};

function isApproved(s: AssetScript): boolean {
  return s.state === 'ready' && !!s.carrier && (s.carrier.audit_status === 'approved' || s.carrier.audit_status === 'passed_edited');
}

// ─────────────────────────  导入钩子视频（链接／文件）＋原型  ─────────────────────────

interface ImportHookModalProps {
  open: boolean;
  categoryId?: string;
  activeItems: AssetCategory[];
  busy: boolean;
  progress: number;
  onOk: (links: string[] | null, files: File[] | null, categoryId: string | undefined) => void;
  onCancel: () => void;
}

const ImportHookModal: React.FC<ImportHookModalProps> = ({
  open, categoryId, activeItems, busy, progress, onOk, onCancel,
}) => {
  const [way, setWay] = useState<'link' | 'file'>('link');
  const [links, setLinks] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [cat, setCat] = useState<string | undefined>(categoryId);
  useEffect(() => {
    if (!open) return;
    setLinks('');
    setFiles([]);
    setCat(categoryId);
  }, [open, categoryId]);
  const linkList = links.split(/[\n\r]+/).map((s) => s.trim()).filter(Boolean);
  const nothing = way === 'link' ? !linkList.length : !files.length;

  return (
    <Modal
      open={open}
      title="导入钩子视频并反推"
      width={620}
      okText="开始"
      confirmLoading={busy}
      okButtonProps={{ disabled: nothing }}
      onOk={() => onOk(way === 'link' ? linkList : null, way === 'file' ? files : null, cat)}
      onCancel={() => { if (!busy) onCancel(); }}
      destroyOnClose
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Segmented
          value={way}
          onChange={(v) => setWay(v as 'link' | 'file')}
          options={[
            { label: '贴链接', value: 'link', icon: <LinkOutlined /> },
            { label: '传视频文件', value: 'file', icon: <UploadOutlined /> },
          ]}
        />
        {way === 'link' ? (
          <Input.TextArea
            rows={6}
            value={links}
            onChange={(e) => setLinks(e.target.value)}
            placeholder="一行一个分享链接（可以直接贴带文案的整段，系统自己认出链接）"
          />
        ) : (
          <Upload.Dragger
            multiple
            accept="video/*"
            fileList={[]}
            beforeUpload={(f) => { setFiles((prev) => [...prev, f]); return false; }}
          >
            <p className="ant-upload-text">点击或拖拽视频文件到这里（可多选）</p>
          </Upload.Dragger>
        )}
        {!!files.length && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            已选 {files.length} 个文件{busy ? `，上传中 ${progress}%` : ''}
          </Text>
        )}
        <Space>
          <Text style={{ fontSize: 12 }}>原型</Text>
          <CategorySelect
            value={cat}
            onChange={(v) => setCat(v)}
            items={activeItems}
            placeholder="整批默认原型（可不选）"
            width={260}
          />
        </Space>
      </Space>
    </Modal>
  );
};

// ─────────────────────────  极简模式主视图  ─────────────────────────

/**
 * 素材库极简模式（2026-11-23，用户原话见 docs/1123-素材库极简模式-需求评审与实现方案.md §1）。
 *
 * 一页上下几块，**不设页内页签**（验收口径「零页签切换」）：
 *   脚本库：导入钩子视频并反推 → 收进脚本库 → 打开改 → 定稿 ｜ 上传／手写脚本 → 定稿
 *   投豆包：勾脚本 → 选三视图 → 出几版 → （轻量过审）→ 投
 *   组合出片：勾豆包成片 × 勾正片 → 顺序 → 叠加 → 出包（需求三屏 3，纯本机 ffmpeg、0 元）
 *
 * 只折叠界面、不旁路逻辑：导入、反推、投产、投板全走五环同一个接口；钩子号、跨人确认、
 * 风险词闸都在后端。定稿冻结／生产载体见后端 assets/misc.py 脚本库段。
 */
const SimpleLibrary: React.FC<Props> = ({
  canImport, canProduce, canReview, isAdmin, userId, reloadToken, onOpenFullTab,
}) => {
  const cats = useAssetCategories();
  const [defaultCat, setDefaultCat] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState('');

  // ── 脚本库 ──
  const [owner, setOwner] = useState<'me' | 'all'>('me');
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [items, setItems] = useState<AssetScript[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const listReqRef = useRef(0);

  const fetchScripts = useCallback(async () => {
    const reqId = ++listReqRef.current;
    setLoading(true);
    try {
      const res = await assetApi.listScripts({ owner, q: q || undefined, page_size: 200 });
      // 请求序号守卫：筛选变更与任务收敛重拉并发时，慢的旧回包不能盖掉新的
      if (reqId !== listReqRef.current) return;
      setItems(res.items || []);
      setTotal(res.total || 0);
    } catch (e) {
      if (reqId === listReqRef.current) message.error((e as Error).message || '脚本库读取失败');
    } finally {
      if (reqId === listReqRef.current) setLoading(false);
    }
  }, [owner, q]);
  useEffect(() => { void fetchScripts(); }, [fetchScripts, reloadToken]);
  // 搜索 400ms 防抖（逐键打接口会让列表一卡一卡）
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 400);
    return () => clearTimeout(t);
  }, [qInput]);

  // ── 待过审（只有有审核职能的人看得到）：同事送审的脚本在这里点那一下 ──
  const [pending, setPending] = useState<AssetScript[]>([]);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const fetchPending = useCallback(async () => {
    if (!canReview) {
      setPending([]);
      return;
    }
    try {
      const res = await assetApi.listScripts({ owner: 'all', carrier_status: 'pending', page_size: 100 });
      setPending(res.items || []);
    } catch {
      /* 待审数读不到不拦主流程 */
    }
  }, [canReview]);
  useEffect(() => { void fetchPending(); }, [fetchPending, reloadToken]);

  const refreshAll = useCallback(
    async () => { await Promise.all([fetchScripts(), fetchPending()]); },
    [fetchScripts, fetchPending],
  );

  // ── 刚导入的钩子视频：记在 sessionStorage（按人隔离），反推出稿后收进脚本库 ──
  const hookKey = userId ? `simple:hooks:${userId}` : '';
  const [hookAssets, setHookAssets] = useState<AssetItem[]>([]);
  const [progress, setProgress] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [editor, setEditor] = useState<{ open: boolean; script: AssetScript | null }>({
    open: false, script: null,
  });

  const readHookIds = useCallback((): string[] => {
    if (!hookKey) return [];
    try {
      const v = JSON.parse(sessionStorage.getItem(hookKey) || '[]');
      return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
    } catch {
      return [];
    }
  }, [hookKey]);
  const writeHookIds = useCallback((ids: string[]) => {
    if (!hookKey) return;
    if (ids.length) sessionStorage.setItem(hookKey, JSON.stringify(ids));
    else sessionStorage.removeItem(hookKey);
  }, [hookKey]);

  const fetchHooks = useCallback(async () => {
    const ids = readHookIds();
    if (!ids.length) {
      setHookAssets([]);
      return;
    }
    // getAsset 回的是详情包（含文案/生产单），条带只要素材行
    const rows = await Promise.all(ids.map((id) => assetApi.getAsset(id).catch(() => null)));
    setHookAssets(rows.map((d) => d?.asset).filter((r): r is AssetItem => !!r));
  }, [readHookIds]);
  useEffect(() => { void fetchHooks(); }, [fetchHooks, reloadToken]);
  const hookRunning = hookAssets.some((a) => a.stage_prompt === 'pending' || a.stage_prompt === 'running');
  useEffect(() => {
    if (!hookRunning) return;
    const t = setInterval(() => void fetchHooks(), HOOK_POLL_MS);
    return () => clearInterval(t);
  }, [hookRunning, fetchHooks]);
  const collectable = hookAssets.filter((a) => a.stage_prompt === 'success');

  /** 导入 → 立刻排反推（后台任务，受理即回）。`force`＝库里已有同链接时仍然再导一份 */
  const importAndReverse = async (
    links: string[] | null, files: File[] | null, categoryId?: string, force = false,
  ) => {
    if (!links && !files) return;
    const name = `极简模式 ${new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}`;
    setBusy('import');
    setProgress(0);
    try {
      let ids: string[] = [];
      if (links) {
        const res = await assetApi.importBatch({
          links, name, category_id: categoryId ?? null, force_duplicates: force,
        });
        ids = (res.items || []).filter((a) => a.media_kind === 'video').map((a) => a.id);
        if (!ids.length && (res.duplicates || []).length) {
          // 库里已有同链接：默认只提示不建——要不要再来一份由人决定（再导＝再花一次反推）
          const n = (res.duplicates || []).length;
          Modal.confirm({
            title: `这 ${n} 条链接库里已经有了`,
            width: 520,
            content: '要用库里已有的那条：切到「完整」模式，在素材列表里能找到。再导一份会重新反推一遍。',
            okText: '再导一份并反推',
            cancelText: '算了',
            onOk: () => importAndReverse(links, null, categoryId, true),
          });
          return;
        }
        if ((res.skipped || []).length) {
          message.warning(`有 ${(res.skipped || []).length} 条没认出来：${(res.skipped || []).slice(0, 2).join('；')}`, 8);
        }
      } else if (files) {
        const res = await assetApi.uploadBatch(
          { files, name, max_duration: REVERSE_TIER, category_id: categoryId ?? undefined },
          setProgress,
        );
        ids = (res.items || []).filter((a) => a.media_kind === 'video').map((a) => a.id);
        if ((res.failed || []).length) {
          message.warning(
            `${(res.failed || []).length} 个文件没传上：`
            + (res.failed || []).slice(0, 2).map((f) => `${f.file_name}（${f.error}）`).join('；'),
            8,
          );
        }
      }
      if (!ids.length) return;
      writeHookIds(Array.from(new Set([...readHookIds(), ...ids])));
      setImportOpen(false);
      void fetchHooks();

      // 反推＝真金白银的一步：按钮本身是那一下确认（与五环 11-12「钱面下架」后同口径）
      const ack = await withCrossPersonConfirm((c) => assetApi.analyzeBatch({
        asset_ids: ids, max_duration: REVERSE_TIER, confirmed: true, force: isAdmin,
        async_mode: true, cross_person_confirm: c || undefined,
      }));
      if (!ack) return; // 取消了「替他人批次花钱」的确认：素材已入库，没反推
      if (isAssetJobAck(ack)) {
        nudgeAssetJobBanner();
        message.success(`已导入 ${ids.length} 条，反推在后台跑——出稿后点「收进脚本库」`, 7);
      }
    } catch (e) {
      message.error((e as Error).message || '导入／反推没成功', 8);
    } finally {
      setBusy('');
    }
  };

  /** 把已出稿的钩子视频收进脚本库（0 元：读库里那份反推稿）。收成功的从条带里移除 */
  const collect = async (rows: AssetItem[]) => {
    const ready = rows.filter((a) => a.stage_prompt === 'success');
    const waiting = rows.length - ready.length;
    if (!ready.length) {
      message.info(waiting ? '反推还在跑或没成功——出稿后才能收' : '没有可收的稿');
      return;
    }
    setBusy('collect');
    const results: AssetScriptVerdictItem[] = [];
    const doneIds: string[] = [];
    for (const a of ready) {
      try {
        const s = await assetApi.saveScriptFromAsset({ asset_id: a.id });
        doneIds.push(a.id);
        results.push({ script_id: s.id, ok: true, code: s.name });
      } catch (e) {
        results.push({ script_id: a.id, ok: false, code: a.code, error: (e as Error).message });
      }
    }
    setBusy('');
    writeHookIds(readHookIds().filter((id) => !doneIds.includes(id)));
    reportVerdict(
      results,
      `已收进脚本库 ${results.filter((r) => r.ok).length} 条——打开改到满意再定稿`,
      '条收进脚本库',
    );
    if (waiting) message.info(`另有 ${waiting} 条还没出稿，出了再收`, 6);
    await refreshAll();
  };

  /** 上传脚本文件：读出正文直接存成库稿，并打开让人改（原型用顶部那个选择器） */
  const uploadScripts = async (file: File) => {
    const text = await file.text().catch(() => '');
    if (!text.trim()) {
      message.warning(`「${file.name}」是空的`);
      return;
    }
    const base = file.name.replace(/\.[^.]+$/, '').slice(0, 60) || '上传的脚本';
    try {
      const s = await assetApi.createScript({
        name: base, body: text, category_id: defaultCat ?? null, source_kind: 'upload',
      });
      if (s.reused) message.info(`「${base}」的内容库里已有一条，打开的是那一行`, 6);
      setEditor({ open: true, script: s });
      await fetchScripts();
    } catch (e) {
      message.error(`「${file.name}」没存上：${(e as Error).message}`, 8);
    }
  };

  const onSaved = async (row: AssetScript, _kind: SaveKind, close: boolean) => {
    await refreshAll();
    if (close) setEditor({ open: false, script: null });
    else setEditor({ open: true, script: row }); // 定稿被拦：切到刚存下的那条，接着改
  };

  /** 送审：没有审核职能的账号走到这一步（等同事过审） */
  const submitRows = async (rows: AssetScript[]) => {
    if (!rows.length) return;
    setBusy('submit');
    try {
      const sub = await assetApi.submitScripts(rows.map((r) => r.id));
      reportVerdict(
        sub.results,
        `已送审 ${sub.results.filter((r) => r.ok).length} 条——等有审核职能的同事过审`,
        '条送审',
      );
      setSelectedIds((prev) => prev.filter((id) => !rows.some((r) => r.id === id)));
    } catch (e) {
      message.error((e as Error).message || '送审没成');
    } finally {
      setBusy('');
      await refreshAll();
    }
  };

  /** 轻量过审：逐条带 ok，没过的点名（HTTP 200 ≠ 全过）。返回过审成功的脚本 id */
  const approveRows = async (rows: AssetScript[]): Promise<string[]> => {
    if (!rows.length) return [];
    const ap = await assetApi.approveScripts(rows.map((r) => r.id));
    const okIds = ap.results.filter((r) => r.ok).map((r) => r.script_id);
    reportVerdict(ap.results, `已过审 ${okIds.length} 条`, '条过审');
    return okIds;
  };

  const reviewPending = async (rows: AssetScript[]) => {
    if (!rows.length) return;
    setBusy('review');
    try {
      await approveRows(rows);
      setPendingIds([]);
    } catch (e) {
      message.error((e as Error).message || '过审没成', 8);
    } finally {
      setBusy('');
      await refreshAll();
    }
  };

  // ── 投豆包 ──
  const [cardIds, setCardIds] = useState<string[]>([]);
  const [boardTotal, setBoardTotal] = useState(1);
  const selected = useMemo(
    () => items.filter((s) => selectedIds.includes(s.id) && s.state === 'ready'),
    [items, selectedIds],
  );
  const unapproved = selected.filter((s) => !isApproved(s));
  const needReview = unapproved.length > 0;

  const doProduce = async () => {
    if (!selected.length) return;
    if (unapproved.length && !canReview) {
      // 没有审核职能：这一下只能是送审
      await submitRows(unapproved);
      return;
    }
    setBusy('produce');
    try {
      let approvedNow = selected.filter(isApproved);
      if (unapproved.length) {
        const okIds = await approveRows(unapproved);
        approvedNow = [...approvedNow, ...unapproved.filter((s) => okIds.includes(s.id))];
        if (!approvedNow.length) return; // 一条都没过：原因已经在弹窗里点名了
      }
      const res = await withCrossOwnerConfirm((c) => assetApi.produceFromScripts({
        script_ids: approvedNow.map((s) => s.id),
        board_total: boardTotal,
        card_asset_ids: cardIds.length ? cardIds : null,
        cross_person_confirm: c,
      }));
      if (!res) return; // 取消了「替他人过审候选投产」的确认
      reportVerdict(res.results, res.message, '条投出');
      nudgeAssetJobBanner();
      setSelectedIds([]);
    } catch (e) {
      message.error((e as Error).message || '投豆包没成功', 8);
    } finally {
      setBusy('');
      await refreshAll();
    }
  };

  const primaryLabel = !selected.length
    ? '投豆包'
    : needReview && !canReview
      ? `送审（${selected.length}）`
      : needReview
        ? `轻量过审并投豆包（${selected.length}）`
        : `投豆包（${selected.length}）`;

  const columns: ColumnsType<AssetScript> = [
    {
      title: '脚本',
      dataIndex: 'name',
      render: (_: unknown, r) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            <Text strong style={{ fontSize: 13 }}>{r.name}</Text>
            {r.source_kind === 'reverse' && <Tag style={{ marginInlineEnd: 0 }}>反推</Tag>}
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: r.preview }}>
            {r.preview || '（空）'}
          </Text>
        </Space>
      ),
    },
    {
      title: '原型',
      dataIndex: 'category_name',
      width: 130,
      render: (v: string | null) => (v ? (
        <Tooltip title={v}>
          <Tag color="purple" style={{ marginInlineEnd: 0 }}>{splitCategoryName(v).short}</Tag>
        </Tooltip>
      ) : <Text type="secondary">未选</Text>),
    },
    {
      title: '状态',
      key: 'status',
      width: 84,
      render: (_: unknown, r) => {
        const st = scriptStatus(r);
        return <Tag color={st.color}>{st.text}</Tag>;
      },
    },
    {
      title: '已投',
      key: 'prod',
      width: 120,
      render: (_: unknown, r) => (r.production_count && r.last_production ? (
        <Tooltip title={`钩子号 ${r.last_production.hook_code || '—'}（最近一单）`}>
          <Text style={{ fontSize: 12 }}>
            {r.production_count} 单 · {PROD_STATUS[r.last_production.status] || r.last_production.status}
          </Text>
        </Tooltip>
      ) : <Text type="secondary">—</Text>),
    },
    ...(owner === 'all' ? [{
      title: '谁的',
      dataIndex: 'owner_name',
      width: 90,
      render: (v: string | null) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '—'}</Text>,
    }] : []),
    {
      title: '操作',
      key: 'ops',
      width: 210,
      render: (_: unknown, r) => (
        <Space size={0} wrap>
          <Button
            size="small" type="link" icon={<EditOutlined />}
            onClick={() => setEditor({ open: true, script: r })}
          >
            {r.state === 'draft' ? '改' : '打开'}
          </Button>
          {r.state === 'draft' && (
            <Button
              size="small" type="link"
              onClick={async () => {
                try {
                  await assetApi.finalizeScript(r.id, {});
                  message.success('已定稿，可以投豆包了', 5);
                  await refreshAll();
                } catch (e) {
                  // 多半是风险词 block（409）——打开改比再点一次有用
                  message.error((e as Error).message || '定稿没成', 8);
                }
              }}
            >
              定稿
            </Button>
          )}
          {r.state === 'ready' && !r.carrier && !canReview && (
            <Button size="small" type="link" onClick={() => void submitRows([r])}>送审</Button>
          )}
          <Button
            size="small" type="link" danger icon={<StopOutlined />}
            disabled={r.state === 'retired'}
            onClick={() => {
              Modal.confirm({
                title: `下架「${r.name}」？`,
                content: '下架后不再出现在脚本库；投过的记录留着，对账查得到。',
                okText: '下架', okType: 'danger', cancelText: '算了',
                onOk: async () => {
                  try {
                    await assetApi.retireScript(r.id);
                    message.success('已下架');
                    setSelectedIds((prev) => prev.filter((x) => x !== r.id));
                    await fetchScripts();
                  } catch (e) {
                    message.error((e as Error).message || '下架没成');
                  }
                },
              });
            }}
          >
            下架
          </Button>
        </Space>
      ),
    },
  ];

  const hint = !canProduce
    ? '你的账号没有投产职能——找管理员在用户管理里开通'
    : !selected.length
      ? '先在上面的脚本库勾选「可投稿」的脚本'
      : undefined;

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* ① 导入／新建：三种来路一行放完 */}
      <Card size="small">
        <Space wrap size={8}>
          <Button
            icon={<ThunderboltOutlined />}
            disabled={!canImport || busy !== ''}
            onClick={() => setImportOpen(true)}
          >
            导入钩子视频并反推
          </Button>
          <Tooltip title=".txt / .md，一个文件一条脚本">
            <Upload
              multiple
              accept=".txt,.md,text/plain,text/markdown"
              fileList={[]}
              showUploadList={false}
              disabled={!canImport}
              beforeUpload={(f) => { void uploadScripts(f); return false; }}
            >
              <Button icon={<UploadOutlined />} disabled={!canImport}>上传脚本文件</Button>
            </Upload>
          </Tooltip>
          <Button
            icon={<EditOutlined />}
            disabled={!canImport}
            onClick={() => setEditor({ open: true, script: null })}
          >
            手写脚本
          </Button>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>新脚本原型</Text>
          <CategorySelect
            value={defaultCat}
            onChange={(v) => setDefaultCat(v)}
            items={cats.activeItems}
            placeholder="可不选"
            width={220}
          />
        </Space>
      </Card>

      {/* ② 刚导入的钩子视频：反推出稿后收进脚本库 */}
      {!!hookAssets.length && (
        <Card
          size="small"
          title={
            <Space size={6}>
              刚导入的钩子视频
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                （{hookAssets.length} 条{hookRunning ? '，反推在后台跑' : ''}）
              </Text>
            </Space>
          }
          extra={
            <Button
              size="small"
              type="primary"
              loading={busy === 'collect'}
              disabled={!collectable.length || busy !== ''}
              onClick={() => void collect(hookAssets)}
            >
              全部收进脚本库
            </Button>
          }
        >
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={hookAssets}
            columns={[
              { title: '素材', dataIndex: 'title', ellipsis: true, render: (v: string | null, r) => v || r.code },
              {
                title: '反推',
                dataIndex: 'stage_prompt',
                width: 100,
                render: (v: string) => (
                  <Tag color={STAGE_COLOR[v] || 'default'}>
                    {ASSET_STAGE_LABELS[v as keyof typeof ASSET_STAGE_LABELS] || v}
                  </Tag>
                ),
              },
              {
                title: '操作',
                key: 'ops',
                width: 120,
                render: (_: unknown, r) => (
                  <Button
                    size="small" type="link"
                    loading={busy === 'collect'}
                    disabled={r.stage_prompt !== 'success' || busy !== ''}
                    onClick={() => void collect([r])}
                  >
                    收进脚本库
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* ③ 待过审（只有有审核职能的人看得到） */}
      {canReview && !!pending.length && (
        <Card
          size="small"
          title={(
            <Space size={6}>
              待过审
              <Badge count={pending.length} color="orange" showZero={false} />
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>同事送审的脚本，过审后他能自己投</Text>
            </Space>
          )}
        >
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={pending}
            rowSelection={{ selectedRowKeys: pendingIds, onChange: (keys) => setPendingIds(keys.map(String)) }}
            columns={[
              { title: '脚本', dataIndex: 'name', ellipsis: true, render: (v: string) => <Text strong>{v}</Text> },
              { title: '谁的', dataIndex: 'owner_name', width: 100 },
              {
                title: '原型',
                dataIndex: 'category_name',
                width: 150,
                ellipsis: true,
                render: (v: string | null) => (v ? splitCategoryName(v).short : '未选'),
              },
            ]}
          />
          <div style={{ marginTop: 8 }}>
            <Button
              size="small"
              type="primary"
              loading={busy === 'review'}
              disabled={!pendingIds.length || busy !== ''}
              onClick={() => void reviewPending(pending.filter((p) => pendingIds.includes(p.id)))}
            >
              过审选中的 {pendingIds.length} 条
            </Button>
            <Button
              size="small"
              type="link"
              disabled={busy !== ''}
              onClick={() => {
                setPendingIds(pending.map((p) => p.id));
              }}
            >
              全选
            </Button>
          </div>
        </Card>
      )}

      {/* ④ 脚本库 */}
      <Card
        size="small"
        title={(
          <Space size={6}>
            脚本库
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>（{total} 条）</Text>
          </Space>
        )}
        extra={
          <Space size={8}>
            <Segmented
              value={owner}
              onChange={(v) => { setOwner(v as 'me' | 'all'); setSelectedIds([]); }}
              options={[{ label: '我的', value: 'me' }, { label: '全部', value: 'all' }]}
            />
            <Input
              allowClear
              placeholder="搜脚本"
              style={{ width: 160 }}
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
            />
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={items}
          columns={columns}
          pagination={false}
          scroll={{ y: 400 }}
          rowSelection={{
            selectedRowKeys: selectedIds,
            // 只有「可投稿」的能勾：库稿要先定稿（审的＝投的那一版）
            getCheckboxProps: (r) => ({ disabled: r.state !== 'ready' }),
            onChange: (keys) => setSelectedIds(keys.map(String)),
          }}
        />
      </Card>

      {/* ⑤ 投豆包 */}
      <Card size="small" title="投豆包">
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Space wrap size={16}>
            <Text>
              已选 <Text strong>{selected.length}</Text> 个脚本
              {selected.length > 0 && (
                <Tooltip title={selected.map((s) => s.name).join('、')}>
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 6, cursor: 'help' }}>看是哪几个</Text>
                </Tooltip>
              )}
            </Text>
            <Space>
              <Text>每个出几版</Text>
              <InputNumber min={1} max={BOARD_TOTAL_MAX} value={boardTotal} onChange={(v) => setBoardTotal(v || 1)} />
            </Space>
            <Button type="link" size="small" style={{ padding: 0 }} onClick={() => onOpenFullTab('outputs')}>
              去成片墙看片 →
            </Button>
          </Space>
          <div>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>人物三视图</Text>
            <AssetCardPicker value={cardIds} onChange={setCardIds} active />
          </div>
          <Space size={8} wrap>
            <Tooltip title={hint || '投出去占当天号池额度（一个脚本一个钩子号）；约 25 分钟出片，回到成片墙'}>
              <Button
                type="primary"
                danger
                size="large"
                icon={<ThunderboltOutlined />}
                loading={busy === 'produce'}
                disabled={!selected.length || !canProduce || busy !== ''}
                onClick={() => void doProduce()}
              >
                {primaryLabel}
              </Button>
            </Tooltip>
            {!!hint && <Text type="secondary" style={{ fontSize: 12 }}>{hint}</Text>}
          </Space>
        </Space>
      </Card>

      {/* ⑥ 组合出片（11-24 需求三 S4：屏 3 的组合导出矩阵＋叠加预设＋批量出包） */}
      <SimpleComposeCard
        canProduce={canProduce}
        isAdmin={isAdmin}
        onDone={refreshAll}
        onOpenFullTab={onOpenFullTab}
      />

      <ImportHookModal
        open={importOpen}
        categoryId={defaultCat}
        activeItems={cats.activeItems}
        busy={busy === 'import'}
        progress={progress}
        onOk={(l, f, c) => void importAndReverse(l, f, c)}
        onCancel={() => setImportOpen(false)}
      />
      <ScriptEditorDrawer
        open={editor.open}
        script={editor.script}
        activeCategories={cats.activeItems}
        defaultCategoryId={defaultCat}
        canFinalize={canImport}
        onSaved={onSaved}
        onClose={() => setEditor({ open: false, script: null })}
      />
    </Space>
  );
};

export default SimpleLibrary;
