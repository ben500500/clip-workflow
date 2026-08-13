import React, { useEffect, useRef, useState } from 'react';
import {
  Card, Button, Space, Typography, Spin, Alert, Breadcrumb, Descriptions, Tag, message, Select, Row, Col, Progress,
  Steps, InputNumber, Tooltip, Popconfirm, Switch, Slider, Input, Table, Upload, Image as AntImage, Radio, ColorPicker,
  Checkbox, Modal, Cascader,
} from 'antd';
import {
  ArrowLeftOutlined, ThunderboltOutlined, RadarChartOutlined, ScissorOutlined,
  CheckCircleOutlined, ClockCircleOutlined, InfoCircleOutlined, PlayCircleOutlined,
  UploadOutlined, DeleteOutlined as DelIcon, PlusOutlined, SettingOutlined, StopOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { autoclipApi } from '../api/autoclip';
import { intervalApi } from '../api/intervals';
import { sliceApi, type BadgeItem, type TextOverlayItem } from '../api/slice';
import ErrorHint from '../components/ErrorHint';
import type { AutoClipRunRecord, ClipCandidate, Episode, IntervalHistoryItem, SliceTask } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text, Paragraph } = Typography;

// ─── 切片模式说明 ─────────────────────────────────────
const SLICE_MODE_HELP: Record<string, { label: string; desc: string; detail: string }> = {
  fast: {
    label: '快速模式',
    desc: '直接按选点结果切割，不做去重处理',
    detail: '根据已通过的片段审核结果，直接将视频切割成多个片段输出。速度最快，但不会处理重复内容，适合初次出片测试。',
  },
  dedupe: {
    label: '去重模式',
    desc: '切割时进行画面去重处理',
    detail: '在切割的同时对每个片段进行画面去重处理，采用「空间变换（缩放裁切/镜像）+ 时域变换（变速）+ 色彩变换（降饱和/复古偏色）+ 质感叠加（老电视噪点/扫描线/暗角）」四层组合，拉开与原素材的帧级特征/色彩直方图/时域指纹距离。可选轻/标准/重三档，标准档为默认效果。适用于需要批量发布到多个平台的场景，降低平台查重风险。',
  },
  scrub: {
    label: '挖洞模式',
    desc: '在去重基础上随机挖洞',
    detail: '在去重模式的基础上，进一步对片段中随机位置进行微小的画面挖洞处理（替换为纯色帧），使每个输出片段的指纹更加独特。适合高频发布场景，有效降低平台查重处罚。',
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

// ─── 工作流步骤定义（可点击跳转对应界面） ─────────────
const WORKFLOW_STEPS = [
  { key: 'upload', title: '上传视频', description: '上传原始视频素材', path: '' },
  { key: 'autoclip', title: 'AI 智能选点', description: '自动分析并推荐精彩片段', path: '' },
  { key: 'review', title: '片段审核', description: '审核并调整选点结果', path: '/clips' },
  { key: 'intervals', title: '区间检测', description: '检测片尾/静止/水印区域', path: '/intervals' },
  { key: 'slice', title: '切片执行', description: '按配置切割输出成品', path: '/slice' },
  { key: 'preview', title: '成品预览', description: '预览并下载切片结果', path: '/preview' },
];

// ─── 区间检测模式中文展示 ─────────────────────────────
const DETECT_MODE_LABELS: Record<string, string> = {
  credits: '片尾字幕',
  static: '静止画面',
  watermark: '水印',
};

// ─── 图片角标位置选项（七位，含最左侧） ─────────────
const BADGE_POSITIONS = [
  { value: 'left', label: '最左侧' },
  { value: 'top-left', label: '左上' },
  { value: 'top-center', label: '中上' },
  { value: 'top-right', label: '右上' },
  { value: 'bottom-left', label: '左下' },
  { value: 'bottom-center', label: '中下' },
  { value: 'bottom-right', label: '右下' },
];

// ─── 一键切片配置预设（可自定义所有默认值并保存多套） ───
interface SlicePreset {
  id: string;
  name: string;
  // 竖屏转横屏
  vert2horiz_enabled: boolean;
  vert2horiz_mode: 'fixed' | 'dynamic';
  vert2horiz_ratio: number;
  vert2horiz_output_size: string;
  vert2horiz_detect_interval: number;
  vert2horiz_smooth_window: number;
  vert2horiz_min_step: number;
  vert2horiz_face_margin: number;
  // ASR 字幕
  subtitle_enabled: boolean;
  subtitle_font_ratio: number;
  subtitle_spacing: number;
  subtitle_style: 'default' | 'custom';
  subtitle_color: string;
  subtitle_border_color: string;
  // 源视频字幕打码
  subtitle_mask_enabled: boolean;
  subtitle_mask_style: 'delogo' | 'mosaic' | 'blur' | 'fill';
  subtitle_mask_width_ratio: number;
  subtitle_mask_height_ratio: number;
  subtitle_mask_bottom_ratio: number;
  // 固定文字
  text_overlay_enabled: boolean;
  text_overlays: TextOverlayItem[];
  // 动态文字水印
  watermark_enabled: boolean;
  watermark_text: string;
  watermark_font_size: number;
  watermark_opacity: number;
  watermark_position: string;
  // 图片角标默认尺寸
  badge_default_width: number;
}

const SLICE_PRESET_STORAGE_KEY = 'slice_presets_v1';

// 默认配置（在默认项基础上：竖屏转横屏开 / ASR字幕开 / 固定文字开）
const DEFAULT_SLICE_PRESET: SlicePreset = {
  id: 'default',
  name: '默认配置',
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
  subtitle_style: 'custom',
  subtitle_color: '#EDD736',
  subtitle_border_color: '#000000',
  subtitle_mask_enabled: false,
  subtitle_mask_style: 'delogo',
  subtitle_mask_width_ratio: 0.9,
  subtitle_mask_height_ratio: 0.12,
  subtitle_mask_bottom_ratio: 0.02,
  text_overlay_enabled: true,
  text_overlays: [
    { text: '热门短剧', position: 'top-right', font_size: 40, color: '#EDD736', border_color: '#000000', vertical: false, offset: 10 },
    { text: '免费热门短剧', position: 'bottom-left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: 10 },
    { text: '本故事纯属虚构', position: 'left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: true, offset: 10 },
  ],
  watermark_enabled: false,
  watermark_text: '',
  watermark_font_size: 28,
  watermark_opacity: 0.5,
  watermark_position: 'bottom',
  badge_default_width: 0,
};

const EpisodeDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const episodeId = id || '';

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detectMode, setDetectMode] = useState('credits');
  const [sliceMode, setSliceMode] = useState('fast');
  // 去重模式档位：轻/标准/重（老电视质感去重强度，默认标准档）
  const [dedupePreset, setDedupePreset] = useState<string>('standard');
  // ── 切片自定义文字水印开关与参数 ──
  const [watermarkEnabled, setWatermarkEnabled] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [watermarkFontSize, setWatermarkFontSize] = useState(28);
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.5);
  const [watermarkPosition, setWatermarkPosition] = useState('bottom');
  // 动态文字水印设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [watermarkModalOpen, setWatermarkModalOpen] = useState(false);
  // ── 竖屏转横屏智能裁切开关与参数 ──
  const [vert2horizEnabled, setVert2horizEnabled] = useState(false);
  const [vert2horizMode, setVert2horizMode] = useState<'fixed' | 'dynamic'>('dynamic');
  const [vert2horizRatio, setVert2horizRatio] = useState(0.5625);
  const [vert2horizOutputSize, setVert2horizOutputSize] = useState('1280x720');
  const [vert2horizDetectInterval, setVert2horizDetectInterval] = useState(2);
  const [vert2horizSmoothWindow, setVert2horizSmoothWindow] = useState(15);
  // ── 图片角标：多角标、六角位置、宽度/偏移/透明度，全程叠加 ──
  const [badges, setBadges] = useState<Array<BadgeItem & { name: string; preview: string }>>([]);
  const [badgeUploading, setBadgeUploading] = useState(false);
  // 角标默认尺寸（px）：角标未单独设 width 时生效；0=保持原图尺寸
  const [badgeDefaultWidth, setBadgeDefaultWidth] = useState<number>(0);
  // 动态模式最小移动阈值（px）：越大越稳、越小越跟手
  const [vert2horizMinStep, setVert2horizMinStep] = useState(5);
  // 动态模式人脸舒适区边距比例（占人脸高度，默认 0.30）：人脸头像大部分仍在画面内时保持窗口不动，抑制频繁移动抖动
  const [vert2horizFaceMargin, setVert2horizFaceMargin] = useState(0.30);
  // 竖屏转横屏设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [vert2horizModalOpen, setVert2horizModalOpen] = useState(false);
  // ── ASR 字幕烧录开关 ──
  const [subtitleEnabled, setSubtitleEnabled] = useState(false);
  // 字幕字号（相对输出视频高度的比例，默认 0.30→FontSize 30；转横屏开启时默认套用，用户可调）
  const [subtitleFontRatio, setSubtitleFontRatio] = useState(0.30);
  // 字幕字间距（ASS Spacing 像素，默认 0 更紧凑；调小/负值让字幕文字更紧凑，调大则字距变宽）
  const [subtitleSpacing, setSubtitleSpacing] = useState(0);
  // 字幕样式：default（白字黑边+半透明黑底）/ custom（自定义字体色+边框色，无底色）
  const [subtitleStyle, setSubtitleStyle] = useState<'default' | 'custom'>('custom');
  // 自定义样式的字体色 / 边框色（CSS 十六进制，默认 #EDD736 黄 / 黑边）
  const [subtitleColor, setSubtitleColor] = useState('#EDD736');
  const [subtitleBorderColor, setSubtitleBorderColor] = useState('#000000');
  // 字幕设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [subtitleModalOpen, setSubtitleModalOpen] = useState(false);
  // 上传的字幕文件（MinIO key + 文件名）：提供后直接应用该字幕，跳过 ASR 识别
  const [subtitleFileKey, setSubtitleFileKey] = useState<string | null>(null);
  const [subtitleFileName, setSubtitleFileName] = useState<string | null>(null);
  const [subtitleUploading, setSubtitleUploading] = useState(false);
  // ── 源视频字幕打码 ──
  const [subtitleMaskEnabled, setSubtitleMaskEnabled] = useState(false);
  const [subtitleMaskStyle, setSubtitleMaskStyle] = useState<'delogo' | 'mosaic' | 'blur' | 'fill'>('delogo');
  const [subtitleMaskWidthRatio, setSubtitleMaskWidthRatio] = useState(0.9);
  const [subtitleMaskHeightRatio, setSubtitleMaskHeightRatio] = useState(0.12);
  const [subtitleMaskBottomRatio, setSubtitleMaskBottomRatio] = useState(0.02);
  const [subtitleMaskModalOpen, setSubtitleMaskModalOpen] = useState(false);
  // ── 固定文字角标（文字版角标，无需上传图片）──
  const [textOverlays, setTextOverlays] = useState<Array<TextOverlayItem & { id: string }>>([]);
  // 固定文字开关：开启后显示「设置文字」按钮，弹窗内集中管理固定文字配置（与字幕设置形式一致）
  const [textOverlayEnabled, setTextOverlayEnabled] = useState(false);
  // 固定文字设置弹窗是否打开（详细配置收进弹窗，节省主界面空间）
  const [textOverlayModalOpen, setTextOverlayModalOpen] = useState(false);
  // ── 一键切片配置预设：多套可保存，自定义所有默认值 ──
  const [presetModalOpen, setPresetModalOpen] = useState(false);
  const [presets, setPresets] = useState<SlicePreset[]>([DEFAULT_SLICE_PRESET]);
  const [activePresetId, setActivePresetId] = useState<string>(DEFAULT_SLICE_PRESET.id);
  const [newPresetName, setNewPresetName] = useState('');
  const [maxClips, setMaxClips] = useState(10);
  const [minScoreThreshold, setMinScoreThreshold] = useState<number | null>(null);
  const [minClipDuration, setMinClipDuration] = useState<number | null>(null);
  const [maxClipDuration, setMaxClipDuration] = useState<number | null>(null);
  // 画面理解（MiniCPM-V 本地视觉模型）：AI 选点时对候选片段抽帧分析画面，辅助打分，默认开启
  const [frameAnalysis, setFrameAnalysis] = useState(true);
  const [autoclipProgress, setAutoclipProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  const [autoclipRunning, setAutoclipRunning] = useState(false);
  const [detectRunning, setDetectRunning] = useState(false);
  const [detectProgress, setDetectProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null; interval_count?: number | null; interval_type?: string | null } | null>(null);
  const [detectResultCount, setDetectResultCount] = useState<number | null>(null);
  const [sliceRunning, setSliceRunning] = useState(false);
  const [sliceProgress, setSliceProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  // 快速转换（跳过 AI 选点/区间检测，整片应用下方配置直接出片，位于「开始切片」旁）
  const [quickConverting, setQuickConverting] = useState(false);
  const [quickProgress, setQuickProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  // 一键切片（免审核直接出片，位于工作台入口）
  const [oneClickSlicing, setOneClickSlicing] = useState(false);
  // 一键切片进度（与普通切片共用轮询逻辑）
  const [oneClickProgress, setOneClickProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);

  const autoclipTimerRef = useRef<number | null>(null);
  const detectTimerRef = useRef<number | null>(null);
  const slicePollTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (autoclipTimerRef.current) {
        window.clearInterval(autoclipTimerRef.current);
      }
      if (detectTimerRef.current) {
        window.clearTimeout(detectTimerRef.current);
      }
      if (slicePollTimerRef.current) {
        window.clearInterval(slicePollTimerRef.current);
      }
    };
  }, []);

  const fetchEpisode = () => {
    setLoading(true);
    projectApi
      .getEpisode(episodeId)
      .then((data) => {
        if (mountedRef.current) setEpisode(data);
      })
      .catch((err: unknown) => {
        if (mountedRef.current) setError(err instanceof Error ? err.message : '获取剧集失败');
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
  };

  // ── 选点/区间检测/切片执行历史（多次执行保留展示） ──
  const [autoclipHistory, setAutoclipHistory] = useState<AutoClipRunRecord[]>([]);
  const [intervalHistory, setIntervalHistory] = useState<IntervalHistoryItem[]>([]);
  const [sliceHistory, setSliceHistory] = useState<SliceTask[]>([]);

  const fetchHistories = async () => {
    if (!episodeId) return;
    try {
      const [ac, iv, st] = await Promise.all([
        autoclipApi.history(episodeId).catch(() => [] as AutoClipRunRecord[]),
        intervalApi.history(episodeId).catch(() => [] as IntervalHistoryItem[]),
        sliceApi.listTasks(episodeId).catch(() => [] as SliceTask[]),
      ]);
      if (mountedRef.current) {
        setAutoclipHistory(ac);
        setIntervalHistory(iv);
        // 切片历史过滤掉 detect_* 内部进度记录
        setSliceHistory(st.filter((t) => !(t.mode && t.mode.startsWith('detect_'))));
      }
    } catch {
      // 历史加载失败不阻塞主流程
    }
  };

  // ── 单独刷新「选点执行历史」（任务进行中用于实时同步状态/进度） ──
  const fetchAutoclipHistory = async () => {
    if (!episodeId) return;
    try {
      const ac = await autoclipApi.history(episodeId);
      if (mountedRef.current) setAutoclipHistory(ac);
    } catch {
      // 忽略
    }
  };

  // ── 单独刷新「区间检测执行历史」 ──
  const fetchIntervalHistory = async () => {
    if (!episodeId) return;
    try {
      const iv = await intervalApi.history(episodeId);
      if (mountedRef.current) setIntervalHistory(iv);
    } catch {
      // 忽略
    }
  };

  // ── 单独刷新「切片执行历史」 ──
  const fetchSliceHistory = async () => {
    if (!episodeId) return;
    try {
      const st = await sliceApi.listTasks(episodeId);
      if (mountedRef.current) {
        setSliceHistory(st.filter((t) => !(t.mode && t.mode.startsWith('detect_'))));
      }
    } catch {
      // 忽略
    }
  };

  // 统计任务耗时：已结束用 completed_at - started_at；运行中/待处理用 now - started_at（实时刷新）
  const formatTaskDuration = (t: SliceTask) => {
    if (!t.started_at) return '-';
    const end = t.completed_at || new Date().toISOString();
    const diff = Math.max(0, (new Date(end).getTime() - new Date(t.started_at).getTime()) / 1000);
    return formatDuration(diff);
  };

  // ── 一键切片配置预设：加载 / 保存 / 应用 ──
  const loadPresets = React.useCallback((): SlicePreset => {
    let toApply: SlicePreset | null = null;
    try {
      const raw = localStorage.getItem(SLICE_PRESET_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
          // 始终保证默认配置在列表头部
          const list = [DEFAULT_SLICE_PRESET, ...parsed.filter((p: SlicePreset) => p.id !== DEFAULT_SLICE_PRESET.id)];
          setPresets(list);
          const savedActive = localStorage.getItem('slice_active_preset');
          const activeId = savedActive && list.some((p) => p.id === savedActive) ? savedActive : DEFAULT_SLICE_PRESET.id;
          setActivePresetId(activeId);
          toApply = list.find((p) => p.id === activeId) || null;
        }
      }
    } catch {
      // 解析失败则保持默认
    }
    return toApply || DEFAULT_SLICE_PRESET;
  }, []);

  const persistPresets = (list: SlicePreset[], activeId: string) => {
    try {
      const withoutDefault = list.filter((p) => p.id !== DEFAULT_SLICE_PRESET.id);
      localStorage.setItem(SLICE_PRESET_STORAGE_KEY, JSON.stringify(withoutDefault));
      localStorage.setItem('slice_active_preset', activeId);
    } catch {
      // 存储失败忽略
    }
  };

  // 收集当前页面切片状态为一套配置
  const collectCurrentPresetConfig = (): SlicePreset => ({
    id: '',
    name: '',
    vert2horiz_enabled: vert2horizEnabled,
    vert2horiz_mode: vert2horizMode,
    vert2horiz_ratio: vert2horizRatio,
    vert2horiz_output_size: vert2horizOutputSize,
    vert2horiz_detect_interval: vert2horizDetectInterval,
    vert2horiz_smooth_window: vert2horizSmoothWindow,
    vert2horiz_min_step: vert2horizMinStep,
    vert2horiz_face_margin: vert2horizFaceMargin,
    subtitle_enabled: subtitleEnabled,
    subtitle_font_ratio: subtitleFontRatio,
    subtitle_spacing: subtitleSpacing,
    subtitle_style: subtitleStyle,
    subtitle_color: subtitleColor,
    subtitle_border_color: subtitleBorderColor,
    subtitle_mask_enabled: subtitleMaskEnabled,
    subtitle_mask_style: subtitleMaskStyle,
    subtitle_mask_width_ratio: subtitleMaskWidthRatio,
    subtitle_mask_height_ratio: subtitleMaskHeightRatio,
    subtitle_mask_bottom_ratio: subtitleMaskBottomRatio,
    text_overlay_enabled: textOverlayEnabled,
    text_overlays: textOverlays.map((t) => ({ text: t.text, position: t.position, font_size: t.font_size, color: t.color, border_color: t.border_color, vertical: t.vertical, offset: t.offset })),
    watermark_enabled: watermarkEnabled,
    watermark_text: watermarkText,
    watermark_font_size: watermarkFontSize,
    watermark_opacity: watermarkOpacity,
    watermark_position: watermarkPosition,
    badge_default_width: badgeDefaultWidth,
  });

  // 将一套配置应用到页面切片状态
  const applyPreset = (p: SlicePreset) => {
    setVert2horizEnabled(p.vert2horiz_enabled);
    setVert2horizMode(p.vert2horiz_mode);
    setVert2horizRatio(p.vert2horiz_ratio);
    setVert2horizOutputSize(p.vert2horiz_output_size);
    setVert2horizDetectInterval(p.vert2horiz_detect_interval);
    setVert2horizSmoothWindow(p.vert2horiz_smooth_window);
    setVert2horizMinStep(p.vert2horiz_min_step);
    setVert2horizFaceMargin(p.vert2horiz_face_margin);
    setSubtitleEnabled(p.subtitle_enabled);
    setSubtitleFontRatio(p.subtitle_font_ratio);
    setSubtitleSpacing(p.subtitle_spacing ?? 0);
    setSubtitleStyle(p.subtitle_style);
    setSubtitleColor(p.subtitle_color);
    setSubtitleBorderColor(p.subtitle_border_color);
    setSubtitleMaskEnabled(p.subtitle_mask_enabled ?? false);
    setSubtitleMaskStyle(p.subtitle_mask_style ?? 'delogo');
    setSubtitleMaskWidthRatio(p.subtitle_mask_width_ratio ?? 0.9);
    setSubtitleMaskHeightRatio(p.subtitle_mask_height_ratio ?? 0.12);
    setSubtitleMaskBottomRatio(p.subtitle_mask_bottom_ratio ?? 0.02);
    setTextOverlayEnabled(p.text_overlay_enabled);
    setTextOverlays(p.text_overlays.map((t) => ({ ...t, id: `tov_preset_${t.position}_${t.text}` })));
    setWatermarkEnabled(p.watermark_enabled);
    setWatermarkText(p.watermark_text);
    setWatermarkFontSize(p.watermark_font_size);
    setWatermarkOpacity(p.watermark_opacity);
    setWatermarkPosition(p.watermark_position);
    setBadgeDefaultWidth(p.badge_default_width);
    setActivePresetId(p.id);
  };

  useEffect(() => {
    // 首次进入默认应用默认配置（竖屏转横屏开 / ASR字幕开 / 固定文字开），
    // 若用户保存过预设则应用上次激活的那套
    const toApply = loadPresets();
    applyPreset(toApply);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadPresets]);

  // 选择预设并应用
  const handleSelectPreset = (id: string) => {
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    applyPreset(preset);
    persistPresets(presets, id);
    message.success(`已应用配置「${preset.name}」`);
  };

  // 保存当前配置为新预设
  const handleSavePreset = () => {
    const name = newPresetName.trim();
    if (!name) {
      message.warning('请先输入配置名称');
      return;
    }
    const current = collectCurrentPresetConfig();
    const id = `preset_${Date.now()}`;
    const newPreset: SlicePreset = { ...current, id, name };
    const list = [...presets.filter((p) => p.id !== DEFAULT_SLICE_PRESET.id), newPreset];
    setPresets([DEFAULT_SLICE_PRESET, ...list]);
    setActivePresetId(id);
    setNewPresetName('');
    persistPresets([DEFAULT_SLICE_PRESET, ...list], id);
    message.success(`已保存配置「${name}」`);
  };

  // 删除自定义预设
  const handleDeletePreset = (id: string) => {
    if (id === DEFAULT_SLICE_PRESET.id) return;
    const list = presets.filter((p) => p.id !== id);
    setPresets(list);
    if (activePresetId === id) {
      setActivePresetId(DEFAULT_SLICE_PRESET.id);
      persistPresets(list, DEFAULT_SLICE_PRESET.id);
    } else {
      persistPresets(list, activePresetId);
    }
    message.success('已删除配置');
  };

  useEffect(() => {
    if (episodeId) fetchEpisode();
    fetchHistories();
  }, [episodeId]);

  // 选点/检测/切片动作触发后刷新历史
  useEffect(() => {
    if (episodeId && (autoclipProgress?.status === 'completed' || autoclipProgress?.status === 'failed')) {
      fetchHistories();
    }
  }, [autoclipProgress?.status]);

  useEffect(() => {
    if (episodeId && (detectProgress?.status === 'completed' || detectProgress?.status === 'failed')) {
      fetchHistories();
    }
  }, [detectProgress?.status]);

  useEffect(() => {
    if (episodeId && (sliceProgress?.status === 'completed' || sliceProgress?.status === 'failed' || sliceProgress?.status === 'cancelled')) {
      fetchHistories();
    }
  }, [sliceProgress?.status]);
  const getCurrentStep = (): number => {
    if (!episode) return 0;
    const status = episode.status;
    // uploaded -> clips_detected -> intervals_detected -> slicing -> completed
    if (status === 'uploaded') return 1;
    if (status === 'clips_detected') return 2;
    if (status === 'intervals_detected') return 3;
    if (status === 'slicing') return 4;
    if (status === 'completed') return 5;
    if (status === 'failed') return 4; // 失败视为停在切片执行步骤
    return 1;
  };

  // ─── 选点任务恢复轮询 ───────────────────────────────
  const resumeAutoclipPolling = async () => {
    try {
      const p = await autoclipApi.progress(episodeId);
      if (p && (p.status === 'pending' || p.status === 'processing' || p.status === 'running')) {
        setAutoclipRunning(true);
        setAutoclipProgress(p);
        autoclipTimerRef.current = window.setInterval(async () => {
          try {
            const prog = await autoclipApi.progress(episodeId);
            if (!mountedRef.current) {
              if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
              return;
            }
            setAutoclipProgress(prog);
            // 任务进行中实时同步「选点执行历史」的状态/进度
            fetchAutoclipHistory();
            if (prog.status === 'completed' || prog.status === 'failed') {
              if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
              autoclipTimerRef.current = null;
              setAutoclipRunning(false);
              if (prog.status === 'completed') {
                message.success('选点分析已完成！请前往「片段审核」查看并确认选点结果');
              } else {
                message.error('选点分析失败');
              }
              fetchEpisode();
              fetchHistories();
            }
          } catch {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            autoclipTimerRef.current = null;
            if (mountedRef.current) setAutoclipRunning(false);
          }
        }, 3000);
      } else if (p && (p.status === 'completed' || p.status === 'failed')) {
        setAutoclipProgress(p);
      }
    } catch {
      // 没有运行中的任务，忽略
    }
  };

  // ─── 区间检测任务轮询 ───────────────────────────────
  const resumeDetectPolling = async () => {
    try {
      const p = await intervalApi.progress(episodeId);
      if (p && (p.status === 'pending' || p.status === 'processing' || p.status === 'running')) {
        setDetectRunning(true);
        setDetectProgress(p);
        detectTimerRef.current = window.setInterval(async () => {
          try {
            const prog = await intervalApi.progress(episodeId);
            if (!mountedRef.current) {
              if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
              return;
            }
            // unknown 表示暂无运行中的检测任务，忽略避免进度条回退/闪烁
            if (prog.status !== 'unknown') {
              setDetectProgress(prog);
              // 任务进行中实时同步「区间检测执行历史」的状态/进度
              fetchIntervalHistory();
            }
            if (prog.status === 'completed' || prog.status === 'failed') {
              if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
              detectTimerRef.current = null;
              setDetectRunning(false);
              if (prog.status === 'completed') {
                setDetectResultCount(prog.interval_count ?? null);
                message.success(prog.interval_count ? `区间检测完成！共检测到 ${prog.interval_count} 个区间` : '区间检测完成！检测结果已自动保存');
              } else {
                message.error('区间检测失败');
              }
              fetchEpisode();
              fetchHistories();
            }
          } catch {
            if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
            detectTimerRef.current = null;
            if (mountedRef.current) setDetectRunning(false);
          }
        }, 3000);
      } else if (p && (p.status === 'completed' || p.status === 'failed')) {
        setDetectProgress(p);
      }
    } catch {
      // 没有运行中的任务，忽略
    }
  };

  // ─── 切片任务进度轮询（从 slice_tasks 表读取最近一次切片任务） ──────────
  const resumeSlicePolling = async () => {
    try {
      const tasks = await sliceApi.listTasks(episodeId);
      const latest = tasks[0];
      if (!latest) return;
      if (latest.status === 'running' || latest.status === 'pending') {
        setSliceRunning(true);
        setSliceProgress({
          status: latest.status === 'pending' ? 'running' : 'running',
          progress: latest.progress || 0,
          message: latest.status === 'pending' ? '切片任务排队中，等待处理…' : `切片任务运行中（${latest.mode}）…`,
        });
        if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
        slicePollTimerRef.current = window.setInterval(async () => {
          try {
            const t = await sliceApi.getTask(latest.id);
            if (!mountedRef.current) {
              if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
              return;
            }
            setSliceProgress({
              status: t.status === 'running' || t.status === 'pending' ? 'running' : t.status || 'unknown',
              progress: t.progress || 0,
              message: t.status === 'running' || t.status === 'pending'
                ? `切片任务运行中（${t.mode || latest.mode}）…`
                : t.status === 'completed'
                  ? '切片任务已完成'
                  : t.status === 'failed'
                    ? `切片失败：${t.error_message || ''}`
                    : t.status || '',
            });
            // 任务进行中实时同步「切片执行历史」的状态/进度
            fetchSliceHistory();
            if (t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled') {
              if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
              slicePollTimerRef.current = null;
              setSliceRunning(false);
              if (t.status === 'completed') {
                message.success('切片已完成！可前往「成品预览」查看结果');
              } else if (t.status === 'failed') {
                message.error(`切片失败：${t.error_message || '未知错误'}`);
              }
              fetchEpisode();
              fetchHistories();
            }
          } catch {
            if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
            slicePollTimerRef.current = null;
            if (mountedRef.current) setSliceRunning(false);
          }
        }, 3000);
      } else if (latest.status === 'completed' || latest.status === 'failed') {
        setSliceProgress({
          status: latest.status,
          progress: latest.progress || (latest.status === 'completed' ? 100 : 0),
          message: latest.status === 'completed' ? '切片任务已完成' : `切片失败：${latest.error_message || ''}`,
        });
      }
    } catch {
      // 没有任务或查询失败，忽略
    }
  };

  useEffect(() => {
    if (episodeId && episode) {
      resumeAutoclipPolling();
      resumeDetectPolling();
      resumeSlicePolling();
    }
  }, [episodeId, episode?.id]);

  // ─── 启动选点 ───────────────────────────────────────
  const runAutoClip = async () => {
    setAutoclipRunning(true);
    setAutoclipProgress({ status: 'pending', progress: 0, message: '正在启动选点任务…' });
    try {
      const res = await autoclipApi.run(episodeId, {
        max_clips: maxClips,
        min_score_threshold: minScoreThreshold ?? undefined,
        min_duration: minClipDuration ?? undefined,
        max_duration: maxClipDuration ?? undefined,
        frame_analysis: frameAnalysis,
      });
      message.success(res.message);
      fetchHistories();
      autoclipTimerRef.current = window.setInterval(async () => {
        try {
          const p = await autoclipApi.progress(episodeId);
          if (!mountedRef.current) {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            return;
          }
          setAutoclipProgress(p);
          // 任务进行中实时同步「选点执行历史」的状态/进度，避免一直停留在排队态
          fetchAutoclipHistory();
          if (p.status === 'completed' || p.status === 'failed') {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            autoclipTimerRef.current = null;
            setAutoclipRunning(false);
            if (p.status === 'completed') {
              message.success('选点分析已完成！请前往「片段审核」查看并确认选点结果');
            } else {
              message.error('选点分析失败');
            }
            fetchEpisode();
            fetchHistories();
          }
        } catch {
          if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
          autoclipTimerRef.current = null;
          if (mountedRef.current) setAutoclipRunning(false);
        }
      }, 3000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动选点失败');
      setAutoclipRunning(false);
      setAutoclipProgress(null);
    }
  };

  // ─── 启动区间检测 ───────────────────────────────────
  const runDetect = async () => {
    setDetectRunning(true);
    setDetectProgress({ status: 'running', progress: 10, message: '正在启动区间检测任务，请稍候…' });
    try {
      const res = await intervalApi.detect(episodeId, detectMode, {});
      const modeLabel = detectMode === 'credits' ? '片尾字幕' : detectMode === 'static' ? '静止画面' : '水印';
      // 更新为更详细的反馈信息，提示用户正在处理中
      setDetectProgress({
        status: 'running',
        progress: 20,
        message: detectMode === 'watermark'
          ? `已提交${modeLabel}检测任务（该模式无自动检测器，完成后可手动添加区间）`
          : `检测任务已提交（${modeLabel}模式），正在分析视频内容…`,
      });
      message.success('检测任务已成功提交，正在后台分析中');
      fetchHistories();
      detectTimerRef.current = window.setInterval(async () => {
        try {
          const p = await intervalApi.progress(episodeId);
          if (!mountedRef.current) {
            if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
            return;
          }
          if (p) {
            // unknown 表示暂无运行中的检测任务，忽略避免进度条回退/闪烁
            if (p.status !== 'unknown') {
              setDetectProgress(p);
              // 任务进行中实时同步「区间检测执行历史」的状态/进度
              fetchIntervalHistory();
            }
            if (p.status === 'completed' || p.status === 'failed') {
              if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
              detectTimerRef.current = null;
              setDetectRunning(false);
              if (p.status === 'completed') {
                setDetectResultCount(p.interval_count ?? null);
                message.success(p.interval_count ? `区间检测完成！共检测到 ${p.interval_count} 个区间` : '区间检测完成！检测结果已自动保存');
              } else {
                message.error('区间检测失败');
              }
              fetchEpisode();
              fetchHistories();
            }
          }
        } catch {
          if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
          detectTimerRef.current = null;
          if (mountedRef.current) setDetectRunning(false);
        }
      }, 3000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动检测失败');
      setDetectRunning(false);
      setDetectProgress(null);
    }
  };

  // ─── 轮询最新切片任务进度（一键切片 / 普通切片共用） ──────────
  const pollLatestSliceProgress = (
    mode: string,
    setRunning: (v: boolean) => void,
    setProgress: (p: { status: string; progress: number; message: string; error_message?: string | null } | null) => void,
  ) => {
    if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
    slicePollTimerRef.current = window.setInterval(async () => {
      try {
        const tasks = await sliceApi.listTasks(episodeId);
        const latest = tasks[0];
        if (!latest) return;
        const t = await sliceApi.getTask(latest.id);
        if (!mountedRef.current) {
          if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
          return;
        }
        setProgress({
          status: t.status === 'running' || t.status === 'pending' ? 'running' : t.status || 'unknown',
          progress: t.progress || 0,
          message: t.status === 'running' || t.status === 'pending'
            ? `切片任务运行中（${t.mode || mode}）…`
            : t.status === 'completed'
              ? '切片任务已完成'
              : t.status === 'failed'
                ? `切片失败：${t.error_message || ''}`
                : t.status || '',
        });
        // 任务进行中实时同步「切片执行历史」的状态/进度
        fetchSliceHistory();
        if (t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled') {
          if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
          slicePollTimerRef.current = null;
          setRunning(false);
          if (t.status === 'completed') {
            message.success('切片已完成！可前往「成品预览」查看结果');
          } else if (t.status === 'failed') {
            message.error(`切片失败：${t.error_message || '未知错误'}`);
          }
          fetchEpisode();
          fetchHistories();
        }
      } catch {
        if (slicePollTimerRef.current) window.clearInterval(slicePollTimerRef.current);
        slicePollTimerRef.current = null;
        if (mountedRef.current) setRunning(false);
      }
    }, 3000);
  };

  // ─── 图片角标管理（上传/更新/删除） ────────────────
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

  // ─── 字幕文件上传（srt/vtt） ────────────────
  const uploadSubtitleFile = async (file: File) => {
    setSubtitleUploading(true);
    try {
      const res = await sliceApi.uploadSubtitle(file);
      setSubtitleFileKey(res.file_key);
      setSubtitleFileName(res.file_name);
      // 上传字幕后自动开启字幕烧录，直接应用该字幕文件
      setSubtitleEnabled(true);
      message.success(`字幕「${res.file_name}」已上传，将直接应用该字幕`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '字幕上传失败');
    } finally {
      setSubtitleUploading(false);
    }
    return false; // 阻止 Upload 默认提交
  };

  const removeSubtitleFile = () => {
    setSubtitleFileKey(null);
    setSubtitleFileName(null);
  };

  // ─── 一键切片（免审核直接出片） ──────────────────────
  const oneClickSlice = async () => {
    setOneClickSlicing(true);
    setOneClickProgress({ status: 'running', progress: 5, message: '正在检查候选片段…' });
    try {
      // ── 无候选片段时自动补一轮 AI 智能选点（一键切片 = 选点 + 切片全自动） ──
      let existingClips: ClipCandidate[] = [];
      try {
        existingClips = await autoclipApi.getCandidates(episodeId);
      } catch {
        existingClips = [];
      }
      if (existingClips.length === 0) {
        setOneClickProgress({ status: 'running', progress: 10, message: '该剧集还没有候选片段，正在自动运行 AI 智能选点…' });
        await autoclipApi.run(episodeId, {
          max_clips: maxClips,
          min_score_threshold: minScoreThreshold ?? undefined,
          min_duration: minClipDuration ?? undefined,
          max_duration: maxClipDuration ?? undefined,
          frame_analysis: frameAnalysis,
        });
        let selected = false;
        for (let i = 0; i < 200 && !selected; i++) {
          await new Promise((r) => setTimeout(r, 3000));
          const p = await autoclipApi.progress(episodeId);
          if (p.status === 'completed') {
            selected = true;
          } else if (p.status === 'failed') {
            throw new Error(p.error_message || 'AI 智能选点失败，请稍后重试');
          } else {
            setOneClickProgress({
              status: 'running',
              progress: 10 + Math.round((p.progress || 0) * 0.6),
              message: `AI 智能选点中 ${Math.round(p.progress || 0)}%…`,
            });
          }
        }
        if (!selected) throw new Error('AI 智能选点超时，请稍后重试');
        setOneClickProgress({ status: 'running', progress: 75, message: '选点完成，正在提交一键切片任务…' });
        // 选点完成后若仍无候选片段，后端会回退为「整片切片」，这里只做提示不中断
        try {
          const after = await autoclipApi.getCandidates(episodeId);
          if (after.length === 0) {
            setOneClickProgress({ status: 'running', progress: 75, message: '未发现候选片段，将回退为整片切片…' });
          }
        } catch {
          // 忽略查询失败
        }
      }
      // auto_accept_all=true：后端自动把所有候选片段（含 pending）纳入切片，
      // 无需逐个审核/预览，直接产出成品视频
      const res = await sliceApi.run(episodeId, 'fast', {
        auto_accept_all: true,
        // 竖屏转横屏：一键切片同样透传配置
        vert2horiz_enabled: vert2horizEnabled,
        vert2horiz_mode: vert2horizEnabled ? vert2horizMode : undefined,
        vert2horiz_ratio: vert2horizEnabled ? vert2horizRatio : undefined,
        vert2horiz_output_size: vert2horizEnabled ? vert2horizOutputSize : undefined,
        vert2horiz_detect_interval: vert2horizEnabled ? vert2horizDetectInterval : undefined,
        vert2horiz_smooth_window: vert2horizEnabled ? vert2horizSmoothWindow : undefined,
        // 图片角标：一键切片同样透传配置
        badges: badges.length > 0
          ? badges.map((b) => ({
              file_key: b.file_key,
              position: b.position,
              ...(b.width ? { width: b.width } : {}),
              ...(b.offset != null ? { offset: b.offset } : {}),
              ...(b.opacity != null ? { opacity: b.opacity } : {}),
            }))
          : undefined,
        badge_default_width: badgeDefaultWidth || undefined,
        vert2horiz_min_step: vert2horizEnabled ? vert2horizMinStep : undefined,
        vert2horiz_face_margin: vert2horizEnabled ? vert2horizFaceMargin : undefined,
        // ASR 字幕烧录：一键切片同样透传配置
        subtitle_enabled: subtitleEnabled,
        // 字幕字号（相对高度比例）：可调大让字幕更清晰易读
        subtitle_font_ratio: subtitleEnabled ? subtitleFontRatio : undefined,
        // 字幕字间距（ASS Spacing 像素）：让字幕文字更紧凑
        subtitle_spacing: subtitleEnabled ? subtitleSpacing : undefined,
        // 字幕样式：custom 时可选字体色/边框色（无底色）
        subtitle_style: subtitleEnabled ? subtitleStyle : undefined,
        subtitle_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleColor : undefined,
        subtitle_border_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleBorderColor : undefined,
        // 上传的字幕文件：提供后直接应用该字幕，跳过 ASR 识别
        subtitle_file_key: subtitleFileKey || undefined,
        // 源视频字幕打码：独立开关，开启后仅打掉片源自带字幕（不依赖 ASR 字幕开关）
        subtitle_mask_enabled: subtitleMaskEnabled,
        subtitle_mask_style: subtitleMaskEnabled ? subtitleMaskStyle : undefined,
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
      message.success(res.message || '一键切片任务已启动，可直接前往「成品预览」查看结果');
      message.info('切片完成后请到「成品预览」查看并下载结果');
      fetchEpisode();
      fetchHistories();
      // 与普通切片一致：轮询任务进度，实时展示进度条
      pollLatestSliceProgress('fast', setOneClickSlicing, setOneClickProgress);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '一键切片失败');
      setOneClickSlicing(false);
      setOneClickProgress(null);
    }
  };

  // ─── 固定文字角标（文字版角标）管理 ──────────────────
  const addTextOverlay = () => {
    setTextOverlays((prev) => [
      ...prev,
      { id: `tov_${Date.now()}_${prev.length}`, text: '', position: 'left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: 10 },
    ]);
  };
  const updateTextOverlay = (index: number, patch: Partial<TextOverlayItem>) => {
    setTextOverlays((prev) => prev.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  };
  const removeTextOverlay = (index: number) => {
    setTextOverlays((prev) => prev.filter((_, i) => i !== index));
  };

  // ─── 转横屏开关联动 ASR 字幕 ──────────────────────
  // 转横屏开启时，默认同时开启 ASR 字幕（字号 45、自定义样式字体色 #EDD736），
  // 用户可手动关闭/调整。
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
      setSubtitleEnabled(true);
      setSubtitleFontRatio(0.30);
      setSubtitleSpacing(0);
      setSubtitleStyle('custom');
      setSubtitleColor('#EDD736');
      // 默认开启固定文字开关并预置三处固定文字（右上角/左下角/最左侧竖排标题）
      setTextOverlayEnabled(true);
      // 默认预置三处固定文字（右上角/左下角/最左侧竖排标题）
      applyDefaultTextOverlays();
    }
  };

  // ─── 启动切片 / 快速转换 ───────────────────────
  const runSlice = async (noCut = false) => {
    const setRunning = noCut ? setQuickConverting : setSliceRunning;
    const setProgress = noCut ? setQuickProgress : setSliceProgress;
    // 快速转换是整片单片段转换，不做去重/挖洞，强制使用 fast 模式
    const mode = noCut ? 'fast' : sliceMode;
    setRunning(true);
    setProgress({ status: 'running', progress: 5, message: noCut ? '正在提交快速转换任务…' : '正在提交切片任务…' });
    try {
      const res = await sliceApi.run(episodeId, mode, {
        // 快速转换：跳过 AI 选点与区间检测，整段源视频直接应用下方配置转换输出
        no_cut: noCut || undefined,
        // 去重模式档位（轻/标准/重），仅去重模式生效
        dedupe_config: mode === 'dedupe' ? { preset: dedupePreset } : undefined,
        // 自定义文字水印：开启后后端下发给引擎，在成品视频上叠加动态文字水印
        watermark_enabled: watermarkEnabled,
        watermark_text: watermarkEnabled ? watermarkText : undefined,
        watermark_font_size: watermarkEnabled ? watermarkFontSize : undefined,
        watermark_opacity: watermarkEnabled ? watermarkOpacity : undefined,
        watermark_position: watermarkEnabled ? watermarkPosition : undefined,
        // 竖屏转横屏：开启后切片前自动把竖屏素材转成横屏
        vert2horiz_enabled: vert2horizEnabled,
        vert2horiz_mode: vert2horizEnabled ? vert2horizMode : undefined,
        vert2horiz_ratio: vert2horizEnabled ? vert2horizRatio : undefined,
        vert2horiz_output_size: vert2horizEnabled ? vert2horizOutputSize : undefined,
        vert2horiz_detect_interval: vert2horizEnabled ? vert2horizDetectInterval : undefined,
        vert2horiz_smooth_window: vert2horizEnabled ? vert2horizSmoothWindow : undefined,
        // 图片角标：多角标、六角位置、宽度/偏移/透明度，全程叠加
        badges: badges.length > 0
          ? badges.map((b) => ({
              file_key: b.file_key,
              position: b.position,
              ...(b.width ? { width: b.width } : {}),
              ...(b.offset != null ? { offset: b.offset } : {}),
              ...(b.opacity != null ? { opacity: b.opacity } : {}),
            }))
          : undefined,
        badge_default_width: badgeDefaultWidth || undefined,
        vert2horiz_min_step: vert2horizEnabled ? vert2horizMinStep : undefined,
        vert2horiz_face_margin: vert2horizEnabled ? vert2horizFaceMargin : undefined,
        // ASR 字幕烧录：开启后对源视频做 ASR 识别并烧录到成品视频
        subtitle_enabled: subtitleEnabled,
        // 字幕字号（相对高度比例）：可调大让字幕更清晰易读
        subtitle_font_ratio: subtitleEnabled ? subtitleFontRatio : undefined,
        // 字幕字间距（ASS Spacing 像素）：让字幕文字更紧凑
        subtitle_spacing: subtitleEnabled ? subtitleSpacing : undefined,
        // 字幕样式：custom 时可选字体色/边框色（无底色）
        subtitle_style: subtitleEnabled ? subtitleStyle : undefined,
        subtitle_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleColor : undefined,
        subtitle_border_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleBorderColor : undefined,
        // 上传的字幕文件：提供后直接应用该字幕，跳过 ASR 识别
        subtitle_file_key: subtitleFileKey || undefined,
        // 源视频字幕打码：独立开关，开启后仅打掉片源自带字幕（不依赖 ASR 字幕开关）
        subtitle_mask_enabled: subtitleMaskEnabled,
        subtitle_mask_style: subtitleMaskEnabled ? subtitleMaskStyle : undefined,
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
      fetchHistories();
      // 启动后轮询任务进度
      pollLatestSliceProgress(mode, setRunning, setProgress);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : (noCut ? '启动快速转换失败' : '启动切片失败'));
      setRunning(false);
      setProgress(null);
    }
  };

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error || !episode) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const currentStep = getCurrentStep();

  // ─── 工作流步骤引导提示 ─────────────────────────────
  const workflowGuide = () => {
    if (episode.status === 'clips_detected') {
      // 选点完成→引导去审核
      return (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message="选点已完成！下一步操作"
          description={
            <Space direction="vertical" size={4}>
              <Text>1. 点击下方「片段审核」查看 AI 推荐的精彩片段，审核通过或拒绝每个片段</Text>
              <Text>2. 审核完成后，可进行「区间检测」识别需要裁剪的区域（片尾字幕、静止画面等）</Text>
              <Text>3. 最后选择切片模式，执行「切片」生成成品视频</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      );
    }
    if (episode.status === 'intervals_detected') {
      // 区间检测完成→引导去切片
      return (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="区间检测已完成！下一步操作"
          description={
            <Space direction="vertical" size={4}>
              <Text>1. 区间检测结果已自动保存，您可以在「区间检测」工作台查看详情</Text>
              <Text>2. 接下来选择下方的「切片模式」，然后点击「开始切片」生成成品视频</Text>
              <Text>3. 切片完成后，前往「成品预览」查看和下载结果</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      );
    }
    if (episode.status === 'uploaded') {
      // 刚上传完成→引导去选点
      return (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="视频已上传，下一步操作"
          description={
            <Space direction="vertical" size={4}>
              <Text>1. 点击下方「AI 智能选点」启动自动分析，系统将推荐精彩片段</Text>
              <Text>2. 选点完成后，在「片段审核」中审核和调整选点结果</Text>
              <Text>3. 之后依次进行「区间检测」→「切片执行」→「成品预览」</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      );
    }
    return null;
  };

  // ─── 各动作进度条（放在对应动作卡片的最底部） ────────────────────
  const renderProgress = (
    p: { status: string; progress: number; message: string; error_message?: string | null } | null
  ) => {
    if (!p) return null;
    return (
      <div style={{ marginTop: 8, borderTop: '1px dashed #f0f0f0', paddingTop: 8 }}>
        <Progress
          percent={p.progress}
          status={p.status === 'failed' ? 'exception' : p.status === 'completed' ? 'success' : 'active'}
          strokeColor={p.status === 'completed' ? '#52c41a' : undefined}
          size="small"
        />
        <Space size={4} align="center">
          <Text type="secondary" style={{ fontSize: 12 }}>{p.message}</Text>
          {p.status === 'failed' && p.error_message && <ErrorHint error={p.error_message} />}
        </Space>
      </div>
    );
  };

  // ─── 各动作执行历史（放在对应动作卡片最底部，多次执行均保留展示） ──
  const renderHistoryTitle = (label: string, count: number) => (
    <div style={{ marginTop: 12, borderTop: '1px dashed #f0f0f0', paddingTop: 8 }}>
      <Space size={8}>
        <Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>{label}</Text>
        {count > 0 && <Tag style={{ fontSize: 11, marginRight: 0 }}>{count} 次</Tag>}
      </Space>
    </div>
  );

  const actions: { title: string; node: React.ReactNode }[] = [
    {
      title: 'AI 智能选点',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap>
            <Button type="primary" icon={<ThunderboltOutlined />} loading={autoclipRunning} onClick={runAutoClip}>
              启动选点
            </Button>
            <Tooltip title="设置 AI 选点推荐的最大片段数量，数量越多等待时间越长（默认 10）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>选点个数:</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={100}
                  placeholder="10"
                  value={maxClips}
                  onChange={(v) => setMaxClips(v ?? 10)}
                  style={{ width: 70 }}
                />
              </Space>
            </Tooltip>
            <Tooltip title="设置候选片段入选的最低评分（0-100），留空则使用系统默认（60 分）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>入选评分:</Text>
                <InputNumber
                  size="small"
                  min={0}
                  max={100}
                  placeholder="60"
                  value={minScoreThreshold}
                  onChange={(v) => setMinScoreThreshold(v ?? null)}
                  style={{ width: 70 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>分</Text>
              </Space>
            </Tooltip>
          </Space>
          <Space wrap>
            <Tooltip title="设置候选片段的最短时长（秒），留空则使用系统默认（30 秒）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>最短时长:</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={86400}
                  placeholder="30"
                  value={minClipDuration}
                  onChange={(v) => setMinClipDuration(v ?? null)}
                  style={{ width: 80 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              </Space>
            </Tooltip>
            <Tooltip title="设置候选片段的最长时长（秒），留空则使用系统默认（180 秒）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>最长时长:</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={86400}
                  placeholder="180"
                  value={maxClipDuration}
                  onChange={(v) => setMaxClipDuration(v ?? null)}
                  style={{ width: 80 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              </Space>
            </Tooltip>
            <Space size={4} align="center">
              <Switch size="small" checked={frameAnalysis} onChange={setFrameAnalysis} />
              <Text strong style={{ fontSize: 12 }}>画面理解</Text>
              <Tooltip title="开启后，AI 选点会对候选片段进行画面理解（抽帧送本地 MiniCPM-V 视觉模型分析场景/动作/情绪/精彩度），结合台词综合打分。关闭则仅依据台词与文案判断。（默认开启）">
                <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
              </Tooltip>
            </Space>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            自动分析视频内容，推荐精彩片段作为切片候选
          </Text>
          {/* 进度条：选点动作 tab 最底部 */}
          {renderProgress(autoclipProgress)}
          {/* 选点执行历史 */}
          {renderHistoryTitle('选点执行历史', autoclipHistory.length)}
          {autoclipHistory.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无执行记录</Text>
          ) : (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={autoclipHistory.slice(0, 8)}
              scroll={{ x: 400 }}
              columns={[
                {
                  title: '状态',
                  dataIndex: 'status',
                  key: 'status',
                  width: 74,
                  render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
                },
                {
                  title: '结果',
                  dataIndex: 'message',
                  key: 'message',
                  ellipsis: true,
                  render: (m: string | null, r: AutoClipRunRecord) =>
                    r.status === 'failed' && r.error_message ? (
                      <ErrorHint error={r.error_message} />
                    ) : r.status === 'completed' ? (
                      <Text style={{ fontSize: 12 }}>{m || '已完成'}</Text>
                    ) : r.status === 'running' || r.status === 'pending' ? (
                      <Text style={{ fontSize: 12 }}>{(r.progress || 0).toFixed(0)}% {m || ''}</Text>
                    ) : (
                      <Text style={{ fontSize: 12 }}>{m || '-'}</Text>
                    ),
                },
                {
                  title: '时间',
                  dataIndex: 'created_at',
                  key: 'created_at',
                  width: 130,
                  render: (d: string) => (
                    <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text>
                  ),
                },
              ]}
            />
          )}
        </Space>
      ),
    },
    {
      title: '通用区间检测',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space>
            <Select value={detectMode} onChange={setDetectMode} style={{ width: 120 }}
              options={[
                { value: 'credits', label: '片尾字幕' },
                { value: 'static', label: '静止画面' },
                { value: 'watermark', label: '水印' },
              ]}
            />
            <Button icon={<RadarChartOutlined />} loading={detectRunning} onClick={runDetect}>开始检测</Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            检测视频中的特定区间（片尾字幕/静止画面/水印），检测结果将用于切片时自动裁剪
          </Text>
          {/* 检测结果：完成后直接展示条数，避免“只有标识没有结果” */}
          {detectResultCount !== null && (
            <Alert
              type={detectResultCount > 0 ? 'success' : 'info'}
              showIcon
              style={{ width: '100%' }}
              message={detectResultCount > 0
                ? `已检测到 ${detectResultCount} 个区间`
                : '本次检测未发现符合条件的区间'}
              description={
                <Space>
                  <Text style={{ fontSize: 12 }}>
                    {detectResultCount > 0 ? '可在「区间检测」工作台查看详情并启用/停用' : '可尝试切换其他模式或手动添加区间'}
                  </Text>
                  <Button size="small" type="link" onClick={() => navigate(`/episodes/${episodeId}/intervals`)}>前往查看</Button>
                </Space>
              }
            />
          )}
          {/* 进度条：区间检测动作 tab 最底部 */}
          {renderProgress(detectProgress)}
          {/* 区间检测执行历史 */}
          {renderHistoryTitle('区间检测执行历史', intervalHistory.length)}
          {intervalHistory.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无执行记录</Text>
          ) : (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={intervalHistory.slice(0, 8)}
              scroll={{ x: 420 }}
              columns={[
                {
                  title: '模式',
                  dataIndex: 'mode',
                  key: 'mode',
                  width: 74,
                  render: (m: string | null) => (
                    <Tag>{DETECT_MODE_LABELS[m || ''] || m || '-'}</Tag>
                  ),
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  key: 'status',
                  width: 74,
                  render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
                },
                {
                  title: '结果',
                  key: 'result',
                  ellipsis: true,
                  render: (_: unknown, r: IntervalHistoryItem) =>
                    r.status === 'failed' && r.error_message ? (
                      <ErrorHint error={r.error_message} />
                    ) : r.status === 'completed' ? (
                      <Text style={{ fontSize: 12 }}>
                        {r.interval_count ? `检测到 ${r.interval_count} 个区间` : '未发现符合条件的区间'}
                      </Text>
                    ) : (
                      <Text style={{ fontSize: 12 }}>{(r.progress || 0).toFixed(0)}%</Text>
                    ),
                },
                {
                  title: '时间',
                  dataIndex: 'created_at',
                  key: 'created_at',
                  width: 130,
                  render: (d: string) => (
                    <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text>
                  ),
                },
              ]}
            />
          )}
        </Space>
      ),
    },
    {
      title: '切片执行',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space>
            <Cascader
              value={sliceMode === 'dedupe' ? ['dedupe', dedupePreset || 'standard'] : [sliceMode]}
              options={SLICE_MODE_OPTIONS}
              onChange={(val: (string | number)[]) => {
                const v = (val ?? []).map(String);
                if (v[0] === 'dedupe') {
                  setSliceMode('dedupe');
                  setDedupePreset(v[1] || 'standard');
                } else if (v[0]) {
                  setSliceMode(v[0]);
                }
              }}
              displayRender={(labels: string[]) => labels.join(' · ')}
              placeholder="选择切片模式"
              style={{ width: 180 }}
            />
            <Button icon={<ScissorOutlined />} loading={sliceRunning} disabled={quickConverting} onClick={() => runSlice(false)}>开始切片</Button>
            <Tooltip title="跳过 AI 选点和区间检测，直接整段视频应用下方配置（竖屏转横屏/水印/角标/字幕/固定文字等）转换输出">
              <Button icon={<ThunderboltOutlined />} loading={quickConverting} disabled={sliceRunning} onClick={() => runSlice(true)}>快速转换</Button>
            </Tooltip>
          </Space>
          {/* 切片模式详细说明 */}
          <Card size="small" style={{ background: '#f0f5ff', border: '1px solid #d6e4ff', width: '100%' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong style={{ fontSize: 13, color: '#1d39c4' }}>
                <InfoCircleOutlined style={{ marginRight: 6 }} />
                {SLICE_MODE_HELP[sliceMode]?.label}
              </Text>
              <Text style={{ fontSize: 13, color: '#1d39c4' }}>
                {SLICE_MODE_HELP[sliceMode]?.desc}
              </Text>
              <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.6 }}>
                {SLICE_MODE_HELP[sliceMode]?.detail}
              </Text>
            </Space>
          </Card>

          {/* ── 竖屏转横屏智能裁切开关 ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space wrap>
                <Switch checked={vert2horizEnabled} onChange={handleVert2horizToggle} size="small" />
                <Text strong style={{ fontSize: 13 }}>竖屏转横屏</Text>
                <Tooltip title="开启后若素材为竖屏（9:16），切片前自动转为横屏（16:9）：固定裁切快速稳定，动态跟踪会逐帧检测人脸确保人物不出画。适用于发布到视频号横屏模式 / B站等横屏平台。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
                {vert2horizEnabled && (
                  <Button size="small" icon={<SettingOutlined />} onClick={() => setVert2horizModalOpen(true)}>配置</Button>
                )}
              </Space>
            </Space>
          </Card>

          {/* 竖屏转横屏设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="竖屏转横屏配置"
            open={vert2horizModalOpen}
            onCancel={() => setVert2horizModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setVert2horizModalOpen(false)}>完成</Button>
            )}
            width={560}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>裁切模式</Text>
                <Select
                  size="small"
                  style={{ width: 150 }}
                  value={vert2horizMode}
                  onChange={setVert2horizMode}
                  options={[
                    { value: 'fixed', label: '固定裁切（快）' },
                    { value: 'dynamic', label: '动态跟踪（准）' },
                  ]}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>固定裁切一遍 ffmpeg 快速稳定；动态跟踪逐帧检测人脸确保人物不出画（较慢，约 3-5 分钟/10 分钟视频）</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>输出分辨率</Text>
                <Input
                  size="small"
                  style={{ width: 140 }}
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
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>横屏目标宽高比（16:9 对应约 0.5625）</Text>
              </Space>
              {vert2horizMode === 'dynamic' && (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap align="center" size={8}>
                    <Text strong style={{ fontSize: 13 }}>检测间隔(帧)</Text>
                    <InputNumber
                      size="small"
                      min={1}
                      max={30}
                      value={vert2horizDetectInterval}
                      onChange={(v) => setVert2horizDetectInterval(v ?? 2)}
                      style={{ width: 80 }}
                    />
                    <Text strong style={{ fontSize: 13 }}>平滑窗口(帧)</Text>
                    <InputNumber
                      size="small"
                      min={1}
                      max={60}
                      value={vert2horizSmoothWindow}
                      onChange={(v) => setVert2horizSmoothWindow(v ?? 15)}
                      style={{ width: 80 }}
                    />
                  </Space>
                  <Space wrap align="center" size={8}>
                    <Text strong style={{ fontSize: 13 }}>最小移动(px)</Text>
                    <InputNumber
                      size="small"
                      min={0}
                      max={30}
                      value={vert2horizMinStep}
                      onChange={(v) => setVert2horizMinStep(v ?? 5)}
                      style={{ width: 80 }}
                    />
                    <Text strong style={{ fontSize: 13 }}>人脸舒适区(比例)</Text>
                    <InputNumber
                      size="small"
                      min={0}
                      max={0.8}
                      step={0.05}
                      value={vert2horizFaceMargin}
                      onChange={(v) => setVert2horizFaceMargin(v ?? 0.30)}
                      style={{ width: 80 }}
                    />
                  </Space>
                </Space>
              )}
            </Space>
          </Modal>

          {/* ── ASR 字幕烧录开关 ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space wrap>
                <Switch checked={subtitleEnabled} onChange={setSubtitleEnabled} size="small" />
                <Text strong style={{ fontSize: 13 }}>ASR 字幕</Text>
                <Tooltip title="开启后对源视频做语音识别（ASR），并把识别到的台词烧录到每个切片成品上（白字黑边，底部居中）。适合把关键对白直观呈现在短剧切片上。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
                {subtitleEnabled && (
                  <Button size="small" icon={<SettingOutlined />} onClick={() => setSubtitleModalOpen(true)}>字幕设置</Button>
                )}
              </Space>
            </Space>
          </Card>

          {/* 字幕设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="字幕设置"
            open={subtitleModalOpen}
            onCancel={() => setSubtitleModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setSubtitleModalOpen(false)}>完成</Button>
            )}
            width={500}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              {/* 上传字幕文件：提供后直接应用，跳过 ASR 识别 */}
              <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
                <Space wrap align="center" size={8}>
                  <Text strong style={{ fontSize: 13 }}>上传字幕文件</Text>
                  <Upload
                    accept=".srt,.vtt"
                    showUploadList={false}
                    beforeUpload={uploadSubtitleFile}
                    disabled={subtitleUploading}
                  >
                    <Button size="small" icon={<UploadOutlined />} loading={subtitleUploading}>选择字幕</Button>
                  </Upload>
                  {subtitleFileName && (
                    <Tag color="blue" closable onClose={removeSubtitleFile}>{subtitleFileName}</Tag>
                  )}
                </Space>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                  支持 srt/vtt；上传后直接应用该字幕文件，跳过 ASR 语音识别。
                </Text>
              </div>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>字幕字号</Text>
                <InputNumber
                  min={10}
                  max={60}
                  step={1}
                  value={Math.round(subtitleFontRatio * 100)}
                  onChange={(v) => {
                    const fs = v ?? 20;
                    setSubtitleFontRatio(Math.max(0.1, Math.min(0.6, fs / 100)));
                  }}
                  style={{ width: 100 }}
                  addonAfter="px"
                />
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>字幕字间距</Text>
                <InputNumber
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
                <Text strong style={{ fontSize: 13 }}>字幕样式</Text>
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
                  <Text strong style={{ fontSize: 13 }}>字体颜色</Text>
                  <ColorPicker
                    value={subtitleColor}
                    onChange={(c) => setSubtitleColor(c.toHexString())}
                    showText
                    size="small"
                  />
                  <Text strong style={{ fontSize: 13 }}>边框颜色</Text>
                  <ColorPicker
                    value={subtitleBorderColor}
                    onChange={(c) => setSubtitleBorderColor(c.toHexString())}
                    showText
                    size="small"
                  />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    自定义模式下仅描边、无底色（不遮挡画面），字幕更清爽
                  </Text>
                </Space>
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                字幕仅在说话时显示，静音/停顿自动隐藏，避免提早出现或延后消失。
              </Text>
            </Space>
          </Modal>

          {/* ── 源视频字幕打码（去片源自带字幕，独立开关） ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space wrap align="center" size={8}>
              <Switch size="small" checked={subtitleMaskEnabled} onChange={setSubtitleMaskEnabled} />
              <Text strong style={{ fontSize: 13 }}>源字幕打码</Text>
              <Tooltip title="把片源自带的字幕去字幕/打码（独立开关，与 ASR 字幕无关）。默认自动检测字幕位置，样式为去水印（智能插值），仅在有源字幕的时间段生效。">
                <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
              </Tooltip>
              {subtitleMaskEnabled && (
                <Button size="small" icon={<SettingOutlined />} onClick={() => setSubtitleMaskModalOpen(true)}>打码设置</Button>
              )}
            </Space>
          </Card>

          {/* 源字幕打码设置弹窗 */}
          <Modal
            title="源字幕打码设置"
            open={subtitleMaskModalOpen}
            onCancel={() => setSubtitleMaskModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setSubtitleMaskModalOpen(false)}>完成</Button>
            )}
            width={500}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>打码样式</Text>
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
                <Text strong style={{ fontSize: 13 }}>区域宽度</Text>
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
                <Text strong style={{ fontSize: 13 }}>区域高度</Text>
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
                <Text strong style={{ fontSize: 13 }}>距底边</Text>
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
              <Text type="secondary" style={{ fontSize: 12 }}>
                仅在有源字幕的时间段打码，其余时间不动画面；未识别到源字幕时全程打码。
              </Text>
            </Space>
          </Modal>

          {/* ── 固定文字角标（文字版角标，最左侧/左下角/右上角等） ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space wrap align="center" size={8}>
              <Switch size="small" checked={textOverlayEnabled} onChange={setTextOverlayEnabled} />
              <Text strong style={{ fontSize: 13 }}>固定文字</Text>
              <Tooltip title="开启后在视频指定位置叠加固定文字（无需上传图片）：最左侧（竖排）/左下角/右上角等，全程覆盖。开启后点击右侧「设置文字」按钮配置文字内容、字号、颜色等。">
                <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
              </Tooltip>
              {textOverlayEnabled && (
                <Button size="small" icon={<SettingOutlined />} onClick={() => setTextOverlayModalOpen(true)}>设置文字</Button>
              )}
            </Space>
          </Card>

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

          {/* ── 图片角标配置（多角标、六角位置，全程叠加） ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space wrap>
                <Text strong style={{ fontSize: 13 }}>图片角标</Text>
                <Tooltip title="可上传多张图片作为角标，全程叠加在视频指定位置；支持六角定位、宽度、偏移量、透明度。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
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
              </Space>
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
            </Space>
          </Card>

          {/* ── 动态文字水印开关（置于配置项最后） ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space wrap>
                <Switch checked={watermarkEnabled} onChange={setWatermarkEnabled} size="small" />
                <Text strong style={{ fontSize: 13 }}>动态文字水印</Text>
                <Tooltip title="开启后会在切片成品视频上叠加动态文字水印（文字缓慢移动 + 透明度呼吸），可用于防搬运/标识来源。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
                {watermarkEnabled && (
                  <Button size="small" icon={<SettingOutlined />} onClick={() => setWatermarkModalOpen(true)}>配置</Button>
                )}
              </Space>
            </Space>
          </Card>

          {/* 动态文字水印设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="动态文字水印配置"
            open={watermarkModalOpen}
            onCancel={() => setWatermarkModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setWatermarkModalOpen(false)}>完成</Button>
            )}
            width={520}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>水印文字</Text>
                <Input
                  size="small"
                  style={{ width: 280 }}
                  placeholder="留空默认：剧集标题 + 日期（支持 {title} {date} {datetime}）"
                  value={watermarkText}
                  onChange={(e) => setWatermarkText(e.target.value)}
                />
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>字号</Text>
                <InputNumber
                  size="small"
                  min={12}
                  max={120}
                  value={watermarkFontSize}
                  onChange={(v) => setWatermarkFontSize(v ?? 28)}
                  style={{ width: 90 }}
                />
                <Text strong style={{ fontSize: 13 }}>透明度</Text>
                <Slider
                  style={{ width: 160, margin: '0 8px' }}
                  min={5}
                  max={100}
                  value={Math.round(watermarkOpacity * 100)}
                  onChange={(v) => setWatermarkOpacity(v / 100)}
                />
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{Math.round(watermarkOpacity * 100)}%</Text>
                <Text strong style={{ fontSize: 13 }}>位置</Text>
                <Select
                  size="small"
                  style={{ width: 90 }}
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

          {/* 进度条：切片动作 tab 最底部 */}
          {renderProgress(sliceProgress)}
          {renderProgress(quickProgress)}
          {/* 切片执行历史 */}
          {renderHistoryTitle('切片执行历史', sliceHistory.length)}
          {sliceHistory.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无执行记录</Text>
          ) : (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={sliceHistory.slice(0, 8)}
              scroll={{ x: 620 }}
              columns={[
                {
                  title: '名称',
                  key: 'name',
                  width: 170,
                  render: (_: unknown, t: SliceTask) =>
                    t.status === 'completed' ? (
                      <a
                        style={{ fontSize: 12 }}
                        title="点击跳转成片预览"
                        onClick={(e) => { e.stopPropagation(); navigate(`/episodes/${episodeId}/preview?task=${t.id}`); }}
                      >
                        {SLICE_MODE_HELP[t.mode || '']?.label || t.mode || '切片任务'} · {formatDateTime(t.created_at)}
                      </a>
                    ) : (
                      <Text style={{ fontSize: 12 }}>{SLICE_MODE_HELP[t.mode || '']?.label || t.mode || '切片任务'} · {formatDateTime(t.created_at)}</Text>
                    ),
                },
                {
                  title: '模式',
                  dataIndex: 'mode',
                  key: 'mode',
                  width: 74,
                  render: (m: string | null) => (
                    <Tag>{SLICE_MODE_HELP[m || '']?.label || m || '-'}</Tag>
                  ),
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  key: 'status',
                  width: 74,
                  render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
                },
                {
                  title: '结果',
                  key: 'result',
                  ellipsis: true,
                  render: (_: unknown, t: SliceTask) =>
                    t.status === 'failed' && t.error_message ? (
                      <ErrorHint error={t.error_message} />
                    ) : t.status === 'completed' ? (
                      <a
                        style={{ fontSize: 12 }}
                        onClick={(e) => { e.stopPropagation(); navigate(`/episodes/${episodeId}/preview?task=${t.id}`); }}
                      >
                        产出 {t.output_count} 个成品 →
                      </a>
                    ) : t.status === 'cancelled' ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>已取消</Text>
                    ) : (
                      <Text style={{ fontSize: 12 }}>{(t.progress || 0).toFixed(0)}%</Text>
                    ),
                },
                {
                  title: '时间',
                  dataIndex: 'created_at',
                  key: 'created_at',
                  width: 130,
                  render: (d: string) => (
                    <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text>
                  ),
                },
                {
                  title: '耗时',
                  key: 'duration',
                  width: 80,
                  render: (_: unknown, t: SliceTask) => (
                    <Text style={{ fontSize: 12 }}>{formatTaskDuration(t)}</Text>
                  ),
                },
                {
                  title: '操作',
                  key: 'action',
                  width: 90,
                  render: (_: unknown, t: SliceTask) =>
                    t.status === 'running' || t.status === 'pending' ? (
                      <Popconfirm
                        title="确定停止该任务？"
                        description="将终止引擎进程并释放资源，已产出成品不会保留"
                        onConfirm={async () => {
                          try {
                            await sliceApi.cancel(t.id);
                            message.success('任务已停止');
                            fetchSliceHistory();
                          } catch (err: unknown) {
                            message.error(err instanceof Error ? err.message : '停止失败');
                          }
                        }}
                      >
                        <Button size="small" danger icon={<StopOutlined />}>停止</Button>
                      </Popconfirm>
                    ) : (
                      <Text type="secondary" style={{ fontSize: 12 }}>-</Text>
                    ),
                },
              ]}
            />
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb style={{ marginBottom: 16 }}
        items={[
          { title: <a onClick={() => navigate('/projects')}>短剧切片</a> },
          { title: <a onClick={() => navigate(`/projects/${episode.project_id}`)}>项目详情</a> },
          { title: episode.title || episode.id },
        ]}
      />
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${episode.project_id}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>{episode.title || '(未命名剧集)'}</Title>
        <Tag color={getStatusColor(episode.status)}>{getStatusLabel(episode.status)}</Tag>
      </Space>

      {/* 工作台入口：上移到页面顶部，便于快速进入各操作工作台 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text strong>工作台入口:</Text>
          <Button type="primary" ghost icon={<CheckCircleOutlined />} onClick={() => navigate(`/episodes/${episodeId}/clips`)}>片段审核</Button>
          <Button type="primary" ghost icon={<RadarChartOutlined />} onClick={() => navigate(`/episodes/${episodeId}/intervals`)}>区间检测</Button>
          <Button type="primary" ghost icon={<ScissorOutlined />} onClick={() => navigate(`/episodes/${episodeId}/slice`)}>切片任务</Button>
          <Button type="primary" ghost icon={<PlayCircleOutlined />} onClick={() => navigate(`/episodes/${episodeId}/preview`)}>成品预览</Button>
          {/* 一键切片：免审核直接出片，放在工作台入口处，方便快速出片 */}
          <Popconfirm
            title="一键切片"
            description="免审核直接出片：自动把所有候选片段（含待审核）直接切割成成品视频，无需逐个审核/预览。"
            onConfirm={() => { void oneClickSlice(); }}
            okText="开始切片"
            cancelText="取消"
            disabled={oneClickSlicing}
          >
            <Button
              type="primary"
              danger
              icon={<ScissorOutlined />}
              loading={oneClickSlicing}
              disabled={oneClickSlicing}
            >
              一键切片
            </Button>
          </Popconfirm>
          <Button
            icon={<SettingOutlined />}
            disabled={oneClickSlicing}
            onClick={() => setPresetModalOpen(true)}
          >
            配置
          </Button>
        </Space>
        {/* 一键切片实时进度条：任务进行中时展示在按钮下方 */}
        {renderProgress(oneClickProgress)}
      </Card>

      {/* 一键切片配置弹窗：可自定义所有默认值并保存多套配置 */}
      <Modal
        title="一键切片配置"
        open={presetModalOpen}
        onCancel={() => setPresetModalOpen(false)}
        footer={(
          <Button type="primary" onClick={() => setPresetModalOpen(false)}>完成</Button>
        )}
        width={720}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {/* 预设选择 / 保存区 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Text strong style={{ fontSize: 13 }}>选择配置</Text>
            <Select
              size="small"
              style={{ width: 180 }}
              value={activePresetId}
              onChange={handleSelectPreset}
              options={presets.map((p) => ({ value: p.id, label: p.name }))}
            />
            {activePresetId !== DEFAULT_SLICE_PRESET.id && (
              <Button size="small" danger icon={<DelIcon />} onClick={() => handleDeletePreset(activePresetId)}>删除</Button>
            )}
            <span style={{ flex: 1 }} />
            <Input
              size="small"
              style={{ width: 150 }}
              placeholder="新配置名称"
              value={newPresetName}
              onChange={(e) => setNewPresetName(e.target.value)}
            />
            <Button size="small" type="primary" onClick={handleSavePreset}>保存当前配置</Button>
          </div>

          {/* ── 竖屏转横屏 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <Switch size="small" checked={vert2horizEnabled} onChange={setVert2horizEnabled} />
              <Text strong style={{ fontSize: 13 }}>竖屏转横屏</Text>
            </Space>
            {vert2horizEnabled && (
              <Space wrap align="center" size={8} style={{ marginTop: 4 }}>
                <Text style={{ fontSize: 12 }}>模式</Text>
                <Select size="small" style={{ width: 130 }} value={vert2horizMode} onChange={setVert2horizMode} options={[
                  { value: 'fixed', label: '固定裁切（快）' },
                  { value: 'dynamic', label: '动态跟踪（准）' },
                ]} />
                <Text style={{ fontSize: 12 }}>分辨率</Text>
                <Input size="small" style={{ width: 90 }} value={vert2horizOutputSize} onChange={(e) => setVert2horizOutputSize(e.target.value)} />
                <Text style={{ fontSize: 12 }}>裁切比例</Text>
                <InputNumber size="small" min={0.1} max={1} step={0.05} value={vert2horizRatio} onChange={(v) => setVert2horizRatio(v ?? 0.5625)} style={{ width: 80 }} />
                {vert2horizMode === 'dynamic' && (
                  <>
                    <Text style={{ fontSize: 12 }}>检测间隔</Text>
                    <InputNumber size="small" min={1} max={30} value={vert2horizDetectInterval} onChange={(v) => setVert2horizDetectInterval(v ?? 2)} style={{ width: 60 }} />
                    <Text style={{ fontSize: 12 }}>平滑窗口</Text>
                    <InputNumber size="small" min={1} max={60} value={vert2horizSmoothWindow} onChange={(v) => setVert2horizSmoothWindow(v ?? 15)} style={{ width: 60 }} />
                    <Text style={{ fontSize: 12 }}>最小移动</Text>
                    <InputNumber size="small" min={0} max={30} value={vert2horizMinStep} onChange={(v) => setVert2horizMinStep(v ?? 5)} style={{ width: 60 }} />
                    <Text style={{ fontSize: 12 }}>人脸舒适区</Text>
                    <InputNumber size="small" min={0} max={0.8} step={0.05} value={vert2horizFaceMargin} onChange={(v) => setVert2horizFaceMargin(v ?? 0.30)} style={{ width: 60 }} />
                  </>
                )}
              </Space>
            )}
          </div>

          {/* ── ASR 字幕 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <Switch size="small" checked={subtitleEnabled} onChange={setSubtitleEnabled} />
              <Text strong style={{ fontSize: 13 }}>ASR 字幕</Text>
            </Space>
            {subtitleEnabled && (
              <Space wrap align="center" size={8}>
                <Text style={{ fontSize: 12 }}>字号</Text>
                <InputNumber size="small" min={10} max={60} step={1} value={Math.round(subtitleFontRatio * 100)} onChange={(v) => { const fs = v ?? 45; setSubtitleFontRatio(Math.max(0.1, Math.min(0.6, fs / 100))); }} style={{ width: 80 }} />
                <Radio.Group size="small" value={subtitleStyle} onChange={(e) => setSubtitleStyle(e.target.value)}>
                  <Radio.Button value="default">默认</Radio.Button>
                  <Radio.Button value="custom">自定义</Radio.Button>
                </Radio.Group>
                {subtitleStyle === 'custom' && (
                  <>
                    <Text style={{ fontSize: 12 }}>字色</Text>
                    <ColorPicker size="small" value={subtitleColor} onChange={(c) => setSubtitleColor(c.toHexString())} showText />
                    <Text style={{ fontSize: 12 }}>描边</Text>
                    <ColorPicker size="small" value={subtitleBorderColor} onChange={(c) => setSubtitleBorderColor(c.toHexString())} showText />
                  </>
                )}
              </Space>
            )}
          </div>

          {/* ── 源视频字幕打码 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <Switch size="small" checked={subtitleMaskEnabled} onChange={setSubtitleMaskEnabled} />
              <Text strong style={{ fontSize: 13 }}>源字幕打码</Text>
            </Space>
            {subtitleMaskEnabled && (
              <Space wrap align="center" size={8}>
                <Text style={{ fontSize: 12 }}>样式</Text>
                <Select size="small" style={{ width: 100 }} value={subtitleMaskStyle} onChange={setSubtitleMaskStyle} options={[
                  { value: 'delogo', label: '去水印' },
                  { value: 'mosaic', label: '马赛克' },
                  { value: 'blur', label: '模糊' },
                  { value: 'fill', label: '纯色块' },
                ]} />
                <Text style={{ fontSize: 12 }}>宽</Text>
                <InputNumber size="small" min={0.1} max={1} step={0.05} value={subtitleMaskWidthRatio} onChange={(v) => setSubtitleMaskWidthRatio(v ?? 0.9)} style={{ width: 70 }} />
                <Text style={{ fontSize: 12 }}>高</Text>
                <InputNumber size="small" min={0.02} max={0.5} step={0.01} value={subtitleMaskHeightRatio} onChange={(v) => setSubtitleMaskHeightRatio(v ?? 0.12)} style={{ width: 70 }} />
                <Text style={{ fontSize: 12 }}>距底</Text>
                <InputNumber size="small" min={0} max={0.5} step={0.01} value={subtitleMaskBottomRatio} onChange={(v) => setSubtitleMaskBottomRatio(v ?? 0.02)} style={{ width: 70 }} />
              </Space>
            )}
          </div>

          {/* ── 固定文字 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <Switch size="small" checked={textOverlayEnabled} onChange={setTextOverlayEnabled} />
              <Text strong style={{ fontSize: 13 }}>固定文字</Text>
              {textOverlayEnabled && (
                <Button size="small" icon={<PlusOutlined />} onClick={addTextOverlay}>添加</Button>
              )}
            </Space>
            {textOverlayEnabled && textOverlays.length > 0 && (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                {textOverlays.map((t, i) => (
                  <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', border: '1px solid #f0f0f0', borderRadius: 4, padding: 6 }}>
                    <Input size="small" placeholder="文字内容" value={t.text} onChange={(e) => updateTextOverlay(i, { text: e.target.value })} style={{ width: 120 }} />
                    <Select size="small" style={{ width: 88 }} value={t.position} onChange={(v) => updateTextOverlay(i, { position: v })} options={BADGE_POSITIONS} />
                    <Checkbox checked={!!t.vertical} onChange={(e) => updateTextOverlay(i, { vertical: e.target.checked })}>竖排</Checkbox>
                    <InputNumber size="small" min={12} max={200} placeholder="字号" value={t.font_size} onChange={(v) => updateTextOverlay(i, { font_size: v ?? undefined })} style={{ width: 70 }} />
                    <Text style={{ fontSize: 12 }}>字色</Text>
                    <ColorPicker size="small" value={t.color || '#FFFFFF'} onChange={(c) => updateTextOverlay(i, { color: c.toHexString() })} showText />
                    <Text style={{ fontSize: 12 }}>描边</Text>
                    <ColorPicker size="small" value={t.border_color || '#000000'} onChange={(c) => updateTextOverlay(i, { border_color: c.toHexString() })} showText />
                    <Button size="small" type="text" danger icon={<DelIcon />} onClick={() => removeTextOverlay(i)} />
                  </div>
                ))}
              </Space>
            )}
          </div>

          {/* ── 动态文字水印 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <Switch size="small" checked={watermarkEnabled} onChange={setWatermarkEnabled} />
              <Text strong style={{ fontSize: 13 }}>动态文字水印</Text>
            </Space>
            {watermarkEnabled && (
              <Space wrap align="center" size={8}>
                <Text style={{ fontSize: 12 }}>文字</Text>
                <Input size="small" style={{ width: 200 }} placeholder="留空=标题+日期" value={watermarkText} onChange={(e) => setWatermarkText(e.target.value)} />
                <Text style={{ fontSize: 12 }}>字号</Text>
                <InputNumber size="small" min={12} max={120} value={watermarkFontSize} onChange={(v) => setWatermarkFontSize(v ?? 28)} style={{ width: 70 }} />
                <Text style={{ fontSize: 12 }}>透明度</Text>
                <Slider style={{ width: 120, margin: '0 8px' }} min={5} max={100} value={Math.round(watermarkOpacity * 100)} onChange={(v) => setWatermarkOpacity(v / 100)} />
                <Text style={{ fontSize: 12 }}>{Math.round(watermarkOpacity * 100)}%</Text>
                <Text style={{ fontSize: 12 }}>位置</Text>
                <Select size="small" style={{ width: 70 }} value={watermarkPosition} onChange={setWatermarkPosition} options={[
                  { value: 'bottom', label: '底部' },
                  { value: 'top', label: '顶部' },
                ]} />
              </Space>
            )}
          </div>

          {/* ── 图片角标默认尺寸 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8}>
              <Text strong style={{ fontSize: 13 }}>图片角标默认尺寸(px)</Text>
              <InputNumber size="small" min={0} max={800} value={badgeDefaultWidth || undefined} onChange={(v) => setBadgeDefaultWidth(v ?? 0)} style={{ width: 90 }} />
              <Text type="secondary" style={{ fontSize: 12 }}>0=保持原图尺寸</Text>
            </Space>
          </div>
        </Space>
      </Modal>

      {/* 工作流步骤条：每个步骤可点击跳转到对应界面 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          current={currentStep}
          size="small"
          items={WORKFLOW_STEPS.map((step, idx) => {
            const clickable = !!step.path;
            const isFinish = idx < currentStep;
            const isProcess = idx === currentStep;
            return {
              title: clickable ? (
                <a
                  onClick={() => navigate(`/episodes/${episodeId}${step.path}`)}
                  style={{
                    cursor: 'pointer',
                    color: isFinish || isProcess ? '#1677ff' : undefined,
                    fontWeight: isProcess ? 600 : undefined,
                  }}
                >
                  {step.title}
                </a>
              ) : step.title,
              description: step.description,
              status: isFinish ? 'finish' : isProcess ? 'process' : 'wait',
              icon: isFinish ? <CheckCircleOutlined /> : isProcess ? (
                <a onClick={() => clickable && navigate(`/episodes/${episodeId}${step.path}`)} style={{ display: 'inline-flex' }}>
                  <ClockCircleOutlined />
                </a>
              ) : <ClockCircleOutlined />,
            };
          })}
        />
      </Card>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="集数">{episode.episode_no ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="时长">{formatDuration(episode.duration)}</Descriptions.Item>
          <Descriptions.Item label="文件大小">{formatFileSize(episode.file_size)}</Descriptions.Item>
          <Descriptions.Item label="上传时间">{formatDateTime(episode.created_at)}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 工作流步骤引导提示 */}
      {workflowGuide()}

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {actions.map((a) => (
          <Col xs={24} md={8} key={a.title}>
            <Card size="small" title={a.title} style={{ height: '100%' }}>{a.node}</Card>
          </Col>
        ))}
      </Row>
    </div>
  );
};

export default EpisodeDetail;