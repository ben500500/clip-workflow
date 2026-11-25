import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Badge, Button, Card, Input, InputNumber, Modal, Segmented, Select, Space, Table, Tabs, Tag, Tooltip,
  Typography, Upload, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  EditOutlined, LinkOutlined, QuestionCircleOutlined, StarFilled, StarOutlined, StopOutlined, ThunderboltOutlined, UploadOutlined,
} from '@ant-design/icons';
import {
  ASSET_STAGE_LABELS, assetApi, isAssetJobAck,
  type AssetCategory, type AssetItem, type AssetScript, type AssetScriptVerdictItem,
} from '../../../api/assets';
import AssetCardPicker from '../AssetCardPicker';
import AssetOutputWall from '../AssetOutputWall';
import { CategorySelect, splitCategoryName, useAssetCategories } from '../AssetCategoryBits';
import { nudgeAssetJobBanner } from '../AssetJobBanner';
import { withCrossOwnerConfirm, withCrossPersonConfirm } from '../crossPerson';
import ScriptEditorDrawer, { type SaveKind } from './ScriptEditorDrawer';
import { ThumbCell, VideoPreviewModal, useCoverMap } from './SimplePreviewBits';
import { reportVerdict } from './scriptResult';
import { useOwnerView } from '../../../hooks/useOwnerView';

const { Text, Link } = Typography;

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

/** 列表「更新」列的紧凑时间（MM-DD HH:mm）；坏值出破折号不出 NaN */
const fmtTime = (v: string | null | undefined): string => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return '—';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

/**
 * 后端取号被拦下时 502 话术里钉的标记（`misc.py` 的 `_HOOK_TAKE_MARKER`），冒号后是**缺口数**。
 * 与「替他人过审候选投产」同一套做法：话术里埋机器认得的串，不让前端猜中文错误文案。
 */
const HOOK_TAKE_MARK = /【需要手工贴号:(\d+)】/;

/**
 * 后端 502 原文里「怎么补」那半句（要么配命令／要么贴号）在弹窗里是重复的——
 * 人已经站在贴号框里了。框只留「差几个、烧没烧」这两件事实，出路这一屏自己讲。
 */
const hookWhyOnly = (msg: string): string => {
  const cut = msg.search(/要么|取号那边修好后|这台服务把自动预取/);
  // 砍在「要么…」前面，末尾会剩一个「：」——那是引出出路句的冒号，出路句已经不要了，跟着去掉
  return (cut > 0 ? msg.slice(0, cut) : msg).trim().replace(/[：:]\s*$/, '');
};

/** 贴号框的文本 → 编号数组：空格／换行／逗号顿号都算分隔，统一大写（后端也统一大写） */
const hookParseCodes = (raw: string): string[] => (
  raw.split(/[\s,，、;；]+/).map((c) => c.trim().toUpperCase()).filter(Boolean)
);

interface Props {
  /** 导入／反推／建稿（_PROD_ROLES） */
  canImport: boolean;
  /** 投产职能＋角色：建单、投板 */
  canProduce: boolean;
  /** 审核职能＋角色：轻量过审 */
  canReview: boolean;
  isAdmin: boolean;
  /**
   * 批 T（11-24）全局「仅看自己」：true＝脚本库默认只摆「我写的＋我收藏的」（后端 owner=me 口径），
   * false／缺省＝看所有人的。用户原话：「默认是要能看到全部的，但是可以加入一个开关或者复选框，
   * 仅看自己。这个仅看自己，不是说仅仅是自己导入的文案，也可以在已有的脚本库里面勾选，然后收藏起来。」
   * ⇒ 默认全部 ＋ 收藏能把别人的脚本挪进"我的"，两件事都由这颗开关和下面那列 ⭐ 承接。
   */
  scopeMine?: boolean;
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
 * 素材库极简模式（2026-11-23 建；**2026-11-24 按用户反馈改回分步页签**）。
 *
 * 用户原话（11-24）：「你这个直接不是过度简化吗？**原来的 tab 形式还是要保留的，这样能分清步骤**」
 * 「你的什么组合出片、什么行列写在那里，谁看得懂？**素材也没有预览**」
 * 「我要的那个**拼接是最后一步，你可以先不做**，到时候直接把**短剧切片中的那个功能搬过来**就可以了」
 * 「**先把前面的文案导入，然后生产豆包这些东西全部做做好**」
 * 「（界面）虽然是要基建，但也不是让人一头雾水、摸不着头脑的那种」
 *
 * 所以这一版：
 *   ① 脚本库（导入 ＋ 改稿·定稿）→ ② 投豆包 → ③ 看成片，**一步一个页签**，
 *   页签带序号与待办数，每屏顶部一句话讲清"这步做什么、下一步去哪"；
 *   每屏都能**看见片子**（缩略图＋点开即播，见 SimplePreviewBits）；
 *   组合出片那一屏**从界面撤下**（后端 compose/matrix 与用例原样留着，等把短剧切片
 *   那套拼接功能搬过来再放，别在中间态摆一张行列矩阵让人猜）。
 *   导入**不再是独立一屏**（11-24 用户：「那一小行的功能块直接放在脚本库的上方，
 *   这样就少一个 tab；名称不要叫"先弄到稿"，就叫"导入"」）——它是脚本库顶部的
 *   一张卡，与"收进脚本库""待过审""改稿·定稿"同屏，省掉一次页签往返。
 *
 * 只折叠界面、不旁路逻辑：导入、反推、投产、投板全走五环同一个接口；钩子号、跨人确认、
 * 风险词闸都在后端。定稿冻结／生产载体见后端 assets/misc.py 脚本库段。
 */
const SimpleLibrary: React.FC<Props> = ({
  canImport, canProduce, canReview, isAdmin, scopeMine, userId, reloadToken, onOpenFullTab,
}) => {
  const cats = useAssetCategories();
  const [defaultCat, setDefaultCat] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState('');
  /** 分步页签（11-24 用户要求保留 tab 形式好分清步骤；导稿并入脚本库后只剩三步） */
  const [tab, setTab] = useState<'scripts' | 'produce' | 'outputs'>('scripts');

  // ── 脚本库 ──
  // 默认**全部**（11-24 用户口径「默认是要能看到全部的」），全局开关打开才收成"我的"。
  const [owner, setOwner] = useOwnerView(scopeMine);
  /** 批 AA：按上传人点名筛（优先级高于 owner，收藏不算归属）；候选从已加载行里收 */
  const [ownerFilter, setOwnerFilter] = useState<string | undefined>(undefined);
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
      const res = await assetApi.listScripts({
        owner, owner_id: ownerFilter || undefined, q: q || undefined, page_size: 200,
      });
      // 请求序号守卫：筛选变更与任务收敛重拉并发时，慢的旧回包不能盖掉新的
      if (reqId !== listReqRef.current) return;
      setItems(res.items || []);
      setTotal(res.total || 0);
    } catch (e) {
      if (reqId === listReqRef.current) message.error((e as Error).message || '脚本库读取失败');
    } finally {
      if (reqId === listReqRef.current) setLoading(false);
    }
  }, [owner, ownerFilter, q]);
  useEffect(() => { void fetchScripts(); }, [fetchScripts, reloadToken]);
  // 搜索 400ms 防抖（逐键打接口会让列表一卡一卡）
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 400);
    return () => clearTimeout(t);
  }, [qInput]);

  // ── 待过审（只有有审核职能的人看得到）：同事送审的脚本在这里点那一下 ──
  // 口径跟「改稿·定稿」那张表同一个开关：选了「我的」就只留我写的∪我收藏的，
  // 别在一屏里一半按开关筛、一半硬编 all（11-24 用户：「选择我的之后，
  // 未定稿的即使不在我的收藏里也会展现」——漏的就是这里原先写死的 'all'）。
  const [pending, setPending] = useState<AssetScript[]>([]);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const fetchPending = useCallback(async () => {
    if (!canReview) {
      setPending([]);
      return;
    }
    try {
      const res = await assetApi.listScripts({
        owner, owner_id: ownerFilter || undefined, carrier_status: 'pending', page_size: 100,
      });
      setPending(res.items || []);
    } catch {
      /* 待审数读不到不拦主流程 */
    }
  }, [canReview, owner, ownerFilter]);
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

  /**
   * 批 AA（11-25 用户：「极简模式里出不了文案，我只有审核台一个入口，给极简也加一个」）：
   * 出候选文案走完整模式同一个口（POST /assets/summaries/generate，提交即回后台跑）。
   * 候选出来后批 X 后端自动镜像进 ① 脚本库，这里不用再搬。
   */
  const genHooks = async (ids: string[], overwrite: boolean) => {
    setBusy('gen');
    try {
      const res = await withCrossPersonConfirm((c) =>
        assetApi.generateSummaries({ asset_ids: ids, async_mode: true, overwrite, cross_person_confirm: c }));
      if (!res) return; // 取消了「替他人批次」确认：什么都不做
      if (isAssetJobAck(res)) {
        // 回执只有任务号：去哪儿看让横幅说，别在这里猜跑没跑完
        message.success(res.message, 8);
        nudgeAssetJobBanner();
      } else {
        message.success(res.message || '已提交出文案');
      }
      void refreshAll();
    } catch (e) {
      message.error((e as Error).message || '出文案失败', 8);
    } finally {
      setBusy('');
    }
  };

  /** 出文案前的「只补／覆盖」确认——与完整模式 AssetListPanel 同一套话术同一套按钮 */
  const generateHooks = (rows: AssetItem[]) => {
    const ok = rows.filter((a) => a.stage_prompt === 'success');
    if (!ok.length) {
      message.info('没有「反推文案成功」的素材——文案是从反推稿里出的，得先反推一遍', 6);
      return;
    }
    const hasCopies = ok.filter((a) => (a.summary_count ?? 0) > 0);
    if (hasCopies.length) {
      Modal.confirm({
        title: `选中的素材里 ${hasCopies.length} 条已经有候选文案`,
        content: (
          <p style={{ marginBottom: 6 }}>「覆盖重出」会把这些旧候选删掉重新生成（已过审的会拦下，必须先撤审）；旧的留档按「只补」。</p>
        ),
        okText: `覆盖重出（${hasCopies.length} 条旧的删掉）`,
        cancelText: '只补还没有文案的',
        onOk: () => void genHooks(ok.map((a) => a.id), true),
        onCancel: () => {
          const onlyNew = ok.filter((a) => (a.summary_count ?? 0) === 0);
          if (onlyNew.length) void genHooks(onlyNew.map((a) => a.id), false);
          else message.info('选中的都有候选了，没有要补的', 6);
        },
      });
      return;
    }
    void genHooks(ok.map((a) => a.id), false);
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

  // 批 U（11-25）：自动取号被拦下时的「我自己贴号」退路。
  // 后端 502 话术开头钉着 `【需要手工贴号:N】`（misc.py 的 _HOOK_TAKE_MARKER），N＝还缺几个号。
  // 为什么要前端接这个标记：本机/没装配号命令的环境里，光 toast 一句原文，一线既不知道
  // 「原来能手贴」，也不知道要贴几个——上一次用户就是被这句「稍后重试」堵死的。
  const [hookPaste, setHookPaste] = useState<{ rows: AssetScript[]; need: number; why: string } | null>(null);
  const [hookText, setHookText] = useState('');

  /** 真发一枪。`hookCodes`＝人工贴的号（只在自动取号没凑齐那一批用） */
  const runProduce = async (rows: AssetScript[], hookCodes: string[] | null) => {
    const res = await withCrossOwnerConfirm((c) => assetApi.produceFromScripts({
      script_ids: rows.map((s) => s.id),
      board_total: boardTotal,
      card_asset_ids: cardIds.length ? cardIds : null,
      cross_person_confirm: c,
      ...(hookCodes && hookCodes.length ? { hook_codes: hookCodes } : {}),
    }));
    if (!res) return false; // 取消了「替他人过审候选投产」的确认
    const sent = res.results.some((r) => r.ok);
    reportVerdict(res.results, res.message, '条投出');
    nudgeAssetJobBanner();
    setSelectedIds([]);
    // 批 V 需求①（11-25 用户：「投了豆包之后，豆包界面上的那些记录就可以清除了，
    // 比如说上传的三视图，或者选的文案等」）：真投出去了就把这一屏的输入擦干净——
    // 卡还挂着、版数还停在上一批的数，回到 ② 时容易当成「上一批没投完」再点一次，
    // 而重复点这一次就是**重复占当天号池**。只在至少投出去一条时清：闸门全挡下的
    // 那一批是要改完重投的，卡和号得留着。
    if (sent) {
      setCardIds([]);
      setBoardTotal(1);
      setHookText('');
    }
    // 投完直接把人带到 ③：这步之后能看的只有等片，别让他在 ② 空等（11-24 分步页签）
    if (sent) setTab('outputs');
    return true;
  };

  /** 失败话术里带缺口标记 → 摆贴号框；没带 → 原样报错。返回 true＝已交给人工贴号 */
  const offerHookPaste = (err: unknown, rows: AssetScript[]): boolean => {
    const msg = (err as Error).message || '';
    const hit = HOOK_TAKE_MARK.exec(msg);
    if (!hit) return false;
    setHookPaste({
      rows,
      need: Math.max(1, Number(hit[1]) || 1),
      why: hookWhyOnly(msg.replace(hit[0], '')),
    });
    setHookText('');
    return true;
  };

  const doProduce = async () => {
    if (!selected.length) return;
    if (unapproved.length && !canReview) {
      // 没有审核职能：这一下只能是送审
      await submitRows(unapproved);
      return;
    }
    setBusy('produce');
    let target: AssetScript[] = [];
    try {
      let approvedNow = selected.filter(isApproved);
      if (unapproved.length) {
        const okIds = await approveRows(unapproved);
        approvedNow = [...approvedNow, ...unapproved.filter((s) => okIds.includes(s.id))];
        if (!approvedNow.length) return; // 一条都没过：原因已经在弹窗里点名了
      }
      target = approvedNow;
      await runProduce(approvedNow, null);
    } catch (e) {
      if (!offerHookPaste(e, target)) message.error((e as Error).message || '投豆包没成功', 8);
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

  // 贴号框点「贴上并重发」：本地校验只挡明显填错（数量／重号），库里撞号仍由后端点名。
  // 重发这一枪仍可能报「还差 N 个」（比如管理员只给了一半），所以失败时照原路把缺口数刷新。
  const submitHookPaste = async () => {
    if (!hookPaste) return;
    const codes = hookParseCodes(hookText);
    if (codes.length !== hookPaste.need) {
      message.error(`还差 ${hookPaste.need} 个号，现在贴了 ${codes.length} 个（每行一个）`, 6);
      return;
    }
    if (new Set(codes).size !== codes.length) {
      message.error('贴的号里有重复：一钩一号，一条脚本只能占一个', 6);
      return;
    }
    setBusy('produce');
    try {
      const done = await runProduce(hookPaste.rows, codes);
      if (done) setHookPaste(null);
    } catch (e) {
      if (!offerHookPaste(e, hookPaste.rows)) message.error((e as Error).message || '贴号重发没成', 8);
    } finally {
      setBusy('');
      await refreshAll();
    }
  };

  // ── 预览（11-24 用户：「素材也没有预览」）──
  // 一张共享播放器＋按素材 id 批量取首帧：脚本行的图＝它出处那条钩子视频的首帧。
  // 素材被删了脚本还在（origin_asset_id 置空／帧取不到）＝这格就是"无图"，不报错、不拦任何一步。
  const coverIds = useMemo(() => {
    const ids: Array<string | null | undefined> = hookAssets.map((a) => a.id);
    items.forEach((s) => ids.push(s.origin_asset_id));
    pending.forEach((s) => ids.push(s.origin_asset_id));
    selected.forEach((s) => ids.push(s.origin_asset_id));
    return ids;
  }, [hookAssets, items, pending, selected]);
  const { cover: covers, loading: coversLoading } = useCoverMap(coverIds);
  const [play, setPlay] = useState<{ assetId: string; title: string } | null>(null);
  const previewOf = (assetId: string | null | undefined, title: string, height = 56) => (
    <ThumbCell
      src={assetId ? covers[assetId] ?? null : null}
      loading={coversLoading}
      title={title}
      height={height}
      onPlay={assetId ? () => setPlay({ assetId, title }) : undefined}
    />
  );

  // ── 批 T（11-24）收藏：用户口径「也可以在已有的脚本库里面勾选，然后收藏起来」──
  // 收藏只改**可见范围**，不改归属：别人的定稿照样改不动（要动＝打开后派生新草稿）。
  // 所以在「仅看自己」里取消收藏别人的脚本，这条会当场从列表消失——这是对的，不是 bug。
  const toggleFavorite = async (r: AssetScript) => {
    try {
      if (r.favorited) {
        await assetApi.unfavoriteScript(r.id);
        message.success(`已取消收藏「${r.name}」`, 4);
      } else {
        await assetApi.favoriteScript(r.id);
        message.success(`已收藏「${r.name}」——打开「仅看自己」就能看到并勾选它`, 5);
      }
      await fetchScripts();
    } catch (e) {
      message.error((e as Error).message || '收藏没改成', 8);
    }
  };

  // 批 AA：/auth/users 只有 admin 能读，上传人候选就从已加载的行里收（owner_id/owner_name 同行带回）
  const ownerOptions = useMemo(() => {
    const m = new Map<string, string>();
    items.forEach((s) => {
      if (s.owner_id && !m.has(s.owner_id)) {
        m.set(s.owner_id, s.owner_name || (s.owner_id === userId ? '我' : '他人'));
      }
    });
    if (ownerFilter && !m.has(ownerFilter)) m.set(ownerFilter, '筛选中…');
    return Array.from(m, ([id, name]) => ({
      value: id,
      label: id === userId ? `${name}（我）` : name,
    }));
  }, [items, ownerFilter, userId]);

  const columns: ColumnsType<AssetScript> = [
    {
      title: '预览',
      key: 'preview',
      width: 62,
      render: (_: unknown, r) => previewOf(r.origin_asset_id, r.name),
    },
    {
      title: (
        <Tooltip title="收藏＝把这条挪进「仅看自己」的清单，下次能直接找到并勾去投。只是让你看得到，不代表你能改它——别人的定稿要动，打开后另存一份草稿。">
          <span>收藏</span>
        </Tooltip>
      ),
      key: 'fav',
      width: 60,
      render: (_: unknown, r) => (
        <Tooltip title={r.favorited ? '已收藏，点这里取消' : '点一下收藏进「我的」'}>
          <Button
            size="small" type="text"
            aria-label={r.favorited ? '取消收藏' : '收藏'}
            icon={r.favorited
              ? <StarFilled style={{ color: '#faad14' }} />
              : <StarOutlined style={{ color: 'rgba(0,0,0,.35)' }} />}
            onClick={() => void toggleFavorite(r)}
          />
        </Tooltip>
      ),
    },
    {
      title: '脚本',
      dataIndex: 'name',
      render: (_: unknown, r) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            {/* 11-24 用户：「点击脚本的标题也直接打开吧，不要只有那个"打开"按钮可以开启」 */}
            <Link strong style={{ fontSize: 13 }} onClick={() => setEditor({ open: true, script: r })}>
              {r.name}
            </Link>
            {r.source_kind === 'reverse' && <Tag style={{ marginInlineEnd: 0 }}>反推</Tag>}
            {r.source_kind === 'mirror' && <Tag color="purple" style={{ marginInlineEnd: 0 }}>候选</Tag>}
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
      sorter: (a, b) => (a.production_count ?? 0) - (b.production_count ?? 0),
      render: (_: unknown, r) => (r.production_count && r.last_production ? (
        <Tooltip title={`钩子号 ${r.last_production.hook_code || '—'}（最近一单）`}>
          <Text style={{ fontSize: 12 }}>
            {r.production_count} 单 · {PROD_STATUS[r.last_production.status] || r.last_production.status}
          </Text>
        </Tooltip>
      ) : <Text type="secondary">—</Text>),
    },
    // 「仅看自己」里也会出现别人的脚本（收藏来的）。这一列的判据跟着**数据**走而不是跟着
    // 开关走：只要当前页里混进了不是我的行，就把「谁的」亮出来，否则用户只会看到一条来路不明的脚本。
    ...((owner === 'all' || !!ownerFilter || items.some((s) => s.owner_id !== userId)) ? [{
      title: '谁的',
      dataIndex: 'owner_name',
      width: 90,
      sorter: (a: AssetScript, b: AssetScript) => (a.owner_name || '').localeCompare(b.owner_name || ''),
      render: (v: string | null, r: AssetScript) => (
        r.owner_id === userId
          ? <Text type="secondary" style={{ fontSize: 12 }}>我的</Text>
          : <Text type="secondary" style={{ fontSize: 12 }}>{v || '他人'}{r.favorited ? ' · 收藏' : ''}</Text>
      ),
    }] : []),
    {
      title: '更新',
      dataIndex: 'updated_at',
      width: 105,
      sorter: (a, b) => (a.updated_at || '').localeCompare(b.updated_at || ''),
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{fmtTime(v)}</Text>,
    },
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
      ? '先到 ① 脚本库 勾选要投的脚本'
      : undefined;

  /** 页签标题＝序号＋步骤名＋这一屏还欠的件数（11-24 用户：原来的 tab 形式要保留，好分清步骤） */
  const tabLabel = (mark: string, text: string, count?: number) => (
    <Space size={6}>
      <span>{`${mark} ${text}`}</span>
      {!!count && <Badge count={count} size="small" />}
    </Space>
  );

  // ── 导入：链接／文件／脚本文件／手写 → 反推 → 收进脚本库（11-24 用户：这一小块直接放脚本库上方，别再单独一个页签）──
  const importBlock = (
    <>
      {/* 三种来路一行放完 */}
      <Card size="small" title="导入">
        <Space wrap size={8} align="center">
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
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            贴链接或传视频＝系统把片子反推成稿（一条一两分钟）；上传脚本文件／手写＝直接进库。
            稿子进库后在下面的表格里改稿、定稿。
          </Text>
        </div>
      </Card>

      {/* 刚导入的钩子视频：反推出稿后收进脚本库 */}
      {!!hookAssets.length && (
        <Card
          size="small"
          title={
            <Space size={6}>
              收进脚本库
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                （{hookAssets.length} 条{hookRunning ? '，反推在后台跑' : ''}）
              </Text>
            </Space>
          }
          extra={
            <Space size={8}>
              <Button
                size="small"
                loading={busy === 'gen'}
                disabled={!collectable.length || busy !== ''}
                onClick={() => generateHooks(hookAssets)}
              >
                全部出文案
              </Button>
              <Button
                size="small"
                type="primary"
                loading={busy === 'collect'}
                disabled={!collectable.length || busy !== ''}
                onClick={() => void collect(hookAssets)}
              >
                全部收进脚本库
              </Button>
            </Space>
          }
        >
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={hookAssets}
            columns={[
              {
                title: '预览',
                key: 'preview',
                width: 62,
                render: (_: unknown, r) => previewOf(r.id, r.title || r.code),
              },
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
                width: 190,
                render: (_: unknown, r) => (
                  <Space size={0}>
                    <Tooltip title="出候选文案（后台跑）；候选出来会自动镜像进下面的脚本库">
                      <Button
                        size="small" type="link"
                        loading={busy === 'gen'}
                        disabled={r.stage_prompt !== 'success' || busy !== ''}
                        onClick={() => generateHooks([r])}
                      >
                        出文案{(r.summary_count ?? 0) > 0 ? `（已有 ${r.summary_count}）` : ''}
                      </Button>
                    </Tooltip>
                    <Button
                      size="small" type="link"
                      loading={busy === 'collect'}
                      disabled={r.stage_prompt !== 'success' || busy !== ''}
                      onClick={() => void collect([r])}
                    >
                      收进脚本库
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}
      {!hookAssets.length && (
        <Text type="secondary" style={{ fontSize: 12, paddingLeft: 2 }}>
          这里会列出刚导入的钩子视频：反推在后台跑，出稿后点「全部收进脚本库」，再到下面的表格里改稿。
        </Text>
      )}
    </>
  );

  // ── ① 脚本库：导入 ＋ 改稿 · 定稿（· 待过审）──
  const paneScripts = (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {importBlock}
      <Text type="secondary" style={{ fontSize: 12 }}>
        打开改到满意点「定稿」，<Text strong>只有定稿的脚本能投豆包</Text>；
        改一份已定稿的会派生新草稿，投过的稿子不会被覆盖。
      </Text>
      {/* 待过审（只有有审核职能的人看得到） */}
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
              {
                title: '预览',
                key: 'preview',
                width: 62,
                render: (_: unknown, r) => previewOf(r.origin_asset_id, r.name),
              },
              { title: '脚本', dataIndex: 'name', ellipsis: true, render: (v: string, r) => (
                  <Space size={4}>
                    <Text strong>{v}</Text>
                    {/* 批 X：镜像候选行（出文案/导入同步落进脚本库的那条）在待过审区也要认得出 */}
                    {r.source_kind === 'mirror' && <Tag color="purple" style={{ marginInlineEnd: 0 }}>候选</Tag>}
                  </Space>
                ) },
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

      {/* 脚本库表格 */}
      <Card
        size="small"
        title={(
          <Space size={6}>
            改稿 · 定稿
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>（库里有 {total} 条）</Text>
          </Space>
        )}
        extra={
          <Space size={8}>
            <Segmented
              value={owner}
              onChange={(v) => { setOwner(v as 'me' | 'all'); setSelectedIds([]); }}
              options={[{ label: '我的', value: 'me' }, { label: '全部', value: 'all' }]}
            />
            <Tooltip title="点名看某一个人写的脚本（收藏不算归属）；清掉即回到「我的／全部」">
              <Select
                allowClear
                showSearch
                placeholder="上传人"
                style={{ width: 130 }}
                optionFilterProp="label"
                value={ownerFilter}
                onChange={(v) => { setOwnerFilter(v || undefined); setSelectedIds([]); }}
                options={ownerOptions}
              />
            </Tooltip>
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
      <Space size={10} wrap>
        <Button type="primary" disabled={!selected.length} onClick={() => setTab('produce')}>
          下一步：投豆包{selected.length ? `（已勾 ${selected.length}）` : ''}
        </Button>
        {!selected.length && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            在上面的表格里勾选脚本（库稿要先定稿才能勾）。
          </Text>
        )}
      </Space>
    </Space>
  );

  // ── ② 投豆包：勾脚本 → 三视图 → 出几版 → （轻量过审）投 ──
  const paneProduce = (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        一个脚本占一个钩子号；「每个出几版」＝板上那条任务的产出数。
        投出去约 25 分钟出片，回来在 ③ 看成片。
      </Text>
      {/* 投豆包这一屏 */}
      <Card size="small" title={`这次要投的脚本（${selected.length}）`}>
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {/* 11-24 用户：「素材也没有预览」——投之前就得看见这几个稿子是从哪条片子来的、点一下能播 */}
          {selected.length ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              {selected.map((s) => {
                const st = scriptStatus(s);
                return (
                  <div key={s.id} style={{ width: 96 }}>
                    {previewOf(s.origin_asset_id, s.name, 84)}
                    <div style={{ marginTop: 4 }}>
                      <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: s.name }}>{s.name}</Text>
                    </div>
                    <Space size={4} style={{ marginTop: 2 }}>
                      <Tag color={st.color} style={{ marginInlineEnd: 0 }}>{st.text}</Tag>
                      <Button
                        size="small" type="link" style={{ padding: 0, height: 18, fontSize: 12 }}
                        onClick={() => setEditor({ open: true, script: s })}
                      >
                        改
                      </Button>
                    </Space>
                  </div>
                );
              })}
            </div>
          ) : (
            <Space size={10} wrap>
              <Text type="secondary" style={{ fontSize: 12 }}>还没勾脚本。</Text>
              <Button size="small" onClick={() => setTab('scripts')}>回 ① 脚本库勾选</Button>
            </Space>
          )}
          <Space wrap size={16}>
            <Space>
              <Text>每个出几版</Text>
              <InputNumber min={1} max={BOARD_TOTAL_MAX} value={boardTotal} onChange={(v) => setBoardTotal(v || 1)} />
            </Space>
            <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setTab('outputs')}>
              ③ 看成片 →
            </Button>
          </Space>
          <div>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>人物三视图</Text>
            <AssetCardPicker value={cardIds} onChange={setCardIds} active />
          </div>
          <Space size={8} wrap>
            <Tooltip title={hint || '投出去占当天号池额度（一个脚本一个钩子号）；约 25 分钟出片，投完自动跳到 ③ 看成片'}>
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
    </Space>
  );

  // ── ③ 看成片（拼接这步暂时走短剧切片，见卡顶说明）──
  const paneOutputs = (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="要拼接（角标／警示语／剧名／片尾引导）先去「短剧切片」"
        description="左侧菜单 短剧切片 → 进剧集 → 详情页那套叠加功能现成能用；素材库这边的组合出片等把它搬过来再放，中间态不摆看不懂的行列矩阵。"
      />
      <AssetOutputWall
        key="simple-outputs"
        reloadToken={reloadToken}
        ownerDefault="all"
        ownerSwitchable={canReview}
        active={tab === 'outputs'}
        onGoToProduction={() => onOpenFullTab('production')}
      />
    </Space>
  );

  return (
    <>
      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as typeof tab)}
        items={[
          { key: 'scripts', label: tabLabel('①', '脚本库', pending.length), children: paneScripts },
          { key: 'produce', label: tabLabel('②', '投豆包', selected.length), children: paneProduce },
          { key: 'outputs', label: '③ 看成片', children: paneOutputs },
        ]}
      />

      {/* 批 U（11-25）：号没凑齐时的退路。本机/没装配号命令的环境，这一框就是唯一走得通的一条 */}
      <Modal
        open={!!hookPaste}
        title={`补钩子编号（还差 ${hookPaste?.need ?? 0} 个）`}
        width={560}
        okText="贴上并重发"
        cancelText="先不投了"
        confirmLoading={busy === 'produce'}
        maskClosable={false}
        onOk={() => void submitHookPaste()}
        onCancel={() => setHookPaste(null)}
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Alert
            type="warning"
            showIcon
            message="这批没有建单：钩子编号没凑齐"
            description={hookPaste?.why || ''}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            编号要在服务器上跑 <Text code>hook_id.py</Text> 取，一个号只能用一次。
            每行贴一个，共贴 {hookPaste?.need ?? 0} 个——已经自动挂上号的脚本会跳过，
            不会把烧过的号再取一遍。
          </Text>
          <Input.TextArea
            rows={Math.min(6, Math.max(2, hookPaste?.need ?? 2))}
            value={hookText}
            onChange={(e) => setHookText(e.target.value)}
            placeholder={'8PZK1\n8PZK2'}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            已贴 {hookParseCodes(hookText).length} / {hookPaste?.need ?? 0} 个
          </Text>
        </Space>
      </Modal>

      {/* 一个共享播放器：列表几十上百行，每行挂一个 Modal 组件树白烧渲染 */}
      <VideoPreviewModal
        open={!!play}
        onClose={() => setPlay(null)}
        title={play?.title || ''}
        assetId={play?.assetId ?? null}
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
    </>
  );
};

export default SimpleLibrary;
