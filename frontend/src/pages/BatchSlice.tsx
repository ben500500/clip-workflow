import React, { useState, useEffect, useCallback } from 'react';
import { WATERMARK_STYLE_OPTIONS } from '../utils/watermarkStyles';
import {
  Card, Form, Input, Button, InputNumber, Select, Switch, Space, Divider,
  Table, Tag, Progress, message, Alert, Typography, Modal, List, Spin, Tooltip, Slider,
  ColorPicker, Checkbox,
} from 'antd';
import {
  PlayCircleOutlined, UploadOutlined, ReloadOutlined, StopOutlined,
  DownloadOutlined, InboxOutlined, EyeOutlined, EditOutlined, PlusOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import Dragger from 'antd/es/upload/Dragger';
import { batchSliceApi, BatchSlice, BatchSliceItem, BatchSliceOutputItem } from '../api/batchSlice';
import { sliceApi, type TextOverlayItem } from '../api/slice';
import { formatDuration } from '../utils/format';
import { loadCustomPresets, type SlicePreset } from '../utils/slicePresets';
import { useDedupePresets } from '../hooks/useDedupePresets';

const { Text, Title } = Typography;

// 输出列表中展平后的单个成品项（含所属剧集/任务信息，供预览/裁剪使用）
interface FlattenOutput {
  seq: number;
  title: string | null;
  episode_id: string | null;
  slice_task_id: string | null;
  file: Record<string, unknown>;
}

// ── 一键切片配置（复用剧集详情页的常用配置项，整批统一生效）──
// AI 智能选点配置
interface AutoClipConfig {
  enabled: boolean;
  max_clips: number;
  min_score_threshold: number;
  min_duration: number;
  max_duration: number;
  frame_analysis: boolean;
}
// 通用区间检测配置
interface IntervalConfig {
  enabled: boolean;
  mode: 'credits' | 'static' | 'watermark';
}

interface SliceConfigState {
  autoclip: AutoClipConfig;
  interval: IntervalConfig;
  vert2horiz_enabled: boolean;
  vert2horiz_mode: 'fixed' | 'dynamic';
  vert2horiz_ratio: number;
  vert2horiz_output_size: string;
  vert2horiz_detect_interval: number;
  vert2horiz_smooth_window: number;
  vert2horiz_min_step: number;
  vert2horiz_face_margin: number;
  subtitle_enabled: boolean;
  subtitle_font_ratio: number;
  subtitle_spacing: number;
  subtitle_bold: number;
  subtitle_style: 'default' | 'custom';
  subtitle_color: string;
  subtitle_border_color: string;
  subtitle_align_mask: boolean;
  subtitle_mask_enabled: boolean;
  subtitle_mask_style: 'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill';
  subtitle_mask_temporal: boolean;
  subtitle_mask_spatial: boolean;
  subtitle_mask_preset: string;
  subtitle_mask_width_ratio: number;
  subtitle_mask_height_ratio: number;
  subtitle_mask_bottom_ratio: number;
  subtitle_mask_srt_offset: number;
  dedupe_preset: string;
  output_tier: string;
  text_overlay_enabled: boolean;
  text_overlays: { text: string; position: string; font_size: number; color: string; border_color?: string; vertical?: boolean }[];
  watermark_enabled: boolean;
  watermark_text: string;
  watermark_font_size: number;
  watermark_opacity: number;
  watermark_position: string;
  watermark_style: string;
}

const DEFAULT_SLICE_CONFIG: SliceConfigState = {
  autoclip: {
    enabled: true,
    max_clips: 30,
    min_score_threshold: 50,
    min_duration: 20,
    max_duration: 70,
    frame_analysis: true,
  },
  interval: {
    enabled: true,
    mode: 'credits',
  },
  vert2horiz_enabled: true,
  vert2horiz_mode: 'dynamic',
  vert2horiz_ratio: 0.5625,
  vert2horiz_output_size: '1280x720',
  vert2horiz_detect_interval: 2,
  vert2horiz_smooth_window: 15,
  vert2horiz_min_step: 5,
  vert2horiz_face_margin: 0.30,
  subtitle_enabled: true,
  subtitle_font_ratio: 0.30,
  subtitle_spacing: 0,
  subtitle_bold: 0,
  subtitle_style: 'custom',
  subtitle_color: '#EDD736',
  subtitle_border_color: '#000000',
  subtitle_align_mask: true,
  subtitle_mask_enabled: false,
  subtitle_mask_style: 'delogo',
  subtitle_mask_temporal: true,
  subtitle_mask_spatial: false,
  subtitle_mask_preset: 'auto',
  subtitle_mask_width_ratio: 0.9,
  subtitle_mask_height_ratio: 0.12,
  subtitle_mask_bottom_ratio: 0.02,
  subtitle_mask_srt_offset: 0,
  dedupe_preset: 'standard',
  output_tier: 'auto',
  text_overlay_enabled: true,
  text_overlays: [
    { text: '热门短剧', position: 'top-right', font_size: 40, color: '#EDD736', border_color: '#000000' },
    { text: '免费热门短剧', position: 'bottom-left', font_size: 36, color: '#FFFFFF', border_color: '#000000' },
    { text: '本故事纯属虚构', position: 'left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: true },
  ],
  watermark_enabled: false,
  watermark_text: '',
  watermark_font_size: 28,
  watermark_opacity: 0.5,
  watermark_position: 'bottom',
  watermark_style: 'scroll',
};

// 与剧集详情页「一键切片配置」共用的一套预设（C2 收敛到 utils/slicePresets.ts，读 slice_presets_v1）

const POSITIONS = ['top-left', 'top-center', 'top-right', 'left', 'bottom-left', 'bottom-center', 'bottom-right'];

// 阶段中文名
const PHASE_LABELS: Record<string, string> = {
  upload: '上传源视频',
  autoclip: 'AI 选点',
  review: '自动审核',
  interval: '区间检测',
  slice: '一键切片',
  source_delete: '删除源视频',
};

const STATUS_COLOR: Record<string, string> = {
  completed: 'green',
  failed: 'red',
  pending: 'default',
  uploading: 'blue',
  autoclip: 'blue',
  reviewing: 'blue',
  detecting: 'blue',
  slicing: 'processing',
  deleting: 'processing',
  cancelled: 'orange',
};

const STATUS_TEXT: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  pending: '待处理',
  uploading: '上传中',
  autoclip: '选点中',
  reviewing: '审核中',
  detecting: '检测中',
  slicing: '切片中',
  deleting: '删除中',
  cancelled: '已取消',
};

const BatchSlicePage: React.FC = () => {
  const navigate = useNavigate();
  const { presetOptions: dedupePresetOptions } = useDedupePresets();
  const [form] = Form.useForm();
  const [sliceConfig, setSliceConfig] = useState<SliceConfigState>({ ...DEFAULT_SLICE_CONFIG, text_overlays: DEFAULT_SLICE_CONFIG.text_overlays.map((t) => ({ ...t })) });
  // ── 一键切片配置预设（与剧集详情页共用，选中即套用到本页全部配置） ──
  const [presetOptions, setPresetOptions] = useState<SlicePreset[]>([]);
  const [slicePresetId, setSlicePresetId] = useState<string>('default');

  // 加载剧集详情页保存过的一键切片配置预设（C2 收敛：统一走 utils/slicePresets.ts）
  useEffect(() => {
    setPresetOptions(loadCustomPresets());
  }, []);

  // 应用选中的一键切片配置预设：把与详情页重叠的字段映射到本页 sliceConfig
  const applySlicePreset = (id: string) => {
    const p = presetOptions.find((x) => x.id === id);
    if (!p) return;
    setSlicePresetId(id);
    setSliceConfig((prev) => ({
      ...prev,
      vert2horiz_enabled: p.vert2horiz_enabled,
      vert2horiz_mode: p.vert2horiz_mode || 'dynamic',
      vert2horiz_ratio: p.vert2horiz_ratio,
      vert2horiz_output_size: p.vert2horiz_output_size,
      vert2horiz_detect_interval: p.vert2horiz_detect_interval,
      vert2horiz_smooth_window: p.vert2horiz_smooth_window,
      vert2horiz_min_step: p.vert2horiz_min_step,
      vert2horiz_face_margin: p.vert2horiz_face_margin,
      subtitle_enabled: p.subtitle_enabled,
      subtitle_font_ratio: p.subtitle_font_ratio,
      subtitle_spacing: p.subtitle_spacing,
      subtitle_bold: p.subtitle_bold,
      subtitle_style: p.subtitle_style,
      subtitle_color: p.subtitle_color,
      subtitle_border_color: p.subtitle_border_color,
      subtitle_align_mask: p.subtitle_align_mask,
      subtitle_mask_enabled: p.subtitle_mask_enabled,
      subtitle_mask_style: p.subtitle_mask_style,
      subtitle_mask_temporal: p.subtitle_mask_temporal,
      subtitle_mask_spatial: p.subtitle_mask_spatial,
      subtitle_mask_preset: p.subtitle_mask_preset || 'auto',
      subtitle_mask_width_ratio: p.subtitle_mask_width_ratio,
      subtitle_mask_height_ratio: p.subtitle_mask_height_ratio,
      subtitle_mask_bottom_ratio: p.subtitle_mask_bottom_ratio,
      subtitle_mask_srt_offset: p.subtitle_mask_srt_offset,
      dedupe_preset: p.dedupe_preset || 'standard',
      output_tier: p.output_tier || 'auto',
      text_overlay_enabled: p.text_overlay_enabled,
      text_overlays: p.text_overlays ? p.text_overlays.map((t) => ({ text: t.text, position: t.position, font_size: t.font_size ?? 40, color: t.color ?? '#EDD736', border_color: t.border_color, vertical: t.vertical, offset: t.offset })) : prev.text_overlays,
      watermark_enabled: p.watermark_enabled,
      watermark_text: p.watermark_text,
      watermark_font_size: p.watermark_font_size,
      watermark_opacity: p.watermark_opacity,
      watermark_position: p.watermark_position,
      watermark_style: p.watermark_style,
    }));
  };

  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [batches, setBatches] = useState<BatchSlice[]>([]);
  const [batchListLoading, setBatchListLoading] = useState(false);

  // 每个批次独立维护明细数据，支持在对应批次行下方内联展开（不再挤到最下方）
  const [expandedBatchIds, setExpandedBatchIds] = useState<React.Key[]>([]);
  const [itemsMap, setItemsMap] = useState<Record<string, BatchSliceItem[]>>({});
  const [detailLoadingMap, setDetailLoadingMap] = useState<Record<string, boolean>>({});
  // 选中的批次（用于顶部汇总/操作按钮）
  const [selectedBatch, setSelectedBatch] = useState<BatchSlice | null>(null);
  const [outputs, setOutputs] = useState<BatchSliceOutputItem[]>([]);
  const [outputModalOpen, setOutputModalOpen] = useState(false);

  // ── 输出列表：预览 ──
  const [previewModal, setPreviewModal] = useState(false);
  const [previewItem, setPreviewItem] = useState<{ file_name: string | null; url: string } | null>(null);

  // ── 输出列表：编辑（拖动进度条选定时间范围裁剪） ──
  const [trimModal, setTrimModal] = useState(false);
  const [trimTarget, setTrimTarget] = useState<FlattenOutput | null>(null);
  const [trimRange, setTrimRange] = useState<[number, number]>([0, 0]);
  const [trimming, setTrimming] = useState(false);
  // 固定文字角标编辑器
  const [textOverlayModalOpen, setTextOverlayModalOpen] = useState(false);
  const trimVideoRef = React.useRef<HTMLVideoElement>(null);

  const fetchBatches = useCallback(async () => {
    setBatchListLoading(true);
    try {
      const data = await batchSliceApi.list();
      setBatches(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '获取批次列表失败');
    } finally {
      setBatchListLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  const loadBatchDetail = useCallback(async (batchId: string) => {
    // 仅加载明细（items）到该批次对应的展开区域；批次概要已在列表中
    setDetailLoadingMap((prev) => ({ ...prev, [batchId]: true }));
    try {
      const [batch, itemList] = await Promise.all([
        batchSliceApi.getById(batchId),
        batchSliceApi.getItems(batchId),
      ]);
      setSelectedBatch(batch);
      setItemsMap((prev) => ({ ...prev, [batchId]: itemList }));
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载批次明细失败');
    } finally {
      setDetailLoadingMap((prev) => ({ ...prev, [batchId]: false }));
    }
  }, []);

  // 展开某批次时加载其明细；已加载则不重复请求
  const handleExpand = useCallback((expanded: boolean, batch: BatchSlice) => {
    setExpandedBatchIds((prev) => {
      const next = expanded
        ? (prev.includes(batch.id) ? prev : [...prev, batch.id])
        : prev.filter((k) => k !== batch.id);
      return next;
    });
    if (expanded) {
      // 顶部汇总跟随当前展开的批次
      setSelectedBatch(batch);
      if (!itemsMap[batch.id]) {
        loadBatchDetail(batch.id);
      }
    }
  }, [itemsMap, loadBatchDetail]);

  // 轮询：仅轮询当前已展开的批次明细，保证进度实时刷新
  useEffect(() => {
    if (expandedBatchIds.length === 0) return;
    const timer = window.setInterval(() => {
      expandedBatchIds.forEach((id) => {
        const key = String(id);
        const b = batches.find((x) => x.id === key);
        if (b && (b.status === 'running' || b.status === 'pending')) {
          loadBatchDetail(key);
        }
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [expandedBatchIds, batches, loadBatchDetail]);

  const handleFileUpload = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      setJsonText(text);
      setJsonError(null);
      try {
        const parsed = JSON.parse(text);
        if (!parsed.drama || !Array.isArray(parsed.episodes)) {
          setJsonError('JSON 需包含 drama（剧名）与 episodes（剧集数组）字段');
        }
      } catch {
        setJsonError('JSON 解析失败，请检查格式');
      }
    };
    reader.readAsText(file);
    return false;
  };

  const buildPayload = () => {
    let parsed: { drama?: string; episodes?: { title?: string; path: string }[] };
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      throw new Error('JSON 解析失败，请检查格式');
    }
    if (!parsed.drama || !parsed.drama.trim()) throw new Error('缺少剧名 drama');
    if (!Array.isArray(parsed.episodes) || parsed.episodes.length === 0) {
      throw new Error('缺少剧集列表 episodes');
    }
    for (const ep of parsed.episodes) {
      if (!ep.path) throw new Error('剧集中存在缺少 path 的项');
    }
    return {
      drama: parsed.drama.trim(),
      episodes: parsed.episodes,
      slice_config: {
        mode: 'fast',
        ...sliceConfig,
        // AI 智能选点：配置并入 autoclip_config / autoclip_enabled
        autoclip_enabled: sliceConfig.autoclip.enabled,
        autoclip_config: {
          max_clips: sliceConfig.autoclip.max_clips,
          min_score_threshold: sliceConfig.autoclip.min_score_threshold,
          min_duration: sliceConfig.autoclip.min_duration,
          max_duration: sliceConfig.autoclip.max_duration,
          frame_analysis: sliceConfig.autoclip.frame_analysis,
        },
        // 通用区间检测：配置并入 interval_config / interval_enabled
        interval_enabled: sliceConfig.interval.enabled,
        interval_config: {
          mode: sliceConfig.interval.mode,
        },
        // text_overlays 仅开启时透传
        text_overlays: sliceConfig.text_overlay_enabled ? sliceConfig.text_overlays : [],
        // 去重档位（轻/标准/重，仅 dedupe 模式生效）
        dedupe_config: { preset: sliceConfig.dedupe_preset },
      },
    };
  };

  const addTextOverlay = () => {
    setSliceConfig((prev) => ({
      ...prev,
      text_overlays: [...prev.text_overlays, { text: '', position: 'top-right', font_size: 40, color: '#EDD736', border_color: '#000000', vertical: false, offset: 10 }],
    }));
  };

  const updateTextOverlay = (index: number, patch: Partial<TextOverlayItem>) => {
    setSliceConfig((prev) => ({
      ...prev,
      text_overlays: prev.text_overlays.map((t, i) => (i === index ? { ...t, ...patch } : t)),
    }));
  };

  const removeTextOverlay = (index: number) => {
    setSliceConfig((prev) => ({
      ...prev,
      text_overlays: prev.text_overlays.filter((_, i) => i !== index),
    }));
  };

  const handleRun = async () => {
    setJsonError(null);
    let payload: ReturnType<typeof buildPayload>;
    try {
      payload = buildPayload();
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : '参数校验失败');
      return;
    }
    setCreating(true);
    try {
      const resp = await batchSliceApi.run(payload);
      message.success(resp.message);
      setJsonText('');
      form.resetFields();
      fetchBatches();
      if (resp.batch_id) {
        // 新批次创建后自动展开该批次明细
        setExpandedBatchIds((prev) => (prev.includes(resp.batch_id!) ? prev : [...prev, resp.batch_id!]));
        await loadBatchDetail(resp.batch_id);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建批次失败');
    } finally {
      setCreating(false);
    }
  };

  const handleRetry = async () => {
    if (!selectedBatch) return;
    const batchId = selectedBatch.id;
    Modal.confirm({
      title: '重试失败项',
      content: '确定重试该批次中失败的剧集吗？（已完成项将跳过）',
      okText: '重试',
      cancelText: '取消',
      onOk: async () => {
        try {
          const resp = await batchSliceApi.retry(batchId);
          message.success(resp.message);
          loadBatchDetail(batchId);
        } catch (err) {
          message.error(err instanceof Error ? err.message : '重试失败');
        }
      },
    });
  };

  const handleCancel = async () => {
    if (!selectedBatch) return;
    const batchId = selectedBatch.id;
    Modal.confirm({
      title: '取消批次',
      content: '确定取消该批次吗？（未完成的剧集将标记为已取消）',
      okText: '取消批次',
      cancelText: '返回',
      onOk: async () => {
        try {
          const resp = await batchSliceApi.cancel(batchId);
          message.success(resp.message);
          loadBatchDetail(batchId);
        } catch (err) {
          message.error(err instanceof Error ? err.message : '取消失败');
        }
      },
    });
  };

  const showOutputs = async () => {
    if (!selectedBatch) return;
    const batchId = selectedBatch.id;
    setOutputModalOpen(true);
    try {
      const data = await batchSliceApi.getOutputs(batchId);
      setOutputs(data.items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '获取输出列表失败');
    }
  };

  const renderOutputModal = () => {
    const allOutputs: FlattenOutput[] = [];
    outputs.forEach((item) => {
      // 后端统一返回恒定结构 { outputs: [...], count: n }
      const out = item.output;
      const files: Record<string, unknown>[] = [];
      if (out && Array.isArray((out as any).outputs)) {
        (out as any).outputs.forEach((f: Record<string, unknown>) => files.push(f));
      }
      files.forEach((f) => allOutputs.push({
        seq: item.seq,
        title: item.title,
        episode_id: item.episode_id,
        slice_task_id: item.slice_task_id,
        file: f,
      }));
    });
    return (
      <Modal
        title={`输出列表（共 ${allOutputs.length} 个成品）`}
        open={outputModalOpen}
        onCancel={() => setOutputModalOpen(false)}
        footer={null}
        width={820}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="每个成品支持「预览」播放，以及「编辑」通过拖动进度条选定时间范围进行简单裁剪（会重新编码生成新片段）。"
        />
        <List
          dataSource={allOutputs}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button key="pv" size="small" icon={<PlayCircleOutlined />} onClick={() => handlePreviewOutput(item)}>预览</Button>,
                <Button key="ed" size="small" type="primary" ghost icon={<EditOutlined />} onClick={() => openTrimModal(item)}>编辑</Button>,
                <a key="dl" href={(item.file as any).presigned_url || '#'} target="_blank" rel="noreferrer">
                  <DownloadOutlined /> 下载
                </a>,
              ]}
            >
              <List.Item.Meta
                title={`第 ${item.seq} 集 · ${(item.file as any).file_name || ''}`}
                description={
                  <Space size={12}>
                    <Text type="secondary">{(item.file as any).duration ? `${(item.file as any).duration}s` : ''}</Text>
                    <Text type="secondary">{(item.file as any).resolution || ''}</Text>
                    <Text type="secondary">{formatSize((item.file as any).file_size)}</Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    );
  };

  // ── 输出预览 ──
  const handlePreviewOutput = async (item: FlattenOutput) => {
    const url = (item.file as any).presigned_url;
    if (!url) {
      message.warning('该成品暂无可用预览地址');
      return;
    }
    setPreviewItem({ file_name: (item.file as any).file_name || '', url });
    setPreviewModal(true);
  };

  // ── 打开编辑（裁剪）弹窗 ──
  const openTrimModal = (item: FlattenOutput) => {
    if (!item.episode_id) {
      message.warning('该成品未关联剧集，无法裁剪');
      return;
    }
    const duration = Number((item.file as any).duration || 0);
    setTrimTarget(item);
    setTrimRange([0, duration > 0 ? duration : 0]);
    setTrimModal(true);
  };

  // 拖动进度条：实时定位预览画面到起始点
  const handleTrimRangeChange = (val: [number, number]) => {
    setTrimRange(val);
    const video = trimVideoRef.current;
    if (video && isFinite(val[0])) {
      video.currentTime = val[0];
    }
  };

  // 提交裁剪：复用剧集「成品重新剪辑」能力（以该成品为源裁剪出新片段）
  const submitTrim = async () => {
    if (!trimTarget) return;
    const [start, end] = trimRange;
    if (!(start >= 0) || !(end > start)) {
      message.warning('剪辑区间不合法：需要 0 <= 开始时间 < 结束时间');
      return;
    }
    setTrimming(true);
    try {
      await sliceApi.run(trimTarget.episode_id!, 'fast', {
        output_id: (trimTarget.file as any).id,
        cut_start: start,
        cut_end: end,
        engine: 'worker',
      });
      message.success('裁剪任务已启动，完成后会生成一个新成品，可在对应剧集成品预览中查看');
      setTrimModal(false);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '启动裁剪失败');
    } finally {
      setTrimming(false);
    }
  };

  const renderPreviewModal = () => (
    <Modal
      title={`预览${previewItem?.file_name ? `：${previewItem.file_name}` : ''}`}
      open={previewModal}
      onCancel={() => setPreviewModal(false)}
      footer={null}
      width={720}
      destroyOnClose
    >
      {previewItem && (
        <video src={previewItem.url} controls autoPlay style={{ width: '100%', maxHeight: 480, background: '#000', borderRadius: 6 }} />
      )}
    </Modal>
  );

  const renderTrimModal = () => {
    const duration = Number((trimTarget?.file as any)?.duration || 0);
    const max = duration > 0 ? duration : 1;
    const [start, end] = trimRange;
    return (
      <Modal
        title={`编辑（裁剪）${trimTarget ? `：${(trimTarget.file as any).file_name || ''}` : ''}`}
        open={trimModal}
        onOk={submitTrim}
        onCancel={() => setTrimModal(false)}
        okText="开始裁剪"
        cancelText="取消"
        confirmLoading={trimming}
        width={720}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="拖动进度条选定时间范围进行简单裁剪，预览会实时定位到起始点。裁剪完成后会重新编码生成一个新成品。"
        />
        <video
          ref={trimVideoRef}
          src={(trimTarget?.file as any)?.presigned_url}
          style={{ width: '100%', maxHeight: 300, background: '#000', borderRadius: 6 }}
          controls
          preload="auto"
        />
        <div style={{ marginTop: 12, padding: '8px 12px', background: '#f5f5f5', borderRadius: 6 }}>
          <Text strong style={{ fontSize: 12 }}>拖动选定时间范围：</Text>
          <Slider
            range
            min={0}
            max={Math.max(max, 1)}
            step={0.1}
            value={[start, end]}
            onChange={(v) => handleTrimRangeChange(v as [number, number])}
            tooltip={{ formatter: (v) => formatDuration(Number(v ?? 0)) }}
            disabled={duration <= 0}
          />
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>起始: {formatDuration(start)}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>结束: {formatDuration(end)}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>时长: {formatDuration(end - start)}</Text>
          </Space>
          <Space style={{ marginTop: 8 }}>
            <Button size="small" onClick={() => trimRange[0] !== 0 && setTrimRange([0, duration])}>选全部</Button>
            <Button size="small" onClick={() => { const v = trimVideoRef.current; if (v && isFinite(v.currentTime)) { const cur = Math.min(v.currentTime, duration); const end = trimRange[1]; setTrimRange([Math.min(cur, Math.max(end - 0.1, 0)), end]); } }}>取当前播放点为起点</Button>
          </Space>
        </div>
      </Modal>
    );
  };

  const formatSize = (size?: number | null) => {
    if (!size) return '';
    if (size < 1024) return `${size}B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
    return `${(size / 1024 / 1024).toFixed(1)}MB`;
  };

  const itemColumns = [
    { title: '序号', dataIndex: 'seq', width: 60 },
    {
      title: '剧集',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '阶段',
      dataIndex: 'phase',
      width: 110,
      render: (v: string | null) => (v ? (PHASE_LABELS[v] || v) : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_TEXT[v] || v}</Tag>,
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 120,
      render: (v: number, r: BatchSliceItem) => (
        <Progress percent={Math.round(v)} size="small" status={r.status === 'failed' ? 'exception' : undefined} />
      ),
    },
    { title: '成品数', dataIndex: 'output_count', width: 80 },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (v: string | null) => (v ? <Text type="danger">{v}</Text> : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, r: BatchSliceItem) => {
        // 提供直接跳转到对应成品预览的快捷方式（优先跳具体切片任务，否则跳该剧集成品预览）
        if (r.episode_id) {
          const to = r.slice_task_id
            ? `/episodes/${r.episode_id}/preview?task=${r.slice_task_id}`
            : `/episodes/${r.episode_id}/preview`;
          return (
            <a
              title="跳转成片预览"
              onClick={(e) => { e.stopPropagation(); navigate(to); }}
            >
              <EyeOutlined /> 成片预览
            </a>
          );
        }
        return <Text type="secondary">-</Text>;
      },
    },
  ];

  const batchColumns = [
    {
      title: '批次',
      dataIndex: 'name',
      ellipsis: true,
      render: (v: string | null, r: BatchSlice) => (
        <a onClick={(e) => { e.stopPropagation(); handleExpand(!expandedBatchIds.includes(r.id), r); }}>{v || r.id}</a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_TEXT[v] || v}</Tag>,
    },
    { title: '总数', dataIndex: 'total', width: 60 },
    { title: '完成', dataIndex: 'done', width: 60 },
    { title: '失败', dataIndex: 'failed', width: 60 },
    { title: '成品数', dataIndex: 'output_count', width: 80 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>批量切片工作流</Title>
      <Alert
        type="info"
        showIcon
        message="上传包含剧名与剧集地址的 JSON，系统按剧名查找/创建项目，并按列表顺序逐集完成「AI 选点 → 自动审核 → 一键切片 → 删除源视频」，最后汇总输出列表。"
        style={{ marginBottom: 16 }}
      />

      <Card title="① 上传列表（JSON）" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical">
          <Form.Item label="JSON 内容（示例）" required>
            <Input.TextArea
              rows={6}
              value={jsonText}
              onChange={(e) => {
                setJsonText(e.target.value);
                setJsonError(null);
              }}
              placeholder={'{\n  "drama": "短剧A",\n  "episodes": [\n    { "title": "第1集", "path": "/mnt/nas/shortdrama/ep01.mp4" },\n    { "title": "第2集", "path": "/mnt/nas/shortdrama/ep02.mp4" }\n  ]\n}'}
            />
            <div style={{ marginTop: 8 }}>
              <Dragger
                accept=".json,.txt"
                beforeUpload={(file) => {
                  handleFileUpload(file as unknown as File);
                  return false;
                }}
                showUploadList={false}
                style={{ padding: 8 }}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
              </Dragger>
            </div>
            {jsonError && <Text type="danger">{jsonError}</Text>}
          </Form.Item>
        </Form>
      </Card>

      <Card title="② 一键切片配置选项" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {/* 一键切片配置预设：与剧集详情页共用一套，选中即套用其全部参数 */}
          <Space wrap align="center" size={8}>
            <Text strong>选择配置：</Text>
            <Select
              size="small"
              style={{ width: 220 }}
              placeholder="选择预设（默认按下方手工配置）"
              value={presetOptions.some((p) => p.id === slicePresetId) ? slicePresetId : undefined}
              onChange={applySlicePreset}
              options={presetOptions.map((p) => ({ value: p.id, label: p.name }))}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              与剧集详情页「一键切片配置」共用，选中后自动套用竖屏转横屏/字幕/打码/水印/去重档位等全部参数
            </Text>
          </Space>
          <Divider orientation="left" style={{ margin: '8px 0' }}>AI 智能选点</Divider>
          <Space size="large" wrap>
            <Text>启用 AI 选点：</Text>
            <Switch
              checked={sliceConfig.autoclip.enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, enabled: v } })}
            />
            {sliceConfig.autoclip.enabled && (
              <>
                <Text>候选数</Text>
                <InputNumber
                  value={sliceConfig.autoclip.max_clips}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, max_clips: v ?? 30 } })}
                  min={1}
                  max={200}
                />
                <Text>最低评分</Text>
                <InputNumber
                  value={sliceConfig.autoclip.min_score_threshold}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, min_score_threshold: v ?? 50 } })}
                  min={0}
                  max={100}
                />
                <Text>最短时长(s)</Text>
                <InputNumber
                  value={sliceConfig.autoclip.min_duration}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, min_duration: v ?? 0 } })}
                  min={0}
                />
                <Text>最长时长(s)</Text>
                <InputNumber
                  value={sliceConfig.autoclip.max_duration}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, max_duration: v ?? 0 } })}
                  min={0}
                />
                <Text>画面理解</Text>
                <Switch
                  checked={sliceConfig.autoclip.frame_analysis}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, frame_analysis: v } })}
                />
              </>
            )}
          </Space>

          <Divider orientation="left" style={{ margin: '8px 0' }}>通用区间检测</Divider>
          <Space size="large" wrap>
            <Text>启用区间检测：</Text>
            <Switch
              checked={sliceConfig.interval.enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, interval: { ...sliceConfig.interval, enabled: v } })}
            />
            {sliceConfig.interval.enabled && (
              <>
                <Text>检测模式</Text>
                <Select
                  value={sliceConfig.interval.mode}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, interval: { ...sliceConfig.interval, mode: v } })}
                  style={{ width: 120 }}
                  options={[
                    { value: 'credits', label: '片尾字幕' },
                    { value: 'static', label: '静止画面' },
                    { value: 'watermark', label: '水印' },
                  ]}
                />
                <Tooltip title="区间检测会在切片前自动检测片尾/静止/水印区间，用于辅助切片流程">
                  <Tag color="blue">切片前自动检测</Tag>
                </Tooltip>
              </>
            )}
          </Space>

          <Divider orientation="left" style={{ margin: '8px 0' }}>切片增强配置</Divider>
          <Space size="large">
            <Text>竖屏转横屏：</Text>
            <Switch
              checked={sliceConfig.vert2horiz_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_enabled: v })}
            />
            {sliceConfig.vert2horiz_enabled && (
              <>
                <Select
                  value={sliceConfig.vert2horiz_mode}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_mode: v })}
                  style={{ width: 120 }}
                  options={[
                    { value: 'fixed', label: '固定裁切' },
                    { value: 'dynamic', label: '动态人脸' },
                  ]}
                />
                <Text>输出</Text>
                <Select
                  value={sliceConfig.vert2horiz_output_size}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_output_size: v })}
                  style={{ width: 110 }}
                  options={['1280x720', '1920x1080'].map((s) => ({ value: s, label: s }))}
                />
              </>
            )}
            {sliceConfig.vert2horiz_enabled && (
              <>
                <Text>检测间隔(s)</Text>
                <InputNumber
                  value={sliceConfig.vert2horiz_detect_interval}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_detect_interval: v ?? 2 })}
                  min={1}
                  max={10}
                  style={{ width: 70 }}
                />
                <Text>平滑窗口</Text>
                <InputNumber
                  value={sliceConfig.vert2horiz_smooth_window}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_smooth_window: v ?? 15 })}
                  min={3}
                  max={30}
                  style={{ width: 70 }}
                />
                <Text>最小步长</Text>
                <InputNumber
                  value={sliceConfig.vert2horiz_min_step}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_min_step: v ?? 5 })}
                  min={1}
                  max={30}
                  style={{ width: 70 }}
                />
                <Text>人脸边距</Text>
                <InputNumber
                  value={sliceConfig.vert2horiz_face_margin}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_face_margin: v ?? 0.30 })}
                  step={0.05}
                  min={0}
                  max={1}
                  style={{ width: 70 }}
                />
              </>
            )}
          </Space>

          <Space size="large" align="center">
            <Text>去重档位：</Text>
            <Select
              value={sliceConfig.dedupe_preset}
              onChange={(v) => setSliceConfig({ ...sliceConfig, dedupe_preset: v })}
              style={{ width: 190 }}
              options={dedupePresetOptions}
            />
            <Tooltip title="去重档位（轻/标准/重），用于降低平台查重风险。仅 dedupe 切片模式生效。">
              <Tag color="blue">去重档位</Tag>
            </Tooltip>
          </Space>

          <Space size="large" align="center">
            <Text>输出档位：</Text>
            <Select
              value={sliceConfig.output_tier}
              onChange={(v) => setSliceConfig({ ...sliceConfig, output_tier: v })}
              style={{ width: 190 }}
              options={[
                { value: 'original', label: '原档（不处理）' },
                { value: 'auto', label: '自动（高规格自动降 720P30）' },
                { value: '1080p', label: '1080P（宽≤1080/fps≤60）' },
                { value: '720p', label: '720P（宽≤720/fps≤30）' },
                { value: '480p', label: '480P（宽≤480/fps≤30）' },
              ]}
            />
            <Tooltip title="输出档位：高分辨率/高 fps 素材可降档提速（引擎滤镜链末尾追加 scale+fps，cover concat 同步同档位）。">
              <Tag color="purple">输出档位</Tag>
            </Tooltip>
          </Space>

          <Space size="large">
            <Text>ASR 字幕烧录：</Text>
            <Switch
              checked={sliceConfig.subtitle_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_enabled: v })}
            />
            {sliceConfig.subtitle_enabled && (
              <>
                <Text>字号</Text>
                <InputNumber
                  value={sliceConfig.subtitle_font_ratio}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_font_ratio: v ?? 0.30 })}
                  step={0.05}
                  min={0.1}
                  max={0.6}
                />
                <Text>间距</Text>
                <InputNumber
                  value={sliceConfig.subtitle_spacing}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_spacing: v ?? 0 })}
                  step={1}
                  min={-5}
                  max={20}
                  style={{ width: 70 }}
                />
                <Text>粗细</Text>
                <Select
                  value={sliceConfig.subtitle_bold}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_bold: v })}
                  style={{ width: 90 }}
                  options={[
                    { value: 0, label: '常规' },
                    { value: -1, label: '加粗' },
                    { value: 1, label: '粗体' },
                  ]}
                />
                <Select
                  value={sliceConfig.subtitle_style}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_style: v })}
                  style={{ width: 110 }}
                  options={[
                    { value: 'default', label: '默认' },
                    { value: 'custom', label: '自定义' },
                  ]}
                />
                {sliceConfig.subtitle_style === 'custom' && (
                  <>
                    <Input
                      value={sliceConfig.subtitle_color}
                      onChange={(e) => setSliceConfig({ ...sliceConfig, subtitle_color: e.target.value })}
                      style={{ width: 90 }}
                      placeholder="字体色"
                    />
                    <Input
                      value={sliceConfig.subtitle_border_color}
                      onChange={(e) => setSliceConfig({ ...sliceConfig, subtitle_border_color: e.target.value })}
                      style={{ width: 90 }}
                      placeholder="边框色"
                    />
                  </>
                )}
                <Text>对齐打码区</Text>
                <Switch
                  checked={sliceConfig.subtitle_align_mask}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_align_mask: v })}
                />
              </>
            )}
          </Space>

          <Space size="large">
            <Text>源字幕打码：</Text>
            <Switch
              checked={sliceConfig.subtitle_mask_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_mask_enabled: v })}
            />
            {sliceConfig.subtitle_mask_enabled && (
              <Select
                value={sliceConfig.subtitle_mask_style}
                onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_mask_style: v })}
                style={{ width: 110 }}
                options={[
                  { value: 'delogo', label: '去水印' },
                  { value: 'gblur', label: '高斯模糊' },
                  { value: 'mosaic', label: '马赛克' },
                  { value: 'blur', label: '模糊' },
                  { value: 'fill', label: '纯色块' },
                ]}
              />
            )}
            {sliceConfig.subtitle_mask_enabled && (
              <Select
                value={sliceConfig.subtitle_mask_preset}
                onChange={(v) => setSliceConfig({
                  ...sliceConfig,
                  subtitle_mask_preset: v,
                  subtitle_mask_temporal: v !== 'quick',
                  subtitle_mask_spatial: v === 'fine',
                })}
                style={{ width: 110 }}
                options={[
                  { value: 'auto', label: '自动' },
                  { value: 'fine', label: '精细' },
                  { value: 'quick', label: '快速' },
                ]}
              />
            )}
            {sliceConfig.subtitle_mask_enabled && (
              <>
                <Text>宽占比</Text>
                <InputNumber
                  value={sliceConfig.subtitle_mask_width_ratio}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_mask_width_ratio: v ?? 0.9 })}
                  step={0.05}
                  min={0.1}
                  max={1}
                  style={{ width: 70 }}
                />
                <Text>高占比</Text>
                <InputNumber
                  value={sliceConfig.subtitle_mask_height_ratio}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_mask_height_ratio: v ?? 0.12 })}
                  step={0.02}
                  min={0.02}
                  max={0.5}
                  style={{ width: 70 }}
                />
                <Text>底占比</Text>
                <InputNumber
                  value={sliceConfig.subtitle_mask_bottom_ratio}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_mask_bottom_ratio: v ?? 0.02 })}
                  step={0.02}
                  min={0}
                  max={0.3}
                  style={{ width: 70 }}
                />
                <Text>时间偏移(s)</Text>
                <InputNumber
                  value={sliceConfig.subtitle_mask_srt_offset}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_mask_srt_offset: v ?? 0 })}
                  step={0.1}
                  style={{ width: 80 }}
                />
              </>
            )}
          </Space>

          <Space size="large">
            <Text>固定文字角标：</Text>
            <Switch
              checked={sliceConfig.text_overlay_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, text_overlay_enabled: v })}
            />
            {sliceConfig.text_overlay_enabled && (
              <>
                <Tag>已启用 {sliceConfig.text_overlays.length} 条文字</Tag>
                <Button size="small" icon={<EditOutlined />} onClick={() => setTextOverlayModalOpen(true)}>设置文字</Button>
              </>
            )}
          </Space>

          <Space size="large">
            <Text>文字水印：</Text>
            <Switch
              checked={sliceConfig.watermark_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_enabled: v })}
            />
            {sliceConfig.watermark_enabled && (
              <>
                <Input
                  value={sliceConfig.watermark_text}
                  onChange={(e) => setSliceConfig({ ...sliceConfig, watermark_text: e.target.value })}
                  placeholder="水印文字（支持 {title}/{date}）"
                  style={{ width: 200 }}
                />
                <Select
                  value={sliceConfig.watermark_position}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_position: v })}
                  style={{ width: 90 }}
                  options={[
                    { value: 'bottom', label: '底部' },
                    { value: 'top', label: '顶部' },
                  ]}
                />
                <Text>形态</Text>
                <Select
                  value={sliceConfig.watermark_style}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_style: v })}
                  style={{ width: 90 }}
                  options={WATERMARK_STYLE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
                <Text>字号</Text>
                <InputNumber
                  value={sliceConfig.watermark_font_size}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_font_size: v ?? 28 })}
                  min={12}
                  max={120}
                  style={{ width: 70 }}
                />
                <Text>透明度</Text>
                <InputNumber
                  value={sliceConfig.watermark_opacity}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_opacity: v ?? 0.5 })}
                  step={0.05}
                  min={0.05}
                  max={1}
                  style={{ width: 70 }}
                />
              </>
            )}
          </Space>
        </Space>

        <Divider />
        <Space>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={creating}
            onClick={handleRun}
          >
            创建批次并开始处理
          </Button>
          <Button
            icon={<UploadOutlined />}
            onClick={() => setSliceConfig({ ...DEFAULT_SLICE_CONFIG, text_overlays: DEFAULT_SLICE_CONFIG.text_overlays.map((t) => ({ ...t })) })}
          >
            恢复默认配置
          </Button>
        </Space>
      </Card>

      <Card title="③ 执行结果" style={{ marginBottom: 16 }}>
        <Space style={{ marginBottom: 16 }}>
          <Button onClick={fetchBatches} icon={<ReloadOutlined />}>刷新批次列表</Button>
          {selectedBatch && (
            <>
              <Tag color={STATUS_COLOR[selectedBatch.status] || 'default'}>
                {STATUS_TEXT[selectedBatch.status] || selectedBatch.status}
              </Tag>
              <Text>完成 {selectedBatch.done}/{selectedBatch.total} · 失败 {selectedBatch.failed} · 成品 {selectedBatch.output_count}</Text>
              {selectedBatch.status === 'partial_failed' && (
                <Button onClick={handleRetry} size="small">重试失败项</Button>
              )}
              {['running', 'pending'].includes(selectedBatch.status) && (
                <Button onClick={handleCancel} danger size="small" icon={<StopOutlined />}>取消批次</Button>
              )}
              <Button onClick={showOutputs} size="small" icon={<DownloadOutlined />}>输出列表</Button>
            </>
          )}
        </Space>
        <Spin spinning={batchListLoading}>
          <Table
            rowKey="id"
            size="small"
            dataSource={batches}
            columns={batchColumns}
            pagination={false}
            onRow={(record: BatchSlice) => ({
              onClick: () => handleExpand(!expandedBatchIds.includes(record.id), record),
              style: { cursor: 'pointer' },
            })}
            expandable={{
              expandedRowKeys: expandedBatchIds,
              onExpandedRowsChange: (keys: readonly React.Key[]) => setExpandedBatchIds(keys as React.Key[]),
              onExpand: (expanded: boolean, record: BatchSlice) => handleExpand(expanded, record),
              expandedRowRender: (record: BatchSlice) => {
                const detailItems = itemsMap[record.id] || [];
                const loading = !!detailLoadingMap[record.id];
                if (loading) {
                  return (
                    <div style={{ padding: '12px 0', textAlign: 'center' }}>
                      <Spin size="small" /> <Text type="secondary">正在加载批次明细…</Text>
                    </div>
                  );
                }
                if (detailItems.length === 0) {
                  return <Text type="secondary">该批次暂无剧集明细</Text>;
                }
                return (
                  <Table
                    rowKey="id"
                    size="small"
                    dataSource={detailItems}
                    columns={itemColumns}
                    pagination={false}
                    onRow={(record: BatchSliceItem) => ({
                      // 双击明细行同样可跳转成片预览（与操作列呼应）
                      onDoubleClick: () => {
                        if (record.episode_id) {
                          navigate(record.slice_task_id
                            ? `/episodes/${record.episode_id}/preview?task=${record.slice_task_id}`
                            : `/episodes/${record.episode_id}/preview`);
                        }
                      },
                    })}
                  />
                );
              },
            }}
          />
        </Spin>
      </Card>

      {renderOutputModal()}
      {renderPreviewModal()}
      {renderTrimModal()}
      <Modal
        title="固定文字设置"
        open={textOverlayModalOpen}
        onCancel={() => setTextOverlayModalOpen(false)}
        footer={(<Button type="primary" onClick={() => setTextOverlayModalOpen(false)}>完成</Button>)}
        width={620}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap align="center" size={8}>
            <Button size="small" icon={<PlusOutlined />} onClick={addTextOverlay}>添加固定文字</Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              在视频指定位置叠加固定文字，全程覆盖。文字内容、位置、字号、颜色、描边、竖排均可自定义。
            </Text>
          </Space>
          {sliceConfig.text_overlays.length > 0 ? (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {sliceConfig.text_overlays.map((t, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
                  <Input
                    size="small"
                    placeholder="文字内容"
                    value={t.text}
                    onChange={(e) => updateTextOverlay(i, { text: e.target.value })}
                    style={{ width: 150 }}
                  />
                  <Select
                    size="small"
                    style={{ width: 95 }}
                    value={t.position}
                    onChange={(v) => updateTextOverlay(i, { position: v })}
                    options={POSITIONS.map((p) => ({ value: p, label: p }))}
                  />
                  <Tooltip title="是否竖排（最左侧常用，垂直居中）">
                    <Checkbox
                      checked={!!t.vertical}
                      onChange={(e) => updateTextOverlay(i, { vertical: e.target.checked })}
                    >竖排</Checkbox>
                  </Tooltip>
                  <InputNumber
                    size="small"
                    min={12}
                    max={200}
                    placeholder="字号"
                    value={t.font_size}
                    onChange={(v) => updateTextOverlay(i, { font_size: v ?? undefined })}
                    style={{ width: 80 }}
                    addonAfter="px"
                  />
                  <Text strong style={{ fontSize: 12 }}>字色</Text>
                  <ColorPicker
                    size="small"
                    value={t.color || '#FFFFFF'}
                    onChange={(c) => updateTextOverlay(i, { color: c.toHexString() })}
                    showText
                  />
                  <Text strong style={{ fontSize: 12 }}>描边</Text>
                  <ColorPicker
                    size="small"
                    value={t.border_color || '#000000'}
                    onChange={(c) => updateTextOverlay(i, { border_color: c.toHexString() })}
                    showText
                  />
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeTextOverlay(i)} />
                </div>
              ))}
            </Space>
          ) : (
            <Alert type="info" showIcon message="暂无固定文字，点击上方「添加固定文字」新增。" />
          )}
        </Space>
      </Modal>
    </div>
  );
};

export default BatchSlicePage;
