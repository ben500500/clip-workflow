import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Col, Collapse, Input, Row, Select, Space, Table, Tag, Tooltip, Typography, Upload, message,
} from 'antd';
import { CloudUploadOutlined, FolderOpenOutlined, InboxOutlined, LinkOutlined, QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { DEFAULT_TIER, DURATION_TIERS, assetApi } from '../../api/assets';
import type {
  AssetBatch, AssetImportBatchResponse, AssetImportDuplicate,
  AssetPairedManifest, AssetPairedManifestItem, AssetPairedResponse, AssetUploadResponse,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { MonoText, yuan } from './AssetBits';
import { CategorySelect, useAssetCategories } from './AssetCategoryBits';
import { nudgeAssetJobBanner } from './AssetJobBanner';

const { Text } = Typography;
const { TextArea } = Input;

/**
 * 配对判据＝文件在 multipart 里带的那个名字。浏览器只带 basename（后端 `validate_file_name`
 * 同样只留 basename），所以**子目录不参与配对**：`悬念/已完成/小男孩遇贵人.mp4` 和
 * `猎奇/小男孩遇贵人.mp4` 落到服务端是同一个文件名——这种必须在门口就认出来，
 * 投出去只会换来一句 400（后端按大小/顺序猜＝把 A 的画面配上 B 的稿，下游没有任何环节会发现）。
 */
const baseOf = (p: string) => p.replace(/\\/g, '/').split('/').pop() || p;

/** 成稿导入只收视频原片（图片走「文件上传」那页——那是投产的角色卡，不是原片） */
const RAW_VIDEO_RE = /\.(mp4|mov|m4v|webm|avi|mkv|flv|ts)$/i;

/** 单请求整包上限：nginx `client_max_body_size 2G`（2026-11-11 运维席 P1 从 500M 抬上来），
 *  留 ~150M 余量；撞在 nginx 上回的是 413 的 HTML 页，界面只会说"上传失败"，所以宁可在前端先拦。 */
const PAIRED_BODY_LIMIT = 1900 * 1024 * 1024;

/** 清单项在前端配对后的状态（与后端 `import_paired_batch` 的判据一一对应） */
type PairedRowState = 'ok' | 'missing' | 'dup_manifest' | 'dup_file' | 'skipped';

/** 配对状态 → 界面话术（绿=照单全收、红=会被拦、橙=要人处理） */
const PAIRED_STATE: Record<PairedRowState, { text: string; color: string }> = {
  ok: { text: '配上', color: 'green' },
  missing: { text: '缺文件', color: 'red' },
  dup_manifest: { text: '清单重名', color: 'orange' },
  dup_file: { text: '文件夹重名', color: 'orange' },
  skipped: { text: '清单标 skip', color: 'default' },
};

interface PairedRow {
  index: number;
  item: AssetPairedManifestItem;
  /** basename＝配对键 */
  name: string;
  state: PairedRowState;
  size: number | null;
  /** 选文件夹时的相对路径，只用来帮人认出到底命中了哪个子目录 */
  path?: string;
}

interface Props {
  canProduce: boolean;
  /** 点了批次行就把素材列表按这个批次筛 */
  onSelectBatch?: (batchId: string) => void;
  /** A′ UX：页签切回来自动刷新 */
  active?: boolean;
}

/**
 * 导入面板：链接批量导入 / 视频与图片文件批量上传 / 成稿配对导入 / 批次台账。
 *
 * 三个必须在前端讲清楚的口径：
 *  - 导入本身**不扣费**：链接形态只是把地址登记进库，真正花钱的是下一步反推。
 *    所以这里的 budget 是「这批若全按 tier 档反推要多少钱」的预警，不是账单。
 *  - 跨批次重复**默认不入库**，只回「几月几日 谁 导入（AS-XXXX）」；
 *    放行有整批（force_duplicates）和逐条（force_urls）两种粒度，默认用逐条。
 *  - 超单批上限由服务端**自动拆批**（批次名带「第 i/k 批」），不是打回让人自己数。
 *  - 「整批默认原型」（11-04 拍板①）只是给这一批每条素材起个结构层标记，
 *    可不选、不拦任何后续动作；建好之后逐条改在素材列表那一列上点。
 *  - 批 G：文件口同时收图片。图片进来是 `media_kind=image` 的**角色卡**，
 *    四环（反推文案/出文案/投产/拼接）对它都不成立，也不计费——所以它的「下一步」
 *    不是在本面板提交，而是到投产弹窗里被挑走。
 *  - 11-09「成稿配对导入」：原片＋外部已经产好的稿，一次进四个槽位（原片 / 反推稿 /
 *    钩子文案 / 豆包提示词），**0 模型费**。页面上必须把两件事说清楚：
 *    ① 只投清单引用到的那些文件（多出来的字节一个都不上传，重名的会被后端拒收）；
 *    ② 缺哪个槽位就欠哪一步——`need_copy`（有稿没文案，点一下出文案就补上）和
 *    `need_prompt`（没稿，要补只能跑反推，那步花钱）是**两条独立的账**，别混成一句。
 */
const AssetImportPanel: React.FC<Props> = ({ canProduce, onSelectBatch, active = true }) => {
  const [tab, setTab] = useState<'link' | 'file' | 'paired'>('link');

  // ── 链接导入 ──
  const [links, setLinks] = useState('');
  // 直接贴文案导入
  const [copyText, setCopyText] = useState('');
  const [copyBatchName, setCopyBatchName] = useState('');
  const [copyBusy, setCopyBusy] = useState(false);
  // P1（评审定稿⑪）：导入前重复预检（0 元、不建行）——粘贴完就地知道哪些已入库
  const [duplicates, setDuplicates] = useState<Map<string, { code?: string; imported_at?: string | null }>>(new Map());
  useEffect(() => {
    const urls = links.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
    if (!urls.length) {
      setDuplicates(new Map());
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await assetApi.importPreflight(urls);
        const map = new Map<string, { code?: string; imported_at?: string | null }>();
        (res.items || []).forEach((d) => d.source_url_norm && map.set(d.source_url_norm, d));
        setDuplicates(map);
      } catch {
        /* 预检失败静默（提交时后端硬拦还在） */
      }
    }, 600);
    return () => clearTimeout(t);
  }, [links]);
  const [batchName, setBatchName] = useState('');
  const [tier, setTier] = useState<number>(DEFAULT_TIER);
  /** 整批默认钩子原型：链接导入和文件上传共用这一个选择（不选＝整批未分类） */
  const [category, setCategory] = useState<string | undefined>();
  const cats = useAssetCategories();
  const [importing, setImporting] = useState(false);
  const [lastImport, setLastImport] = useState<AssetImportBatchResponse | null>(null);
  /**
   * 贴文案/文件导入被形态闸门跳过的条目（2026-11-11 评审·业务席 P2）。
   * 原来只 console.warn——一线不看控制台，等于「少了 3 条」这件事没人知道。
   */
  const [copySkipped, setCopySkipped] = useState<{ index: number; problems: string[]; text: string }[]>([]);

  // ── 文件上传 ──
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const rawFiles = useRef<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [lastUpload, setLastUpload] = useState<AssetUploadResponse | null>(null);

  // ── 批次台账 ──
  const [batches, setBatches] = useState<AssetBatch[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);

  // ── 成稿配对导入（11-09）：清单 JSON + 原片字节，一次进四个槽位、0 模型费 ──
  const [pairedSpec, setPairedSpec] = useState<AssetPairedManifest | null>(null);
  const [pairedSpecName, setPairedSpecName] = useState('');
  /** 已选的原片字节（真正上传时只投清单引用到的那几个） */
  const [pairedFiles, setPairedFiles] = useState<File[]>([]);
  const [pairedForceDup, setPairedForceDup] = useState(false);
  const [pairedBusy, setPairedBusy] = useState(false);
  const [pairedProgress, setPairedProgress] = useState(0);
  const [lastPaired, setLastPaired] = useState<AssetPairedResponse | null>(null);

  /** basename → 字节（重名的两条都会在这里露出来，前端必须先于后端认出来） */
  const pairedByFile = useMemo(() => {
    const m = new Map<string, File[]>();
    pairedFiles.forEach((f) => m.set(f.name, [...(m.get(f.name) || []), f]));
    return m;
  }, [pairedFiles]);

  const pairedRows = useMemo<PairedRow[]>(() => {
    if (!pairedSpec) return [];
    const items = pairedSpec.items || [];
    const nameCount = new Map<string, number>();
    items.forEach((it) => {
      const n = baseOf(String(it?.video || ''));
      nameCount.set(n, (nameCount.get(n) || 0) + 1);
    });
    return items.map((item, i) => {
      const name = baseOf(String(item?.video || ''));
      const row = { index: i + 1, item, name } as PairedRow;
      if (item.skip) return { ...row, state: 'skipped', size: null };
      // 清单侧重名：后端直接 400 整批（配不出唯一对应，宁可不投也不能猜）
      if ((nameCount.get(name) || 0) > 1) return { ...row, state: 'dup_manifest', size: null };
      const cands = pairedByFile.get(name) || [];
      if (!cands.length) return { ...row, state: 'missing', size: null };
      // 文件侧重名：两个不同子目录里的同名 mp4 到服务端只有一个名字，配不到唯一那条
      if (cands.length > 1) {
        return { ...row, state: 'dup_file', size: cands[0].size, path: `${cands.length} 个同名文件` };
      }
      return { ...row, state: 'ok', size: cands[0].size, path: cands[0].webkitRelativePath || undefined };
    });
  }, [pairedSpec, pairedByFile]);

  const pairedStat = useMemo(() => {
    const ok = pairedRows.filter((r) => r.state === 'ok');
    const matched = new Set(ok.map((r) => r.name));
    const bytes = ok.reduce((a, r) => a + (r.size || 0), 0);
    return {
      ok: ok.length,
      missing: pairedRows.filter((r) => r.state === 'missing').length,
      dupManifest: pairedRows.filter((r) => r.state === 'dup_manifest').length,
      dupFile: pairedRows.filter((r) => r.state === 'dup_file').length,
      skipped: pairedRows.filter((r) => r.state === 'skipped').length,
      needCopy: ok.filter((r) => !!r.item.script_text && !r.item.hook_copy).length,
      noScript: ok.filter((r) => !r.item.script_text).length,
      bytes,
      /** 清单里多出来、没被引用的文件：本口一个都不投（投了会被后端判成 leftover） */
      leftover: pairedFiles.filter((f) => !matched.has(f.name)).length,
      /** 后端按原型名一批次，这里预告会建几批 */
      groups: new Set(ok.map((r) => (r.item.category || '').trim())).size,
    };
  }, [pairedRows, pairedFiles]);

  /** 读配对清单（外部产好的 manifest.json；顶层多余字段如 source_dir/note 直接丢掉不投） */
  const loadPairedManifest = async (file: File) => {
    try {
      const raw = JSON.parse(await file.text());
      const items = (Array.isArray(raw?.items) ? raw.items : Array.isArray(raw) ? raw : null) as
        AssetPairedManifestItem[] | null;
      if (!items || !items.length) {
        message.error('清单里没有 items（要的是 {"items":[{"video":"xxx.mp4", ...}]}）', 8);
        return false;
      }
      const noVideo = items.filter((it) => !String(it?.video || '').trim()).length;
      if (noVideo) {
        message.error(`清单里有 ${noVideo} 条缺 video（原片文件名），补齐后重新选这份清单`, 8);
        return false;
      }
      const prefix = String(raw?.batch_name || '').trim();
      setPairedSpec({ batch_name: prefix || undefined, items });
      setPairedSpecName(file.name);
      setLastPaired(null);
      message.success(`已读入清单：${items.length} 条（其中 skip ${items.filter((i) => i.skip).length} 条）`);
    } catch (e) {
      message.error(`${file.name} 不是合法 JSON：${(e as Error).message}`, 8);
    }
    return false; // 阻止 antd 默认上传
  };

  /** 收原片字节：文件夹里混的 txt/图片/表格在这里就被滤掉（图片是角色卡，走「文件上传」页） */
  const collectPairedVideo = (file: File) => {
    if (!RAW_VIDEO_RE.test(file.name)) return false;
    const f = file as File;
    // 去重键＝「相对路径＋字节数＋修改时间」：重选同一个文件夹不会把待传列表翻倍；
    // 而两个不同子目录里的同名 mp4 相对路径不同 → 两份都留下 → 预览正好把 dup_file 报出来
    const keyOf = (x: File) => `${x.webkitRelativePath || x.name}|${x.size}|${x.lastModified}`;
    setPairedFiles((prev) => (prev.some((p) => keyOf(p) === keyOf(f)) ? prev : [...prev, f]));
    return false;
  };

  const submitPaired = async () => {
    if (!pairedSpec) {
      message.warning('先选配对清单（.json），再选放原片的文件夹');
      return;
    }
    // R-2 同款护栏：上一枪没回来不再接受第二次提交（这口没有唯一约束，连点＝同一片建两行素材）
    if (pairedBusy) return;
    if (!pairedStat.ok) {
      message.warning('一条都没配上：检查清单里的文件名与所选文件夹里的 mp4 是否一一对应');
      return;
    }
    if (pairedStat.bytes > PAIRED_BODY_LIMIT) {
      message.error(
        `配上的 ${pairedStat.ok} 条整包 ${(pairedStat.bytes / 1024 / 1024).toFixed(0)}MB，超了单次上传上限 ${Math.round(PAIRED_BODY_LIMIT / 1024 / 1024)}MB——`
        + '按原型分几次投（每次选对应的文件夹/文件）',
        10,
      );
      return;
    }
    setPairedBusy(true);
    setPairedProgress(0);
    const picked = pairedRows
      .filter((r) => r.state === 'ok')
      .map((r) => (pairedByFile.get(r.name) || [])[0])
      .filter(Boolean) as File[];
    try {
      const res = await assetApi.importPaired(
        {
          files: picked,
          manifest: { ...pairedSpec, batch_name: batchName.trim() || pairedSpec.batch_name },
          max_duration: tier,
          force_duplicates: pairedForceDup || undefined,
        },
        setPairedProgress,
      );
      setLastPaired(res);
      message.success(res.message, 10);
      fetchBatches();
      // 入库即自动排抽帧（后台任务，0 元）；nudge 让任务条立刻亮出来、列表跟着刷新
      if (res.created) nudgeAssetJobBanner();
      // 全配上才清空待传字节；有没配上的留着清单和文件，让人照着预览改完再投
      if (!res.errors?.length) {
        setPairedFiles([]);
        setPairedSpec(null);
        setPairedSpecName('');
      }
    } catch (e) {
      message.error((e as Error).message || '成稿配对导入失败', 10);
    } finally {
      setPairedBusy(false);
    }
  };

  // 直接贴文案提交：按空行分段，一段=一条候选
  const submitCopyImport = async () => {
    const texts = copyText
      .split(/\n{2,}/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!texts.length) {
      message.warning('没有可导入的文案（按空行分隔，一条一段）');
      return;
    }
    setCopyBusy(true);
    try {
      const res = await assetApi.importCopySummaries(copyBatchName, texts);
      message.success(res.message, 6);
      if (res.skipped.length) {
        message.warning(`${res.skipped.length} 条形态不合格被跳过（超字数等）`, 8);
        setCopySkipped(res.skipped);
      } else {
        setCopySkipped([]);
      }
      setCopyText('');
      setCopyBatchName('');
      fetchBatches();
      onSelectBatch?.(res.batch_id);
    } catch (e) {
      message.error((e as Error).message || '贴文案导入失败');
    } finally {
      setCopyBusy(false);
    }
  };

  // 上传文件即导入：txt/csv 读文本 → 按空行分段（无空行则按行分段）→ 直接调导入接口
  const importCopyFromFile = async (file: File) => {
    try {
      const text = await file.text();
      // 优先空行分段（多段式）；整段没有空行时退化为按行分段（一列一条）
      let segs = text.split(/\n{2,}/).map((s) => s.trim()).filter(Boolean);
      if (segs.length <= 1) {
        segs = text.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
      }
      if (!segs.length) {
        message.warning(`文件 ${file.name} 里没有可导入的文案`);
        return false;
      }
      setCopyBusy(true);
      const res = await assetApi.importCopySummaries(
        copyBatchName || `文件导入-${file.name}`,
        segs,
      );
      message.success(res.message, 6);
      if (res.skipped.length) {
        message.warning(`${res.skipped.length} 条形态不合格被跳过（超字数等）`, 8);
        setCopySkipped(res.skipped);
      } else {
        setCopySkipped([]);
      }
      setCopyText('');
      setCopyBatchName('');
      fetchBatches();
      onSelectBatch?.(res.batch_id);
    } catch (e) {
      message.error((e as Error).message || `文件 ${file.name} 导入失败`);
    } finally {
      setCopyBusy(false);
    }
    return false; // 阻止 antd 默认上传
  };

  const fetchBatches = useCallback(async () => {
    setBatchLoading(true);
    try {
      const data = await assetApi.listBatches({ limit: 100 });
      setBatches(data.items || []);
    } catch (e) {
      message.error((e as Error).message || '加载批次列表失败');
    } finally {
      setBatchLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  // A′ UX：切走再切回页签时自动刷新批次台账
  const wasActive = React.useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) fetchBatches();
    wasActive.current = active;
  }, [active, fetchBatches]);

  const parsedLinks = links
    .split(/[\r\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const submitLinks = async (forceUrls?: string[]) => {
    if (!parsedLinks.length) {
      message.warning('粘贴至少一条分享链接');
      return;
    }
    // R-2（11-04 第二轮审核）：连点两次＝同一批链接发两个请求，库里没有唯一约束，
    // 于是同一条视频建出两行素材、反推**按行计费＝同一部片子付两遍钱**（实测 0.0972 元/条）。
    // 上一份请求没回来之前不再接受第二次提交。
    if (importing) return;
    setImporting(true);
    try {
      const res = await assetApi.importBatch({
        links: parsedLinks,
        name: batchName || undefined,
        prompt_max_duration: tier,
        force_urls: forceUrls,
        category_id: category || null,
      });
      setLastImport(res);
      message.success(res.message);
      fetchBatches();
      // 11-06 用户拍板：导入即自动下载原片——下载是后台任务，nudge 让任务条立刻亮出来
      if ((res.items || []).length) nudgeAssetJobBanner();
      // 原来只在「没有重复且不是放行请求」时清空输入框，于是**这一次真建出来的那几条还留在框里**：
      // 下次再点（或点某条的放行）它们就全被判成跨批次重复，一线看到的是"怎么全是重复"。
      // 改成按返回的 items 精确摘掉已入库的那几行，只留下这次没建成的（重复/被跳过）继续在框里等处理。
      const done = new Set((res.items || []).map((it) => (it.source_url || '').trim()));
      if (done.size) {
        const rest = parsedLinks.filter((u) => !done.has(u));
        setLinks(rest.join('\n'));
      } else if (!res.duplicates?.length && !forceUrls) {
        setLinks('');
      }
    } catch (e) {
      message.error((e as Error).message || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  /**
   * 逐条放行：**只**放行点名的这一条。
   *
   * R-2（11-04 第二轮审核）原来这里把「点名的这条 + 上一次回显里其余全部重复」一起塞进
   * `force_urls`，注释还写着「别拿整批陪跑」——实现正好相反，等于**整批放行**：
   * 一线只想放一条，结果另外几条重复素材一起入库、反推按行扣钱。
   * 放行成功后这条会从重复清单里消失（新响应的 duplicates 不再含它），
   * 所以不存在"再点一次把同一部片子二次入库"的路径。
   */
  const forceOne = (dup: AssetImportDuplicate) => submitLinks([dup.source_url]);

  const submitFiles = async () => {
    if (!rawFiles.current.length) {
      message.warning('选择要上传的视频或图片文件');
      return;
    }
    // 2026-11-11 评审（运维席）：整包超过 nginx 上限时，用户看到的是 413 的白屏报错，
    // 而不是「这批 2.3G 要拆成两批」。在门口按字节算总量，先说清楚。
    const totalBytes = rawFiles.current.reduce((a, f) => a + f.size, 0);
    if (totalBytes > PAIRED_BODY_LIMIT) {
      message.error(
        `已选 ${rawFiles.current.length} 个文件共 ${(totalBytes / 1024 / 1024).toFixed(0)}MB，`
        + `超过单次上传上限 ${(PAIRED_BODY_LIMIT / 1024 / 1024).toFixed(0)}MB——请分批选，先少选几个传`,
        10,
      );
      return;
    }
    setUploading(true);
    setProgress(0);
    try {
      const res = await assetApi.uploadBatch(
        {
          files: rawFiles.current,
          name: batchName || undefined,
          max_duration: tier,
          category_id: category,
        },
        setProgress,
      );
      setLastUpload(res);
      message.success(res.message);
      fetchBatches();
      if (!res.failed?.length) {
        setFileList([]);
        rawFiles.current = [];
      }
    } catch (e) {
      message.error((e as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  /** 补投只投失败的那几个，且落回**同一批次**（不新建批次行，对账才认得出） */
  const retryFailed = async () => {
    const names = lastUpload?.failed_files || [];
    if (!lastUpload?.batch_id || !names.length) return;
    const again = rawFiles.current.filter((f) => names.includes(f.name));
    if (!again.length) {
      message.warning('失败的文件已不在本次选择里，请重新选中这几个原文件再补传');
      return;
    }
    setUploading(true);
    try {
      const res = await assetApi.retryUpload({ batch_id: lastUpload.batch_id, files: again });
      setLastUpload(res);
      message.success(res.message);
      fetchBatches();
    } catch (e) {
      message.error((e as Error).message || '补传失败');
    } finally {
      setUploading(false);
    }
  };

  const batchCols: ColumnsType<AssetBatch> = [
    {
      title: '批次',
      dataIndex: 'code',
      width: 130,
      render: (v: string, row) => (
        <a onClick={() => onSelectBatch?.(row.id)}>
          <MonoText>{v}</MonoText>
        </a>
      ),
    },
    // 批 N（评审二·P2）：给名称定宽＋ellipsis——原来不定宽，被其它列挤压后整列只剩两三个字
    { title: '名称', dataIndex: 'name', width: 150, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '来路',
      dataIndex: 'source_kind',
      width: 70,
      render: (v: string) => <Tag>{v === 'link' ? '链接' : '文件'}</Tag>,
    },
    { title: '条数', dataIndex: 'item_count', width: 66 },
    {
      // 批 N（评审二·P2）：width 70 装不下四个字的表头（折行成两行）
      title: '时长上限',
      dataIndex: 'prompt_max_duration',
      width: 88,
      render: (v: number | null) => (v ? `${v}s` : '未定'),
    },
    {
      title: '创建',
      dataIndex: 'created_at',
      width: 120,
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {parseServerTime(v)?.format('MM-DD HH:mm') || '-'}
        </Text>
      ),
    },
  ];

  // 用户口径 2026-09：批次账目不再占大块空间——钱的明细收进行展开，看哪行点哪行
  const batchExpand = (row: AssetBatch) => (
    <div style={{ padding: '4px 12px', fontSize: 12 }}>
      <Space size={16} wrap>
        <span>
          预估 <b>{yuan(row.cost_estimate)}</b>
        </span>
        <span>
          实扣 <b>{yuan(row.cost_actual)}</b>
          {row.cost_actual != null && row.cost_estimate != null && row.cost_actual > row.cost_estimate && (
            <Tag color="warning" style={{ marginLeft: 4 }}>
              超预估
            </Tag>
          )}
          <Tooltip title="实扣是按（反推文案 + 查时长）重新汇总的，不是逐条累加；反推文案记的是按时长上限推算的额度，对账用，别当精确值">
            <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
          </Tooltip>
        </span>
        <span>预算上限 {row.budget_cap != null ? yuan(row.budget_cap) : '全局默认'}</span>
        <span>
          预算检查{' '}
          {row.budget_gate ? (
            <Tag color={row.budget_gate === 'blocked' ? 'red' : row.budget_gate === 'need_approval' ? 'orange' : 'green'}>
              {row.budget_gate === 'blocked' ? '已拦下' : row.budget_gate === 'need_approval' ? '要审批' : '正常'}
            </Tag>
          ) : (
            '-'
          )}
        </span>
        <span>档位 {row.prompt_max_duration ? `${row.prompt_max_duration}s` : '未定'}</span>
      </Space>
      {row.budget_note && (
        <div style={{ color: '#888', marginTop: 4 }}>预算说明：{row.budget_note}</div>
      )}
    </div>
  );

  /** 成稿导入的配对预览表：一行＝清单里的一条，状态就是后端那一枪会怎么处理它 */
  const pairedCols: ColumnsType<PairedRow> = [
    {
      title: '配对',
      key: 'state',
      width: 92,
      render: (_, r) => {
        const s = PAIRED_STATE[r.state];
        return <Tag color={s.color} style={{ fontSize: 11 }}>{s.text}</Tag>;
      },
    },
    {
      title: '清单里的原片',
      key: 'video',
      ellipsis: true,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{r.name}</Text>
          {r.path && r.path.includes('/') && (
            <Text type="secondary" style={{ fontSize: 11 }}>{r.path}</Text>
          )}
        </Space>
      ),
    },
    { title: '标题', key: 'title', width: 150, ellipsis: true, render: (_, r) => r.item.title || '-' },
    { title: '原型', key: 'cat', width: 92, render: (_, r) => r.item.category || <Text type="secondary">未填</Text> },
    {
      title: (
        <Tooltip title="四个槽位：原片（配对上就有）／反推稿 script_text／钩子文案 hook_copy／豆包提示词 doubao_prompt。缺稿＝欠一次反推（花钱）；有稿没文案＝欠一次出文案（免费）">
          <span>槽位</span>
        </Tooltip>
      ),
      key: 'slots',
      width: 120,
      render: (_, r) => (
        <Space size={2}>
          <Tag color={r.item.script_text ? 'green' : 'default'} style={{ fontSize: 11 }}>稿</Tag>
          <Tag color={r.item.hook_copy ? 'green' : 'default'} style={{ fontSize: 11 }}>案</Tag>
          <Tag color={r.item.doubao_prompt ? 'green' : 'default'} style={{ fontSize: 11 }}>示</Tag>
        </Space>
      ),
    },
    {
      title: '大小',
      key: 'size',
      width: 80,
      render: (_, r) => (r.size != null ? <Text type="secondary" style={{ fontSize: 12 }}>{(r.size / 1024 / 1024).toFixed(1)}MB</Text> : '-'),
    },
  ];

  if (!canProduce) {
    return (
      <Card size="small">
        <Alert
          type="info"
          showIcon
          message="当前角色不能导入"
          description="导入/上传是生产动作，只有素材专员、运营与管理员可以做；浏览不受影响，素材列表照常可看。"
        />
        <Table<AssetBatch>
          rowKey="id"
          size="small"
          style={{ marginTop: 16 }}
          loading={batchLoading}
          columns={batchCols}
          dataSource={batches}
          expandable={{ expandedRowRender: batchExpand, rowExpandable: () => true }}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 批` }}
        />
      </Card>
    );
  }

  return (
    <>
    <Row gutter={12}>
      {/* P1 新增：直接贴文案——跳过链接/反推，直挂候选进审核队列 */}
      <Col span={24} style={{ marginBottom: 12 }}>
        <Collapse
          size="small"
          /* 2026-11-12 复杂度审计：贴文案是当前主路径（两轮实走评审全走它），默认收起
             等于每次多一击。默认展开；链接/文件/成稿配对仍是并列入口不受影响。 */
          defaultActiveKey={['paste-copy']}
          items={[{
            key: 'paste-copy',
            label: <Text strong style={{ fontSize: 12 }}>直接贴文案（跳过链接/反推，直进审核队列）</Text>,
            children: (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已有外部生成好的钩子文案？按空行分段粘贴（一段=一条候选），提交后直进审核队列——后面质检、投产、投板照走。
                </Text>
                <Input
                  placeholder="批次名（可选，留空自动命名）"
                  value={copyBatchName}
                  onChange={(e) => setCopyBatchName(e.target.value)}
                  style={{ width: 260 }}
                  size="small"
                />
                <Input.TextArea
                  rows={6}
                  placeholder={'一条文案一段（空行分隔），例：\n\n她替姐姐嫁的第二天，新郎出现在她姐的婚礼上\n\n总裁摘下手表坐在塑料凳上吃泡面，秘书问他为什么'}
                  value={copyText}
                  onChange={(e) => setCopyText(e.target.value)}
                />
                <Space size={8} wrap>
                  <Button
                    type="primary"
                    size="small"
                    loading={copyBusy}
                    disabled={!copyText.trim()}
                    onClick={submitCopyImport}
                  >
                    导入进审核队列
                  </Button>
                  <Upload
                    accept=".txt,.csv,.text"
                    showUploadList={false}
                    beforeUpload={importCopyFromFile}
                    disabled={copyBusy}
                  >
                    <Button size="small" icon={<InboxOutlined />} loading={copyBusy} disabled={copyBusy}>
                      上传文件导入（.txt/.csv，空行或换行分条）
                    </Button>
                  </Upload>
                </Space>
                {!!copySkipped.length && (
                  <Alert
                    type="warning"
                    showIcon
                    message={`${copySkipped.length} 条被形态闸门拦下、没进审核队列（改完可以再贴一次，已入库的不会重复）`}
                    description={
                      <div style={{ maxHeight: 180, overflow: 'auto' }}>
                        {copySkipped.map((s) => (
                          <div key={s.index} style={{ fontSize: 12 }}>
                            第 {s.index} 条（{s.problems.join('；')}）：{s.text.slice(0, 40)}
                          </div>
                        ))}
                      </div>
                    }
                    style={{ marginTop: 4 }}
                  />
                )}
              </Space>
            ),
          }]}
        />
      </Col>
      <Col span={24}>
        <Card
          size="small"
          title={
            <Space>
              <Button type={tab === 'link' ? 'primary' : 'default'} size="small" icon={<LinkOutlined />} onClick={() => setTab('link')}>
                链接导入
              </Button>
              <Button type={tab === 'file' ? 'primary' : 'default'} size="small" icon={<CloudUploadOutlined />} onClick={() => setTab('file')}>
                文件上传
              </Button>
              <Button type={tab === 'paired' ? 'primary' : 'default'} size="small" icon={<FolderOpenOutlined />} onClick={() => setTab('paired')}>
                成稿导入
              </Button>
              <Tooltip title="外部已经产好稿的一批原片：清单(JSON) + 原片文件夹一起投，原片/反推稿/钩子文案/豆包提示词四个槽位一次进库，0 模型费">
                <Text type="secondary" style={{ fontSize: 12 }}>已有人工稿的原片走这页</Text>
              </Tooltip>
            </Space>
          }
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space.Compact style={{ width: '100%' }}>
              <Text style={{ lineHeight: '32px', marginRight: 8 }}>批次名</Text>
              <Input
                placeholder={`默认「链接导入 ${tier}s」；超上限拆批会自动加「第 i/k 批」`}
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
              />
              <Select
                style={{ width: 150 }}
                value={tier}
                onChange={setTier}
                options={DURATION_TIERS.map((t) => ({ value: t, label: `${t}s${t === DEFAULT_TIER ? '（默认）' : ''}` }))}
              />
            </Space.Compact>

            {tab !== 'paired' && (
              <Space wrap align="center">
                <Text>整批默认原型</Text>
                <Tooltip title="给这一批每条素材起个开头套路的标记（A–G，照《钩子模版换皮参数设定.docx》）；不选照样导入和反推，之后在素材列表「原型」那列逐条改">
                  <Text type="secondary" style={{ fontSize: 12 }}>可不选，鼠标放这看说明</Text>
                </Tooltip>
                <CategorySelect
                  items={cats.activeItems}
                  value={category}
                  onChange={setCategory}
                  width={250}
                  loading={cats.loading}
                  placeholder="可不选（这批全标未分类）"
                />
              </Space>
            )}
            {tab === 'paired' && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                成稿导入的原型来自清单每条的 category（一个原型建一个批次），所以这里不设整批默认值；
                「批次名」这一栏会作为批次名前缀写进清单（留空用清单自带的）。
              </Text>
            )}

            {tab === 'link' ? (
              <>
                <TextArea
                  rows={10}
                  value={links}
                  onChange={(e) => setLinks(e.target.value)}
                  placeholder={'一行一条分享链接（可以整段粘含中文的分享文案，后端自己提 http token）\n例如：https://v.douyin.com/xxxx/ 这剧太上头了'}
                />
            {duplicates.size > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 6 }}
                message={`${duplicates.size} 条已导入过（提交会被拦，逐条放行或删除）——${[...duplicates.values()].slice(0, 3).map((d) => d.code).join('、')}${duplicates.size > 3 ? '…' : ''}`}
              />
            )}
                <Space>
                  <Button type="primary" loading={importing} onClick={() => submitLinks()}>
                    导入 {parsedLinks.length} 条链接
                  </Button>
                  <Tooltip title="导入后系统自动下载原片（解析 0.01 元/条照记账，进批次成本）；不想要这批的片就别导入。进度看页面顶上的任务条">
                    <Text type="secondary" style={{ fontSize: 12 }}>导入后自动下载原片</Text>
                  </Tooltip>
                </Space>
              </>
            ) : tab === 'file' ? (
              <>
                <Upload.Dragger
                  multiple
                  /**
                   * 批 G：这里同时收视频和图片。图片（jpg/jpeg/png/webp）落库后
                   * `media_kind=image`，**只作投产的角色卡**——不反推、不出文案、不拼接、不抽帧、不计费。
                   * ⚠️ 只改这一个 accept，不改采集侧那两个全局视频白名单
                   * （`prompt_service.UPLOAD_ALLOWED_EXTS` / `settings.ALLOWED_VIDEO_EXTENSIONS`）：
                   * 那两处一放图片，就能把 jpg 喂进 doc/120 视频反推，白扣一次钱。
                   */
                  accept="video/*,.jpg,.jpeg,.png,.webp"
                  fileList={fileList}
                  beforeUpload={(file) => {
                    rawFiles.current = [...rawFiles.current, file as unknown as File];
                    // status 'done' 只表示「已在待传列表里」：这里没真上传（beforeUpload 返回 false，
                    // 字节要在点「上传」时由 uploadBatch 一次性带走）
                    setFileList((prev) => [
                      ...prev,
                      { uid: `${prev.length}-${file.name}`, name: file.name, size: file.size, status: 'done' },
                    ]);
                    return false;
                  }}
                  onRemove={(file) => {
                    rawFiles.current = rawFiles.current.filter((f) => f.name !== file.name);
                    setFileList((prev) => prev.filter((p) => p.uid !== file.uid));
                  }}
                >
                  <p className="ant-upload-drag-icon">
                    <InboxOutlined />
                  </p>
                  <p className="ant-upload-text">拖入或选择视频／图片文件（可多个）</p>
                  <p className="ant-upload-hint" style={{ fontSize: 12 }}>
                    视频直接落到我们自己的存储；单文件失败不影响整批，可一键补传。
                    图片是<b>投产用的角色卡</b>（不反推、不计费），长边超了只提醒不拦。
                  </p>
                </Upload.Dragger>
                <Space>
                  <Button type="primary" loading={uploading} onClick={submitFiles}>
                    上传 {rawFiles.current.length} 个文件
                  </Button>
                  {uploading && <Progressish percent={progress} />}
                  <Tooltip title="反推文案时文件还要经中转再上传一次，所以文件批次的预估里含每次 0.001 元的上传费（图片不进反推，不收这笔）">
                    <Text type="secondary" style={{ fontSize: 12 }}>文件批次预估含 0.001 元/条中转上传费</Text>
                  </Tooltip>
                </Space>
              </>
            ) : (
              <>
                <Space wrap align="center">
                  <Upload accept=".json,.txt" showUploadList={false} beforeUpload={loadPairedManifest} disabled={pairedBusy}>
                    <Button size="small" icon={<InboxOutlined />}>选配对清单（.json）</Button>
                  </Upload>
                  <Upload directory accept="video/*" showUploadList={false} beforeUpload={collectPairedVideo} disabled={pairedBusy}>
                    <Button size="small" icon={<FolderOpenOutlined />}>选原片所在文件夹</Button>
                  </Upload>
                  <Upload multiple accept="video/*" showUploadList={false} beforeUpload={collectPairedVideo} disabled={pairedBusy}>
                    <Button size="small" icon={<CloudUploadOutlined />}>或手工多选几个 mp4</Button>
                  </Upload>
                  {!!pairedFiles.length && (
                    <Button size="small" onClick={() => setPairedFiles([])} disabled={pairedBusy}>
                      清空已选文件
                    </Button>
                  )}
                </Space>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  清单：{pairedSpec ? `${pairedSpec.items.length} 条（${pairedSpecName}）` : '还没选'}；
                  已选原片 {pairedFiles.length} 个 · 配上的整包 {(pairedStat.bytes / 1024 / 1024).toFixed(0)}MB
                  （<b>只投清单引用到的那些</b>，文件夹里多出来的字节不会上传）
                </Text>

                {!!pairedSpec && (
                  <Alert
                    type={pairedStat.missing + pairedStat.dupManifest + pairedStat.dupFile + pairedStat.leftover ? 'warning' : 'success'}
                    showIcon
                    message={
                      `配上 ${pairedStat.ok} 条（按原型会建 ${pairedStat.groups} 个批次）· `
                      + `缺文件 ${pairedStat.missing} · 清单重名 ${pairedStat.dupManifest} · 文件夹重名 ${pairedStat.dupFile} · `
                      + `清单标 skip ${pairedStat.skipped} · 多出来的文件 ${pairedStat.leftover}`
                    }
                    description={
                      <Space direction="vertical" size={2}>
                        <Text style={{ fontSize: 12 }}>
                          两条欠账分开记：<b>有稿没文案 {pairedStat.needCopy} 条</b>（入库后点一下「出文案」就补上，不吃反推钱）；
                          <b> 没反推稿 {pairedStat.noScript} 条</b>（要补只能跑一次反推，那步花钱；不补则过审时没有稿做一致性对照）。
                        </Text>
                        {(pairedStat.dupManifest > 0 || pairedStat.dupFile > 0) && (
                          <Text type="warning" style={{ fontSize: 12 }}>
                            重名的一律不投：后端按文件名一一对应，猜大小/顺序配错＝A 的画面配 B 的稿，后面没有任何环节能发现。
                            请给其中一份改名，或在清单里把它标 skip。
                          </Text>
                        )}
                        {pairedStat.missing > 0 && (
                          <Text type="warning" style={{ fontSize: 12 }}>
                            缺文件的那几条照样不会入库（清单里的 video 是纯文件名匹配，子目录不参与）——请确认选到了对应文件夹。
                          </Text>
                        )}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          人工写的文案就算超字数也照样入库、只在结果里点名（这是人写的稿，扔掉等于让ta白干）；
                          真正拦下来的是审核口。
                        </Text>
                      </Space>
                    }
                  />
                )}

                {!!pairedSpec && (
                  <Table<PairedRow>
                    rowKey="index"
                    size="small"
                    columns={pairedCols}
                    dataSource={pairedRows}
                    pagination={{ pageSize: 12, showTotal: (t) => `共 ${t} 条清单项` }}
                  />
                )}

                <Space wrap align="center">
                  <Button
                    type="primary"
                    loading={pairedBusy}
                    disabled={!pairedStat.ok}
                    onClick={submitPaired}
                  >
                    配对导入 {pairedStat.ok} 条（0 模型费）
                  </Button>
                  {pairedBusy && <Progressish percent={pairedProgress} />}
                  <Checkbox checked={pairedForceDup} onChange={(e) => setPairedForceDup(e.target.checked)} disabled={pairedBusy}>
                    库里已有同名素材也要再入一份
                  </Checkbox>
                  <Tooltip title="默认不重复入库：库里已有同名原片的那几条会被跳过并在结果里点名。勾上这条＝照样再入一份（会多占存储、也会被当成两条素材投产）">
                    <QuestionCircleOutlined style={{ color: '#999' }} />
                  </Tooltip>
                </Space>
              </>
            )}

            {lastImport && (
              <Alert
                type={lastImport.duplicates?.length ? 'warning' : 'success'}
                showIcon
                message={lastImport.message}
                description={
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {lastImport.split_into && (
                      <Text style={{ fontSize: 12 }}>{lastImport.split_into.note}</Text>
                    )}
                    {!!lastImport.skipped?.length && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        清洗提示：{lastImport.skipped.slice(0, 6).join('；')}
                      </Text>
                    )}
                    {lastImport.budget?.gate !== 'ok' && (
                      <Text type="warning" style={{ fontSize: 12 }}>
                        {lastImport.budget.note || `这批全按 ${lastImport.budget.tier}s 上限反推文案预估要 ${yuan(lastImport.budget.cost_estimate)}，超了单批上限 ${yuan(lastImport.budget.cap)}`}
                      </Text>
                    )}
                  </Space>
                }
              />
            )}

            {!!lastImport?.duplicates?.length && (
              <Card size="small" title={`跨批次重复 ${lastImport.duplicates.length} 条（默认没入库）`} style={{ background: '#fffbe6' }}>
                <Table<AssetImportDuplicate>
                  rowKey={(r) => r.source_url}
                  size="small"
                  pagination={false}
                  dataSource={lastImport.duplicates}
                  columns={[
                    {
                      title: '你提交的链接',
                      dataIndex: 'source_url',
                      ellipsis: true,
                      render: (v: string) => <MonoText>{v}</MonoText>,
                    },
                    {
                      title: '已存在的素材',
                      key: 'existing',
                      width: 260,
                      render: (_, r) => (
                        <Space direction="vertical" size={0}>
                          <MonoText>{r.existing.code}</MonoText>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {r.hint || r.existing.hint}
                          </Text>
                        </Space>
                      ),
                    },
                    {
                      title: '',
                      key: 'op',
                      width: 100,
                      render: (_, r) => (
                        // 上一份放行请求没回来前掐住按钮：连点两次＝同一部片子建两行素材（R-2）
                        <Button size="small" loading={importing} disabled={importing} onClick={() => forceOne(r)}>
                          仍要入库
                        </Button>
                      ),
                    },
                  ]}
                />
              </Card>
            )}

            {lastUpload && (
              <Alert
                type={lastUpload.failed?.length ? 'warning' : 'success'}
                showIcon
                message={lastUpload.message}
                description={
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {!!lastUpload.failed?.length && (
                      <>
                        {lastUpload.failed.slice(0, 8).map((f) => (
                          <Text key={f.file_name} style={{ fontSize: 12 }}>
                            {f.file_name}：{f.error}
                          </Text>
                        ))}
                        <Button size="small" icon={<ReloadOutlined />} onClick={retryFailed} loading={uploading}>
                          一键补传这 {lastUpload.failed_files.length} 个（放回同一批次）
                        </Button>
                      </>
                    )}
                    {/* 批 G：图片尺寸/画幅超限**不拒收**，但必须逐张看见——
                        角色卡的宽高比决定成片是竖屏还是横屏，看不见这条就会投出一批横屏片 */}
                    {!!lastUpload.image_notes?.length && (
                      <div>
                        <Text type="warning" style={{ fontSize: 12 }}>
                          {lastUpload.image_notes.length} 张图入库时量出要留意的尺寸/画幅：
                        </Text>
                        {lastUpload.image_notes.slice(0, 8).map((note, i) => (
                          <div key={`${note.file_name}-${i}`} style={{ fontSize: 12, color: '#8c8c8c' }}>
                            {note.file_name || '未命名'}
                            {note.resolution ? `（${note.resolution}${note.ratio ? ` · ${note.ratio}` : ''}）` : ''}
                            ：{note.notes.join('；')}
                          </div>
                        ))}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          照样收下了，不改也能用；想竖屏就换竖版卡重传一张。
                        </Text>
                      </div>
                    )}
                  </Space>
                }
              />
            )}

            {/* 11-09 成稿配对导入的结果：欠账两条轴分开点名，别合成一句「还差文案」 */}
            {lastPaired && (
              <Alert
                type={lastPaired.created ? 'success' : 'warning'}
                showIcon
                message={lastPaired.message}
                description={
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {!!lastPaired.batches?.length && (
                      <Text style={{ fontSize: 12 }}>
                        建了 {lastPaired.batches.length} 个批次：
                        {lastPaired.batches.map((b) => (
                          <a key={b.id} style={{ marginRight: 10 }} onClick={() => onSelectBatch?.(b.id)}>
                            <MonoText>{b.code}</MonoText>（{b.item_count} 条）
                          </a>
                        ))}
                      </Text>
                    )}
                    {!!lastPaired.need_copy?.length && (
                      <Text type="success" style={{ fontSize: 12 }}>
                        {lastPaired.need_copy.length} 条有稿没文案 → 到「出文案」勾这批点一次就补上（吃的是稿，不再花反推钱）：
                        {lastPaired.need_copy.slice(0, 12).join('、')}
                        {lastPaired.need_copy.length > 12 ? '…' : ''}
                      </Text>
                    )}
                    {!!lastPaired.need_prompt?.length && (
                      <Text type="warning" style={{ fontSize: 12 }}>
                        {lastPaired.need_prompt.length} 条没反推稿 → 要补只能跑一次反推（那步花钱）；不补则过审时没有稿做一致性对照：
                        {lastPaired.need_prompt.slice(0, 12).join('、')}
                        {lastPaired.need_prompt.length > 12 ? '…' : ''}
                      </Text>
                    )}
                    {!!lastPaired.shape_warnings?.length && (
                      <div>
                        <Text type="warning" style={{ fontSize: 12 }}>
                          {lastPaired.shape_warnings.length} 条人工文案形态不合格（已照样入库，审核口才拦）：
                        </Text>
                        {lastPaired.shape_warnings.slice(0, 8).map((w, i) => (
                          <div key={`${w.code}-${i}`} style={{ fontSize: 12, color: '#8c8c8c' }}>
                            {w.code} {w.video}：{w.problems.join('；')}
                          </div>
                        ))}
                      </div>
                    )}
                    {!!lastPaired.unknown_categories?.length && (
                      <Text type="warning" style={{ fontSize: 12 }}>
                        这些原型名不在字典里，已落未分类（要让它们可选，去「原型字典」加行）：
                        {lastPaired.unknown_categories.join('、')}
                      </Text>
                    )}
                    {!!lastPaired.skipped?.length && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        清单里 skip/丢弃 {lastPaired.skipped.length} 条：
                        {lastPaired.skipped.slice(0, 6).map((s) => `${s.video || `第 ${s.index} 项`}（${s.reason}）`).join('；')}
                      </Text>
                    )}
                    {!!lastPaired.errors?.length && (
                      <Text type="warning" style={{ fontSize: 12 }}>
                        没配上 {lastPaired.errors.length} 条（改名或在清单里标 skip 后重投这几条）：
                        {lastPaired.errors.slice(0, 6).map((e) => `${e.video || `第 ${e.index} 项`}：${e.error}`).join('；')}
                      </Text>
                    )}
                    {!!lastPaired.leftover_files?.length && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        文件夹里另有 {lastPaired.leftover_files.length} 个文件清单没引用，没上传：
                        {lastPaired.leftover_files.slice(0, 5).join('、')}
                        {lastPaired.leftover_files.length > 5 ? '…' : ''}
                      </Text>
                    )}
                    {lastPaired.frames && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        抽帧：排了 {lastPaired.frames.enqueued} 个（审核台卡片靠它，0 元）
                        {lastPaired.frames.note ? ` · ${lastPaired.frames.note}` : ''}
                      </Text>
                    )}
                  </Space>
                }
              />
            )}
          </Space>
        </Card>
      </Col>

    </Row>
    {/* 用户口径 2026-11-09：整个批次台账不占主区——收进下方折叠块（默认收起），
        标题带上概览数字（批次数/素材/实扣合计），要用再点开；行可展开看单批账目 */}
    <Collapse
      size="small"
      style={{ marginTop: 12 }}
      items={[{
        key: 'batch-ledger',
        label: (
          <Space size={8} wrap>
            <Text strong style={{ fontSize: 12 }}>批次台账</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {batches.length} 批 · 素材 {batches.reduce((a, b) => a + (b.item_count || 0), 0)} 条 · 实扣合计{' '}
              {yuan(batches.reduce((a, b) => a + (b.cost_actual || 0), 0))}（点开看每批，行内可展开账目）
            </Text>
          </Space>
        ),
        extra: (
          <Button size="small" icon={<ReloadOutlined />} onClick={(e) => { e.stopPropagation(); fetchBatches(); }}>
            刷新
          </Button>
        ),
        children: (
          <Table<AssetBatch>
            rowKey="id"
            size="small"
            loading={batchLoading}
            columns={batchCols}
            dataSource={batches}
            expandable={{ expandedRowRender: batchExpand, rowExpandable: () => true }}
            pagination={{
              pageSize: 12,
              showTotal: (t) =>
                `共 ${t} 批 · 素材 ${batches.reduce((a, b) => a + (b.item_count || 0), 0)} 条 · 实扣合计 ${yuan(batches.reduce((a, b) => a + (b.cost_actual || 0), 0))}`,
            }}
          />
        ),
      }]}
    />
    </>
  );
};

/** 上传进度条：antd 的 Progress 在这里只是显示，不参与逻辑 */
const Progressish: React.FC<{ percent: number }> = ({ percent }) => (
  <Tag color={percent >= 100 ? 'green' : 'blue'}>上传 {percent}%</Tag>
);

export default AssetImportPanel;
