import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Select, Progress, Popconfirm, Tooltip, Alert, Switch, InputNumber, Input, Upload, List, Image as AntImage, Radio, ColorPicker, Checkbox, Modal, Cascader,
} from 'antd';
import { UploadOutlined, PlusOutlined, DeleteOutlined as DelIcon } from '@ant-design/icons';
import { ArrowLeftOutlined, PlayCircleOutlined, ReloadOutlined, StopOutlined, InfoCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, DeleteOutlined, DesktopOutlined, SettingOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi, type BadgeItem, type TextOverlayItem } from '../api/slice';
import { previewApi } from '../api/preview';
import ErrorHint from '../components/ErrorHint';
import DedupeManualConfig, { type DedupeManualConfigValue } from '../components/DedupeManualConfig';
import type { SliceOutput, SliceTask } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

// 切片模式说明
// 角标位置选项（七位）：最左侧/左上/中上/右上/左下/中下/右下
const BADGE_POSITIONS = [
  { value: 'left', label: '最左侧' },
  { value: 'top-left', label: '左上' },
  { value: 'top-center', label: '中上' },
  { value: 'top-right', label: '右上' },
  { value: 'bottom-left', label: '左下' },
  { value: 'bottom-center', label: '中下' },
  { value: 'bottom-right', label: '右下' },
];

const SLICE_MODE_HELP: Record<string, { label: string; desc: string }> = {
  fast: {
    label: '快速模式',
    desc: '直接按选点结果切割，不做去重处理。速度最快，适合初次出片测试。',
  },
  dedupe: {
    label: '去重模式',
    desc: '切割时进行画面去重处理，采用「空间变换（缩放裁切/镜像）+ 时域变换（变速）+ 色彩变换（降饱和/复古偏色）+ 质感叠加（老电视噪点/扫描线/暗角/锐化/贴纸水印）」四层组合，可选轻/标准/重三档（标准档为默认效果），并支持「去重高级配置」逐项手动调整每个手段。适合批量发布到多个平台，降低查重风险。',
  },
  scrub: {
    label: '挖洞模式',
    desc: '在去重基础上随机挖洞（替换为纯色帧），使每个输出片段指纹更独特。适合高频发布场景，降低平台查重处罚。',
  },
};

// ─── 切片模式级联选项（去重模式带 轻/标准/重 档位，悬停即弹出选择框）──
const SLICE_MODE_OPTIONS = [
  { value: 'fast', label: '快速模式' },
  {
    value: 'dedupe',
    label: '去重模式',
    children: [
      { value: 'light', label: '轻' },
      { value: 'standard', label: '标准' },
      { value: 'heavy', label: '重' },
    ],
  },
  { value: 'scrub', label: '挖洞模式' },
];

const SliceTasks: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<SliceTask[]>([]);
  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [currentTask, setCurrentTask] = useState<string | null>(null);
  const [mode, setMode] = useState('fast');
  const [engine, setEngine] = useState('worker');
  // 去重模式档位：轻/标准/重（老电视质感去重强度，默认标准档）
  const [dedupePreset, setDedupePreset] = useState<string>('standard');
  // 去重模式手动配置（每项去重手段可单独覆盖预设，为空时沿用预设档位）
  const [dedupeManual, setDedupeManual] = useState<DedupeManualConfigValue>({});
  const [dedupeManualOpen, setDedupeManualOpen] = useState(false);
  // 自定义文字水印开关与参数
  const [watermarkEnabled, setWatermarkEnabled] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [watermarkFontSize, setWatermarkFontSize] = useState(28);
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.5);
  const [watermarkPosition, setWatermarkPosition] = useState('bottom');
  // 动态文字水印设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [watermarkModalOpen, setWatermarkModalOpen] = useState(false);
  // 图片角标列表：每个含 file_key（上传后 MinIO key）、position（位置）、width（可选宽度）、offset（可选偏移）、opacity（可选透明度）
  const [badges, setBadges] = useState<Array<BadgeItem & { name: string; preview: string }>>([]);
  const [badgeUploading, setBadgeUploading] = useState(false);
  // 角标默认尺寸（px）：角标未单独设 width 时生效；0=保持原图尺寸
  const [badgeDefaultWidth, setBadgeDefaultWidth] = useState<number>(0);
  // ── 竖屏转横屏智能裁切开关与参数 ──
  const [vert2horizEnabled, setVert2horizEnabled] = useState(false);
  const [vert2horizMode, setVert2horizMode] = useState<'fixed' | 'dynamic'>('dynamic');
  const [vert2horizRatio, setVert2horizRatio] = useState(0.5625);
  const [vert2horizOutputSize, setVert2horizOutputSize] = useState('1280x720');
  const [vert2horizDetectInterval, setVert2horizDetectInterval] = useState(2);
  const [vert2horizSmoothWindow, setVert2horizSmoothWindow] = useState(15);
  // 动态模式最小移动阈值（px）：越大越稳、越小越跟手
  const [vert2horizMinStep, setVert2horizMinStep] = useState(5);
  // 竖屏转横屏设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [vert2horizModalOpen, setVert2horizModalOpen] = useState(false);
  // ── ASR 字幕烧录（与转横屏联动：转横屏开启时默认开启字幕）──
  const [subtitleEnabled, setSubtitleEnabled] = useState(false);
  // 字幕字号（px，UI 显示值；转成比例 subtitleFontRatio = 字号/100 → FontSize）
  const [subtitleFontSize, setSubtitleFontSize] = useState(30);
  // 字幕字间距（ASS Spacing 像素，默认 0 更紧凑；调小/负值让字幕文字更紧凑，调大则字距变宽）
  const [subtitleSpacing, setSubtitleSpacing] = useState(0);
  // 字幕样式：default（白字黑边带底色）/ custom（自定义字体色+边框色，无底色）
  const [subtitleStyle, setSubtitleStyle] = useState<'default' | 'custom'>('custom');
  // 自定义样式的字体色 / 边框色（默认 #EDD736 黄 / 黑边）
  const [subtitleColor, setSubtitleColor] = useState('#EDD736');
  const [subtitleBorderColor, setSubtitleBorderColor] = useState('#000000');
  // 字幕设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [subtitleModalOpen, setSubtitleModalOpen] = useState(false);
  // ── 源视频字幕打码（去片源自带字幕，独立开关）──
  const [subtitleMaskEnabled, setSubtitleMaskEnabled] = useState(false);
  const [subtitleMaskStyle, setSubtitleMaskStyle] = useState<'delogo' | 'mosaic' | 'blur' | 'fill'>('delogo');
  // 精细化（帧级检测）：只在字幕/水印实际出现的时段打码
  const [subtitleMaskTemporal, setSubtitleMaskTemporal] = useState(true);
  // 仅字幕显示区域打码（空间精细化）：需开启精细化后才能开启，
  // 只对字幕文字实际占用的横向子区域打码，而不是整条横带都盖住。
  const [subtitleMaskSpatial, setSubtitleMaskSpatial] = useState(false);
  // 打码区域（相对输出视频宽高比例，默认宽度 0.9 / 高度 0.12 / 距底 0.02）
  const [subtitleMaskWidthRatio, setSubtitleMaskWidthRatio] = useState(0.9);
  const [subtitleMaskHeightRatio, setSubtitleMaskHeightRatio] = useState(0.12);
  const [subtitleMaskBottomRatio, setSubtitleMaskBottomRatio] = useState(0.02);
  // 源字幕打码设置弹窗是否打开
  const [subtitleMaskModalOpen, setSubtitleMaskModalOpen] = useState(false);
  // ── 固定文字角标（文字版角标，无需上传图片）──
  const [textOverlays, setTextOverlays] = useState<Array<TextOverlayItem & { id: string }>>([]);
  // 固定文字开关：开启后显示「设置文字」按钮，弹窗内集中管理固定文字配置
  const [textOverlayEnabled, setTextOverlayEnabled] = useState(false);
  // 固定文字设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [textOverlayModalOpen, setTextOverlayModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const fetchTasks = React.useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const list = await sliceApi.listTasks(episodeId || '');
      setTasks(list);
    } catch (err: unknown) {
      if (!silent) message.error(err instanceof Error ? err.message : '获取任务失败');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [episodeId]);

  useEffect(() => {
    fetchTasks();
    const timer = window.setInterval(() => fetchTasks(true), 5000);
    return () => window.clearInterval(timer);
  }, [fetchTasks]);

  // 构造去重配置：preset 基础档位 + manual 手动覆盖（过滤空值；贴纸水印仅 enabled 时启用）
  const buildDedupeConfig = (preset: string, manual: DedupeManualConfigValue) => {
    const m: Record<string, unknown> = {};
    if (manual.crop !== undefined) m.crop = manual.crop;
    if (manual.hflip !== undefined) m.hflip = manual.hflip;
    if (manual.speed !== undefined) m.speed = manual.speed;
    if (manual.saturation !== undefined) m.saturation = manual.saturation;
    if (manual.gamma !== undefined) m.gamma = manual.gamma;
    if (manual.contrast !== undefined) m.contrast = manual.contrast;
    if (manual.brightness !== undefined) m.brightness = manual.brightness;
    if (manual.noise !== undefined) m.noise = manual.noise;
    if (manual.sharpen !== undefined) m.sharpen = manual.sharpen;
    if (manual.vignette) m.vignette = manual.vignette;
    if (manual.roll_band !== undefined) m.roll_band = manual.roll_band;
    if (manual.jitter !== undefined) m.jitter = manual.jitter;
    if (manual.watermark?.enabled) {
      m.watermark = {
        text: manual.watermark.text || 'Clip',
        opacity: manual.watermark.opacity ?? 0.25,
        position: manual.watermark.position || 'bottom-right',
        drift: !!manual.watermark.drift,
      };
    }
    return Object.keys(m).length > 0 ? { preset, manual: m } : { preset };
  };

  const runSlice = async () => {
    setRunning(true);
    try {
      const res = await sliceApi.run(episodeId || '', mode, {
        engine,
        // 去重模式档位（轻/标准/重）+ 手动配置（每项手段可单独覆盖预设），仅去重模式生效
        dedupe_config: mode === 'dedupe'
          ? buildDedupeConfig(dedupePreset, dedupeManual)
          : undefined,
        watermark_enabled: watermarkEnabled,
        watermark_text: watermarkEnabled ? watermarkText : undefined,
        watermark_font_size: watermarkEnabled ? watermarkFontSize : undefined,
        watermark_opacity: watermarkEnabled ? watermarkOpacity : undefined,
        watermark_position: watermarkEnabled ? watermarkPosition : undefined,
        // 图片角标：传递每个角标的 file_key / position / width / offset / opacity
        badges: badges.length > 0
          ? badges.map((b) => ({
              file_key: b.file_key,
              position: b.position,
              ...(b.width ? { width: b.width } : {}),
              ...(b.offset != null ? { offset: b.offset } : {}),
              ...(b.opacity != null ? { opacity: b.opacity } : {}),
            }))
          : undefined,
        // 角标默认尺寸（px）：角标未单独设 width 时生效；0=保持原图尺寸
        badge_default_width: badgeDefaultWidth || undefined,
        // 竖屏转横屏：开启后切片前自动把竖屏素材转成横屏
        vert2horiz_enabled: vert2horizEnabled,
        vert2horiz_mode: vert2horizEnabled ? vert2horizMode : undefined,
        vert2horiz_ratio: vert2horizEnabled ? vert2horizRatio : undefined,
        vert2horiz_output_size: vert2horizEnabled ? vert2horizOutputSize : undefined,
        vert2horiz_detect_interval: vert2horizEnabled ? vert2horizDetectInterval : undefined,
        vert2horiz_smooth_window: vert2horizEnabled ? vert2horizSmoothWindow : undefined,
        vert2horiz_min_step: vert2horizEnabled ? vert2horizMinStep : undefined,
        // ASR 字幕烧录：开启后对源视频做 ASR 识别并烧录到成品视频
        subtitle_enabled: subtitleEnabled,
        // 字幕字号（px → 相对高度比例，字号/100；FontSize=字号）
        subtitle_font_ratio: subtitleEnabled ? Math.max(0.1, Math.min(0.6, subtitleFontSize / 100)) : undefined,
        // 字幕字间距（ASS Spacing 像素）：让字幕文字更紧凑
        subtitle_spacing: subtitleEnabled ? subtitleSpacing : undefined,
        // 字幕样式：custom 时可选字体色/边框色（无底色）
        subtitle_style: subtitleEnabled ? subtitleStyle : undefined,
        subtitle_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleColor : undefined,
        subtitle_border_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleBorderColor : undefined,
        // 源视频字幕打码：独立开关，开启后仅打掉片源自带字幕（不依赖 ASR 字幕开关）
        subtitle_mask_enabled: subtitleMaskEnabled,
        subtitle_mask_style: subtitleMaskEnabled ? subtitleMaskStyle : undefined,
        subtitle_mask_temporal: subtitleMaskEnabled ? subtitleMaskTemporal : undefined,
        subtitle_mask_spatial: (subtitleMaskEnabled && subtitleMaskTemporal) ? subtitleMaskSpatial : undefined,
        subtitle_mask_width_ratio: subtitleMaskEnabled ? subtitleMaskWidthRatio : undefined,
        subtitle_mask_height_ratio: subtitleMaskEnabled ? subtitleMaskHeightRatio : undefined,
        subtitle_mask_bottom_ratio: subtitleMaskEnabled ? subtitleMaskBottomRatio : undefined,
        // 固定文字角标：传递每条文字内容/位置/字号/颜色/竖排（仅开关开启时生效）
        text_overlays: textOverlayEnabled && textOverlays.length > 0
          ? textOverlays.map((t) => ({
              text: t.text,
              position: t.position,
              ...(t.font_size ? { font_size: t.font_size } : {}),
              ...(t.color ? { color: t.color } : {}),
              ...(t.border_color ? { border_color: t.border_color } : {}),
              ...(t.vertical != null ? { vertical: t.vertical } : {}),
              ...(t.offset != null ? { offset: t.offset } : {}),
            }))
          : undefined,
      });
      message.success(res.message);
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动切片失败');
    } finally {
      setRunning(false);
    }
  };

  const showOutputs = async (taskId: string) => {
    setCurrentTask(taskId);
    try {
      const list = await sliceApi.getOutputs(taskId);
      setOutputs(list);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取输出失败');
    }
  };

  const deleteTask = async (taskId: string) => {
    try {
      const res = await sliceApi.delete(taskId);
      message.success(res.message);
      if (currentTask === taskId) {
        setCurrentTask(null);
        setOutputs([]);
      }
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除任务失败');
    }
  };

  // ─── 图片角标管理 ──────────────────────────────────
  const uploadBadgeFile = async (file: File) => {
    setBadgeUploading(true);
    try {
      const res = await sliceApi.uploadBadge(file);
      const preview = URL.createObjectURL(file);
      setBadges((prev) => [
        ...prev,
        {
          file_key: res.file_key,
          position: 'top-left',
          name: res.file_name,
          preview,
        },
      ]);
      message.success(`角标「${res.file_name}」已添加`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '角标上传失败');
    } finally {
      setBadgeUploading(false);
    }
    return false; // 阻止 Upload 默认提交
  };

  const updateBadge = (index: number, patch: Partial<BadgeItem>) => {
    setBadges((prev) => prev.map((b, i) => (i === index ? { ...b, ...patch } : b)));
  };

  const removeBadge = (index: number) => {
    setBadges((prev) => prev.filter((_, i) => i !== index));
  };

  // ─── 固定文字角标（文字版角标）管理 ──────────────────
  const addTextOverlay = () => {
    setTextOverlays((prev) => [
      ...prev,
      { id: `tov_${Date.now()}_${prev.length}`, text: '', position: 'bottom-left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: 10 },
    ]);
  };
  const updateTextOverlay = (index: number, patch: Partial<TextOverlayItem>) => {
    setTextOverlays((prev) => prev.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  };
  const removeTextOverlay = (index: number) => {
    setTextOverlays((prev) => prev.filter((_, i) => i !== index));
  };

  // ─── 转横屏开关联动 ASR 字幕 + 固定文字 ─────────────
  // 转横屏开启时，默认同时开启 ASR 字幕（字号 45、自定义样式字体色 #EDD736），
  // 并按样图预置三处固定文字（右上角品牌黄字/左下角/最左侧竖排标题），
  // 用户可手动编辑、删除或调整。
  // 预置三处固定文字（按样图规格）：右上角品牌字、左下角推广字、最左侧竖排标题
  const applyDefaultTextOverlays = () => {
    const preset: Array<TextOverlayItem & { id: string }> = [
      { id: `tov_preset_tr`, text: '热门短剧', position: 'top-right', font_size: 40, color: '#EDD736', border_color: '#000000', vertical: false, offset: 10 },
      { id: `tov_preset_bl`, text: '免费热门短剧', position: 'bottom-left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: 10 },
      { id: `tov_preset_l`, text: '本故事纯属虚构', position: 'left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: true, offset: 10 },
    ];
    setTextOverlays((prev) => {
      const exists = (position: string, text: string) =>
        prev.some((t) => t.position === position && t.text === text);
      const added = preset.filter((p) => !exists(p.position, p.text));
      return added.length > 0 ? [...prev, ...added] : prev;
    });
  };
  const handleVert2horizToggle = (on: boolean) => {
    setVert2horizEnabled(on);
    if (on) {
      // 转横屏开启时默认开启字幕并套用默认参数
      setSubtitleEnabled(true);
      setSubtitleFontSize(30);
      setSubtitleSpacing(0);
      setSubtitleStyle('custom');
      setSubtitleColor('#EDD736');
      // 固定文字开关默认开启
      setTextOverlayEnabled(true);
      // 默认预置三处固定文字（右上角/左下角/最左侧竖排）
      applyDefaultTextOverlays();
    }
  };

  // ─── 总体进度计算 ──────────────────────────────────
  const runningTasks = tasks.filter((t) => t.status === 'running' || t.status === 'pending');
  const completedTasks = tasks.filter((t) => t.status === 'completed');
  const failedTasks = tasks.filter((t) => t.status === 'failed');
  const cancelledTasks = tasks.filter((t) => t.status === 'cancelled');

  // 当前正在运行的任务的平均进度
  const averageProgress = runningTasks.length > 0
    ? Math.round(runningTasks.reduce((sum, t) => sum + (t.progress || 0), 0) / runningTasks.length)
    : 0;

  // 总任务进度（所有非取消任务的进度加权平均）
  const activeTasks = tasks.filter((t) => t.status !== 'cancelled');
  const totalProgress = activeTasks.length > 0
    ? Math.round(activeTasks.reduce((sum, t) => {
        if (t.status === 'completed') return sum + 100;
        if (t.status === 'failed') return sum + 100; // 失败的也算完成
        return sum + (t.progress || 0);
      }, 0) / activeTasks.length)
    : 0;

  const hasRunningTask = runningTasks.length > 0;

  // 统计任务耗时：已结束用 completed_at - started_at；运行中/待处理用 now - started_at（实时刷新）
  const formatTaskDuration = (t: SliceTask) => {
    if (!t.started_at) return '-';
    const end = t.completed_at || new Date().toISOString();
    const diff = Math.max(0, (new Date(end).getTime() - new Date(t.started_at).getTime()) / 1000);
    return formatDuration(diff);
  };

  const columns = [
    {
      title: '模式',
      dataIndex: 'mode',
      key: 'mode',
      width: 120,
      render: (m: string) => {
        const help = SLICE_MODE_HELP[m];
        return help ? (
          <Tooltip title={help.desc}>
            <Tag>{help.label}</Tag>
          </Tooltip>
        ) : (
          <Tag>{m || '-'}</Tag>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 160,
      render: (s: string, t: SliceTask) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>
          {(t.status === 'running' || t.status === 'pending') && (
            <Progress
              percent={t.progress || 0}
              size="small"
              style={{ width: 120 }}
              status={t.status === 'pending' ? 'active' : 'active'}
            />
          )}
        </Space>
      ),
    },
    { title: '输出数', dataIndex: 'output_count', key: 'output_count', width: 80, render: (c: number, t: SliceTask) =>
      t.status === 'completed' && c > 0 ? (
        <a style={{ fontSize: 12 }} onClick={(e) => { e.stopPropagation(); navigate(`/episodes/${episodeId}/preview?task=${t.id}`); }}>
          {c} 个 →
        </a>
      ) : (
        <Text style={{ fontSize: 12 }}>{c ?? 0}</Text>
      ),
    },
    {
      title: '执行节点',
      dataIndex: 'node_id',
      key: 'node_id',
      width: 150,
      render: (n: string) => n ? (
        <Space size={4}>
          <DesktopOutlined style={{ fontSize: 12, color: '#1677ff' }} />
          <Text style={{ fontSize: 12 }}>{n}</Text>
        </Space>
      ) : <Text type="secondary" style={{ fontSize: 12 }}>Celery/未知</Text>,
    },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true, render: (e: string) => e ? <ErrorHint error={e} /> : '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160, render: (d: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text> },
    {
      title: '耗时',
      key: 'duration',
      width: 90,
      render: (_: unknown, t: SliceTask) => <Text style={{ fontSize: 12 }}>{formatTaskDuration(t)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 260,
      render: (_: unknown, t: SliceTask) => (
        <Space size="small">
          <Button size="small" onClick={() => showOutputs(t.id)}>查看输出</Button>
          {t.status === 'running' || t.status === 'pending' ? (
            <Popconfirm title="确定取消该任务？" onConfirm={async () => {
              try {
                await sliceApi.cancel(t.id);
                message.success('已取消');
                fetchTasks();
              } catch (err: unknown) {
                message.error(err instanceof Error ? err.message : '取消失败');
              }
            }}>
              <Button size="small" danger icon={<StopOutlined />}>取消</Button>
            </Popconfirm>
          ) : (
            <Popconfirm title="确定重试该任务？" onConfirm={async () => {
              try {
                await sliceApi.retry(t.id);
                message.success('已重新调度');
                fetchTasks();
              } catch (err: unknown) {
                message.error(err instanceof Error ? err.message : '重试失败');
              }
            }}>
              <Button size="small" icon={<ReloadOutlined />}>重试</Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="确定删除该任务？"
            description="将同时删除该任务的输出文件（MinIO 临时资源）"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => deleteTask(t.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 单个下载：先经 axios（自动携带 Authorization token）换取带
  // Content-Disposition: attachment 的 presigned 直链，再触发浏览器下载。
  // 不能直接用 <a href="/api/..."> 导航：浏览器导航不带 token 会 401。
  const downloadOne = async (o: SliceOutput) => {
    if (!o.id) {
      message.warning('暂无下载地址');
      return;
    }
    try {
      const res = await previewApi.download(o.id);
      if (!res?.url) {
        message.warning('暂无下载地址');
        return;
      }
      const a = document.createElement('a');
      a.href = res.url;
      a.download = o.file_name || `output_${o.id}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '下载失败');
    }
  };

  const outputColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name' },
    { title: '大小', dataIndex: 'file_size', key: 'file_size', width: 110, render: (s: number) => formatFileSize(s) },
    { title: '时长', dataIndex: 'duration', key: 'duration', width: 90 },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, o: SliceOutput) => (
        <Space size="small">
          <Button size="small" onClick={() => {
            // presigned_url 已由后端用外部 MinIO endpoint 生成，可直接播放
            if (!o.presigned_url) {
              message.warning('暂无预览地址');
              return;
            }
            window.open(o.presigned_url, '_blank');
          }}>预览</Button>
          <Button size="small" onClick={() => downloadOne(o)}>下载</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${episodeId}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>切片任务</Title>
      </Space>

      {/* ── 总体进度 ── */}
      {tasks.length > 0 && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space wrap>
              <Text strong>总体进度</Text>
              <Tag color="blue">总计: {tasks.length}</Tag>
              <Tag color="processing">运行中: {runningTasks.length}</Tag>
              <Tag color="green">已完成: {completedTasks.length}</Tag>
              <Tag color="red">失败: {failedTasks.length}</Tag>
              {cancelledTasks.length > 0 && <Tag>已取消: {cancelledTasks.length}</Tag>}
            </Space>
            <Progress
              percent={totalProgress}
              status={failedTasks.length > 0 && runningTasks.length === 0 ? 'exception' : hasRunningTask ? 'active' : 'success'}
              strokeColor={totalProgress === 100 && failedTasks.length === 0 ? '#52c41a' : undefined}
              format={(p) => `${p}%`}
            />
            {hasRunningTask && (
              <Space>
                <Text type="secondary">
                  当前 {runningTasks.length} 个任务运行中
                  {runningTasks.length > 0 && `，平均进度 ${averageProgress}%`}
                </Text>
              </Space>
            )}
            {!hasRunningTask && completedTasks.length === tasks.length && tasks.length > 0 && (
              <Alert
                type="success"
                showIcon
                icon={<CheckCircleOutlined />}
                message="所有切片任务已完成"
                style={{ marginBottom: 0 }}
              />
            )}
          </Space>
        </Card>
      )}

      {/* ── 新建任务 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Cascader
            value={mode === 'dedupe' ? ['dedupe', dedupePreset || 'standard'] : [mode]}
            options={SLICE_MODE_OPTIONS}
            onChange={(val: (string | number)[]) => {
              const v = (val ?? []).map(String);
              if (v[0] === 'dedupe') {
                setMode('dedupe');
                setDedupePreset(v[1] || 'standard');
              } else if (v[0]) {
                setMode(v[0]);
              }
            }}
            displayRender={(labels: string[]) => labels.join(' · ')}
            placeholder="选择切片模式"
            style={{ width: 180 }}
          />
          <Tooltip title={SLICE_MODE_HELP[mode]?.desc}>
            <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
          </Tooltip>
          <Text type="secondary" style={{ fontSize: 12 }}>{SLICE_MODE_HELP[mode]?.desc}</Text>
          <Select value={engine} onChange={setEngine} style={{ width: 130 }}
            options={[
              { value: 'worker', label: 'Worker 节点' },
              { value: 'celery', label: 'Celery 队列' },
            ]}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {engine === 'worker' ? '分布式 Worker 节点执行' : 'Celery 队列（回退）'}
          </Text>
          {/* 去重高级配置：仅在去重模式显示，逐项手动覆盖各去重手段 */}
          {mode === 'dedupe' && (
            <>
              <Button size="small" icon={<SettingOutlined />} onClick={() => setDedupeManualOpen(true)}>去重高级配置</Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {Object.keys(dedupeManual).length > 0 ? '已启用手动配置' : '跟随所选档位'}
              </Text>
            </>
          )}
          {/* 竖屏转横屏智能裁切开关 */}
          <Space wrap align="center" size={8}>
            <Switch
              size="small"
              checked={vert2horizEnabled}
              onChange={handleVert2horizToggle}
              checkedChildren="转横屏开"
              unCheckedChildren="转横屏"
            />
            {vert2horizEnabled && (
              <Button size="small" icon={<SettingOutlined />} onClick={() => setVert2horizModalOpen(true)}>配置</Button>
            )}
          </Space>

          {/* 竖屏转横屏设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="竖屏转横屏配置"
            open={vert2horizModalOpen}
            onCancel={() => setVert2horizModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setVert2horizModalOpen(false)}>完成</Button>
            )}
            width={540}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>裁切模式</Text>
                <Select
                  size="small"
                  style={{ width: 140 }}
                  value={vert2horizMode}
                  onChange={setVert2horizMode}
                  options={[
                    { value: 'fixed', label: '固定裁切（快）' },
                    { value: 'dynamic', label: '动态跟踪（准）' },
                  ]}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>固定裁切一遍 ffmpeg 快速稳定；动态跟踪逐帧检测人脸确保人物不出画</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>输出分辨率</Text>
                <Input
                  size="small"
                  style={{ width: 130 }}
                  value={vert2horizOutputSize}
                  onChange={(e) => setVert2horizOutputSize(e.target.value)}
                  placeholder="1280x720"
                />
                <Text strong style={{ fontSize: 13 }}>裁切比例</Text>
                <InputNumber
                  size="small"
                  min={0.1}
                  max={1}
                  step={0.05}
                  value={vert2horizRatio}
                  onChange={(v) => setVert2horizRatio(v ?? 0.5625)}
                  style={{ width: 80 }}
                  addonBefore="比例"
                />
                <Text type="secondary" style={{ fontSize: 12 }}>横屏目标宽高比（16:9 对应约 0.5625）</Text>
              </Space>
              {vert2horizMode === 'dynamic' && (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap align="center" size={8}>
                    <Tooltip title="人脸检测间隔帧数">
                      <InputNumber
                        size="small"
                        min={1}
                        max={30}
                        value={vert2horizDetectInterval}
                        onChange={(v) => setVert2horizDetectInterval(v ?? 2)}
                        style={{ width: 100 }}
                        addonBefore="间隔(帧)"
                      />
                    </Tooltip>
                    <Tooltip title="平滑窗口大小（帧）">
                      <InputNumber
                        size="small"
                        min={1}
                        max={60}
                        value={vert2horizSmoothWindow}
                        onChange={(v) => setVert2horizSmoothWindow(v ?? 15)}
                        style={{ width: 100 }}
                        addonBefore="平滑(帧)"
                      />
                    </Tooltip>
                  </Space>
                  <Space wrap align="center" size={8}>
                    <Tooltip title="最小移动阈值(px)：越大越稳、越小越跟手">
                      <InputNumber
                        size="small"
                        min={0}
                        max={30}
                        value={vert2horizMinStep}
                        onChange={(v) => setVert2horizMinStep(v ?? 5)}
                        style={{ width: 100 }}
                        addonBefore="阈值(px)"
                      />
                    </Tooltip>
                  </Space>
                </Space>
              )}
            </Space>
          </Modal>

          {/* 去重高级配置弹窗：手动逐项配置各去重手段 */}
          <Modal
            title="去重高级配置"
            open={dedupeManualOpen}
            onCancel={() => setDedupeManualOpen(false)}
            onOk={() => setDedupeManualOpen(false)}
            okText="完成"
            cancelText="取消"
            width={520}
          >
            <DedupeManualConfig value={dedupeManual} onChange={setDedupeManual} />
          </Modal>

          {/* ── 图片角标（多角标，全程叠加）── */}
          <Upload
            accept="image/*"
            showUploadList={false}
            beforeUpload={uploadBadgeFile}
            disabled={badgeUploading}
          >
            <Button size="small" icon={<UploadOutlined />} loading={badgeUploading}>
              添加角标图片
            </Button>
          </Upload>
          <Tooltip title="可上传多张图片作为角标，全程叠加在视频指定位置">
            <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
          </Tooltip>
          <Tooltip title="角标默认尺寸（px），所有角标未单独设置宽度时的统一宽度；留空=保持原图尺寸">
            <InputNumber
              size="small"
              min={0}
              max={800}
              placeholder="默认尺寸"
              value={badgeDefaultWidth || undefined}
              onChange={(v) => setBadgeDefaultWidth(v ?? 0)}
              style={{ width: 100 }}
              addonAfter="px"
            />
          </Tooltip>
          {badges.length > 0 && (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {badges.map((b, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <AntImage src={b.preview} width={40} height={40} style={{ objectFit: 'contain', borderRadius: 4, border: '1px solid #eee' }} />
                  <Text style={{ fontSize: 12 }}>{b.name}</Text>
                  <Select
                    size="small"
                    style={{ width: 90 }}
                    value={b.position}
                    onChange={(v) => updateBadge(i, { position: v })}
                    options={BADGE_POSITIONS}
                  />
                  <Tooltip title="角标宽度（px），留空=使用默认尺寸/原图尺寸">
                    <InputNumber
                      size="small"
                      min={10}
                      max={800}
                      placeholder="宽"
                      value={b.width}
                      onChange={(v) => updateBadge(i, { width: v ?? undefined })}
                      style={{ width: 80 }}
                    />
                  </Tooltip>
                  <Tooltip title="到视频边缘的偏移量（px），默认 10">
                    <InputNumber
                      size="small"
                      min={0}
                      max={500}
                      placeholder="偏移"
                      value={b.offset}
                      onChange={(v) => updateBadge(i, { offset: v ?? undefined })}
                      style={{ width: 80 }}
                    />
                  </Tooltip>
                  <Tooltip title="角标透明度（0~1），默认 1 不透明">
                    <InputNumber
                      size="small"
                      min={0}
                      max={1}
                      step={0.05}
                      placeholder="透明"
                      value={b.opacity}
                      onChange={(v) => updateBadge(i, { opacity: v ?? undefined })}
                      style={{ width: 80 }}
                    />
                  </Tooltip>
                  <Button size="small" type="text" danger icon={<DelIcon />} onClick={() => removeBadge(i)} />
                </div>
              ))}
            </Space>
          )}

          {/* ── 固定文字角标（文字版角标，最左侧/左下角/右上角等）── */}
          <Space wrap align="center" size={8}>
            <Switch size="small" checked={textOverlayEnabled} onChange={setTextOverlayEnabled} />
            <Text strong style={{ fontSize: 12 }}>固定文字</Text>
            <Tooltip title="开启后在视频指定位置叠加固定文字（无需上传图片）：最左侧（竖排）/左下角/右上角等，全程覆盖。开启后点击右侧「设置文字」按钮配置文字内容、字号、颜色等。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
            {textOverlayEnabled && (
              <Button size="small" icon={<SettingOutlined />} onClick={() => setTextOverlayModalOpen(true)}>设置文字</Button>
            )}
          </Space>

          {/* 固定文字设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="固定文字设置"
            open={textOverlayModalOpen}
            onCancel={() => setTextOverlayModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setTextOverlayModalOpen(false)}>完成</Button>
            )}
            width={620}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Button size="small" icon={<PlusOutlined />} onClick={addTextOverlay}>添加固定文字</Button>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  在视频指定位置叠加固定文字，全程覆盖。文字内容、字号、颜色可自定义；最左侧常用竖排。
                </Text>
              </Space>
              {textOverlays.length > 0 ? (
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {textOverlays.map((t, i) => (
                    <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
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
                        options={BADGE_POSITIONS}
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
                      <Button size="small" type="text" danger icon={<DelIcon />} onClick={() => removeTextOverlay(i)} />
                    </div>
                  ))}
                </Space>
              ) : (
                <Alert type="info" showIcon message="暂无固定文字，点击上方「添加固定文字」新增。" />
              )}
            </Space>
          </Modal>

          {/* ── ASR 字幕烧录（转横屏开启时默认开启）── */}
          <Space wrap align="center" size={8}>
            <Switch size="small" checked={subtitleEnabled} onChange={setSubtitleEnabled} />
            <Text strong style={{ fontSize: 12 }}>ASR 字幕</Text>
            <Tooltip title="开启后对源视频做语音识别（ASR），并把识别到的台词烧录到每个切片成品上。转横屏开启时默认开启。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
            {subtitleEnabled && (
              <Button size="small" icon={<SettingOutlined />} onClick={() => setSubtitleModalOpen(true)}>设置字幕</Button>
            )}
          </Space>

          {/* 字幕设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="字幕设置"
            open={subtitleModalOpen}
            onCancel={() => setSubtitleModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setSubtitleModalOpen(false)}>完成</Button>
            )}
            width={480}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>字幕字号</Text>
                <InputNumber
                  size="small"
                  min={10}
                  max={60}
                  step={1}
                  value={subtitleFontSize}
                  onChange={(v) => setSubtitleFontSize(v ?? 30)}
                  style={{ width: 100 }}
                  addonAfter="px"
                />
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>字幕字间距</Text>
                <InputNumber
                  size="small"
                  min={-5}
                  max={20}
                  step={1}
                  value={subtitleSpacing}
                  onChange={(v) => setSubtitleSpacing(v ?? 0)}
                  style={{ width: 100 }}
                  addonAfter="px"
                />
                <Text type="secondary" style={{ fontSize: 12 }}>越小越紧凑</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>字幕样式</Text>
                <Radio.Group
                  size="small"
                  value={subtitleStyle}
                  onChange={(e) => setSubtitleStyle(e.target.value)}
                >
                  <Radio.Button value="default">默认（白字黑边带底色）</Radio.Button>
                  <Radio.Button value="custom">自定义（无底色）</Radio.Button>
                </Radio.Group>
              </Space>
              {subtitleStyle === 'custom' && (
                <Space wrap align="center" size={8}>
                  <Text strong style={{ fontSize: 12 }}>字体颜色</Text>
                  <ColorPicker
                    value={subtitleColor}
                    onChange={(c) => setSubtitleColor(c.toHexString())}
                    showText
                    size="small"
                  />
                  <Text strong style={{ fontSize: 12 }}>边框颜色</Text>
                  <ColorPicker
                    value={subtitleBorderColor}
                    onChange={(c) => setSubtitleBorderColor(c.toHexString())}
                    showText
                    size="small"
                  />
                </Space>
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                字幕仅在说话时显示，静音/停顿自动隐藏；默认白字黑描边，自定义样式无底色更清爽。
              </Text>
            </Space>
          </Modal>

          {/* ── 源视频字幕打码（去片源自带字幕，独立开关）── */}
          <Space wrap align="center" size={8}>
            <Switch size="small" checked={subtitleMaskEnabled} onChange={setSubtitleMaskEnabled} />
            <Text strong style={{ fontSize: 12 }}>源字幕打码</Text>
            <Tooltip title="把片源自带的字幕去字幕/打码（独立开关，与 ASR 字幕无关）。默认自动检测字幕位置，样式为去水印（智能插值），仅在有源字幕的时间段生效。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
            {subtitleMaskEnabled && (
              <Button size="small" icon={<SettingOutlined />} onClick={() => setSubtitleMaskModalOpen(true)}>设置打码</Button>
            )}
          </Space>

          {/* 源字幕打码设置弹窗 */}
          <Modal
            title="源字幕打码设置"
            open={subtitleMaskModalOpen}
            onCancel={() => setSubtitleMaskModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setSubtitleMaskModalOpen(false)}>完成</Button>
            )}
            width={480}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>打码样式</Text>
                <Radio.Group
                  size="small"
                  value={subtitleMaskStyle}
                  onChange={(e) => setSubtitleMaskStyle(e.target.value)}
                >
                  <Radio.Button value="delogo">去水印</Radio.Button>
                  <Radio.Button value="mosaic">马赛克</Radio.Button>
                  <Radio.Button value="blur">模糊</Radio.Button>
                  <Radio.Button value="fill">纯色块</Radio.Button>
                </Radio.Group>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>区域宽度</Text>
                <InputNumber
                  size="small"
                  min={0.1}
                  max={1}
                  step={0.05}
                  value={subtitleMaskWidthRatio}
                  onChange={(v) => setSubtitleMaskWidthRatio(v ?? 0.9)}
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>相对画面宽（0.9）</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>区域高度</Text>
                <InputNumber
                  size="small"
                  min={0.02}
                  max={0.5}
                  step={0.01}
                  value={subtitleMaskHeightRatio}
                  onChange={(v) => setSubtitleMaskHeightRatio(v ?? 0.12)}
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>相对画面高（0.12）</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 12 }}>距底边</Text>
                <InputNumber
                  size="small"
                  min={0}
                  max={0.5}
                  step={0.01}
                  value={subtitleMaskBottomRatio}
                  onChange={(v) => setSubtitleMaskBottomRatio(v ?? 0.02)}
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>相对画面高（0.02）</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Switch size="small" checked={subtitleMaskTemporal} onChange={setSubtitleMaskTemporal} />
                <Text strong style={{ fontSize: 12 }}>精细化（只在出现时打码）</Text>
                <Tooltip title="开启后逐帧检测字幕/水印实际出现的时段，只在出现时打码，画面其余时间零改动（处理较慢但更精细）；关闭则按 SRT 时间轴或全程打码（快）。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
              </Space>
              <Space wrap align="center" size={8}>
                <Switch
                  size="small"
                  checked={subtitleMaskSpatial}
                  disabled={!subtitleMaskTemporal}
                  onChange={setSubtitleMaskSpatial}
                />
                <Text strong style={{ fontSize: 12, opacity: subtitleMaskTemporal ? 1 : 0.4 }}>仅字幕显示区域打码</Text>
                <Tooltip title="需开启「精细化」后才能开启。开启后，在每个字幕出现时段内只对字幕文字实际占用的那部分横向区域打码，而不把整条横带都盖住（更精细，处理更慢）。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {subtitleMaskTemporal
                  ? '精细化：只在字幕/水印实际出现的时段打码，其余画面不动（推荐）。'
                  : '快速：在检测出的字幕区域全程（至始至终）打码，速度快。'}
              </Text>
            </Space>
          </Modal>

          {/* 动态文字水印开关（置于配置项最后） */}
          <Space wrap align="center" size={8}>
            <Switch
              size="small"
              checked={watermarkEnabled}
              onChange={setWatermarkEnabled}
              checkedChildren="水印开"
              unCheckedChildren="水印"
            />
            <Text strong style={{ fontSize: 12 }}>动态文字水印</Text>
            {watermarkEnabled && (
              <Button size="small" icon={<SettingOutlined />} onClick={() => setWatermarkModalOpen(true)}>配置</Button>
            )}
          </Space>

          {/* 动态文字水印设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="动态文字水印配置"
            open={watermarkModalOpen}
            onCancel={() => setWatermarkModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setWatermarkModalOpen(false)}>完成</Button>
            )}
            width={480}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>水印文字</Text>
                <Input
                  size="small"
                  style={{ width: 260 }}
                  placeholder="水印文字（留空=标题+日期）"
                  value={watermarkText}
                  onChange={(e) => setWatermarkText(e.target.value)}
                />
              </Space>
              <Space wrap align="center" size={8}>
                <Tooltip title="水印字号">
                  <InputNumber
                    size="small"
                    min={12}
                    max={120}
                    value={watermarkFontSize}
                    onChange={(v) => setWatermarkFontSize(v ?? 28)}
                    style={{ width: 90 }}
                    addonBefore="字号"
                  />
                </Tooltip>
                <Tooltip title="水印透明度">
                  <InputNumber
                    size="small"
                    min={5}
                    max={100}
                    value={Math.round(watermarkOpacity * 100)}
                    onChange={(v) => setWatermarkOpacity((v ?? 50) / 100)}
                    style={{ width: 110 }}
                    addonBefore="透明"
                    addonAfter="%"
                  />
                </Tooltip>
                <Text strong style={{ fontSize: 13 }}>位置</Text>
                <Select
                  size="small"
                  style={{ width: 80 }}
                  value={watermarkPosition}
                  onChange={setWatermarkPosition}
                  options={[
                    { value: 'bottom', label: '底部' },
                    { value: 'top', label: '顶部' },
                  ]}
                />
              </Space>
            </Space>
          </Modal>

          <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runSlice}>新建切片任务</Button>
          <Button icon={<ReloadOutlined />} onClick={() => fetchTasks()}>刷新</Button>
        </Space>
      </Card>

      {/* ── 任务列表 ── */}
      <Card size="small" title="任务列表" style={{ marginBottom: 16 }}>
        <Table rowKey="id" columns={columns} dataSource={tasks} loading={loading} pagination={false} size="small" scroll={{ x: 1190 }} />
      </Card>

      {currentTask && (
        <Card size="small" title={`输出文件（任务 ${currentTask}）`}>
          <Table rowKey="id" columns={outputColumns} dataSource={outputs} pagination={false} size="small" scroll={{ x: 560 }} />
        </Card>
      )}
    </div>
  );
};

export default SliceTasks;