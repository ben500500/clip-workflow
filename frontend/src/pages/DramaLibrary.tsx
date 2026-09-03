import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Form, Input, Button, Select, Table, Tag, Modal, message, Space, Typography,
  Popconfirm, Drawer, Descriptions, Upload, Image as AntImage, Empty, Tooltip, Spin,
  Radio, Checkbox, Divider, Alert, Steps, Progress,
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, ImportOutlined,
  UploadOutlined, LinkOutlined, FileImageOutlined, ReloadOutlined, ExportOutlined,
  CloudSyncOutlined,
} from '@ant-design/icons';
import { DatePicker } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import dayjs from 'dayjs';
import {
  Drama, DramaDetail, DramaCreateParams, DramaUpdateParams, DramaImportRow,
  listDramas, getDrama, createDrama, updateDrama, deleteDrama,
  uploadDramaImage, addDramaStill, deleteDramaStill, linkDramaAccounts,
  dramaImportParse, dramaImportPreview, dramaImportConfirm,
  getDramaSliceStatus, linkDramaEpisodes,
  DramaSliceStatus, getTopicPresets, TopicPreset, feishuImportDrama,
} from '../api/dramas';
import { lanSourceApi } from '../api/lanSource';
import type { LanSourceEpisodeItem } from '../api/lanSource';
import { publishApi } from '../api/publish';
import { theaterApi } from '../api/theaters';
import type { Theater } from '../types';
import type { VideoAccount } from '../types';

const { Text } = Typography;

// 受控枚举
const FREQUENCIES = ['男频', '女频'];
const DRAMA_TYPES = ['AI真人剧', '真人剧', '动漫', '微短剧'];
const LISTING_STATUSES = ['草稿', '待上架', '已上架', '已下架', '归档'];
const RATINGS = ['SS+', '新剧S+', '新剧A+', '新剧B+'];
const STATUS_COLORS: Record<string, string> = {
  已上架: 'green',
  待上架: 'orange',
  草稿: 'default',
  已下架: 'red',
  归档: 'default',
  // 切片产线阶段状态
  completed: 'green',
  running: 'blue',
  pending: 'orange',
  failed: 'red',
  cancelled: 'red',
  unknown: 'default',
};

const DraggableUpload: React.FC<{
  text: string;
  onFile: (key: string, name: string) => void;
}> = ({ text, onFile }) => {
  const [uploading, setUploading] = useState(false);
  const handle = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadDramaImage(file);
      onFile(res.file_key, res.file_name);
      message.success('图片上传成功');
    } catch (e) {
      message.error((e as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
    return false;
  };
  return (
    <Upload.Dragger
      beforeUpload={handle}
      showUploadList={false}
      accept=".png,.jpg,.jpeg,.webp,.gif,.bmp"
      disabled={uploading}
    >
      <p className="ant-upload-drag-icon"><FileImageOutlined /></p>
      <p className="ant-upload-text">{uploading ? '上传中…' : text}</p>
    </Upload.Dragger>
  );
};

const DramaLibrary: React.FC = () => {
  const [data, setData] = useState<Drama[]>([]);
  const [loading, setLoading] = useState(false);
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);

  // 筛选
  const [keyword, setKeyword] = useState('');
  const [freq, setFreq] = useState<string | undefined>();
  const [rating, setRating] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [theaterFilter, setTheaterFilter] = useState<string | undefined>();
  const [theaters, setTheaters] = useState<Theater[]>([]);

  // 上线时间日期筛选（默认 当日+明日：展示今天与明天上线待发的剧目）
  // 预设：all / today / tomorrow / today_tomorrow / custom
  const [onlineFilter, setOnlineFilter] = useState<string>('today_tomorrow');
  const [onlineRange, setOnlineRange] = useState<[string, string] | null>(null);
  const onlineParamsRef = useRef<Record<string, string>>({});

  // 新增/编辑弹窗
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Drama | null>(null);
  const [form] = Form.useForm();
  // 话题大方向预设（ISSUE #93 视频号中老年短剧话题）
  const [topicPresets, setTopicPresets] = useState<TopicPreset[]>([]);

  // 详情抽屉
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DramaDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // 切片产线状态（剧集维度打通切片产线）
  const [sliceStatus, setSliceStatus] = useState<DramaSliceStatus | null>(null);
  const [sliceLoading, setSliceLoading] = useState(false);
  const [episodeInput, setEpisodeInput] = useState('');

  // 导入弹窗
  const [importOpen, setImportOpen] = useState(false);
  const [importStep, setImportStep] = useState(0);
  const [parsedRows, setParsedRows] = useState<DramaImportRow[]>([]);
  const [fileName, setFileName] = useState('');
  const [preview, setPreview] = useState<{
    new: Array<{ name: string; fields: Record<string, unknown> }>;
    update: Array<{ id: string; code: string; name: string; diff: Record<string, { old: unknown; new: unknown }> }>;
    unchanged: Array<{ id: string; code: string; name: string }>;
    summary: { new_count: number; update_count: number; unchanged_count: number };
  } | null>(null);
  const [checkNew, setCheckNew] = useState<Set<number>>(new Set());
  const [checkUpdate, setCheckUpdate] = useState<Set<number>>(new Set());
  const [importing, setImporting] = useState(false);

  // 局域网获取剧集（lan_source）面板
  const [lanEnabled, setLanEnabled] = useState(false);
  const [lanDramas, setLanDramas] = useState<{ name: string; total: number | null }[]>([]);
  const [lanPreview, setLanPreview] = useState<LanSourceEpisodeItem[] | null>(null);
  const [lanPreviewLoading, setLanPreviewLoading] = useState(false);
  // 局域网面板内的轻提示（打开详情自动 preview / 加载清单 失败时不弹全局 error，只在面板内提示）
  const [lanNotice, setLanNotice] = useState<string | null>(null);
  const [lanImporting, setLanImporting] = useState(false);
  const [lanTask, setLanTask] = useState<{
    id: string; drama_name: string; status: string; progress: number; message: string | null;
    imported_count: number; failed_count: number; total_episodes: number | null;
  } | null>(null);
  const [lanSelectName, setLanSelectName] = useState('');
  const [lanManualName, setLanManualName] = useState('');

  // ── 推送到下载平台（dupload） ──
  const [duploadEnabled, setDuploadEnabled] = useState(false);
  const [duploadPushing, setDuploadPushing] = useState(false);

  const fetchList = useCallback(async (kw?: string, f?: string, r?: string, s?: string, t?: string) => {
    setLoading(true);
    try {
      const list = await listDramas({
        q: kw, frequency: f, rating: r, listing_status: s, theater_id: t,
        ...onlineParamsRef.current,
      });
      setData(list);
    } catch (e) {
      message.error((e as Error).message || '加载剧目库失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // 上线时间筛选参数：随预设/区间变化重算并重新拉取（默认 当日+明日）
  useEffect(() => {
    const today = dayjs().format('YYYY-MM-DD');
    const tomorrow = dayjs().add(1, 'day').format('YYYY-MM-DD');
    let p: Record<string, string> = {};
    if (onlineFilter === 'today') p = { online_date: today };
    else if (onlineFilter === 'tomorrow') p = { online_date: tomorrow };
    else if (onlineFilter === 'today_tomorrow') p = { online_from: today, online_to: tomorrow };
    else if (onlineFilter === 'custom' && onlineRange) p = { online_from: onlineRange[0], online_to: onlineRange[1] };
    onlineParamsRef.current = p;
    fetchList(keyword, freq, rating, status, theaterFilter);
  }, [onlineFilter, onlineRange, fetchList, keyword, freq, rating, status, theaterFilter]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // 加载剧场列表（供筛选 + 编辑表单）
  useEffect(() => {
    theaterApi.list().then(setTheaters).catch(() => setTheaters([]));
  }, []);

  // 加载视频号账号库（用于关联）
  useEffect(() => {
    publishApi.getVideoAccounts().then(setVideoAccounts).catch(() => setVideoAccounts([]));
  }, []);

  // 加载话题大方向预设（ISSUE #93 视频号中老年短剧话题）
  useEffect(() => {
    getTopicPresets().then((r) => setTopicPresets(r.presets || [])).catch(() => setTopicPresets([]));
  }, []);

  const doSearch = () => fetchList(keyword, freq, rating, status, theaterFilter);

  // ── 新增/编辑 ──
  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ listing_status: '已上架' });
    setModalOpen(true);
  };

  const openEdit = (d: Drama) => {
    setEditing(d);
    form.setFieldsValue({
      name: d.name,
      frequency: d.frequency || undefined,
      type: d.type || undefined,
      tags: d.tags || [],
      rating: d.rating || undefined,
      synopsis: d.synopsis || undefined,
      listing_status: d.listing_status,
      material_link: d.material_link || undefined,
      topics: d.topics || [],
      theater_ids: d.theater_ids || (d.theater_id ? [d.theater_id] : []),
      updated_date: d.updated_date ? dayjs(d.updated_date) : undefined,
      listed_at: d.listed_at ? dayjs(d.listed_at) : undefined,
    });
    setModalOpen(true);
  };

  // 选择话题大方向 → 自动带入对应成套话题标签到表单 topics（可再手动微调）
  const onTopicPresetChange = (presetKey?: string) => {
    const preset = topicPresets.find((p) => p.key === presetKey);
    if (preset) {
      form.setFieldsValue({ topics: [...preset.topics] });
    }
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload: DramaCreateParams = {
      name: values.name as string,
      frequency: values.frequency || null,
      type: values.type || null,
      tags: values.tags || null,
      rating: values.rating || null,
      synopsis: values.synopsis || null,
      listing_status: values.listing_status,
      material_link: values.material_link || null,
      topics: values.topics || null,
      theater_ids: values.theater_ids || [],
      updated_date: values.updated_date ? values.updated_date.format('YYYY-MM-DD') : null,
      listed_at: values.listed_at ? values.listed_at.format('YYYY-MM-DD HH:mm:ss') : null,
    };
    try {
      if (editing) {
        await updateDrama(editing.id, payload);
        message.success('剧目已更新');
      } else {
        await createDrama(payload);
        message.success('剧目已创建');
      }
      setModalOpen(false);
      fetchList(keyword, freq, rating, status, theaterFilter);
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    }
  };

  const remove = async (id: string, name: string) => {
    try {
      await deleteDrama(id);
      message.success(`已删除 ${name}`);
      fetchList(keyword, freq, rating, status, theaterFilter);
    } catch (e) {
      message.error((e as Error).message || '删除失败');
    }
  };

  // ── 飞书自动爬取（ISSUE #142）──
  const [feishuOpen, setFeishuOpen] = useState(false);
  const [feishuUrl, setFeishuUrl] = useState('');
  const [feishuLoading, setFeishuLoading] = useState(false);

  const runFeishuSync = async () => {
    setFeishuLoading(true);
    try {
      const res = await feishuImportDrama(feishuUrl.trim() || undefined);
      if (res && res.success) {
        message.success(res.message || '飞书同步完成');
      } else {
        message.warning(res?.error || res?.message || '飞书同步未完成');
      }
      setFeishuOpen(false);
      fetchList(keyword, freq, rating, status, theaterFilter);
    } catch (e) {
      message.error((e as Error).message || '飞书同步失败');
    } finally {
      setFeishuLoading(false);
    }
  };

  // ── 详情 ──
  const openDetail = async (d: Drama) => {
    setDetailId(d.id);
    setDetailOpen(true);
    setDetailLoading(true);
    setSliceStatus(null);
    loadLanConfig();
    loadDuploadConfig();
    try {
      const res = await getDrama(d.id);
      setDetail(res);
      // 打开剧目详情自动用当前剧目名拉取局域网预览（保留下方手动输入兜底）
      // silent=true：自动 preview 失败时不弹全局 error，只在局域网面板内轻提示
      if (res?.name) previewLanDrama(res.name, true);
    } catch (e) {
      message.error((e as Error).message || '加载详情失败');
    } finally {
      setDetailLoading(false);
    }
    loadSliceStatus(d.id);
  };

  // 剧集维度打通切片产线：加载剧目切片产线状态
  const loadSliceStatus = async (dramaId: string) => {
    setSliceLoading(true);
    try {
      const res = await getDramaSliceStatus(dramaId);
      setSliceStatus(res);
    } catch (e) {
      message.error((e as Error).message || '加载切片产线状态失败');
    } finally {
      setSliceLoading(false);
    }
  };

  // ── 局域网获取剧集（lan_source）面板 ──
  const loadLanConfig = async () => {
    try {
      const cfg = await lanSourceApi.getConfig();
      setLanEnabled(cfg.enabled);
    } catch {
      setLanEnabled(false);
    }
  };

  // ── 推送到下载平台（dupload） ──
  const loadDuploadConfig = async () => {
    try {
      const cfg = await lanSourceApi.getDuploadConfig();
      setDuploadEnabled(cfg.enabled);
    } catch {
      setDuploadEnabled(false);
    }
  };

  // 推送当前剧目到下载平台（仅下载）
  const submitDuploadPush = async () => {
    if (!detailId) return;
    setDuploadPushing(true);
    try {
      const res = await lanSourceApi.duploadTrigger({ drama_id: detailId });
      message.success(`已推送《${res.drama_name}》到下载平台（仅下载）`);
    } catch (e) {
      message.error((e as Error).message || '推送失败');
    } finally {
      setDuploadPushing(false);
    }
  };

  // 加载局域网可导入的剧目清单
  const loadLanDramas = async () => {
    setLanPreview(null);
    setLanNotice(null);
    try {
      const res = await lanSourceApi.getDramas();
      setLanDramas(res.items.map((d) => ({ name: d.name, total: d.total })));
      if (!res.items.length) {
        setLanNotice('局域网源暂未返回剧目清单，可手动输入剧目名预览重试');
      }
    } catch (e) {
      // 清单拉取失败只在面板内轻提示，不弹全局 error 打断
      setLanNotice((e as Error).message || '获取局域网剧目清单失败');
      setLanDramas([]);
    }
  };

  // 预览某剧目直链（发现但不入库）
  // silent=true 时失败不弹全局 error（打开详情自动预览场景），只在局域网面板内轻提示
  const previewLanDrama = async (name: string, silent?: boolean) => {
    const trimmed = (name || '').trim();
    if (!trimmed) return;
    setLanPreviewLoading(true);
    setLanPreview(null);
    setLanNotice(null);
    try {
      const res = await lanSourceApi.preview(trimmed);
      setLanPreview(res.items);
      if (!res.items.length) setLanNotice(`《${trimmed}》未返回剧集直链，请确认局域网源地址或剧目名`);
    } catch (e) {
      const err = e as Error & { status?: number };
      // 剧不存在（404）：语义明确，一律走面板内轻提示（自动/手动预览都不弹全局 error）
      if (err.status === 404) {
        setLanNotice(err.message || `《${trimmed}》在局域网源暂无剧集`);
      } else if (silent) {
        // 自动 preview 静默：失败不弹全局 error，只在面板内轻提示
        setLanNotice(err.message || `预览《${trimmed}》剧集失败`);
      } else {
        message.error(err.message || `预览《${trimmed}》剧集失败`);
      }
    } finally {
      setLanPreviewLoading(false);
    }
  };

  // 提交导入任务
  const submitLanImport = async (name: string) => {
    const trimmed = (name || '').trim();
    if (!trimmed) return;
    setLanImporting(true);
    try {
      const res = await lanSourceApi.import({ drama_name: trimmed });
      message.success(`已创建《${trimmed}》导入任务，开始从局域网拉流`);
      setLanTask({
        id: res.task_id, drama_name: res.drama_name, status: res.status, progress: 0,
        message: res.message, imported_count: 0, failed_count: 0, total_episodes: null,
      });
      pollLanTask(res.task_id);
    } catch (e) {
      message.error((e as Error).message || '创建导入任务失败');
    } finally {
      setLanImporting(false);
    }
  };

  // 轮询导入任务进度
  const pollLanTask = async (taskId: string) => {
    let finished = false;
    for (let i = 0; i < 600 && !finished; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const t = await lanSourceApi.getTask(taskId);
        setLanTask({
          id: t.id, drama_name: t.drama_name, status: t.status, progress: t.progress,
          message: t.message, imported_count: t.imported_count, failed_count: t.failed_count,
          total_episodes: t.total_episodes,
        });
        if (t.status === 'completed' || t.status === 'failed') {
          finished = true;
          if (detailId) {
            // 导入完成后刷新剧目剧集与切片产线状态
            try { setDetail(await getDrama(detailId)); } catch { /* ignore */ }
            loadSliceStatus(detailId);
            loadLanDramas();
          }
        }
      } catch {
        // 单次查询失败继续轮询
      }
    }
  };

  // 已导入剧集一键投入切片（默认第一集 fast）
  const lanToSlice = async (taskId: string) => {
    try {
      const res = await lanSourceApi.toSlice(taskId, { mode: 'fast' });
      message.success('已创建切片任务并投入切片队列');
      if (detailId) loadSliceStatus(detailId);
    } catch (e) {
      message.error((e as Error).message || '一键入切片失败');
    }
  };

  // 剧集维度打通切片产线：关联剧集（逗号/换行分隔的 episode id）
  const saveLinkedEpisodes = async () => {
    if (!detailId) return;
    const ids = episodeInput.split(/[,，\n\s]+/).map((s) => s.trim()).filter(Boolean);
    try {
      await linkDramaEpisodes(detailId, ids);
      message.success(`已关联 ${ids.length} 个剧集`);
      setEpisodeInput('');
      const res = await getDrama(detailId);
      setDetail(res);
      loadSliceStatus(detailId);
    } catch (e) {
      message.error((e as Error).message || '关联剧集失败');
    }
  };

  const setCover = async (fileKey: string) => {
    if (!detailId) return;
    try {
      await updateDrama(detailId, { cover_file_key: fileKey });
      message.success('封面已更新');
      const res = await getDrama(detailId);
      setDetail(res);
      fetchList(keyword, freq, rating, status, theaterFilter);
    } catch (e) {
      message.error((e as Error).message || '更新封面失败');
    }
  };

  const addStill = async (fileKey: string) => {
    if (!detailId) return;
    try {
      await addDramaStill(detailId, fileKey, (detail?.stills.length || 0));
      message.success('剧照已添加');
      const res = await getDrama(detailId);
      setDetail(res);
    } catch (e) {
      message.error((e as Error).message || '添加剧照失败');
    }
  };

  const removeStill = async (stillId: string) => {
    try {
      await deleteDramaStill(stillId);
      message.success('剧照已删除');
      if (detailId) {
        const res = await getDrama(detailId);
        setDetail(res);
      }
    } catch (e) {
      message.error((e as Error).message || '删除剧照失败');
    }
  };

  const linkAccounts = async (accountIds: string[]) => {
    if (!detailId) return;
    try {
      await linkDramaAccounts(detailId, accountIds);
      message.success('账号关联已更新');
      const res = await getDrama(detailId);
      setDetail(res);
    } catch (e) {
      message.error((e as Error).message || '关联失败');
    }
  };

  // ── 导入 ──
  const resetImport = () => {
    setImportStep(0);
    setParsedRows([]);
    setFileName('');
    setPreview(null);
    setCheckNew(new Set());
    setCheckUpdate(new Set());
  };

  const onImportFile = async (file: File) => {
    try {
      const res = await dramaImportParse(file);
      setParsedRows(res.rows);
      setFileName(res.file_name);
      message.success(res.message);
      setImportStep(1);
      // 自动预览
      const pv = await dramaImportPreview(res.rows, res.file_name);
      setPreview(pv);
      setCheckNew(new Set(pv.new.map((_, i) => i)));
      setCheckUpdate(new Set(pv.update.map((_, i) => i)));
      setImportStep(2);
    } catch (e) {
      message.error((e as Error).message || '解析失败');
    }
    return false;
  };

  const toggleNew = (i: number) => {
    const s = new Set(checkNew);
    if (s.has(i)) s.delete(i); else s.add(i);
    setCheckNew(s);
  };
  const toggleUpdate = (i: number) => {
    const s = new Set(checkUpdate);
    if (s.has(i)) s.delete(i); else s.add(i);
    setCheckUpdate(s);
  };

  const doImport = async () => {
    setImporting(true);
    try {
      const acceptNew = [...checkNew].sort((a, b) => a - b)
        .filter((i) => Boolean(preview?.new[i]))
        .map((i) => ({
          name: (preview!.new[i] as { name: string }).name,
          frequency: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.frequency as string) || null,
          type: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.type as string) || null,
          tags: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.tags as string[]) || null,
          rating: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.rating as string) || null,
          listing_status: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.listing_status as string) || '已上架',
          updated_date: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.updated_date as string) || null,
          listed_at: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.listed_at as string) || null,
          material_link: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.material_link as string) || null,
          account_name: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.account_name as string) || null,
          theater_name: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.theater_name as string) || null,
        }));
      const acceptUpdate = [...checkUpdate].sort((a, b) => a - b).map((i) => {
        const u = preview!.update[i] as { id: string; code: string; name: string; diff: Record<string, { old: unknown; new: unknown }> };
        return {
          id: u.id,
          name: u.name,
          frequency: (u.diff.frequency?.new as string) || null,
          type: (u.diff.type?.new as string) || null,
          tags: (u.diff.tags?.new as string[]) || null,
          rating: (u.diff.rating?.new as string) || null,
          listing_status: (u.diff.listing_status?.new as string) || '已上架',
          updated_date: (u.diff.updated_date?.new as string) || null,
          listed_at: (u.diff.listed_at?.new as string) || null,
          material_link: (u.diff.material_link?.new as string) || null,
          theater_name: Array.isArray(u.diff.theater_name?.new)
            ? (u.diff.theater_name!.new as string[]).join(',')
            : (u.diff.theater_name?.new as string) || null,
        };
      });
      const res = await dramaImportConfirm(acceptNew, acceptUpdate, fileName);
      message.success(`导入完成：新增 ${res.imported}，更新 ${res.updated}，跳过 ${res.skipped}`);
      setImportOpen(false);
      resetImport();
      fetchList(keyword, freq, rating, status, theaterFilter);
    } catch (e) {
      message.error((e as Error).message || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  // ── 表格列 ──
  const columns: ColumnsType<Drama> = [
    {
      title: '封面',
      dataIndex: 'cover_file_key',
      width: 70,
      render: (_, r) =>
        r.cover_url ? (
          <AntImage src={r.cover_url} width={44} height={44} style={{ objectFit: 'cover', borderRadius: 4 }} />
        ) : (
          <div style={{ width: 44, height: 44, borderRadius: 4, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FileImageOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />
          </div>
        ),
    },
    {
      title: '剧目ID',
      dataIndex: 'code',
      width: 120,
      render: (v) => <Text code>{v}</Text>,
    },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '频', dataIndex: 'frequency', width: 70, render: (v) => v || '-' },
    {
      title: '题材',
      dataIndex: 'tags',
      width: 200,
      render: (v: string[] | null) =>
        v && v.length ? v.slice(0, 4).map((t) => <Tag key={t} color="blue">{t}</Tag>) : '-',
    },
    { title: '评级', dataIndex: 'rating', width: 90, render: (v) => (v ? <Tag color="gold">{v}</Tag> : '-') },
    {
      title: '上线时间',
      dataIndex: 'listed_at',
      width: 140,
      render: (v: string | null) => (v ? dayjs(v).format('MM-DD HH:mm') : '-'),
    },
    {
      title: '状态',
      dataIndex: 'listing_status',
      width: 90,
      render: (v) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '剧场',
      dataIndex: 'theater_names',
      width: 160,
      render: (v: string[] | null) => {
        const names = (v || []).filter(Boolean);
        return names.length
          ? names.map((n) => <Tag key={n} color="purple">{n}</Tag>)
          : '-';
      },
    },
    {
      title: '操作',
      width: 180,
      render: (_, r) => (
        <Space>
          <Button size="small" type="link" onClick={() => openDetail(r)}>详情</Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title={`删除「${r.name}」？`} onConfirm={() => remove(r.id, r.name)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const accountNameById = (id: string) => videoAccounts.find((a) => a.id === id)?.account_name || id;

  return (
    <div>
      <Card
        title="剧目库"
        extra={
          <Space>
            <Input
              placeholder="搜索名称/ID"
              prefix={<SearchOutlined />}
              style={{ width: 200 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={doSearch}
            />
            <Select
              placeholder="男/女频"
              allowClear
              style={{ width: 110 }}
              value={freq}
              onChange={(v) => { setFreq(v); fetchList(keyword, v, rating, status, theaterFilter); }}
              options={FREQUENCIES.map((f) => ({ value: f, label: f }))}
            />
            <Select
              placeholder="评级"
              allowClear
              style={{ width: 120 }}
              value={rating}
              onChange={(v) => { setRating(v); fetchList(keyword, freq, v, status, theaterFilter); }}
              options={RATINGS.map((f) => ({ value: f, label: f }))}
            />
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 110 }}
              value={status}
              onChange={(v) => { setStatus(v); fetchList(keyword, freq, rating, v, theaterFilter); }}
              options={LISTING_STATUSES.map((f) => ({ value: f, label: f }))}
            />
            <Select
              placeholder="按剧场筛选"
              allowClear
              showSearch
              optionFilterProp="label"
              style={{ width: 150 }}
              value={theaterFilter}
              onChange={(v) => { setTheaterFilter(v); fetchList(keyword, freq, rating, status, v); }}
              options={theaters.map((t) => ({ value: t.id, label: t.name }))}
            />
            <Select
              placeholder="上线时间"
              style={{ width: 140 }}
              value={onlineFilter}
              onChange={(v) => setOnlineFilter(v)}
              options={[
                { value: 'all', label: '全部上线时间' },
                { value: 'today', label: '当日' },
                { value: 'tomorrow', label: '明日' },
                { value: 'today_tomorrow', label: '当日+明日' },
                { value: 'custom', label: '自定义区间' },
              ]}
            />
            {onlineFilter === 'custom' && (
              <DatePicker.RangePicker
                style={{ width: 260 }}
                value={onlineRange ? [dayjs(onlineRange[0]), dayjs(onlineRange[1])] : null}
                onChange={(dates) => {
                  if (dates && dates[0] && dates[1]) {
                    setOnlineRange([dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')]);
                  } else {
                    setOnlineRange(null);
                  }
                }}
              />
            )}
            <Button icon={<SearchOutlined />} onClick={doSearch}>查询</Button>
            <Button icon={<ImportOutlined />} onClick={() => { resetImport(); setImportOpen(true); }}>导入剧目</Button>
            <Button icon={<CloudSyncOutlined />} onClick={() => setFeishuOpen(true)}>飞书同步</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增剧目</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>

      {/* 新增/编辑弹窗 */}
      <Modal
        title={editing ? `编辑剧目：${editing.name}` : '新增剧目'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        width={640}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="漫剧名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="剧目名称（去重键）" />
          </Form.Item>
          <Space size="large" style={{ display: 'flex' }}>
            <Form.Item name="frequency" label="男/女频">
              <Select allowClear placeholder="男频/女频" style={{ width: 140 }} options={FREQUENCIES.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item name="type" label="漫剧类型">
              <Select allowClear placeholder="AI真人剧等" style={{ width: 160 }} options={DRAMA_TYPES.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item name="rating" label="评级">
              <Select allowClear placeholder="评级" style={{ width: 120 }} options={RATINGS.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
          </Space>
          <Form.Item name="tags" label="题材标签">
            <Select mode="tags" placeholder="输入题材，回车添加" tokenSeparators={[',', '/']} />
          </Form.Item>
          <Form.Item label="话题大方向" extra="选择后自动带入对应成套话题标签，可再手动增删；发布时直接复用。">
            <Select
              placeholder="选择话题大方向（视频号中老年短剧）"
              allowClear
              showSearch
              optionFilterProp="label"
              onChange={onTopicPresetChange}
              options={(topicPresets || []).map((p) => ({ value: p.key, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="topics" label="话题标签">
            <Select mode="tags" placeholder="回车添加话题标签（如 #短剧）" tokenSeparators={[',', '/', ' ']} />
          </Form.Item>
          <Form.Item name="synopsis" label="剧情简介">
            <Input.TextArea rows={3} placeholder="用于发布时生成短标题/配文/话题" />
          </Form.Item>
          <Space size="large" style={{ display: 'flex' }}>
            <Form.Item name="listing_status" label="上架状态" initialValue="已上架">
              <Select style={{ width: 130 }} options={LISTING_STATUSES.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item name="updated_date" label="更新日期">
              <Input type="date" style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="listed_at" label="上线时间">
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: 200 }} placeholder="选择上线日期时间" />
            </Form.Item>
          </Space>
          <Form.Item name="theater_ids" label="所属剧场（一剧多剧场，可多选）">
            <Select
              mode="multiple"
              placeholder="选择所属剧场（可多选）"
              allowClear
              showSearch
              optionFilterProp="label"
              options={theaters.map((t) => ({ value: t.id, label: t.name }))}
            />
          </Form.Item>
          <Form.Item name="material_link" label="素材链接">
            <Input placeholder="百度网盘等素材链接（提取码请勿填入）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情抽屉 */}
      <Drawer
        title={detail ? `${detail.name}（${detail.code}）` : '剧目详情'}
        width={620}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      >
        {detailLoading || !detail ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
              <Descriptions.Item label="剧目ID"><Text code>{detail.code}</Text></Descriptions.Item>
              <Descriptions.Item label="男/女频">{detail.frequency || '-'}</Descriptions.Item>
              <Descriptions.Item label="类型">{detail.type || '-'}</Descriptions.Item>
              <Descriptions.Item label="评级">{detail.rating || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">{detail.listing_status}</Descriptions.Item>
              <Descriptions.Item label="上线时间">{detail.listed_at ? dayjs(detail.listed_at).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
            </Descriptions>
            {detail.synopsis && (
              <Alert type="info" showIcon message="剧情简介" description={detail.synopsis} />
            )}

            <Divider orientation="left">发布话题（发布时复用）</Divider>
            {detail.topics && detail.topics.length > 0 ? (
              <Space wrap>
                {detail.topics.map((t) => <Tag key={t} color="volcano">{t}</Tag>)}
              </Space>
            ) : (
              <Text type="secondary">尚未设置发布话题，可在编辑剧目中选择「话题大方向」自动带入。</Text>
            )}

            <Divider orientation="left">封面</Divider>
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              {detail.cover_url ? (
                <AntImage src={detail.cover_url} width={120} height={160} style={{ objectFit: 'cover', borderRadius: 6 }} />
              ) : (
                <div style={{ width: 120, height: 160, borderRadius: 6, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FileImageOutlined style={{ color: '#bfbfbf', fontSize: 28 }} />
                </div>
              )}
              <div style={{ flex: 1 }}>
                <DraggableUpload text="上传/更换封面" onFile={(key) => setCover(key)} />
              </div>
            </div>

            <Divider orientation="left">剧照</Divider>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
              {detail.stills.map((s) => (
                <div key={s.id} style={{ position: 'relative' }}>
                  {s.presigned_url ? (
                    <AntImage src={s.presigned_url} width={96} height={96} style={{ objectFit: 'cover', borderRadius: 6 }} />
                  ) : (
                    <div style={{ width: 96, height: 96, borderRadius: 6, background: '#f5f5f5' }} />
                  )}
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    style={{ position: 'absolute', top: -8, right: -8 }}
                    onClick={() => removeStill(s.id)}
                  />
                </div>
              ))}
            </div>
            <DraggableUpload text="添加剧照（可多张）" onFile={(key) => addStill(key)} />

            <Divider orientation="left">关联视频号</Divider>
            <Select
              mode="multiple"
              style={{ width: '100%' }}
              placeholder="选择该剧目在哪些视频号上架"
              value={detail.account_ids || []}
              onChange={linkAccounts}
              optionFilterProp="label"
              options={videoAccounts.map((a) => ({ value: a.id, label: a.account_name }))}
            />
            {detail.material_link && (
              <Alert type="info" showIcon message="素材链接" description={detail.material_link} />
            )}

            {/* 剧集已获取（lanPreview 有剧集直链数组且 length>0）时隐藏推送区块 */}
            {(!lanPreview || lanPreview.length === 0) && (
              <>
                <Divider orientation="left">推送到下载平台</Divider>
                {!duploadEnabled ? (
                  <Alert type="warning" showIcon message="推送到下载平台功能未开启" description="请在系统设置中开启「推送到下载平台」（配置 dupload_config.enabled=true 及 base_url 指向 dupload 服务），保存后即可在此把剧目素材链接推给下载平台，无需重启。" />
                ) : (
                  <Space direction="vertical" style={{ width: '100%' }} size="small">
                    {!detail.material_link ? (
                      <Alert type="warning" showIcon message="当前剧目未填写素材链接" description="请先在剧目编辑中填写「素材链接」（百度网盘等 shareUrl），再一键推送到下载平台。" />
                    ) : (
                      <Space wrap>
                        <Button
                          type="primary"
                          icon={<ExportOutlined />}
                          loading={duploadPushing}
                          onClick={submitDuploadPush}
                        >推送到下载平台（仅下载）</Button>
                      </Space>
                    )}
                  </Space>
                )}
              </>
            )}

            <Divider orientation="left">局域网获取剧集</Divider>
            {!lanEnabled ? (
              <Alert type="warning" showIcon message="局域网获取剧集功能未开启" description="请在系统设置中开启「局域网获取剧集」（配置 lan_source_config.enabled=true 及 base_url 指向局域网 cdn 源），保存后即可在此导入局域网剧集，无需重启。" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                <Space wrap>
                  <Button size="small" icon={<ReloadOutlined />} onClick={loadLanDramas}>加载局域网剧目</Button>
                </Space>
                <Space.Compact style={{ width: '100%' }}>
                  <Select
                    style={{ width: '45%' }}
                    placeholder="选择局域网剧目"
                    value={lanSelectName}
                    onChange={setLanSelectName}
                    showSearch
                    optionFilterProp="label"
                    options={lanDramas.map((d) => ({ value: d.name, label: `${d.name}${d.total ? `（${d.total}集）` : ''}` }))}
                    onDropdownVisibleChange={(open) => { if (open && !lanDramas.length) loadLanDramas(); }}
                  />
                  <Input
                    style={{ flex: 1 }}
                    placeholder="或手动输入剧目名（用于预览直链）"
                    value={lanManualName}
                    onChange={(e) => setLanManualName(e.target.value)}
                  />
                  <Button
                    type="primary"
                    loading={lanPreviewLoading}
                    onClick={() => previewLanDrama(lanSelectName || lanManualName)}
                  >预览</Button>
                  <Button
                    type="primary"
                    danger
                    loading={lanImporting}
                    onClick={() => submitLanImport(lanSelectName || lanManualName)}
                  >导入到切片</Button>
                </Space.Compact>
                {lanNotice && (
                  <Alert
                    type="warning"
                    showIcon
                    message={lanNotice}
                    closable
                    onClose={() => setLanNotice(null)}
                  />
                )}
                {lanPreview && (
                  <Alert
                    type="info"
                    showIcon
                    message={`《${lanSelectName || lanManualName}》发现 ${lanPreview.length} 集直链`}
                    description={
                      <Table
                        rowKey={(r, i) => String(r.episode ?? i)}
                        size="small"
                        pagination={{ pageSize: 5, showSizeChanger: false }}
                        dataSource={lanPreview}
                        columns={[
                          { title: '集', dataIndex: 'episode', width: 56, render: (v) => v ?? '-' },
                          { title: '标题', dataIndex: 'title', ellipsis: true, render: (v) => v || '-' },
                          { title: '大小', dataIndex: 'size', width: 90, render: (v) => (v ? `${Math.round(v / 1024 / 1024)}MB` : '-') },
                        ]}
                      />
                    }
                  />
                )}
                {lanTask && (
                  <Card size="small" style={{ background: '#fafafa' }}>
                    <Space direction="vertical" style={{ width: '100%' }} size="small">
                      <Space wrap>
                        <Text strong>《{lanTask.drama_name}》</Text>
                        <Tag color={lanTask.status === 'completed' ? 'green' : lanTask.status === 'failed' ? 'red' : 'blue'}>{lanTask.status}</Tag>
                        <Tag>成功 {lanTask.imported_count}</Tag>
                        <Tag>失败 {lanTask.failed_count}</Tag>
                        {lanTask.status === 'completed' && (
                          <Button size="small" type="primary" onClick={() => lanToSlice(lanTask.id)}>一键投入切片</Button>
                        )}
                      </Space>
                      <Progress percent={Math.round(lanTask.progress)} size="small" />
                      <Text type="secondary">{lanTask.message}</Text>
                    </Space>
                  </Card>
                )}
              </Space>
            )}

            <Divider orientation="left">切片产线（剧集维度）</Divider>
            {sliceLoading && !sliceStatus ? (
              <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                {sliceStatus && sliceStatus.total_episodes > 0 ? (
                  <Space wrap>
                    <Tag color="blue">关联剧集 {sliceStatus.total_episodes} 集</Tag>
                    <Tag color="green">已切片 {sliceStatus.sliced_count}</Tag>
                    <Tag color="orange">待切片 {sliceStatus.pending_count}</Tag>
                    <Tag>整体进度 {sliceStatus.progress_percent}%</Tag>
                  </Space>
                ) : (
                  <Alert type="warning" showIcon message="尚未关联任何剧集" description="在下方输入剧集 id 关联后，即可在剧目维度查看每集选点/检测/切片的产线状态（该剧已切片/待切片）。" />
                )}

                {sliceStatus && sliceStatus.episodes.length > 0 && (
                  <Table
                    rowKey="episode_id"
                    size="small"
                    pagination={{ pageSize: 5, showSizeChanger: false }}
                    dataSource={sliceStatus.episodes}
                    columns={[
                      {
                        title: '集', dataIndex: 'episode_no', width: 48,
                        render: (v, r) => v ?? r.title ?? '-',
                      },
                      { title: '标题', dataIndex: 'title', ellipsis: true, render: (v) => v || '-' },
                      {
                        title: '选点', dataIndex: ['stages', 'autoclip', 'status'], width: 76,
                        render: (v: string) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag>,
                      },
                      {
                        title: '检测', dataIndex: ['stages', 'detect', 'status'], width: 76,
                        render: (v: string) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag>,
                      },
                      {
                        title: '切片', dataIndex: ['stages', 'slice', 'status'], width: 76,
                        render: (v: string) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag>,
                      },
                      {
                        title: '产出', dataIndex: ['stages', 'slice', 'output_count'], width: 56,
                        render: (v) => v ?? '-',
                      },
                      {
                        title: '切片状态', width: 100,
                        render: (_, r) => r.sliced
                          ? <Tag color="green">已切片</Tag>
                          : <Tag color="orange">待切片</Tag>,
                      },
                    ]}
                  />
                )}

                <Divider orientation="left" style={{ margin: '8px 0' }}>关联剧集</Divider>
                <Space.Compact style={{ width: '100%' }}>
                  <Input.TextArea
                    placeholder="粘贴剧集 id（逗号/换行分隔）— 例如从切片产线剧集列表复制 id"
                    value={episodeInput}
                    onChange={(e) => setEpisodeInput(e.target.value)}
                    autoSize={{ minRows: 1, maxRows: 3 }}
                  />
                  <Button type="primary" onClick={saveLinkedEpisodes}>关联</Button>
                </Space.Compact>
                <Space>
                  <Button size="small" icon={<ReloadOutlined />} onClick={() => detailId && loadSliceStatus(detailId)}>刷新状态</Button>
                  {sliceStatus && sliceStatus.total_episodes > 0 && (
                    <Button size="small" danger onClick={async () => { if (!detailId) return; try { await linkDramaEpisodes(detailId, []); message.success('已清空关联'); setDetail(await getDrama(detailId)); loadSliceStatus(detailId); } catch (e) { message.error((e as Error).message || '清空失败'); } }}>清空关联</Button>
                  )}
                </Space>
              </Space>
            )}
          </Space>
        )}
      </Drawer>

      {/* 导入弹窗 */}
      <Modal
        title="导入剧目"
        open={importOpen}
        onCancel={() => { setImportOpen(false); resetImport(); }}
        footer={null}
        width={860}
      >
        <Steps
          current={importStep}
          items={[{ title: '上传' }, { title: '解析' }, { title: '确认' }]}
          style={{ marginBottom: 20 }}
        />
        {importStep === 0 && (
          <Upload.Dragger
            beforeUpload={onImportFile}
            showUploadList={false}
            accept=".xlsx,.xls,.csv"
          >
            <p className="ant-upload-drag-icon"><ImportOutlined /></p>
            <p className="ant-upload-text">点击或拖拽剧目 Excel 文件到此处</p>
            <p className="ant-upload-hint">列名对齐：漫剧名称 / 更新日期 / 男/女频 / 题材 / 漫剧类型 / 上架状态 / 上架日期 / 评级 / 素材链接 / 上架账号</p>
          </Upload.Dragger>
        )}
        {importStep === 1 && (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin tip="解析中…" /></div>
        )}
        {importStep === 2 && preview && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Alert
              type="info"
              showIcon
              message={`文件「${fileName}」解析到 ${preview.summary.new_count + preview.summary.update_count + preview.summary.unchanged_count} 条，同名称剧目会自动 diff 并询问`}
            />
            {preview.new.length > 0 && (
              <div>
                <Divider orientation="left">
                  <Space>
                    <Checkbox
                      checked={checkNew.size === preview.new.length}
                      onChange={(e) => setCheckNew(e.target.checked ? new Set(preview.new.map((_, i) => i)) : new Set())}
                    />
                    <Text strong>新增（{preview.new.length} 条）</Text>
                  </Space>
                </Divider>
                <Table
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  dataSource={preview.new.map((n, i) => ({ ...n, __i: i }))}
                  columns={[
                    {
                      title: '', width: 40,
                      render: (_, row) => (
                        <Checkbox checked={checkNew.has(row.__i)} onChange={() => toggleNew(row.__i)} />
                      ),
                    },
                    { title: '名称', dataIndex: 'name' },
                    { title: '频', dataIndex: ['fields', 'frequency'], render: (v) => v || '-' },
                    { title: '题材', dataIndex: ['fields', 'tags'], render: (v: string[]) => (v && v.length ? v.join(' / ') : '-') },
                    { title: '评级', dataIndex: ['fields', 'rating'], render: (v) => v || '-' },
                    { title: '上线时间', dataIndex: ['fields', 'listed_at'], render: (v) => v || '-' },
                    { title: '状态', dataIndex: ['fields', 'listing_status'], render: (v) => v || '已上架' },
                    { title: '剧场', dataIndex: ['fields', 'theater_name'], render: (v) => v || '-' },
                  ]}
                />
              </div>
            )}
            {preview.update.length > 0 && (
              <div>
                <Divider orientation="left">
                  <Space>
                    <Checkbox
                      checked={checkUpdate.size === preview.update.length}
                      onChange={(e) => setCheckUpdate(e.target.checked ? new Set(preview.update.map((_, i) => i)) : new Set())}
                    />
                    <Text strong>更新（{preview.update.length} 条）</Text>
                  </Space>
                </Divider>
                {preview.update.map((u, i) => (
                  <Card key={u.id} size="small" style={{ marginBottom: 8 }}>
                    <Space align="start" style={{ width: '100%' }}>
                      <Checkbox checked={checkUpdate.has(i)} onChange={() => toggleUpdate(i)} />
                      <div style={{ flex: 1 }}>
                        <Text strong>{u.name}</Text> <Text code>{u.code}</Text>
                        {Object.entries(u.diff).map(([field, d]) => (
                          <div key={field} style={{ marginTop: 4 }}>
                            <Text type="secondary">{field}: </Text>
                            <Text delete>{String(d.old ?? '-')}</Text>
                            <Text type="warning"> → </Text>
                            <Text>{String(d.new ?? '-')}</Text>
                          </div>
                        ))}
                      </div>
                    </Space>
                  </Card>
                ))}
              </div>
            )}
            {preview.unchanged.length > 0 && (
              <Alert type="success" showIcon message={`${preview.unchanged.length} 条无变化，默认跳过`} />
            )}
            <Divider />
            <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button onClick={() => { setImportStep(0); setParsedRows([]); setPreview(null); }}>重新选择</Button>
              <Button type="primary" loading={importing} onClick={doImport}>
                确认导入（新增 {checkNew.size} / 更新 {checkUpdate.size}）
              </Button>
            </Space>
          </Space>
        )}
      </Modal>

      {/* 飞书自动爬取弹窗（ISSUE #142） */}
      <Modal
        title="飞书表格自动同步"
        open={feishuOpen}
        onCancel={() => { setFeishuOpen(false); setFeishuUrl(''); }}
        onOk={runFeishuSync}
        okText="开始同步"
        confirmLoading={feishuLoading}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <Typography.Text type="secondary">
            从飞书表格拉取「剧目 ↔ 剧场」对应关系，自动更新现有剧目的剧场关联（一剧多剧场）。
            仅更新存量剧目，不自动新建。
          </Typography.Text>
          <Input
            placeholder="粘贴飞书表格链接（电子表格 / 知识库多维表格 / wiki 链接均可）"
            value={feishuUrl}
            onChange={(e) => setFeishuUrl(e.target.value)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            支持普通电子表格（/sheets/…）、多维表格（/base/…、/wiki/…）链接；
            需要后端配置 FEISHU_APP_ID / FEISHU_APP_SECRET 方可读取。
          </Typography.Text>
        </Space>
      </Modal>
    </div>
  );
};

export default DramaLibrary;
