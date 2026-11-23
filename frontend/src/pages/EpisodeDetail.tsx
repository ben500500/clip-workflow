import React, { useEffect, useRef, useState } from 'react';
import {
  Card, Button, Space, Typography, Spin, Alert, Breadcrumb, Descriptions, Tag, message, Select, Row, Col, Progress,
  Steps, InputNumber, Tooltip, Popconfirm, Switch, Slider, Input, Table, Upload, Image as AntImage, Radio, ColorPicker,
  Checkbox, Modal, Cascader, Popover, Collapse,
} from 'antd';
import {
  ArrowLeftOutlined, ThunderboltOutlined, RadarChartOutlined, ScissorOutlined,
  CheckCircleOutlined, ClockCircleOutlined, InfoCircleOutlined, PlayCircleOutlined,
  UploadOutlined, VideoCameraOutlined, DeleteOutlined as DelIcon, PlusOutlined, SettingOutlined, StopOutlined, PictureOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { autoclipApi } from '../api/autoclip';
import { intervalApi } from '../api/intervals';
import { sliceApi, type BadgeItem, type TextOverlayItem } from '../api/slice';
import ErrorHint from '../components/ErrorHint';
import DedupeManualConfig, { type DedupeManualConfigValue } from '../components/DedupeManualConfig';
import SubtitleMarginPicker from '../components/SubtitleMarginPicker';
import { useDedupePresets } from '../hooks/useDedupePresets';
import type { AutoClipRunRecord, Episode, IntervalHistoryItem, SliceTask } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';
import { buildSliceConfigTooltip } from '../utils/sliceConfigTooltip';
import { WATERMARK_STYLE_OPTIONS, WATERMARK_STYLE_LABEL } from '../utils/watermarkStyles';
import { DEFAULT_SLICE_PRESET, SLICE_ACTIVE_PRESET_KEY, SLICE_PRESET_STORAGE_KEY, VERT2HORIZON_OUTPUT_SIZES, loadPresetList, persistPresets, type SlicePreset } from '../utils/slicePresets';

const { Title, Text, Paragraph } = Typography;

// ─── 悬停预览（封面图 / 钩子视频） ───────────────────────────
// 鼠标移到文件名上时，延迟打开 Popover 并懒加载对应 file_key 的临时预览 URL。
// 图片用 <img> 显示、视频用 <video> 自动播放，松开/移开即收起。
// 传单个 fileKey 显示单条预览；传 fileKeys 数组（钩子文件夹）按网格展示全部视频预览。
function FileHoverPreview({
  fileKey,
  fileKeys,
  kind,
  children,
}: {
  fileKey?: string | null;
  fileKeys?: Array<string | null>;
  kind: 'image' | 'video';
  children: React.ReactNode;
}) {
  const keys = fileKeys && fileKeys.length > 0 ? fileKeys : fileKey ? [fileKey] : [];
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const fetchedRef = useRef<string | null>(null);

  const signature = keys.join('\u0001');
  const ensureUrls = async () => {
    if (fetchedRef.current === signature) return;
    fetchedRef.current = signature;
    setLoading(true);
    try {
      const entries = await Promise.all(
        keys.map(async (k) => {
          if (!k) return null;
          try {
            const res = await sliceApi.getRawPreviewUrl(k);
            return { k, url: res.url };
          } catch {
            return { k, url: null };
          }
        }),
      );
      const map: Record<string, string> = {};
      entries.forEach((e) => { if (e && e.url) map[e.k] = e.url; });
      setUrls(map);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) ensureUrls();
      }}
      trigger="hover"
      mouseEnterDelay={0.25}
      mouseLeaveDelay={0.1}
      content={
        <div style={{ maxWidth: 400, maxHeight: 280, overflow: 'auto' }}>
          {loading ? (
            <div style={{ width: 240, height: 140, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Spin size="small" />
            </div>
          ) : keys.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>预览不可用</Text>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {keys.map((k, idx) =>
                urls[k as string] ? (
                  kind === 'image' ? (
                    <img
                      key={k as string}
                      src={urls[k as string]}
                      alt={`预览 ${idx + 1}`}
                      style={{ maxWidth: 360, maxHeight: 240, display: 'block', objectFit: 'contain' }}
                    />
                  ) : (
                    <video
                      key={k as string}
                      src={urls[k as string]}
                      controls
                      autoPlay
                      muted
                      style={{ maxWidth: 360, maxHeight: 240, display: 'block', background: '#000' }}
                    />
                  )
                ) : (
                  <Text key={k as string} type="secondary" style={{ fontSize: 12 }}>
                    第 {idx + 1} 个：预览不可用
                  </Text>
                ),
              )}
            </div>
          )}
        </div>
      }
    >
      {children}
    </Popover>
  );
}

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
    detail: '在切割的同时对每个片段进行画面去重处理，采用「空间变换（缩放裁切）+ 时域变换（变速）+ 色彩变换（轻微降饱和）+ 轻微锐化/贴纸水印」组合，拉开与原素材的帧级特征/色彩直方图/时域指纹距离；统一不做镜像，明显影响画质的噪点/扫描线/复古偏色/色温/暗角/滚动暗带/抖动均去掉或降到最低，最大程度保留原画质。提供两套推荐配方（保守裁切降饱和=默认首选 / 复古扫描）及轻/标准/重三档，并支持「去重高级配置」逐项手动调整每个手段（裁切/镜像/变速/调色/噪点/锐化/暗角/滚动暗带/抖动/贴纸水印）。适用于需要批量发布到多个平台的场景，降低查重风险。',
  },
  scrub: {
    label: '挖洞模式',
    desc: '在去重基础上随机挖洞',
    detail: '在去重模式的基础上，进一步对片段中随机位置进行微小的画面挖洞处理（替换为纯色帧），使每个输出片段的指纹更加独特。适合高频发布场景，有效降低平台查重处罚。',
  },
};

// ─── 源字幕打码预设（三档，收敛 temporal/spatial 两个开关，降低配置出错率）──
const SUBTITLE_MASK_PRESETS = [
  { value: 'auto', label: '自动', desc: 'SRT动态窗口优先，兼顾效果与速度（推荐）' },
  { value: 'fine', label: '精细', desc: '帧级+空间子区域，最精确但更慢' },
  { value: 'quick', label: '快速', desc: '固定区域全程打码，最快' },
];
const SUBTITLE_MASK_PRESET_DEFAULT = 'auto';

// 根据预设对象推导当前打码预设值：显式 preset 优先；旧数据按 temporal/spatial 推导回退。
function resolveSubtitleMaskPreset(p: any): 'auto' | 'fine' | 'quick' {
  const v = (p && p.subtitle_mask_preset) ? String(p.subtitle_mask_preset) : '';
  if (['auto', 'fine', 'quick'].includes(v)) return v as 'auto' | 'fine' | 'quick';
  const t = !!(p && p.subtitle_mask_temporal);
  const s = !!(p && p.subtitle_mask_spatial);
  if (s) return 'fine';
  if (!t) return 'quick';
  return 'auto';
}

// ─── 切片模式级联选项（去重模式带档位，档位来自共享 hook 的 useDedupePresets）──
// 两套推荐配方说明见各档位 desc；档位 value/label 以后端 GET /api/dedupe/presets 为准。
const buildSliceModeOptions = (dedupePresets: { value: string; label: string }[]) => [
  { value: 'fast', label: '快速模式' },
  {
    value: 'dedupe',
    label: '去重模式',
    children: dedupePresets.map((p) => ({ value: p.value, label: p.label })),
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
// C2 收敛：SlicePreset / DEFAULT_SLICE_PRESET / 存储键 / loadPresetList / persistPresets
// 已统一到 utils/slicePresets.ts 作为单一事实源，三页面共用。

const EpisodeDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const episodeId = id || '';
  const { presetOptions } = useDedupePresets();
  const SLICE_MODE_OPTIONS = buildSliceModeOptions(presetOptions);

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detectMode, setDetectMode] = useState('credits');
  const [sliceMode, setSliceMode] = useState('fast');
  // 去重模式档位：轻/标准/重（老电视质感去重强度，默认标准档）
  const [dedupePreset, setDedupePreset] = useState<string>('std_crop_desat');
  // 输出档位：original / auto（默认）/ 1080p / 720p / 480p（高分辨率/高 fps 素材降档提速）
  const [outputTier, setOutputTier] = useState<string>('auto');
  // 一键切片去重模式开关（配置弹窗内可设，开启后一键切片按档位做画面去重）
  const [dedupeEnabled, setDedupeEnabled] = useState(false);
  // ── 视频封面（选择图片作为视频首帧，一键切片时下发） ──
  const [coverImageKey, setCoverImageKey] = useState<string | null>(null);
  const [coverImageName, setCoverImageName] = useState<string | null>(null);
  const [coverUploading, setCoverUploading] = useState(false);
  // ── 片尾视频（2026-11-23 用户需求）：拼接到每个成品末尾，与钩子独立 ──
  const [outroKey, setOutroKey] = useState<string | null>(() => localStorage.getItem('slice_outro_key') || null);
  const [outroList, setOutroList] = useState<{ file_key: string; file_name: string; file_size: number }[]>([]);
  const [outroUploading, setOutroUploading] = useState(false);
  const setOutroKeyPersist = (k: string | null) => {
    setOutroKey(k);
    if (k) localStorage.setItem('slice_outro_key', k);
    else localStorage.removeItem('slice_outro_key');
  };

  const handleCoverUpload = async (file: File) => {
    setCoverUploading(true);
    try {
      const res = await sliceApi.uploadBadge(file);
      if (mountedRef.current) {
        setCoverImageKey(res.file_key);
        setCoverImageName(res.file_name);
        // 封面按剧集独立存储：上传后同步写回该集，切片时用本集封面
        sliceApi.updateEpisodeCover(episodeId, res.file_key).catch((err: unknown) => {
          console.error('封面保存到剧集失败', err);
        });
        message.success(`封面已上传：${res.file_name}`);
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        message.error(err instanceof Error ? err.message : '封面上传失败');
      }
    } finally {
      if (mountedRef.current) setCoverUploading(false);
    }
    return false;
  };
  // ── 钩子视频（作为片头/片尾拼接，一键切片时下发） ──
  // 支持两种选择方式：整个文件夹 / 多选文件。
  // 选择后仅暂存在本页（hookPendingFiles），点「开始切片/一键切片」时才真正上传——
  // 避免选完即传的长时间等待；已上传的 keys 持久化到 localStorage（刷新可复用）。
  // 暂存中的 File 对象无法持久化，刷新页面后需重新选择（界面上有橙色「待上传」标记提示）。
  const [hookVideoKeys, setHookVideoKeys] = useState<string[]>([]);
  const [hookVideoNames, setHookVideoNames] = useState<string[]>([]);
  const [hookPendingFiles, setHookPendingFiles] = useState<File[]>([]);
  const [hookPendingNames, setHookPendingNames] = useState<string[]>([]);
  const [hookUploading, setHookUploading] = useState(false);
  // 钩子混搭模式：sequential（顺序循环）/ random（随机混搭）/ combine（拼接所有钩子）
  const [hookMixMode, setHookMixMode] = useState<'sequential' | 'random' | 'combine'>('sequential');
  // 钩子拼接位置：head=片头（默认，[封面][钩子][本体]）/ tail=片尾（[封面][本体][钩子]）
  const [hookPosition, setHookPosition] = useState<'head' | 'tail'>('head');
  // 钩子混搭输出数量：当模式为 random/combine 时，生成多个不同钩子组合的成品（-v1, -v2 后缀）
  const [hookMixOutputCount, setHookMixOutputCount] = useState<number>(1);
  // ── 角标保存库：从历史上传的角标直接选用（免重复上传） ──
  const [badgeLibraryOpen, setBadgeLibraryOpen] = useState(false);
  const [badgeLibraryLoading, setBadgeLibraryLoading] = useState(false);
  const [badgeLibraryItems, setBadgeLibraryItems] = useState<
    { file_key: string; file_name: string; file_size?: number; preview: string }[]
  >([]);

  // 钩子选择持久化：变化时写 localStorage（为空则清除）
  useEffect(() => {
    if (!episodeId) return;
    const k = `hook_video_${episodeId}`;
    try {
      if (hookVideoKeys.length > 0) {
        localStorage.setItem(k, JSON.stringify({ keys: hookVideoKeys, names: hookVideoNames }));
      } else {
        localStorage.removeItem(k);
      }
    } catch { /* 忽略存储异常 */ }
  }, [hookVideoKeys, hookVideoNames, episodeId]);

  // 页面加载恢复本集已选的钩子
  useEffect(() => {
    if (!episodeId) return;
    try {
      const raw = localStorage.getItem(`hook_video_${episodeId}`);
      if (raw) {
        const o = JSON.parse(raw);
        // 兼容旧版单钩子格式 {key, name}
        if (o && Array.isArray(o.keys)) {
          setHookVideoKeys(o.keys);
          setHookVideoNames(Array.isArray(o.names) ? o.names : []);
        } else if (o && o.key) {
          setHookVideoKeys([o.key]);
          setHookVideoNames(o.name ? [o.name] : []);
        }
      }
    } catch { /* 忽略 */ }
  }, [episodeId]);

  // 选择钩子（文件夹或多选文件）：仅暂存，不立即上传。
  // 新选择整体替换旧选择（含已上传的旧 keys）。
  const handleHookFilesSelected = (files: File[]) => {
    if (!files || files.length === 0) return;
    const videos = files.filter((f) => /\.(mp4|mov|avi|mkv|webm|flv|wmv|m4v|ts)$/i.test(f.name));
    if (videos.length === 0) {
      message.warning('所选位置没有视频文件');
      return;
    }
    setHookPendingFiles(videos);
    setHookPendingNames(videos.map((f) => f.name));
    // 新选择替换旧选择：清掉已上传的 keys（localStorage 由其 effect 联动清除）
    setHookVideoKeys([]);
    setHookVideoNames([]);
    message.info(`已选择 ${videos.length} 个钩子视频（暂存，开始切片时自动上传）`);
  };

  // 切片开始时上传暂存的钩子文件，返回可下发的 file_key 列表。
  // 无暂存文件时直接返回已上传的 keys；上传失败抛错由调用方终止切片。
  const uploadPendingHooks = async (): Promise<string[]> => {
    if (hookPendingFiles.length === 0) return hookVideoKeys;
    try {
      const res = await sliceApi.uploadHookFolder(hookPendingFiles);
      const keys = res.items.map((it) => it.file_key);
      const names = res.items.map((it) => it.file_name);
      if (res.errors && res.errors.length > 0) {
        message.warning(`部分文件未上传：${res.errors.join('；')}`);
      }
      if (keys.length === 0) {
        throw new Error('钩子视频上传后无可用文件');
      }
      setHookVideoKeys(keys);
      setHookVideoNames(names);
      setHookPendingFiles([]);
      setHookPendingNames([]);
      return keys;
    } catch (err: unknown) {
      // 吞掉本地状态清理（保持暂存，便于重试），错误抛给切片流程终止任务
      throw err instanceof Error ? err : new Error('钩子视频上传失败');
    }
  };

  // 清除钩子选择（暂存 + 已上传一并清掉）
  const clearHookSelection = () => {
    setHookPendingFiles([]);
    setHookPendingNames([]);
    setHookVideoKeys([]);
    setHookVideoNames([]);
  };

  // 钩子选择：AntD Upload（directory/multiple）都按文件逐个触发 beforeUpload，
  // 这里把同一批选择的文件累积到 ref，稍后统一暂存一次，避免重复暂存。
  const hookFilesRef = useRef<File[]>([]);
  const hookUploadTimerRef = useRef<number | null>(null);
  const collectHookFiles = (file: File) => {
    hookFilesRef.current.push(file);
    if (hookUploadTimerRef.current) clearTimeout(hookUploadTimerRef.current);
    hookUploadTimerRef.current = window.setTimeout(() => {
      const files = hookFilesRef.current;
      hookFilesRef.current = [];
      hookUploadTimerRef.current = null;
      if (files.length > 0) handleHookFilesSelected(files);
    }, 300);
    return false;
  };
  // ── 切片自定义文字水印开关与参数 ──
  // 去重模式手动配置（每项去重手段可单独覆盖预设，为空时沿用预设档位）
  const [dedupeManual, setDedupeManual] = useState<DedupeManualConfigValue>({});
  const [dedupeManualOpen, setDedupeManualOpen] = useState(false);
  // 多视频号素材去重：多版本生成数（null/1=不生成，零侵入；>1=切片后自动派生 N 个去重版本）
  const [variantCount, setVariantCount] = useState<number | undefined>(undefined);
  const [watermarkEnabled, setWatermarkEnabled] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [watermarkFontSize, setWatermarkFontSize] = useState(28);
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.5);
  const [watermarkPosition, setWatermarkPosition] = useState('bottom');
  const [watermarkStyle, setWatermarkStyle] = useState('scroll');
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
  // ── 高光混剪（把入选高光段按源时间顺序混剪拼接为一个成品）──
  const [highlightMixEnabled, setHighlightMixEnabled] = useState(false);
  // 双配模式：单次选点同时产出 正片段+高光爆点 两批候选（clip_type 区分）
  const [dualProfile, setDualProfile] = useState(false);
  // 双批混拼：高光批×N + 正片批×M 组成每条成品（高光在前/在后）
  const [dualMixEnabled, setDualMixEnabled] = useState(false);
  const [dualMixHighlightCount, setDualMixHighlightCount] = useState(2);
  const [dualMixMainCount, setDualMixMainCount] = useState(1);
  const [dualMixHighlightPosition, setDualMixHighlightPosition] = useState<'head' | 'tail'>('head');
  const [dualMixOutputCount, setDualMixOutputCount] = useState<number | null>(null);
  // 输出总时长上限（秒，可选）：累计各高光段不超过该值，最后一段会超额时丢弃
  const [highlightMixMaxDuration, setHighlightMixMaxDuration] = useState<number | null>(null);
  // 单段最大时长（秒，可选）：仅纳入时长不超过该值的短高光段
  const [highlightMixMaxClipDuration, setHighlightMixMaxClipDuration] = useState<number | null>(null);
  // 拼接顺序：time（源时间顺序，默认）/ score（评分从高到低）
  const [highlightMixOrder, setHighlightMixOrder] = useState<'time' | 'score' | 'random'>('time');
  // 输出文件个数（默认 1=单成品）：>1 时把入选段分组填充产出 N 个混剪文件，
  // 「输出总时长上限」语义变为每个文件的时长上限；未设上限时按段数均分
  const [highlightMixOutputCount, setHighlightMixOutputCount] = useState<number>(1);
  // Remotion 混剪增强（任务级）：切片完成后走 Remotion 引擎渲染增强版混剪
  // （片头/转场/字幕/段标题/片尾）；全局能力开关在系统设置页。
  const [remotionMixEnabled, setRemotionMixEnabled] = useState(false);
  // ── Remotion 片头片尾自定义（默认全部关闭 = 不配置 → 无片头片尾直接正片）──
  const [remotionIntroEnabled, setRemotionIntroEnabled] = useState(false);
  const [remotionIntroTitle, setRemotionIntroTitle] = useState('');
  const [remotionIntroEpisode, setRemotionIntroEpisode] = useState('');
  const [remotionIntroCover, setRemotionIntroCover] = useState(true);
  const [remotionIntroDuration, setRemotionIntroDuration] = useState<number>(3);
  const [remotionIntroBg, setRemotionIntroBg] = useState('#0d0d12');
  const [remotionOutroEnabled, setRemotionOutroEnabled] = useState(false);
  const [remotionOutroText, setRemotionOutroText] = useState('感谢观看');
  const [remotionOutroSubtitle, setRemotionOutroSubtitle] = useState('点赞 · 收藏 · 关注');
  const [remotionOutroDuration, setRemotionOutroDuration] = useState<number>(2.5);
  const [remotionOutroBg, setRemotionOutroBg] = useState('#0d0d12');
  // 高光混剪设置弹窗是否打开
  const [highlightMixModalOpen, setHighlightMixModalOpen] = useState(false);
  // Remotion 片头片尾配置弹窗是否打开
  const [remotionIntroOutroModalOpen, setRemotionIntroOutroModalOpen] = useState(false);
  // ── ASR 字幕烧录开关 ──
  const [subtitleEnabled, setSubtitleEnabled] = useState(false);
  // 字幕字号（相对输出视频高度的比例，默认 0.30→FontSize 30；转横屏开启时默认套用，用户可调）
  const [subtitleFontRatio, setSubtitleFontRatio] = useState(0.30);
  // 字幕高度（距画面底边的比例，默认 1/4=0.25，字幕块中心约在 3/4 屏高处）
  const [subtitleMarginRatio, setSubtitleMarginRatio] = useState(0.25);
  // 字幕字间距（ASS Spacing 像素，默认 -1 更紧凑；调小/负值让字幕文字更紧凑，调大则字距变宽）
  const [subtitleSpacing, setSubtitleSpacing] = useState(-2);
  // 字幕字体粗细（ASS Bold：0=不加粗，-1 或 1=加粗，默认 0 不加粗；加粗让字幕更醒目）
  const [subtitleBold, setSubtitleBold] = useState(0);
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
  const [subtitleMaskStyle, setSubtitleMaskStyle] = useState<'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill'>('delogo');
  // 精细化（帧级检测）：只在字幕/水印实际出现的时段打码
  const [subtitleMaskTemporal, setSubtitleMaskTemporal] = useState(true);
  // 仅字幕显示区域打码（空间精细化）：需开启精细化后才能开启
  const [subtitleMaskSpatial, setSubtitleMaskSpatial] = useState(false);
  // 打码预设（三档：自动/精细/快速），收敛上面两个开关
  const [subtitleMaskPreset, setSubtitleMaskPreset] = useState<string>('auto');
  const [subtitleMaskWidthRatio, setSubtitleMaskWidthRatio] = useState(0.9);
  const [subtitleMaskHeightRatio, setSubtitleMaskHeightRatio] = useState(0.12);
  const [subtitleMaskBottomRatio, setSubtitleMaskBottomRatio] = useState(0.02);
  // 打码时间轴整体偏移（秒）：校正 ASR 字幕时间与画面字幕偏差（字幕滞后用正值延后）
  const [subtitleMaskSrtOffset, setSubtitleMaskSrtOffset] = useState(0);
  // 字幕对齐源字幕打码区域（默认开启）：开启后 ASR 字幕位置对齐到检测到的打码区域
  const [subtitleAlignMask, setSubtitleAlignMask] = useState(true);
  const [subtitleMaskModalOpen, setSubtitleMaskModalOpen] = useState(false);
  // ── 恒定水印/角标打码（打掉片源固定水印，独立开关） ──
  const [watermarkMaskEnabled, setWatermarkMaskEnabled] = useState(false);
  const [watermarkMaskStyle, setWatermarkMaskStyle] = useState<'delogo' | 'mosaic' | 'blur' | 'gblur' | 'fill'>('delogo');
  const [watermarkMaskWidthRatio, setWatermarkMaskWidthRatio] = useState(0.9);
  const [watermarkMaskHeightRatio, setWatermarkMaskHeightRatio] = useState(0.12);
  const [watermarkMaskBottomRatio, setWatermarkMaskBottomRatio] = useState(0.02);
  const [watermarkMaskModalOpen, setWatermarkMaskModalOpen] = useState(false);
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
  // 画面理解（AI 选点时对候选片段抽帧分析画面，辅助打分）：默认开启
  // 视觉模型提供商默认走在线（llm，OpenAI 兼容网关如 MiMo/Agnes），本地 ollama 为可选回退
  const [frameAnalysis, setFrameAnalysis] = useState(true);
  // 画面理解视觉模型提供商：`ollama`（本地）/ `llm`（在线 OpenAI 兼容视觉模型如 MiMo/Agnes）
  const [frameAnalysisProvider, setFrameAnalysisProvider] = useState('llm');
  // ── 高光识别（AI 选点找出多段 ≤10s 的短高光片段）──
  const [highlightMode, setHighlightMode] = useState(false);
  // 高光单段最大时长（秒，默认 10）：仅保留不超过该时长的短高光
  const [highlightMaxDuration, setHighlightMaxDuration] = useState<number>(10);
  // 高光识别配置弹窗是否打开
  const [highlightModalOpen, setHighlightModalOpen] = useState(false);
  const [autoclipProgress, setAutoclipProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  const [autoclipRunning, setAutoclipRunning] = useState(false);
  const [detectRunning, setDetectRunning] = useState(false);
  const [detectProgress, setDetectProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null; interval_count?: number | null; interval_type?: string | null } | null>(null);
  const [detectResultCount, setDetectResultCount] = useState<number | null>(null);
  const [sliceRunning, setSliceRunning] = useState(false);
  // 开始切片时选择的 AI 选点历史（用于补选点配置复用）
  const [sliceAutoclipRunId, setSliceAutoclipRunId] = useState<string | undefined>(undefined);
  const [sliceProgress, setSliceProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  // 快速转换（跳过 AI 选点/区间检测，整片应用下方配置直接出片，位于「开始切片」旁）
  const [quickConverting, setQuickConverting] = useState(false);
  const [quickProgress, setQuickProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  // ── 选点 LLM 快捷配置（2026-11-23 用户需求：选点界面直接配置 LLM）──
  // preset: system=跟随系统设置；mimo=小米 MiMo；qwen=通义 qwen-plus；custom=自定义
  // 密钥不落盘（仅本次会话内存），模型/地址记忆在浏览器
  const [llmPreset, setLlmPreset] = useState<string>(() => {
    // 迁移历史值：'mimo' 预设已被仓库条目取代；'qwen' 预设指向已删除条目
    const stored = localStorage.getItem('ac_llm_preset') || 'system';
    if (stored === 'mimo') return 'saved:小米 MiMo';
    if (stored === 'qwen') return 'system';
    return stored;
  });
  const [llmCustom, setLlmCustom] = useState<{ model: string; base: string; key: string }>(() => {
    try {
      const raw = localStorage.getItem('ac_llm_custom');
      if (raw) return JSON.parse(raw);
    } catch { /* 坏数据走默认 */ }
    return { model: '', base: '', key: '' };
  });
  // 自定义模型：连通性测试 + 保存进仓库（用户需求 2026-11-23）
  const [llmTesting, setLlmTesting] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<{ ok: boolean; latency_ms: number; error?: string; reply?: string } | null>(null);
  const [llmSavingRepo, setLlmSavingRepo] = useState(false);
  const handleLlmTest = async () => {
    if (!llmCustom.model.trim()) { message.warning('请先填写模型名'); return; }
    setLlmTesting(true);
    try {
      const r = await autoclipApi.llmTest({
        model: llmCustom.model, api_base: llmCustom.base, api_key: llmCustom.key || undefined,
      });
      setLlmTestResult(r);
      if (r.ok) message.success(`连通正常（${r.latency_ms}ms，回复：${(r.reply || '').slice(0, 20)}）`);
      else message.error(`连通失败（${r.latency_ms}ms）：${r.error || '未知错误'}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '测试请求失败';
      setLlmTestResult({ ok: false, latency_ms: 0, error: msg });
      message.error(msg);
    } finally {
      setLlmTesting(false);
    }
  };
  const handleLlmSaveRepo = async () => {
    if (!llmCustom.model.trim()) { message.warning('请先填写模型名'); return; }
    setLlmSavingRepo(true);
    try {
      const name = llmCustom.model; // 仓库名称默认=模型名，同名覆盖
      await autoclipApi.saveLlmModel({
        name, model: llmCustom.model, api_base: llmCustom.base, api_key: llmCustom.key || undefined,
      });
      setLlmPresetPersist(`saved:${name}`);
      refreshLlmRepo();
      message.success(`已保存到模型仓库：${name}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setLlmSavingRepo(false);
    }
  };
  const refreshLlmRepo = () => {
    autoclipApi.llmModels().then((list) => setLlmRepo(list || [])).catch(() => undefined);
  };
  const setLlmPresetPersist = (v: string) => {
    setLlmPreset(v);
    localStorage.setItem('ac_llm_preset', v);
  };
  // 模型仓库（系统设置 llm_config.models，服务端保管密钥；下拉按名称选择，
  // 选点时只发 llm_model_name，密钥由服务端解析注入）
  const [llmRepo, setLlmRepo] = useState<{ name: string; model: string; api_base?: string }[]>([]);
  const setLlmCustomPersist = (patch: Partial<{ model: string; base: string; key: string }>) => {
    setLlmCustom((prev) => {
      const next = { ...prev, ...patch };
      localStorage.setItem('ac_llm_custom', JSON.stringify({ model: next.model, base: next.base, key: '' }));
      return next;
    });
  };
  // 业务线下拉折叠的展开状态（默认展开选片线起点+切片执行提交点，偏好记忆 localStorage）
  const [openLines, setOpenLines] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem('slice_open_lines');
      if (raw) return JSON.parse(raw);
    } catch { /* 坏数据走默认 */ }
    return ['⚙ 切片执行 · 汇聚提交'];
  });
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
        if (mountedRef.current) {
          setEpisode(data);
          // 封面按剧集独立存储：进入页面时从剧集恢复（不再从个人账号恢复）
          setCoverImageKey(data.cover_image_key || null);
          if (data.cover_image_key) {
            setCoverImageName(null);
          }
        }
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

  // 删除单条选点执行历史记录
  const handleDeleteAutoclipHistory = async (runId: string) => {
    try {
      const res = await autoclipApi.deleteHistory(episodeId, runId);
      // 若被删的正是「选点历史」下拉中选中的那条，清除选择，避免引用已删除记录
      if (sliceAutoclipRunId === runId) setSliceAutoclipRunId(undefined);
      message.success(res?.message || '选点执行记录已删除');
      fetchAutoclipHistory();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
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

  // ── 一键切片配置预设：加载 / 保存 / 应用（C2 收敛到 utils/slicePresets.ts） ──
  const loadPresets = React.useCallback((): SlicePreset => {
    // 读取完整列表（默认头 + 自定义）并解析激活 id；始终保证默认配置在列表头部
    const { presets: list, activeId } = loadPresetList();
    setPresets(list);
    setActivePresetId(activeId);
    return list.find((p) => p.id === activeId) || DEFAULT_SLICE_PRESET;
  }, []);

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
    subtitle_margin_ratio: subtitleMarginRatio,
    subtitle_spacing: subtitleSpacing,
    subtitle_bold: subtitleBold,
    subtitle_style: subtitleStyle,
    subtitle_color: subtitleColor,
    subtitle_border_color: subtitleBorderColor,
    subtitle_mask_enabled: subtitleMaskEnabled,
    subtitle_mask_style: subtitleMaskStyle,
    subtitle_mask_temporal: subtitleMaskTemporal,
    subtitle_mask_spatial: subtitleMaskTemporal ? subtitleMaskSpatial : false,
    subtitle_mask_preset: subtitleMaskPreset,
    subtitle_mask_width_ratio: subtitleMaskWidthRatio,
    subtitle_mask_height_ratio: subtitleMaskHeightRatio,
    subtitle_mask_bottom_ratio: subtitleMaskBottomRatio,
    subtitle_mask_srt_offset: subtitleMaskSrtOffset,
    subtitle_align_mask: subtitleAlignMask,
    watermark_mask_enabled: watermarkMaskEnabled,
    watermark_mask_style: watermarkMaskStyle,
    watermark_mask_width_ratio: watermarkMaskWidthRatio,
    watermark_mask_height_ratio: watermarkMaskHeightRatio,
    watermark_mask_bottom_ratio: watermarkMaskBottomRatio,
    text_overlay_enabled: textOverlayEnabled,
    text_overlays: textOverlays.map((t) => ({ text: t.text, position: t.position, font_size: t.font_size, color: t.color, border_color: t.border_color, vertical: t.vertical, offset: t.offset })),
    watermark_enabled: watermarkEnabled,
    watermark_text: watermarkText,
    watermark_font_size: watermarkFontSize,
    watermark_opacity: watermarkOpacity,
    watermark_position: watermarkPosition,
    watermark_style: watermarkStyle,
    badge_default_width: badgeDefaultWidth,
    dedupe_enabled: dedupeEnabled,
    dedupe_preset: dedupePreset,
    output_tier: outputTier,
    // AI 智能选点参数（随预设持久化，缺失时按页面默认）
    max_clips: maxClips,
    min_score_threshold: minScoreThreshold ?? null,
    min_clip_duration: minClipDuration ?? null,
    max_clip_duration: maxClipDuration ?? null,
    frame_analysis: frameAnalysis,
    frame_analysis_provider: frameAnalysisProvider,
    highlight_mode: highlightMode,
    highlight_max_duration: highlightMode ? highlightMaxDuration : undefined,
    highlight_mix_enabled: highlightMixEnabled && !dualMixEnabled,
    highlight_mix_max_duration: highlightMixMaxDuration ?? undefined,
    highlight_mix_max_clip_duration: highlightMixMaxClipDuration ?? undefined,
    highlight_mix_order: highlightMixOrder,
    highlight_mix_output_count: highlightMixOutputCount,
    // 双批混拼：高光批×N + 正片批×M（与高光混剪互斥，双批优先）
    dual_mix_enabled: dualMixEnabled,
    dual_mix_highlight_count: dualMixHighlightCount,
    dual_mix_main_count: dualMixMainCount,
    dual_mix_highlight_position: dualMixHighlightPosition,
    dual_mix_output_count: dualMixOutputCount ?? undefined,
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
    setSubtitleMarginRatio(p.subtitle_margin_ratio ?? 0.25);
    setSubtitleSpacing(p.subtitle_spacing ?? -2);
    setSubtitleBold(p.subtitle_bold ?? 0);
    setSubtitleStyle(p.subtitle_style);
    setSubtitleColor(p.subtitle_color);
    setSubtitleBorderColor(p.subtitle_border_color);
    setSubtitleMaskEnabled(p.subtitle_mask_enabled ?? false);
    setSubtitleMaskStyle(p.subtitle_mask_style ?? 'delogo');
    setSubtitleMaskTemporal(p.subtitle_mask_temporal ?? true);
    setSubtitleMaskSpatial(p.subtitle_mask_spatial ?? false);
    // 预设优先；旧预设没有 preset 字段时按 temporal/spatial 推导回退（向后兼容）
    setSubtitleMaskPreset(resolveSubtitleMaskPreset(p));
    setSubtitleMaskWidthRatio(p.subtitle_mask_width_ratio ?? 0.9);
    setSubtitleMaskHeightRatio(p.subtitle_mask_height_ratio ?? 0.12);
    setSubtitleMaskBottomRatio(p.subtitle_mask_bottom_ratio ?? 0.02);
    setSubtitleMaskSrtOffset(p.subtitle_mask_srt_offset ?? 0);
    setSubtitleAlignMask(p.subtitle_align_mask ?? true);
    setWatermarkMaskEnabled(p.watermark_mask_enabled ?? false);
    setWatermarkMaskStyle(p.watermark_mask_style ?? 'delogo');
    setWatermarkMaskWidthRatio(p.watermark_mask_width_ratio ?? 0.9);
    setWatermarkMaskHeightRatio(p.watermark_mask_height_ratio ?? 0.12);
    setWatermarkMaskBottomRatio(p.watermark_mask_bottom_ratio ?? 0.02);
    setTextOverlayEnabled(p.text_overlay_enabled);
    setTextOverlays(p.text_overlays.map((t) => ({ ...t, id: `tov_preset_${t.position}_${t.text}` })));
    setWatermarkEnabled(p.watermark_enabled);
    setWatermarkText(p.watermark_text);
    setWatermarkFontSize(p.watermark_font_size);
    setWatermarkOpacity(p.watermark_opacity);
    setWatermarkPosition(p.watermark_position);
    setWatermarkStyle(p.watermark_style || 'scroll');
    setBadgeDefaultWidth(p.badge_default_width);
    setDedupeEnabled(p.dedupe_enabled ?? false);
    setDedupePreset(p.dedupe_preset ?? 'std_crop_desat');
    setOutputTier(p.output_tier ?? 'auto');
    // AI 智能选点参数（预设优先，缺失回退页面默认）
    setMaxClips(p.max_clips ?? 10);
    setMinScoreThreshold(p.min_score_threshold != null ? p.min_score_threshold : null);
    setMinClipDuration(p.min_clip_duration != null ? p.min_clip_duration : null);
    setMaxClipDuration(p.max_clip_duration != null ? p.max_clip_duration : null);
    setFrameAnalysis(p.frame_analysis ?? true);
    setFrameAnalysisProvider(p.frame_analysis_provider ?? 'llm');
    setHighlightMode(p.highlight_mode ?? false);
    if (p.highlight_mode && p.highlight_max_duration != null) setHighlightMaxDuration(p.highlight_max_duration);
    setHighlightMixEnabled(p.highlight_mix_enabled ?? false);
    setDualMixEnabled(p.dual_mix_enabled ?? false);
    setDualMixHighlightCount(p.dual_mix_highlight_count ?? 2);
    setDualMixMainCount(p.dual_mix_main_count ?? 1);
    setDualMixHighlightPosition((p.dual_mix_highlight_position as 'head' | 'tail') ?? 'head');
    setDualMixOutputCount(p.dual_mix_output_count ?? null);
    setHighlightMixMaxDuration(p.highlight_mix_max_duration ?? null);
    setHighlightMixMaxClipDuration(p.highlight_mix_max_clip_duration ?? null);
    setHighlightMixOrder((p.highlight_mix_order as 'time' | 'score' | 'random') ?? 'time');
    setHighlightMixOutputCount(p.highlight_mix_output_count ?? 1);
    setActivePresetId(p.id);
  };

  useEffect(() => {
    // 首次进入默认应用默认配置（竖屏转横屏开 / ASR字幕开 / 固定文字开），
    // 若用户保存过预设则应用上次激活的那套
    const toApply = loadPresets();
    applyPreset(toApply);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadPresets]);

  // ── 个人账号切片配置：进入页面加载 + 防抖自动保存（跨设备/浏览器持久化） ──
  const saveUserPrefsTimer = useRef<number | null>(null);
  const userPrefLoadedRef = useRef(false);

  // 选择预设并应用
  const handleSelectPreset = (id: string) => {
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    applyPreset(preset);
    persistPresets(presets, id);
    message.success(`已应用配置「${preset.name}」`);
  };

  // 收集需持久化到个人账号的切片配置（含切片模式/去重档位/AI 选点参数；封面按剧集存储不入个人配置）
  const collectPersistConfig = () => ({
    sliceMode,
    dedupePreset,
    ...collectCurrentPresetConfig(),
    badge_default_width: badgeDefaultWidth,
    // AI 智能选点参数
    autoclip_max_clips: maxClips,
    autoclip_min_score_threshold: minScoreThreshold,
    autoclip_min_duration: minClipDuration,
    autoclip_max_duration: maxClipDuration,
    autoclip_frame_analysis: frameAnalysis,
    autoclip_frame_analysis_provider: frameAnalysisProvider,
    autoclip_highlight_mode: highlightMode,
    autoclip_highlight_max_duration: highlightMaxDuration,
  });

  // 应用个人账号配置到当前页面状态
  const applyPersistConfig = (cfg: Record<string, unknown>) => {
    if (cfg.sliceMode) setSliceMode(String(cfg.sliceMode));
    if (cfg.dedupePreset) setDedupePreset(String(cfg.dedupePreset));
    // AI 智能选点参数
    if (typeof cfg.autoclip_max_clips === 'number') setMaxClips(cfg.autoclip_max_clips);
    if (typeof cfg.autoclip_min_score_threshold === 'number') setMinScoreThreshold(cfg.autoclip_min_score_threshold);
    if (typeof cfg.autoclip_min_duration === 'number') setMinClipDuration(cfg.autoclip_min_duration);
    if (typeof cfg.autoclip_max_duration === 'number') setMaxClipDuration(cfg.autoclip_max_duration);
    if (typeof cfg.autoclip_frame_analysis === 'boolean') setFrameAnalysis(cfg.autoclip_frame_analysis);
    if (typeof cfg.autoclip_frame_analysis_provider === 'string') setFrameAnalysisProvider(cfg.autoclip_frame_analysis_provider);
    if (typeof cfg.autoclip_highlight_mode === 'boolean') setHighlightMode(cfg.autoclip_highlight_mode);
    if (typeof cfg.autoclip_highlight_max_duration === 'number') setHighlightMaxDuration(cfg.autoclip_highlight_max_duration);
    // 应用云端个人配置时保留用户当前激活的预设 id（从 localStorage 读），
    // 避免把 activePresetId 覆盖成不存在的 'cloud' 占位 id，
    // 否则「选择配置」下拉会因为 value 无匹配选项而显示出一个名为 "cloud" 的幽灵配置。
    const savedActive = localStorage.getItem(SLICE_ACTIVE_PRESET_KEY);
    const keepId = savedActive && presets.some((p) => p.id === savedActive) ? savedActive : DEFAULT_SLICE_PRESET.id;
    applyPreset({ ...collectCurrentPresetConfig(), ...cfg, id: keepId, name: '个人配置' } as SlicePreset);
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

  // 拉取已保存片尾视频库（失败静默）
  useEffect(() => {
    sliceApi.outroVideos().then((list) => setOutroList(list || [])).catch(() => undefined);
  }, []);

  // 拉取模型仓库（下拉项；失败静默走快捷预设）
  useEffect(() => {
    autoclipApi.llmModels().then((list) => setLlmRepo(list || [])).catch(() => undefined);
  }, []);

  // 进入页面时从个人账号加载已保存配置，覆盖默认值（保证下次进入不恢复初始状态）
  useEffect(() => {
    let cancelled = false;
    sliceApi.getPreferences().then((res) => {
      if (cancelled) return;
      userPrefLoadedRef.current = true;
      if (res.slice_config) {
        applyPersistConfig(res.slice_config as Record<string, unknown>);
      }
    }).catch(() => {
      userPrefLoadedRef.current = true;
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 配置变化后防抖自动保存到个人账号（已从后端加载过个人配置后才写入，避免挂载初覆盖）
  useEffect(() => {
    if (!userPrefLoadedRef.current) return;
    if (saveUserPrefsTimer.current) window.clearTimeout(saveUserPrefsTimer.current);
    saveUserPrefsTimer.current = window.setTimeout(() => {
      sliceApi.savePreferences(collectPersistConfig() as Record<string, unknown>).catch(() => {
        // 保存失败静默，不阻塞操作
      });
    }, 600);
    return () => {
      if (saveUserPrefsTimer.current) window.clearTimeout(saveUserPrefsTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    sliceMode, dedupePreset, vert2horizEnabled, vert2horizMode, vert2horizRatio,
    vert2horizOutputSize, vert2horizDetectInterval, vert2horizSmoothWindow,
    vert2horizMinStep, vert2horizFaceMargin, subtitleEnabled, subtitleFontRatio,
    subtitleMarginRatio, subtitleSpacing, subtitleBold, subtitleStyle, subtitleColor, subtitleBorderColor,
    subtitleMaskEnabled, subtitleMaskStyle, subtitleMaskTemporal, subtitleMaskSpatial,
    subtitleMaskPreset, subtitleMaskWidthRatio, subtitleMaskHeightRatio, subtitleMaskBottomRatio,
    subtitleMaskSrtOffset, subtitleAlignMask,
    watermarkMaskEnabled, watermarkMaskStyle, watermarkMaskWidthRatio, watermarkMaskHeightRatio,
    watermarkMaskBottomRatio, textOverlayEnabled, textOverlays, watermarkEnabled, watermarkText,
    watermarkFontSize, watermarkOpacity, watermarkPosition, watermarkStyle, badgeDefaultWidth,
    dedupeEnabled, outputTier,
    maxClips, minScoreThreshold, minClipDuration, maxClipDuration, frameAnalysis,
    // 高光识别 / 高光混剪及其子参数：不加入则切换开关不会触发自动保存，
    // 刷新页面后被预设重置回默认关闭（用户感知为「开关状态没保存」）
    frameAnalysisProvider,
    highlightMode, highlightMaxDuration,
    highlightMixEnabled, highlightMixMaxDuration, highlightMixMaxClipDuration, highlightMixOrder, highlightMixOutputCount,
  ]);

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
      // 2026-11-21：processing（Remotion 渲染中）纳入进度显示——其进度由渲染管线直接回写 DB，
      // 此前页面加载恢复时该状态不启动轮询，进度条消失（用户问「切片执行时的进度显示呢」）
      if (latest.status === 'running' || latest.status === 'pending' || latest.status === 'processing') {
        setSliceRunning(true);
        setSliceProgress({
          status: 'running',
          progress: latest.progress || 0,
          message: latest.status === 'pending'
            ? '切片任务排队中，等待处理…'
            : latest.status === 'processing'
              ? 'Remotion 增强渲染中（进度来自渲染管线）…'
              : `切片任务运行中（${latest.mode}）…`,
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
              status: t.status === 'running' || t.status === 'pending' || t.status === 'processing' ? 'running' : t.status || 'unknown',
              progress: t.progress || 0,
              message: t.status === 'running' || t.status === 'pending'
                ? `切片任务运行中（${t.mode || latest.mode}）…`
                : t.status === 'processing'
                  ? 'Remotion 增强渲染中（进度来自渲染管线）…'
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
        frame_analysis_provider: frameAnalysisProvider,
        highlight_mode: highlightMode,
        highlight_max_duration: highlightMode ? highlightMaxDuration : undefined,
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
          status: t.status === 'running' || t.status === 'pending' || t.status === 'processing' ? 'running' : t.status || 'unknown',
          progress: t.progress || 0,
          message: t.status === 'running' || t.status === 'pending'
            ? `切片任务运行中（${t.mode || mode}）…`
            : t.status === 'processing'
              ? 'Remotion 增强渲染中（进度来自渲染管线）…'
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

  const openBadgeLibrary = async () => {
    setBadgeLibraryOpen(true);
    setBadgeLibraryLoading(true);
    try {
      const res = await sliceApi.listBadges();
      setBadgeLibraryItems(res.items || []);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '角标库加载失败');
    } finally {
      setBadgeLibraryLoading(false);
    }
  };

  const pickBadgeFromLibrary = (item: { file_key: string; file_name: string; preview: string }) => {
    setBadges((prev) =>
      prev.some((b) => b.file_key === item.file_key)
        ? prev
        : [...prev, { file_key: item.file_key, position: 'top-left', name: item.file_name, preview: item.preview }],
    );
    message.success(`角标「${item.file_name}」已添加`);
    setBadgeLibraryOpen(false);
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

  // ─── 补选点配置：选择某套 AI 选点历史时复用其参数，否则用当前表单值 ──
  const resolveAutoclipConfig = () => {
    const selected = sliceAutoclipRunId
      ? autoclipHistory.find((h) => h.id === sliceAutoclipRunId)
      : undefined;
    const llmExtra = (): Record<string, unknown> => {
      if (llmPreset.startsWith('saved:')) {
        // 仓库模型：只发名称，服务端解析注入（含密钥，不经过前端）
        return { llm_model_name: llmPreset.slice(6) };
      }
      if (llmPreset === 'custom') {
        return {
          ...(llmCustom.model ? { llm_model: llmCustom.model } : {}),
          ...(llmCustom.base ? { llm_api_base: llmCustom.base } : {}),
          ...(llmCustom.key ? { llm_api_key: llmCustom.key } : {}),
        };
      }
      return {};
    };
    if (selected && selected.config) {
      const c = selected.config as Record<string, unknown>;
      return {
        ...llmExtra(),
        dual_profile: dualProfile || undefined,
        max_clips: c.max_clips != null ? Number(c.max_clips) : undefined,
        min_score_threshold: c.min_score_threshold != null ? Number(c.min_score_threshold) : undefined,
        min_duration: c.min_duration != null ? Number(c.min_duration) : undefined,
        max_duration: c.max_duration != null ? Number(c.max_duration) : undefined,
        frame_analysis: typeof c.frame_analysis === 'boolean' ? c.frame_analysis : undefined,
        frame_analysis_provider: typeof c.frame_analysis_provider === 'string' ? c.frame_analysis_provider : undefined,
        highlight_mode: typeof c.highlight_mode === 'boolean' ? c.highlight_mode : undefined,
        highlight_max_duration: c.highlight_max_duration != null ? Number(c.highlight_max_duration) : undefined,
      };
    }
    return {
      ...llmExtra(),
      dual_profile: dualProfile || undefined,
      max_clips: maxClips,
      min_score_threshold: minScoreThreshold ?? undefined,
      min_duration: minClipDuration ?? undefined,
      max_duration: maxClipDuration ?? undefined,
      frame_analysis: frameAnalysis,
      frame_analysis_provider: frameAnalysisProvider,
      highlight_mode: highlightMode,
      highlight_max_duration: highlightMode ? highlightMaxDuration : undefined,
    };
  };

  // ─── 一键切片（免审核直接出片） ──────────────────────
  // ── 切片 payload 单源组装（2026-11-20 评审 #9）──────────────────
  // 此前「一键切片」「开始切片/快速转换」各手抄一份 ~90 字段 payload，条件已经
  // 漂移（dedupe 门控一边用 dedupeEnabled、一边用 mode === 'dedupe'）。抽成单源
  // builder：公共字段只写一遍，两处调用只传差异项。dedupeOn 由调用方传入以保留
  // 两入口历史语义（一键=dedupeEnabled 独立开关；主路径=sliceMode==='dedupe'）。
  const buildSlicePayload = (args: {
    hookKeys: string[];
    hooksActive: boolean;
    noCut?: boolean;
    autoAcceptAll?: boolean;
    dedupeOn: boolean;
  }) => ({
    no_cut: args.noCut || undefined,
    auto_accept_all: args.autoAcceptAll || undefined,
    // 无候选片段时自动补一轮 AI 选点（复用所选选点历史参数）
    auto_autoclip_if_empty: true,
    autoclip_config: resolveAutoclipConfig(),
    // 视频封面（首帧）：选择图片作为成品视频首帧
    cover_image_key: coverImageKey || undefined,
    // 钩子视频：作为片头/片尾拼接（[封面][钩子][本体] 或 [封面][本体][钩子]）
    hook_video_keys: args.hooksActive ? args.hookKeys : undefined,
    // 片尾视频：拼接到每个成品末尾（与钩子独立）
    outro_video_key: outroKey || undefined,
    hook_video_key: args.hooksActive && args.hookKeys.length === 1 ? args.hookKeys[0] : undefined,
    // 钩子混搭模式：多钩子时生效（sequential/random/combine）
    hook_mix_mode: args.hooksActive ? (hookMixMode || 'sequential') : undefined,
    // 钩子拼接位置（head=片头默认 / tail=片尾）
    hook_position: args.hooksActive ? hookPosition : undefined,
    // 钩子混搭输出数量：random/combine 模式；高光混剪有自己的输出个数（cutlist 组数），
    // 两者并存会按组相乘导致输出爆炸 → 高光混剪开启时忽略
    hook_mix_output_count: args.hooksActive && !highlightMixEnabled && (hookMixMode === 'random' || hookMixMode === 'combine') && hookMixOutputCount > 1 ? hookMixOutputCount : undefined,
    // 高光混剪：把入选高光段按源时间顺序混剪拼接为一个成品
    highlight_mix_enabled: highlightMixEnabled,
    highlight_mix_max_duration: highlightMixEnabled ? (highlightMixMaxDuration ?? undefined) : undefined,
    highlight_mix_max_clip_duration: highlightMixEnabled ? (highlightMixMaxClipDuration ?? undefined) : undefined,
    highlight_mix_order: highlightMixEnabled ? highlightMixOrder : undefined,
    highlight_mix_output_count: highlightMixEnabled ? highlightMixOutputCount : undefined,
    dual_mix_enabled: dualMixEnabled,
    dual_mix_highlight_count: dualMixEnabled ? dualMixHighlightCount : undefined,
    dual_mix_main_count: dualMixEnabled ? dualMixMainCount : undefined,
    dual_mix_highlight_position: dualMixEnabled ? dualMixHighlightPosition : undefined,
    dual_mix_output_count: dualMixEnabled ? (dualMixOutputCount ?? undefined) : undefined,
    remotion_mix_enabled: remotionMixEnabled,
    // Remotion 片头片尾（默认关闭=不配置，渲染直接进入正片）
    remotion_intro: remotionMixEnabled && remotionIntroEnabled ? {
      title: remotionIntroTitle,
      episode: remotionIntroEpisode,
      cover_use_episode: remotionIntroCover,
      duration_seconds: remotionIntroDuration,
      background: remotionIntroBg,
    } : undefined,
    remotion_outro: remotionMixEnabled && remotionOutroEnabled ? {
      text: remotionOutroText,
      subtitle: remotionOutroSubtitle,
      duration_seconds: remotionOutroDuration,
      background: remotionOutroBg,
    } : undefined,
    // 选点历史：当前候选为空（最近选点失败）时用所选历史 run 恢复候选再切片
    slice_autoclip_run_id: sliceAutoclipRunId || undefined,
    // 输出档位：高分辨率/高 fps 素材降档提速（原档不处理 / auto 自动降档 / 1080p / 720p / 480p）
    output_tier: outputTier || 'auto',
    // 去重档位（轻/标准/重）+ 手动覆盖，仅 dedupeOn 时生效
    dedupe_config: args.dedupeOn ? buildDedupeConfig(dedupePreset, dedupeManual) : undefined,
    // 多视频号素材去重：多版本生成数（去重模式下配置，>1 时切片后自动派生 N 个去重版本）
    variant_count: args.dedupeOn && variantCount && variantCount > 1 ? variantCount : undefined,
    // 自定义文字水印：开启后后端下发给引擎，在成品视频上叠加动态文字水印
    watermark_enabled: watermarkEnabled,
    watermark_text: watermarkEnabled ? watermarkText : undefined,
    watermark_font_size: watermarkEnabled ? watermarkFontSize : undefined,
    watermark_opacity: watermarkEnabled ? watermarkOpacity : undefined,
    watermark_position: watermarkEnabled ? watermarkPosition : undefined,
    watermark_style: watermarkEnabled ? watermarkStyle : undefined,
    // 恒定水印/角标打码：开启后打掉片源固定水印（独立开关，与字幕打码互不干扰）
    watermark_mask_enabled: watermarkMaskEnabled,
    watermark_mask_style: watermarkMaskEnabled ? watermarkMaskStyle : undefined,
    watermark_mask_width_ratio: watermarkMaskEnabled ? watermarkMaskWidthRatio : undefined,
    watermark_mask_height_ratio: watermarkMaskEnabled ? watermarkMaskHeightRatio : undefined,
    watermark_mask_bottom_ratio: watermarkMaskEnabled ? watermarkMaskBottomRatio : undefined,
    // 竖屏转横屏：开启后切片前自动把竖屏素材转成横屏
    vert2horiz_enabled: vert2horizEnabled,
    vert2horiz_mode: vert2horizEnabled ? vert2horizMode : undefined,
    vert2horiz_ratio: vert2horizEnabled ? vert2horizRatio : undefined,
    vert2horiz_output_size: vert2horizEnabled ? vert2horizOutputSize : undefined,
    vert2horiz_detect_interval: vert2horizEnabled ? vert2horizDetectInterval : undefined,
    vert2horiz_smooth_window: vert2horizEnabled ? vert2horizSmoothWindow : undefined,
    vert2horiz_min_step: vert2horizEnabled ? vert2horizMinStep : undefined,
    vert2horiz_face_margin: vert2horizEnabled ? vert2horizFaceMargin : undefined,
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
    // ASR 字幕烧录：开启后对源视频做 ASR 识别并烧录到成品视频
    subtitle_enabled: subtitleEnabled,
    // 字幕字号/间距/高度（相对高度比例，默认 1/4）/粗细
    subtitle_font_ratio: subtitleEnabled ? subtitleFontRatio : undefined,
    subtitle_margin_ratio: subtitleEnabled ? subtitleMarginRatio : undefined,
    subtitle_spacing: subtitleEnabled ? subtitleSpacing : undefined,
    subtitle_bold: subtitleEnabled ? subtitleBold : undefined,
    subtitle_align_mask: subtitleEnabled ? subtitleAlignMask : undefined,
    // 字幕样式：custom 时可选字体色/边框色（无底色）
    subtitle_style: subtitleEnabled ? subtitleStyle : undefined,
    subtitle_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleColor : undefined,
    subtitle_border_color: subtitleEnabled && subtitleStyle === 'custom' ? subtitleBorderColor : undefined,
    // 上传的字幕文件：提供后直接应用该字幕，跳过 ASR 识别
    subtitle_file_key: subtitleFileKey || undefined,
    // 源视频字幕打码：独立开关，开启后仅打掉片源自带字幕（不依赖 ASR 字幕开关）
    subtitle_mask_enabled: subtitleMaskEnabled,
    subtitle_mask_style: subtitleMaskEnabled ? subtitleMaskStyle : undefined,
    subtitle_mask_preset: subtitleMaskEnabled ? subtitleMaskPreset : undefined,
    subtitle_mask_temporal: subtitleMaskEnabled ? subtitleMaskTemporal : undefined,
    subtitle_mask_spatial: (subtitleMaskEnabled && subtitleMaskTemporal) ? subtitleMaskSpatial : undefined,
    subtitle_mask_width_ratio: subtitleMaskEnabled ? subtitleMaskWidthRatio : undefined,
    subtitle_mask_height_ratio: subtitleMaskEnabled ? subtitleMaskHeightRatio : undefined,
    subtitle_mask_bottom_ratio: subtitleMaskEnabled ? subtitleMaskBottomRatio : undefined,
    subtitle_mask_srt_offset: (subtitleMaskEnabled && !subtitleMaskTemporal) ? subtitleMaskSrtOffset : undefined,
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

  // 一键切片模式弹窗（2026-11-23 用户简化：双配+双批混拼收进一键切片，
  // 只需配两套时长范围，其余全默认：高光×2+正片×1、高光在前、条数自动、钩子照旧）
  const [oneClickModalOpen, setOneClickModalOpen] = useState(false);
  const [ocMode, setOcMode] = useState<'normal' | 'dual'>('normal');
  const [ocHlMin, setOcHlMin] = useState<number>(() => Number(localStorage.getItem('oc_hl_min')) || 5);
  const [ocHlMax, setOcHlMax] = useState<number>(() => Number(localStorage.getItem('oc_hl_max')) || 10);
  const [ocMainMin, setOcMainMin] = useState<number>(() => Number(localStorage.getItem('oc_main_min')) || 120);
  const [ocMainMax, setOcMainMax] = useState<number>(() => Number(localStorage.getItem('oc_main_max')) || 240);

  const oneClickSlice = async () => {
    setOneClickSlicing(true);
    setOneClickProgress({ status: 'running', progress: 5, message: '正在提交一键切片任务…' });
    try {
      // 钩子延迟上传：选完仅在切片开始时上传（失败则终止切片，暂存保留可重试）
      setOneClickProgress({ status: 'running', progress: 3, message: '正在上传钩子视频…' });
      const hookKeys = await uploadPendingHooks();
      // 冲突矩阵：Remotion 增强渲染管线不消费钩子 → 钩子参数不下发
      const hooksActive = hookKeys.length > 0 && !remotionMixEnabled;
      setOneClickProgress({ status: 'running', progress: 5, message: '正在提交一键切片任务…' });
      // auto_accept_all=true：后端自动把所有候选片段（含 pending）纳入切片，
      // 无需逐个审核/预览，直接产出成品视频；无候选片段时由后端自动补一轮 AI 选点
      // （auto_autoclip_if_empty）——提交即走，关窗口安全
      const payload: Record<string, unknown> = buildSlicePayload({
        hookKeys,
        hooksActive,
        // 一键切片：免审核自动纳入全部候选 + 自动补选点（提交即走、关窗口安全）
        autoAcceptAll: true,
        dedupeOn: dedupeEnabled,
      });
      if (ocMode === 'dual') {
        // 双配混拼模式：强制重跑一轮双配选点（正片批+高光批一次出），
        // 每条成品 = 高光×2 + 正片×1（高光在前），条数按正片自动；钩子照现有配置
        payload.autoclip_force = true;
        payload.autoclip_config = {
          ...(payload.autoclip_config || {}),
          dual_profile: true,
          min_duration: ocMainMin,
          max_duration: ocMainMax,
          highlight_min_duration: ocHlMin,
          highlight_max_duration: ocHlMax,
        };
        payload.dual_mix_enabled = true;
        payload.dual_mix_highlight_count = 2;
        payload.dual_mix_main_count = 1;
        payload.dual_mix_highlight_position = 'head';
        payload.dual_mix_output_count = undefined;
        payload.highlight_mix_enabled = false;
        payload.timeout_ms = 50 * 60 * 1000; // 双配全程 15-30 分钟，长连接不设 60s 超时
      }
      const res = await sliceApi.run(episodeId, dedupeEnabled ? 'dedupe' : 'fast', payload);
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
      setSubtitleSpacing(-1);
      setSubtitleStyle('custom');
      setSubtitleColor('#EDD736');
      // 默认开启固定文字开关并预置三处固定文字（右上角/左下角/最左侧竖排标题）
      setTextOverlayEnabled(true);
      // 默认预置三处固定文字（右上角/左下角/最左侧竖排标题）
      applyDefaultTextOverlays();
    }
  };

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
    if (manual.sparkle?.enabled) {
      m.sparkle = {
        enabled: true,
        count: manual.sparkle.count ?? 3,
        size: manual.sparkle.size ?? 3,
        opacity: manual.sparkle.opacity ?? 10,
      };
    }
    if (manual.face_watermark?.enabled) {
      m.face_watermark = {
        enabled: true,
        text: manual.face_watermark.text || 'W',
        opacity: manual.face_watermark.opacity ?? 0.08,
        font_size: manual.face_watermark.font_size ?? 24,
      };
    }
    return Object.keys(m).length > 0 ? { preset, manual: m } : { preset };
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
      // 钩子延迟上传：选完仅在切片开始时上传（失败则终止切片，暂存保留可重试）
      setProgress({ status: 'running', progress: 3, message: '正在上传钩子视频…' });
      const hookKeys = await uploadPendingHooks();
      // 冲突矩阵：Remotion 增强渲染管线不消费钩子 → 钩子参数不下发
      const hooksActive = hookKeys.length > 0 && !remotionMixEnabled;
      setProgress({ status: 'running', progress: 5, message: noCut ? '正在提交快速转换任务…' : '正在提交切片任务…' });
      const res = await sliceApi.run(episodeId, mode, buildSlicePayload({
        hookKeys,
        hooksActive,
        // 快速转换：跳过 AI 选点与区间检测，整段源视频直接应用配置转换输出
        noCut,
        dedupeOn: mode === 'dedupe',
      }));
      message.success(res.message);
      fetchHistories();
      // 任务已加入处理队列，立即恢复按钮状态，可继续添加任务（不再锁定到任务完成）
      setRunning(false);
      setProgress(null);
      // 仍启动轮询，在历史列表/进度区实时同步任务状态，但按钮保持可用
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
          percent={Math.round(p.progress * 10) / 10}
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

  // ─── 钩子视频选择器（主切片区与一键切片配置弹窗共用） ──
  // 布局约束：文件名不再拼进 Tag（几十个文件会把同行后续控件挤出屏幕），
  // Tag 只显示数量，完整文件列表收进弹层（内部滚动，不撑破页面）。
  const renderHookPickerCore = () => {
    const pending = hookPendingFiles.length > 0;
    const count = pending ? hookPendingFiles.length : hookVideoKeys.length;
    const disabled = hookUploading || remotionMixEnabled;
    const names = pending ? hookPendingNames : hookVideoNames;
    const listContent = (
      <div style={{ maxHeight: 240, overflowY: 'auto', maxWidth: 380, paddingRight: 4 }}>
        {names.map((n, i) => (
          <div key={`${i}_${n}`} style={{ fontSize: 12, padding: '2px 0', color: '#555', wordBreak: 'break-all' }}>
            {i + 1}. {n}
            {pending && hookPendingFiles[i] && (
              <span style={{ color: '#999', fontSize: 11 }}>（{formatFileSize(hookPendingFiles[i].size)}）</span>
            )}
          </div>
        ))}
      </div>
    );
    return (
      <Space wrap align="center" size={8}>
        <Upload
          directory
          accept="video/*"
          showUploadList={false}
          beforeUpload={(f) => collectHookFiles(f as File)}
          disabled={disabled}
        >
          <Button size="small" icon={<PlayCircleOutlined />} disabled={disabled}>
            {count > 0 ? '更换文件夹' : '选择文件夹'}
          </Button>
        </Upload>
        <Upload
          multiple
          accept="video/*"
          showUploadList={false}
          beforeUpload={(f) => collectHookFiles(f as File)}
          disabled={disabled}
        >
          <Button size="small" icon={<PlayCircleOutlined />} disabled={disabled}>选择文件</Button>
        </Upload>
        <Tooltip title="支持选整个文件夹，或多选若干视频文件；选完仅暂存本页，点「开始切片/一键切片」时才上传。每个成品按混搭模式取钩子拼在片头/片尾。">
          <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
        </Tooltip>
        {count > 0 && (
          <>
            {pending ? (
              <Tag closable onClose={clearHookSelection} color="orange">
                钩子×{count}（待上传，开始切片时上传）
              </Tag>
            ) : (
              <FileHoverPreview fileKeys={hookVideoKeys} kind="video">
                <Tag closable onClose={clearHookSelection}>钩子×{count}</Tag>
              </FileHoverPreview>
            )}
            <Popover trigger="click" title={`钩子文件列表（${count} 个）`} content={listContent}>
              <Button size="small" type="text">文件列表</Button>
            </Popover>
          </>
        )}
        {remotionMixEnabled && (
          <Text type="warning" style={{ fontSize: 12 }}>
            Remotion 增强模式下钩子不生效（渲染管线暂不消费钩子），可改用普通切片或高光混剪
          </Text>
        )}
      </Space>
    );
  };

  // 钩子选项行：混搭模式 / 拼接位置 / 生成数量（单独一行，保证在任何浏览器都完整可见）
  const renderHookOptions = () => {
    const pending = hookPendingFiles.length > 0;
    const count = pending ? hookPendingFiles.length : hookVideoKeys.length;
    if (count === 0 || remotionMixEnabled) return null;
    return (
      <Space wrap align="center" size={8} style={{ marginTop: 6 }}>
        <Select
          size="small"
          style={{ width: 140 }}
          value={hookMixMode}
          onChange={(v) => setHookMixMode(v as 'sequential' | 'random' | 'combine')}
          options={[
            { value: 'sequential', label: '顺序循环' },
            { value: 'random', label: '随机混搭' },
            { value: 'combine', label: '拼接组合' },
          ]}
        />
        <Select
          size="small"
          style={{ width: 110 }}
          value={hookPosition}
          onChange={(v) => setHookPosition(v as 'head' | 'tail')}
          options={[
            { value: 'head', label: '放在片头' },
            { value: 'tail', label: '放在片尾' },
          ]}
        />
        {/* 钩子混搭输出数量：高光混剪有自己的输出个数（cutlist 组数），两者并存会按组相乘
            导致输出爆炸 → 高光混剪开启时不展示也不下发。
            2026-11-21 权限排查修正：数量框此前只在 random/combine 模式渲染，顺序循环模式
            （新账号默认态）下整块消失，被误认为「素材专员没有权限看到」——改为常驻可见、
            顺序模式下置灰 + 提示，任何账号任何状态都不会找不到框 */}
        {!highlightMixEnabled && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 12, color: '#666', whiteSpace: 'nowrap' }}>生成数量：</span>
            <InputNumber
              size="small"
              min={1}
              max={999}
              style={{ width: 100 }}
              disabled={hookMixMode === 'sequential'}
              value={hookMixOutputCount}
              onChange={(v) => setHookMixOutputCount(v ?? 1)}
            />
            {hookMixMode === 'sequential' && (
              <Tooltip title="顺序循环模式每个切片组固定产出 1 个成品；把混搭模式切到「随机混搭」或「拼接组合」后，此数量才会生效">
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>顺序模式固定 1</Text>
              </Tooltip>
            )}
          </div>
        )}
        {highlightMixEnabled && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            高光混剪模式：输出个数由「混剪配置」决定，钩子按混搭模式拼进每个混剪成品
          </Text>
        )}
      </Space>
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

  // ─── 选点历史参数单行摘要（用于 Select 选项） ──
  const renderAutoclipParamsLabel = (r: AutoClipRunRecord) => {
    const c = (r.config || {}) as Record<string, unknown>;
    const min = c.min_duration as number | undefined;
    const max = c.max_duration as number | undefined;
    const clips = c.max_clips as number | undefined;
    const parts: string[] = [];
    if (min != null || max != null) parts.push(`${min ?? '默认'}~${max ?? '默认'}s`);
    if (clips != null) parts.push(`${clips}个`);
    return parts.length > 0 ? `(${parts.join('，')})` : '(默认)';
  };

  // ─── 选点历史参数展示：从 config 中提取时间范围等选点参数 ──
  const renderAutoclipParams = (r: AutoClipRunRecord) => {
    const c = (r.config || {}) as Record<string, unknown>;
    const min = c.min_duration as number | undefined;
    const max = c.max_duration as number | undefined;
    const clips = c.max_clips as number | undefined;
    const score = c.min_score_threshold as number | undefined;
    const frame = c.frame_analysis as boolean | undefined;
    const parts: string[] = [];
    if (min != null || max != null) {
      parts.push(`时长 ${min ?? '默认'}~${max ?? '默认'}s`);
    }
    if (clips != null) parts.push(`个数 ${clips}`);
    if (score != null) parts.push(`评分 ${score}`);
    if (frame != null) parts.push(`画面理解 ${frame ? '开' : '关'}${c.frame_analysis_provider === 'llm' ? '·在线' : '·本地'}`);
    if (parts.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>默认</Text>;
    return (
      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'pre-line' }}>
        {parts.join('\n')}
      </Text>
    );
  };

  // ── 「画面包装线」已开启功能计数（卡头徽标实时展示）──
  // 与 runSlice payload 的生效条件保持一致：固定文字需开关+列表均非空，图片角标看列表长度
  const visualEnabledCount = [
    vert2horizEnabled,
    subtitleEnabled,
    subtitleMaskEnabled,
    watermarkMaskEnabled,
    textOverlayEnabled && textOverlays.length > 0,
    badges.length > 0,
    watermarkEnabled,
  ].filter(Boolean).length;

  // ── 「预计产出」实时算式：镜像 runSlice payload 的真实逻辑 ──
  // 注意：最终产出几个成品取决于 AI 选点命中的片段数（提交前无法预知，不瞎乘），
  // 这里只镜像 payload 中可预知的放大因子：
  //   1) hook_mix_output_count：钩子混搭 random/combine 且 >1 时每个切片产出 N 个；
  //      生效条件 = 有已上传/暂存钩子 且 未开 Remotion（Remotion 管线不消费钩子）且 未开高光混剪
  //   2) highlight_mix_output_count：高光混剪开启时产出 N 个混剪文件
  //   3) variant_count：仅去重模式（快速转换 mode=fast 不生效）且 >1 时切片后自动派生 N 个去重版本
  // 前端 payload 保证钩子个数与高光个数互斥（高光开启时不下发钩子个数），故二者不会同时 >1
  const hooksActiveForEstimate = (hookVideoKeys.length > 0 || hookPendingFiles.length > 0) && !remotionMixEnabled;
  const estHookFactor = hooksActiveForEstimate && !highlightMixEnabled && (hookMixMode === 'random' || hookMixMode === 'combine') && hookMixOutputCount > 1 ? hookMixOutputCount : 1;
  const estHighlightFactor = highlightMixEnabled ? highlightMixOutputCount : 1;
  // 2026-11-21 UX 复评：两个入口的 dedupe 门控不同（一键切片=dedupeEnabled 开关、
  // 主路径=sliceMode==='dedupe'），预计产出按「任一入口生效」的上界估计，避免一键+去重+多版本时恒显示 1
  const estVariantFactor = (dedupeEnabled || sliceMode === 'dedupe') && variantCount && variantCount > 1 ? variantCount : 1;
  const estOutputCount = estHookFactor * estHighlightFactor * estVariantFactor;
  // 体检条明细（2026-11-21 业务线重组）：只列 >1 的放大因子，不可能叠加的项不会同时出现
  const estimateParts: string[] = [];
  if (estHookFactor > 1) estimateParts.push(`钩子×${estHookFactor}`);
  if (estHighlightFactor > 1) estimateParts.push(`混剪×${estHighlightFactor}`);
  if (estVariantFactor > 1) estimateParts.push(`变体×${estVariantFactor}`);
  const estimateDetail = estimateParts.length > 0 ? `（${estimateParts.join(' · ')}）` : '';

  const actions: { title: string; extra?: React.ReactNode; node: React.ReactNode }[] = [
    {
      title: '🎬 选片线 · AI 智能选点',
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
            <Tooltip title="设置候选片段入选的最低评分（0-100），留空则使用系统默认（50 分）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>入选评分:</Text>
                <InputNumber
                  size="small"
                  min={0}
                  max={100}
                  placeholder="50"
                  value={minScoreThreshold}
                  onChange={(v) => setMinScoreThreshold(v ?? null)}
                  style={{ width: 70 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>分</Text>
              </Space>
            </Tooltip>
          </Space>
          <Space wrap>
            <Tooltip title="设置候选片段的最短时长（秒），留空则使用系统默认（20 秒）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>最短时长:</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={86400}
                  placeholder="20"
                  value={minClipDuration}
                  onChange={(v) => setMinClipDuration(v ?? null)}
                  style={{ width: 80 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              </Space>
            </Tooltip>
            <Tooltip title="设置候选片段的最长时长（秒），留空则使用系统默认（70 秒）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>最长时长:</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={86400}
                  placeholder="70"
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
              <Tooltip title="开启后，AI 选点会对候选片段进行画面理解（抽帧分析场景/动作/情绪/精彩度），结合台词综合打分。关闭则仅依据台词与文案判断。（默认开启）">
                <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
              </Tooltip>
              {frameAnalysis && (
                <Select
                  size="small"
                  value={frameAnalysisProvider}
                  onChange={setFrameAnalysisProvider}
                  style={{ width: 100 }}
                  options={[
                    { value: 'ollama', label: '本地模型' },
                    { value: 'llm', label: '在线模型' },
                  ]}
                />
              )}
            </Space>
            <Space size={4} align="center">
              <Switch size="small" checked={highlightMode} onChange={setHighlightMode} />
              <Text strong style={{ fontSize: 12 }}>高光识别</Text>
              <Tooltip title="开启后，AI 选点改为找出多段 ≤ 单段最大时长的短高光片段（默认 10s），适合高光混剪等需要多段短爆点的场景。">
                <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
              </Tooltip>
              {highlightMode && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  找出的多段短高光可在下方「混剪方式」线混剪成一条成品
                </Text>
              )}
              <Button
                size="small"
                icon={<SettingOutlined />}
                disabled={!highlightMode}
                onClick={() => setHighlightModalOpen(true)}
              >
                配置
              </Button>
            </Space>
          </Space>
          <Space size={4} align="center" wrap>
            <Text strong style={{ fontSize: 12 }}>选点模型</Text>
            <Select
              size="small"
              style={{ minWidth: 200 }}
              value={llmPreset}
              onChange={(v) => setLlmPresetPersist(v as string)}
              options={[
                { value: 'system', label: '跟随系统设置' },
                ...llmRepo.map((m) => ({ value: `saved:${m.name}`, label: `${m.name}（${m.model}）` })),
                { value: 'custom', label: '自定义…' },
              ]}
            />
            {llmPreset === 'custom' && (
              <>
                <Input size="small" placeholder="模型名（必填）" style={{ width: 150 }} value={llmCustom.model} onChange={(e) => setLlmCustomPersist({ model: e.target.value })} />
                <Input size="small" placeholder="API 地址（OpenAI 兼容）" style={{ width: 220 }} value={llmCustom.base} onChange={(e) => setLlmCustomPersist({ base: e.target.value })} />
                <Input.Password size="small" placeholder="API 密钥（留空沿用系统，仅本次有效）" style={{ width: 200 }} value={llmCustom.key} onChange={(e) => setLlmCustomPersist({ key: e.target.value })} />
                <Button size="small" loading={llmTesting} onClick={handleLlmTest}>测试连通</Button>
                {llmTestResult && (llmTestResult.ok
                  ? <Tag color="success">✓ 连通 {llmTestResult.latency_ms}ms</Tag>
                  : <Tooltip title={llmTestResult.error || '未知错误'}><Tag color="error">✗ 失败 {llmTestResult.latency_ms}ms</Tag></Tooltip>)}
                <Button size="small" icon={<PlusOutlined />} loading={llmSavingRepo}
                  disabled={!llmCustom.model.trim()}
                  onClick={handleLlmSaveRepo}
                  title="把该自定义模型保存进系统模型仓库（密钥由服务端保管），以后可在下拉直接选择">
                  保存到仓库
                </Button>
              </>
            )}
            <Tooltip title="选点用的文本 LLM，对「启动选点」和「一键切片」的自动补选点同样生效。跟随系统设置=用系统设置里的「默认使用模型」；其余选项来自系统设置的模型仓库；自定义可临时填密钥（仅本次会话，不落盘）。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
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
              dataSource={autoclipHistory}
              scroll={{ x: 640, y: 260 }}
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
                  title: '选点参数',
                  dataIndex: 'config',
                  key: 'config',
                  width: 200,
                  render: (_: unknown, r: AutoClipRunRecord) => renderAutoclipParams(r),
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
                  title: '操作',
                  key: 'action',
                  width: 80,
                  render: (_: unknown, r: AutoClipRunRecord) =>
                    r.status === 'running' || r.status === 'pending' ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>运行中</Text>
                    ) : (
                      <Popconfirm
                        title="确定删除该条选点执行记录？"
                        description="删除后若该集已无选点历史，片段候选与区间检测结果将一并清空，下次一键切片会重新选点；若切片成品仍在引用候选，需先删除切片任务"
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                        onConfirm={() => handleDeleteAutoclipHistory(r.id)}
                      >
                        <Button size="small" danger type="text" icon={<DelIcon />}>删除</Button>
                      </Popconfirm>
                    ),
                },
              ]}
            />
          )}
        </Space>
      ),
    },
    {
      title: '🎬 选片线 · 通用区间检测',
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
      title: '🧩 混剪方式 · 混成一条还是一段一片',
      extra: (highlightMixEnabled || remotionMixEnabled) ? <Tag color="purple">已启用</Tag> : undefined,
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {/* Remotion 逐帧渲染提示：开启增强时提醒用户渲染进度特征，避免误判卡死 */}
          {remotionMixEnabled && (
            <Alert
              type="info"
              showIcon
              message="Remotion 渲染为逐帧渲染，期间进度缓步属正常，请耐心等待；若长期无进度请到 Worker 页检查节点状态"
            />
          )}
          {/* 高光混剪：把入选高光段按源时间顺序混剪拼接为一个成品 */}
          <Space wrap align="center" size={8}>
            <Text strong style={{ fontSize: 13 }}>高光混剪</Text>
            <Switch
              size="small"
              checked={highlightMixEnabled}
              onChange={(v) => setHighlightMixEnabled(v)}
            />
            {highlightMixEnabled && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                高光片段来自「选片线 · AI 智能选点」的高光识别
              </Text>
            )}
            <Tooltip title="开启后混剪由 Remotion 渲染：段间转场 + 字幕 + 段标题；可在「片头片尾」里自定义片头标题卡与片尾文案卡（默认不配置 = 直接正片）。需在系统设置开启「Remotion 渲染」。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
            <Switch
              size="small"
              checked={remotionMixEnabled}
              onChange={(v) => {
                setRemotionMixEnabled(v);
                // Remotion 增强是「高光混剪」的渲染器替换：后端仅在两者同时开启时
                // 才投递 Remotion 渲染任务，这里联动开启避免任务卡死在 processing
                if (v && !highlightMixEnabled) {
                  setHighlightMixEnabled(true);
                }
                // 冲突提示：Remotion 渲染管线不消费钩子视频，开启后已选钩子将被忽略
                if (v && (hookPendingFiles.length > 0 || hookVideoKeys.length > 0)) {
                  message.warning('已开启 Remotion 增强：渲染管线暂不消费钩子视频，本次切片将忽略已选钩子；如需钩子请改用普通高光混剪（关闭此开关）');
                }
              }}
            />
            <Text strong style={{ fontSize: 12 }}>Remotion 增强</Text>
            <Tooltip title="开启后不再把每个高光段切成独立文件，而是把所有入选高光段按源时间顺序混剪拼接为单个成品视频（可设输出总时长上限/单段最大时长/拼接顺序）。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
            <Button
              size="small"
              icon={<SettingOutlined />}
              disabled={!highlightMixEnabled}
              onClick={() => setHighlightMixModalOpen(true)}
            >
              混剪配置
            </Button>
            <Button
              size="small"
              icon={<SettingOutlined />}
              disabled={!remotionMixEnabled}
              onClick={() => setRemotionIntroOutroModalOpen(true)}
            >
              片头片尾
            </Button>
            {remotionMixEnabled && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {!remotionIntroEnabled && !remotionOutroEnabled
                  ? '无片头片尾（直接正片）'
                  : [
                      remotionIntroEnabled ? `片头${remotionIntroDuration}s` : '无片头',
                      remotionOutroEnabled ? `片尾${remotionOutroDuration}s` : '无片尾',
                    ].join(' · ')}
              </Text>
            )}
            {highlightMixEnabled && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {highlightMixMaxDuration ? `总时长≤${highlightMixMaxDuration}s` : '总时长由片段自然决定'}
                {highlightMixMaxClipDuration ? ` · 单段≤${highlightMixMaxClipDuration}s` : ''}
                {highlightMixOrder === 'score' ? ' · 评分优先' : highlightMixOrder === 'random' ? ' · 随机抽取' : ' · 时间顺序'}
                {highlightMixOutputCount > 1 ? ` · 输出${highlightMixOutputCount}个文件` : ''}
              </Text>
            )}
          </Space>

          </Space>
      ),
    },
    {
      title: '🪝 营销钩子 · 片头片尾拼什么',
      extra: (hookVideoKeys.length + hookPendingFiles.length) > 0 ? <Tag color="orange">钩子×{hookVideoKeys.length + hookPendingFiles.length}</Tag> : undefined,
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {/* 钩子视频（可选）：支持选整个文件夹或多选文件；选完仅暂存，开始切片时才上传。
              混搭模式/拼接位置/生成数量独立成行，避免长文件列表把后续控件挤出屏幕 */}
          <div style={{ width: '100%' }}>
            <Space wrap align="center" size={8}>
              <Text strong style={{ fontSize: 13 }}>钩子视频</Text>
              {renderHookPickerCore()}
            </Space>
            {renderHookOptions()}
          </div>

          </Space>
      ),
    },
    {
      title: '🎨 画面包装 · 画面上叠什么',
      extra: <Tag color="green">{visualEnabledCount} 项已开启</Tag>,
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {/* 视频封面（首帧，可选）：选择图片作为成品第一帧，不选则按源视频首帧 */}
          <Space wrap align="center" size={8}>
            <Text strong style={{ fontSize: 13 }}>视频封面（首帧）</Text>
            <Upload
              accept="image/*"
              showUploadList={false}
              beforeUpload={(file) => handleCoverUpload(file as File)}
              disabled={coverUploading}
            >
              <Button size="small" icon={<PictureOutlined />} loading={coverUploading}>
                {coverImageKey ? '更换封面' : '选择封面图片'}
              </Button>
            </Upload>
            {coverImageKey && (
              <FileHoverPreview fileKey={coverImageKey} kind="image">
              <Tag closable onClose={() => {
    setCoverImageKey(null);
    setCoverImageName(null);
    sliceApi.updateEpisodeCover(episodeId, null).catch((err: unknown) => {
      console.error('清除剧集封面失败', err);
    });
}}>
                  封面：{coverImageName || '已选择'}
              </Tag>
              </FileHoverPreview>
            )}
          </Space>
          {/* 视频结尾：拼接到每个成品末尾（可上传新视频或从已保存库选择） */}
          <Space wrap align="center" size={8}>
            <Text strong style={{ fontSize: 13 }}>视频结尾（片尾）</Text>
            <Select
              size="small"
              style={{ minWidth: 200 }}
              allowClear
              placeholder="不拼接片尾"
              value={outroKey ?? undefined}
              onChange={(v) => setOutroKeyPersist((v as string) || null)}
              options={outroList.map((o) => ({ value: o.file_key, label: o.file_name }))}
            />
            <Upload
              accept="video/mp4,video/avi,video/mov,video/mkv,video/webm"
              showUploadList={false}
              beforeUpload={(file) => {
                setOutroUploading(true);
                sliceApi.outroUpload(file as File)
                  .then((r) => {
                    setOutroKeyPersist(r.file_key);
                    setOutroList((prev) => [{ file_key: r.file_key, file_name: r.file_name, file_size: r.file_size }, ...prev.filter((x) => x.file_key !== r.file_key)]);
                    message.success(`片尾视频已上传：${r.file_name}`);
                  })
                  .catch((err: unknown) => message.error(err instanceof Error ? err.message : '片尾上传失败'))
                  .finally(() => setOutroUploading(false));
                return false;
              }}
              disabled={outroUploading}
            >
              <Button size="small" icon={<VideoCameraOutlined />} loading={outroUploading}>上传片尾视频</Button>
            </Upload>
            {outroKey && (
              <Tag closable onClose={() => setOutroKeyPersist(null)}>
                片尾：{outroList.find((x) => x.file_key === outroKey)?.file_name || '已选择'}
              </Tag>
            )}
            <Tooltip title="选中的小视频会拼接到每个成品视频的末尾（[...][本体][片尾]），与钩子独立；上传后进入已保存库可跨剧集复用。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
          </Space>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(270px, 1fr))', gap: 8, alignItems: 'start' }}>
            {/* ── 竖屏转横屏智能裁切开关 ── */}
            <Card size="small" style={{ width: '100%' }}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Space wrap>
                  <Switch checked={vert2horizEnabled} onChange={handleVert2horizToggle} size="small" />
                  <Text strong style={{ fontSize: 13 }}>竖屏转横屏</Text>
                  {vert2horizEnabled && <Tag color="green">已开启</Tag>}
                  <Tooltip title="开启后若素材为竖屏（9:16），切片前自动转为横屏（16:9）：固定裁切快速稳定，动态跟踪会逐帧检测人脸确保人物不出画。适用于发布到视频号横屏模式 / B站等横屏平台。">
                    <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                  </Tooltip>
                  {vert2horizEnabled && (
                    <Button size="small" icon={<SettingOutlined />} onClick={() => setVert2horizModalOpen(true)}>配置</Button>
                  )}
                </Space>
              </Space>
            </Card>

            {/* ── ASR 字幕烧录开关 ── */}
            <Card size="small" style={{ width: '100%' }}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Space wrap>
                  <Switch checked={subtitleEnabled} onChange={setSubtitleEnabled} size="small" />
                  <Text strong style={{ fontSize: 13 }}>ASR 字幕</Text>
                  {subtitleEnabled && <Tag color="green">已开启</Tag>}
                  <Tooltip title="开启后对源视频做语音识别（ASR），并把识别到的台词烧录到每个切片成品上（白字黑边，底部居中）。适合把关键对白直观呈现在短剧切片上。">
                    <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                  </Tooltip>
                  {subtitleEnabled && (
                    <Button size="small" icon={<SettingOutlined />} onClick={() => setSubtitleModalOpen(true)}>字幕设置</Button>
                  )}
                </Space>
              </Space>
            </Card>

            {/* ── 源视频字幕打码（去片源自带字幕，独立开关） ── */}
            <Card size="small" style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Switch size="small" checked={subtitleMaskEnabled} onChange={setSubtitleMaskEnabled} />
                <Text strong style={{ fontSize: 13 }}>源字幕打码</Text>
                {subtitleMaskEnabled && <Tag color="green">已开启</Tag>}
                <Tooltip title="把片源自带的字幕去字幕/打码（独立开关，与 ASR 字幕无关）。默认自动检测字幕位置，样式为去水印（智能插值），仅在有源字幕的时间段生效。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
                {subtitleMaskEnabled && (
                  <Button size="small" icon={<SettingOutlined />} onClick={() => setSubtitleMaskModalOpen(true)}>打码设置</Button>
                )}
              </Space>
            </Card>

            {/* ── 恒定水印/角标打码（打掉片源固定水印，独立开关） ── */}
            <Card size="small" style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Switch size="small" checked={watermarkMaskEnabled} onChange={setWatermarkMaskEnabled} />
                <Text strong style={{ fontSize: 13 }}>恒定水印打码</Text>
                {watermarkMaskEnabled && <Tag color="green">已开启</Tag>}
                <Tooltip title="打掉片源固定的水印/角标（如频道角标、平台水印、底部固定字条）。与源字幕打码互不干扰：字幕打码管动态对话字幕，水印打码管恒定出现的水印。默认自动检测恒定出现区域，样式为去水印（智能插值）。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
                {watermarkMaskEnabled && (
                  <Button size="small" icon={<SettingOutlined />} onClick={() => setWatermarkMaskModalOpen(true)}>打码设置</Button>
                )}
              </Space>
            </Card>

            {/* ── 固定文字角标（文字版角标，最左侧/左下角/右上角等） ── */}
            <Card size="small" style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Switch size="small" checked={textOverlayEnabled} onChange={setTextOverlayEnabled} />
                <Text strong style={{ fontSize: 13 }}>固定文字</Text>
                {(textOverlayEnabled && textOverlays.length > 0) && <Tag color="green">已开启</Tag>}
                <Tooltip title="开启后在视频指定位置叠加固定文字（无需上传图片）：最左侧（竖排）/左下角/右上角等，全程覆盖。开启后点击右侧「设置文字」按钮配置文字内容、字号、颜色等。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
                {textOverlayEnabled && (
                  <Button size="small" icon={<SettingOutlined />} onClick={() => setTextOverlayModalOpen(true)}>设置文字</Button>
                )}
              </Space>
            </Card>

            {/* ── 图片角标配置（多角标、六角位置，全程叠加） ── */}
            <Card size="small" style={{ width: '100%' }}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Space wrap>
                  <Text strong style={{ fontSize: 13 }}>图片角标</Text>
                  {badges.length > 0 && <Tag color="green">已开启</Tag>}
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
                  <Button size="small" onClick={openBadgeLibrary}>
                    从已保存选择
                  </Button>
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
                  {watermarkEnabled && <Tag color="green">已开启</Tag>}
                  <Tooltip title="开启后会在切片成品视频上叠加动态文字水印（文字缓慢移动 + 透明度呼吸），可用于防搬运/标识来源。">
                    <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                  </Tooltip>
                  {watermarkEnabled && (
                    <Button size="small" icon={<SettingOutlined />} onClick={() => setWatermarkModalOpen(true)}>配置</Button>
                  )}
                </Space>
              </Space>
            </Card>
        </div>
        </Space>
      ),
    },
    {
      title: '🛡 防搬运 · 过查重',
      extra: (sliceMode === 'dedupe' || dedupeEnabled) ? <Tag color="red">去重生效</Tag> : undefined,
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {sliceMode === 'dedupe'
              ? '当前切片模式＝去重（档位在「切片执行」卡的切片模式选择器二级选项中调整）'
              : '当前切片模式未选去重；需要防搬运时在「切片执行」卡的切片模式中选择「去重」并选档位'}
          </Text>
          {/* 去重高级配置：去重生效即显示（2026-11-21 审计高危①：此前只看 sliceMode，
              一键切片经 dedupeEnabled 静默走去重+变体数时本块不可见=「产出变了找不到原因」；
              现按两个入口的并集显示，并标注生效入口） */}
          {(sliceMode === 'dedupe' || dedupeEnabled) && (
            <Space wrap>
              <Tag color={sliceMode === 'dedupe' ? 'processing' : 'default'}>
                {sliceMode === 'dedupe' ? '主路径去重模式' : '一键切片将走去重（在「一键切片配置」中开启）'}
              </Tag>
              <Button size="small" icon={<SettingOutlined />} onClick={() => setDedupeManualOpen(true)}>
                去重高级配置
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {Object.keys(dedupeManual).length > 0 ? '已启用手动配置' : '跟随所选档位'}
              </Text>
              {/* 多视频号素材去重：多版本生成数（>1 时切片后自动派生 N 个去重版本）。
                  2026-11-21 审计：随去重块常驻（去重生效时它是影响产出的实际参数，藏起来=同型陷阱） */}
              <InputNumber
                size="small"
                min={1}
                max={20}
                placeholder="变体数"
                value={variantCount}
                onChange={(v) => setVariantCount(v ?? undefined)}
                style={{ width: 90 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>多版本数</Text>
            </Space>
          )}

          </Space>
      ),
    },
    {
      title: '⚙ 切片执行 · 汇聚提交',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {/* 配置体检（2026-11-21 业务线重组 PR3）：提交前最后一眼——明细估算 + 跨线冲突 */}
          <Card size="small" style={{ width: '100%', background: '#fafafa' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong style={{ fontSize: 13 }}>
                预计产出 ≈ {estOutputCount} 个成品{estimateDetail}
              </Text>
              {remotionMixEnabled && (hookVideoKeys.length > 0 || hookPendingFiles.length > 0) && (
                <Alert type="warning" showIcon message="冲突：Remotion 增强开启，已选钩子将被忽略（Remotion 渲染管线不消费钩子）" />
              )}
              {dedupeEnabled && sliceMode !== 'dedupe' && (
                <Alert type="info" showIcon message="提示：一键切片将按去重模式出片（主路径切片模式未选去重）；多版本数等参数见「防搬运」卡" />
              )}
            </Space>
          </Card>
          {/* 切片模式选择：鼠标悬停停顿显示当前模式介绍（去掉常驻说明文字） */}
          <Tooltip title={`${SLICE_MODE_HELP[sliceMode]?.label || '切片模式'}：${SLICE_MODE_HELP[sliceMode]?.detail || ''}`}>
            <Cascader
              value={sliceMode === 'dedupe' ? ['dedupe', dedupePreset || 'std_crop_desat'] : [sliceMode]}
              options={SLICE_MODE_OPTIONS}
              onChange={(val: (string | number)[]) => {
                const v = (val ?? []).map(String);
                if (v[0] === 'dedupe') {
                  setSliceMode('dedupe');
                  setDedupePreset(v[1] || 'std_crop_desat');
                } else if (v[0]) {
                  setSliceMode(v[0]);
                }
              }}
              displayRender={(labels: string[]) => labels.join(' · ')}
              placeholder="选择切片模式"
              style={{ width: 220 }}
            />
          </Tooltip>
          {/* 输出档位：高分辨率/高 fps 素材可降档提速（与一键切片配置弹窗同源，runSlice 已透传 output_tier） */}
          <Space wrap align="center" size={8}>
            <Text strong style={{ fontSize: 13 }}>输出档位</Text>
            <Tooltip title="高分辨率/高 fps 素材可降档提速（引擎滤镜链末尾追加 scale+fps，cover concat 同步同档位）。">
              <InfoCircleOutlined style={{ color: '#999' }} />
            </Tooltip>
            <Select
              size="small"
              style={{ width: 220 }}
              value={outputTier || 'auto'}
              onChange={setOutputTier}
              options={[
                { value: 'original', label: '原档（不处理）' },
                { value: 'auto', label: '自动（高规格自动降 720P30）' },
                { value: '1080p', label: '1080P（宽≤1080/fps≤60）' },
                { value: '720p', label: '720P（宽≤720/fps≤30）' },
                { value: '480p', label: '480P（宽≤480/fps≤30）' },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>降档后编码耗时显著下降（预计 1/3 以下）</Text>
          </Space>
          {/* 选择 AI 选点历史：补选点/切片复用它那套选点参数（时长范围等）。
              2026-11-21 审计高危②修复后常驻；2026-11-21 用户裁定去掉专家模式门槛，所有账号直接可用 */}
          <Space wrap align="center" size={8}>
            <Text strong style={{ fontSize: 13 }}>选点历史</Text>
            <Select
              size="small"
              allowClear
              placeholder="不选则用当前选点参数"
              value={sliceAutoclipRunId}
              onChange={(v) => setSliceAutoclipRunId(v ?? undefined)}
              style={{ width: 260 }}
              options={autoclipHistory.map((h, i) => ({
                value: h.id,
                label: `${formatDateTime(h.created_at)} · ${renderAutoclipParamsLabel(h)}`,
              }))}
            />
            <Tooltip title="选择某一套 AI 智能选点历史后，切片时（含无候选自动补选点）将复用该次选点的时间范围等参数；不选则使用当前页面设置的选点参数。">
              <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
            </Tooltip>
          </Space>
          {/* 开始切片 / 快速转换按钮（位于切片模式选择下方） */}
          <Space wrap>
            <Button icon={<ScissorOutlined />} loading={sliceRunning} disabled={quickConverting} onClick={() => runSlice(false)}>开始切片</Button>
            <Tooltip title="跳过 AI 选点和区间检测，直接整段视频应用下方配置（竖屏转横屏/水印/角标/字幕/固定文字等）转换输出">
              <Button icon={<ThunderboltOutlined />} loading={quickConverting} disabled={sliceRunning} onClick={() => runSlice(true)}>快速转换</Button>
            </Tooltip>
          </Space>

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
            <DedupeManualConfig value={dedupeManual} onChange={setDedupeManual} preset={dedupePreset} />
          </Modal>

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
                <Select
                  size="small"
                  style={{ width: 180 }}
                  value={vert2horizOutputSize}
                  onChange={setVert2horizOutputSize}
                  options={VERT2HORIZON_OUTPUT_SIZES}
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

          {/* 高光混剪设置弹窗（详细配置收进弹窗，节省主界面空间） */}
          <Modal
            title="高光混剪配置"
            open={highlightMixModalOpen}
            onCancel={() => setHighlightMixModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setHighlightMixModalOpen(false)}>完成</Button>
            )}
            width={560}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>输出总时长上限(秒)</Text>
                <InputNumber
                  size="small"
                  min={5}
                  max={600}
                  placeholder="不填=由片段自然决定"
                  value={highlightMixMaxDuration}
                  onChange={(v) => setHighlightMixMaxDuration(v ?? null)}
                  style={{ width: 150 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>累计各高光段时长不超过该值，最后一段塞入会超额时自动丢弃（不裁剪首尾）</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>单段最大时长(秒)</Text>
                <InputNumber
                  size="small"
                  min={2}
                  max={60}
                  placeholder="不填=不限（短高光建议10）"
                  value={highlightMixMaxClipDuration}
                  onChange={(v) => setHighlightMixMaxClipDuration(v ?? null)}
                  style={{ width: 150 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>仅纳入时长不超过该值的短高光片段</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>拼接顺序</Text>
                <Select
                  size="small"
                  style={{ width: 180 }}
                  value={highlightMixOrder}
                  onChange={setHighlightMixOrder}
                  options={[
                    { value: 'time', label: '源时间顺序（默认）' },
                    { value: 'score', label: '评分从高到低' },
                    { value: 'random', label: '随机抽取（凑总时长）' },
                  ]}
                />
                <Space wrap align="center" size={8}>
                  <Text strong style={{ fontSize: 13 }}>输出个数</Text>
                  <InputNumber
                    size="small"
                    min={1}
                    max={100}
                    value={highlightMixOutputCount}
                    onChange={(v) => setHighlightMixOutputCount(v ?? 1)}
                    style={{ width: 120 }}
                  />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    产出 N 个混剪文件（剧名_MMDD_001..N）；「总时长上限」即每个文件的时长上限，不填则按段数均分
                  </Text>
                </Space>
              </Space>
            </Space>
          </Modal>

          {/* ── 角标保存库弹窗：点选历史角标直接加入 ── */}
          <Modal
            title="从已保存角标中选择"
            open={badgeLibraryOpen}
            onCancel={() => setBadgeLibraryOpen(false)}
            footer={null}
            width={640}
          >
            {badgeLibraryLoading ? (
              <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
            ) : badgeLibraryItems.length === 0 ? (
              <Alert type="info" showIcon message="角标库为空——上传过的角标图片会自动保存在这里，下次无需重复上传。" />
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                {badgeLibraryItems.map((item) => (
                  <div
                    key={item.file_key}
                    onClick={() => pickBadgeFromLibrary(item)}
                    style={{
                      width: 120, cursor: 'pointer', textAlign: 'center',
                      border: '1px solid #eee', borderRadius: 8, padding: 8,
                    }}
                  >
                    <AntImage src={item.preview} width={96} height={72} style={{ objectFit: 'contain' }} />
                    <div style={{ fontSize: 11, color: '#666', marginTop: 4, wordBreak: 'break-all' }}>
                      {item.file_name.length > 16 ? `${item.file_name.slice(0, 16)}…` : item.file_name}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Modal>

          {/* Remotion 片头片尾配置弹窗（默认全关 = 不配置，直接进入正片） */}
          <Modal
            title="Remotion 片头片尾配置"
            open={remotionIntroOutroModalOpen}
            onCancel={() => setRemotionIntroOutroModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setRemotionIntroOutroModalOpen(false)}>完成</Button>
            )}
            width={560}
          >
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              {/* ── 片头 ── */}
              <div>
                <Space wrap align="center" size={8}>
                  <Text strong style={{ fontSize: 13 }}>片头</Text>
                  <Switch size="small" checked={remotionIntroEnabled} onChange={setRemotionIntroEnabled} />
                  <Text type="secondary" style={{ fontSize: 12 }}>关闭 = 无片头直接正片</Text>
                </Space>
                {remotionIntroEnabled && (
                  <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 10 }}>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>主标题</Text>
                      <Input size="small" style={{ width: 220 }} placeholder="不填=「高光混剪」" value={remotionIntroTitle} onChange={(e) => setRemotionIntroTitle(e.target.value)} />
                    </Space>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>副标题</Text>
                      <Input size="small" style={{ width: 220 }} placeholder="如：第 1 集" value={remotionIntroEpisode} onChange={(e) => setRemotionIntroEpisode(e.target.value)} />
                    </Space>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>时长(秒)</Text>
                      <InputNumber size="small" min={2} max={6} step={0.5} value={remotionIntroDuration} onChange={(v) => setRemotionIntroDuration(v ?? 3)} style={{ width: 90 }} />
                      <Text style={{ fontSize: 12, width: 64 }}>背景色</Text>
                      <Input size="small" style={{ width: 120 }} value={remotionIntroBg} onChange={(e) => setRemotionIntroBg(e.target.value)} placeholder="#0d0d12" />
                    </Space>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>封面图</Text>
                      <Switch size="small" checked={remotionIntroCover} onChange={setRemotionIntroCover} />
                      <Text type="secondary" style={{ fontSize: 12 }}>使用剧集封面图（未上传封面时片头不带图）</Text>
                    </Space>
                  </Space>
                )}
              </div>
              {/* ── 片尾 ── */}
              <div>
                <Space wrap align="center" size={8}>
                  <Text strong style={{ fontSize: 13 }}>片尾</Text>
                  <Switch size="small" checked={remotionOutroEnabled} onChange={setRemotionOutroEnabled} />
                  <Text type="secondary" style={{ fontSize: 12 }}>关闭 = 无片尾</Text>
                </Space>
                {remotionOutroEnabled && (
                  <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 10 }}>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>结尾文案</Text>
                      <Input size="small" style={{ width: 220 }} value={remotionOutroText} onChange={(e) => setRemotionOutroText(e.target.value)} placeholder="感谢观看" />
                    </Space>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>副文案</Text>
                      <Input size="small" style={{ width: 220 }} value={remotionOutroSubtitle} onChange={(e) => setRemotionOutroSubtitle(e.target.value)} placeholder="留空则不显示该行" />
                    </Space>
                    <Space wrap align="center" size={8}>
                      <Text style={{ fontSize: 12, width: 64 }}>时长(秒)</Text>
                      <InputNumber size="small" min={2} max={5} step={0.5} value={remotionOutroDuration} onChange={(v) => setRemotionOutroDuration(v ?? 2.5)} style={{ width: 90 }} />
                      <Text style={{ fontSize: 12, width: 64 }}>背景色</Text>
                      <Input size="small" style={{ width: 120 }} value={remotionOutroBg} onChange={(e) => setRemotionOutroBg(e.target.value)} placeholder="#0d0d12" />
                    </Space>
                  </Space>
                )}
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                片头为「标题卡」（主标题 + 副标题 + 可选封面图），片尾为「结尾文案卡」；两项都关闭时渲染直接进入正片。
              </Text>
            </Space>
          </Modal>

          {/* 高光识别配置弹窗（AI 选点找出多段短高光） */}
          <Modal
            title="高光识别配置"
            open={highlightModalOpen}
            onCancel={() => setHighlightModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setHighlightModalOpen(false)}>完成</Button>
            )}
            width={520}
          >
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>单段最大时长(秒)</Text>
                <InputNumber
                  size="small"
                  min={2}
                  max={30}
                  value={highlightMaxDuration}
                  onChange={(v) => setHighlightMaxDuration(v ?? 10)}
                  style={{ width: 100 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>仅保留时长不超过该值的短高光片段（默认 10s），用于高光混剪等多段短爆点场景</Text>
              </Space>
            </Space>
          </Modal>

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
                    const fs = v ?? 22;
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
                  onChange={(v) => setSubtitleSpacing(v ?? -2)}
                  style={{ width: 100 }}
                  addonAfter="px"
                />
                <Text type="secondary" style={{ fontSize: 12 }}>越小越紧凑</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>字体粗细</Text>
                <Select
                  size="small"
                  value={subtitleBold}
                  onChange={(v) => setSubtitleBold(v)}
                  style={{ width: 120 }}
                  options={[
                    { value: 0, label: '常规' },
                    { value: -1, label: '加粗' },
                    { value: 1, label: '粗体' },
                  ]}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>加粗让字幕更醒目</Text>
              </Space>
              <Space wrap align="center" size={8}>
                <SubtitleMarginPicker value={subtitleMarginRatio} onChange={setSubtitleMarginRatio} labelStrong numberWidth={100} />
                <Text type="secondary" style={{ fontSize: 12 }}>预设或精调（越小越贴底）</Text>
                <Tooltip title="注意：开启「字幕对齐源字幕打码区域」且检测到源字幕时，ASR 字幕位置会跟随打码区域，此处高度设置暂不生效。">
                  <Text type="warning" style={{ fontSize: 12, cursor: 'help' }}>何时无效？</Text>
                </Tooltip>
              </Space>
              <Space wrap align="center" size={8}>
                <Switch size="small" checked={subtitleAlignMask} onChange={setSubtitleAlignMask} />
                <Text strong style={{ fontSize: 13 }}>字幕对齐源字幕打码区域</Text>
                <Tooltip title="开启源字幕打码并检测到字幕区域时，把 ASR 字幕默认位置对齐到打码区域（与被打掉的源字幕位置重合）；关闭则用默认底边距。默认开启。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
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

          {/* 恒定水印打码设置弹窗 */}
          <Modal
            title="恒定水印打码设置"
            open={watermarkMaskModalOpen}
            onCancel={() => setWatermarkMaskModalOpen(false)}
            footer={(
              <Button type="primary" onClick={() => setWatermarkMaskModalOpen(false)}>完成</Button>
            )}
            width={500}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>打码样式</Text>
                <Radio.Group
                  size="small"
                  value={watermarkMaskStyle}
                  onChange={(e) => setWatermarkMaskStyle(e.target.value)}
                >
                  <Radio.Button value="delogo">去水印</Radio.Button>
                  <Radio.Button value="gblur">高斯模糊</Radio.Button>
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
                  value={watermarkMaskWidthRatio}
                  onChange={(v) => setWatermarkMaskWidthRatio(v ?? 0.9)}
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
                  value={watermarkMaskHeightRatio}
                  onChange={(v) => setWatermarkMaskHeightRatio(v ?? 0.12)}
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
                  value={watermarkMaskBottomRatio}
                  onChange={(v) => setWatermarkMaskBottomRatio(v ?? 0.02)}
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>相对画面高（0.02），水印常在底部</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                自动检测失败时回退到"距底边"指定的底部水印带；若水印在顶部（台标/角标），
                建议用手动绝对坐标（暂未开放，可后续扩展）。
              </Text>
            </Space>
          </Modal>

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
                  <Radio.Button value="gblur">高斯模糊</Radio.Button>
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
              {/* 时间偏移（2026-11-21 审计⑤）：SRT 时轴校正与打码方式正交，改为常驻——
                  temporal（精细）模式无意义故置灰提示；payload 仅在非 temporal 时下发（1509 行门控保留） */}
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>时间偏移</Text>
                <InputNumber
                  size="small"
                  min={-10}
                  max={10}
                  step={0.5}
                  disabled={subtitleMaskTemporal}
                  value={subtitleMaskSrtOffset}
                  onChange={(v) => setSubtitleMaskSrtOffset(v ?? 0)}
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {subtitleMaskTemporal ? '秒：仅「快速」预设（非逐帧精细化）时生效' : '秒：字幕比SRT晚出现用正值延后（如 0.5）'}
                </Text>
              </Space>
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>打码预设</Text>
                <Select
                  size="small"
                  style={{ width: 130 }}
                  value={subtitleMaskPreset}
                  onChange={(v) => {
                    setSubtitleMaskPreset(v);
                    // 同步维护 temporal/spatial 派生状态（向后兼容旧字段）
                    setSubtitleMaskTemporal(v !== 'quick');
                    setSubtitleMaskSpatial(v === 'fine');
                  }}
                  options={SUBTITLE_MASK_PRESETS.map((o) => ({
                    value: o.value,
                    label: `${o.label}（${o.desc}）`,
                  }))}
                />
                <Tooltip title="三档预设收敛了原先「精细化/仅字幕显示区域」两个开关，降低配置出错率：自动=SRT动态窗口优先兼顾效果与速度（推荐）；精细=帧级+空间子区域最精确但更慢；快速=固定区域全程打码最快。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {SUBTITLE_MASK_PRESETS.find((o) => o.value === subtitleMaskPreset)?.desc}
              </Text>
            </Space>
          </Modal>

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
              <Space wrap align="center" size={8}>
                <Text strong style={{ fontSize: 13 }}>形态</Text>
                <Select
                  size="small"
                  style={{ width: 160 }}
                  value={watermarkStyle}
                  onChange={setWatermarkStyle}
                  options={WATERMARK_STYLE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
                <Text type="secondary" style={{ fontSize: 12, maxWidth: 260 }}>
                  {WATERMARK_STYLE_LABEL[watermarkStyle] ? (WATERMARK_STYLE_OPTIONS.find((o) => o.value === watermarkStyle)?.desc || '') : ''}
                </Text>
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
                  width: 120,
                  render: (m: string | null, t: SliceTask) => {
                    const label = SLICE_MODE_HELP[m || '']?.label || m || '-';
                    const tip = buildSliceConfigTooltip(t, label);
                    return (
                      <Tooltip title={tip}>
                        <Tag>{label}</Tag>
                      </Tooltip>
                    );
                  },
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
                      <Popconfirm
                        title="确定删除该条切片记录？"
                        description="将删除该任务及其全部成品文件，不可恢复"
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                        onConfirm={async () => {
                          try {
                            await sliceApi.delete(t.id);
                            message.success('切片记录已删除');
                            fetchSliceHistory();
                            fetchHistories();
                          } catch (err: unknown) {
                            message.error(err instanceof Error ? err.message : '删除失败');
                          }
                        }}
                      >
                        <Button size="small" danger type="text" icon={<DelIcon />}>删除</Button>
                      </Popconfirm>
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
          <Button
            type="primary"
            danger
            icon={<ScissorOutlined />}
            loading={oneClickSlicing}
            disabled={oneClickSlicing}
            onClick={() => setOneClickModalOpen(true)}
          >
            一键切片
          </Button>
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

          {/* ── 视频封面（选择图片作为视频首帧） ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <PictureOutlined />
              <Text strong style={{ fontSize: 13 }}>视频封面（首帧，可选）</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>选择一张图片作为视频首帧（成品开头先展示封面画面），不选择则直接按源视频首帧出片</Text>
            </Space>
            <Space wrap align="center" size={8}>
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={(file) => handleCoverUpload(file as File)}
                disabled={coverUploading}
              >
                <Button size="small" icon={<PictureOutlined />} loading={coverUploading}>选择封面图片</Button>
              </Upload>
              {coverImageKey && (
                <FileHoverPreview fileKey={coverImageKey} kind="image">
                <Tag closable onClose={() => {
  setCoverImageKey(null);
  setCoverImageName(null);
  sliceApi.updateEpisodeCover(episodeId, null).catch((err: unknown) => {
    console.error('清除剧集封面失败', err);
  });
}}>
                    封面：{coverImageName || '已选择'}
                </Tag>
                </FileHoverPreview>
              )}
            </Space>
          </div>

          {/* ── 钩子视频文件夹（片头，可选） ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <PlayCircleOutlined />
              <Text strong style={{ fontSize: 13 }}>钩子视频（可选）</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>支持选整个文件夹或多选视频文件，按混搭模式拼在片头/片尾；选完仅暂存，一键切片开始时才上传</Text>
            </Space>
            {renderHookPickerCore()}
            {renderHookOptions()}
          </div>

          {/* ── 输出档位 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8}>
              <Text strong style={{ fontSize: 13 }}>输出档位</Text>
              <Tooltip title="高分辨率/高 fps 素材可降档提速（引擎滤镜链末尾追加 scale+fps，cover concat 同步同档位）。">
                <InfoCircleOutlined style={{ color: '#999' }} />
              </Tooltip>
              <Select
                size="small"
                style={{ width: 240 }}
                value={outputTier || 'auto'}
                onChange={setOutputTier}
                options={[
                  { value: 'original', label: '原档（不处理）' },
                  { value: 'auto', label: '自动（高规格自动降 720P30）' },
                  { value: '1080p', label: '1080P（宽≤1080/fps≤60）' },
                  { value: '720p', label: '720P（宽≤720/fps≤30）' },
                  { value: '480p', label: '480P（宽≤480/fps≤30）' },
                ]}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>降档后编码耗时显著下降（预计 1/3 以下）</Text>
            </Space>
          </div>

          {/* ── AI 智能选点 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <CheckCircleOutlined />
              <Text strong style={{ fontSize: 13 }}>AI 智能选点</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>一键切片自动补选点时按此参数生成候选片段（与主页「AI 智能选点」参数同步）</Text>
            </Space>
            <Space wrap align="center" size={8}>
              <Text style={{ fontSize: 12 }}>选点上限</Text>
              <InputNumber size="small" min={1} max={20} style={{ width: 70 }} value={maxClips} onChange={(v) => setMaxClips(v ?? 10)} />
              <Text style={{ fontSize: 12 }}>最短时长</Text>
              <InputNumber size="small" min={0} style={{ width: 70 }} placeholder="不限" value={minClipDuration ?? undefined} onChange={(v) => setMinClipDuration(v ?? null)} />
              <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              <Text style={{ fontSize: 12 }}>最长时长</Text>
              <InputNumber size="small" min={1} style={{ width: 70 }} placeholder="不限" value={maxClipDuration ?? undefined} onChange={(v) => setMaxClipDuration(v ?? null)} />
              <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              <Text style={{ fontSize: 12 }}>最低分数</Text>
              <InputNumber size="small" min={0} max={100} style={{ width: 70 }} placeholder="不限" value={minScoreThreshold ?? undefined} onChange={(v) => setMinScoreThreshold(v ?? null)} />
            </Space>
            <Space wrap align="center" size={8} style={{ marginTop: 8 }}>
              <Switch size="small" checked={frameAnalysis} onChange={setFrameAnalysis} />
              <Text style={{ fontSize: 12 }}>画面理解（帧分析）</Text>
              {frameAnalysis && (
                <Select
                  size="small"
                  value={frameAnalysisProvider}
                  onChange={setFrameAnalysisProvider}
                  style={{ width: 100 }}
                  options={[
                    { value: 'ollama', label: '本地模型' },
                    { value: 'llm', label: '在线模型' },
                  ]}
                />
              )}
              <Switch size="small" checked={highlightMode} onChange={setHighlightMode} />
              <Text style={{ fontSize: 12 }}>高光识别模式</Text>
              {highlightMode && (
                <>
                  <Text style={{ fontSize: 12 }}>高光单段上限</Text>
                  <InputNumber size="small" min={3} max={60} style={{ width: 70 }} value={highlightMaxDuration} onChange={(v) => setHighlightMaxDuration(v ?? 10)} />
                  <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
                </>
              )}
            </Space>
          </div>

          {/* ── 去重模式 ── */}
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
            <Space wrap align="center" size={8} style={{ marginBottom: 8 }}>
              <Switch size="small" checked={dedupeEnabled} onChange={setDedupeEnabled} />
              <Text strong style={{ fontSize: 13 }}>去重模式</Text>
              <Tooltip title="开启后一键切片按所选档位对成品做画面去重（空间/时域/色彩变换组合），降低多平台批量发布查重风险">
                <InfoCircleOutlined style={{ color: '#999' }} />
              </Tooltip>
            </Space>
            {dedupeEnabled && (
              <Space wrap align="center" size={8}>
                <Text style={{ fontSize: 12 }}>档位</Text>
                <Select
                  size="small"
                  style={{ width: 200 }}
                  value={dedupePreset || 'std_crop_desat'}
                  onChange={setDedupePreset}
                  options={[
                    { value: 'std_crop_desat', label: '保守裁切降饱和（推荐）' },
                    { value: 'std_retro_scan', label: '复古扫描' },
                    { value: 'light', label: '轻' },
                    { value: 'standard', label: '标准' },
                    { value: 'heavy', label: '重' },
                  ]}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>手动逐项配置沿用主页「去重高级配置」</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={20}
                  placeholder="变体数"
                  value={variantCount}
                  onChange={(v) => setVariantCount(v ?? undefined)}
                  style={{ width: 90 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>多版本数（&gt;1 时切片后派生 N 个去重版本）</Text>
              </Space>
            )}
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
                <Select size="small" style={{ width: 180 }} value={vert2horizOutputSize} onChange={setVert2horizOutputSize} options={VERT2HORIZON_OUTPUT_SIZES} />
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
                <InputNumber size="small" min={10} max={60} step={1} value={Math.round(subtitleFontRatio * 100)} onChange={(v) => { const fs = v ?? 30; setSubtitleFontRatio(Math.max(0.1, Math.min(0.6, fs / 100))); }} style={{ width: 80 }} />
                <SubtitleMarginPicker value={subtitleMarginRatio} onChange={setSubtitleMarginRatio} />
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
                  { value: 'gblur', label: '高斯模糊' },
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
                <Text style={{ fontSize: 12 }}>预设</Text>
                <Select
                  size="small"
                  style={{ width: 110 }}
                  value={subtitleMaskPreset}
                  onChange={(v) => {
                    setSubtitleMaskPreset(v);
                    setSubtitleMaskTemporal(v !== 'quick');
                    setSubtitleMaskSpatial(v === 'fine');
                  }}
                  options={SUBTITLE_MASK_PRESETS.map((o) => ({ value: o.value, label: o.label }))}
                />
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
                <Text style={{ fontSize: 12 }}>形态</Text>
                <Select size="small" style={{ width: 90 }} value={watermarkStyle} onChange={setWatermarkStyle} options={WATERMARK_STYLE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
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

      {/* 2026-11-21 业务线重组：3 张动作卡 → 6 条业务线纵排（选片/混剪方式/营销钩子/画面包装/防搬运/执行提交），
          纯 JSX 重排，所有 state 留在原地；各线卡头带「已开启」徽标，跨线冲突在「切片执行」卡顶部体检条汇总 */}
      {/* 2026-11-23 布局定稿：左栏=选片线（选点历史固定高度滚动，不再撑长页面）；
          右栏=混剪方式/营销钩子/画面包装/防搬运均下拉折叠（默认收起）+切片执行常驻展开 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {actions
              .filter((a) => a.title.startsWith('🎬'))
              .map((a) => (
                <Card size="small" key={a.title} title={a.title} extra={a.extra}>{a.node}</Card>
              ))}
          </Space>
        </Col>
        <Col xs={24} md={12}>
          <Collapse
            size="small"
            activeKey={openLines}
            onChange={(keys) => {
              const arr = Array.isArray(keys) ? keys : [keys];
              setOpenLines(arr);
              localStorage.setItem('slice_open_lines', JSON.stringify(arr));
            }}
            items={actions
              .filter((a) => !a.title.startsWith('🎬'))
              .map((a) => ({
                key: a.title,
                label: a.title,
                extra: a.extra,
                children: a.node,
              }))}
          />
        </Col>
      </Row>
      {/* 一键切片模式选择（2026-11-23 简化：双配+双批混拼收进一键切片） */}
      <Modal
        title="一键切片"
        open={oneClickModalOpen}
        onCancel={() => setOneClickModalOpen(false)}
        confirmLoading={oneClickSlicing}
        onOk={() => {
          setOneClickModalOpen(false);
          localStorage.setItem('oc_hl_min', String(ocHlMin));
          localStorage.setItem('oc_hl_max', String(ocHlMax));
          localStorage.setItem('oc_main_min', String(ocMainMin));
          localStorage.setItem('oc_main_max', String(ocMainMax));
          void oneClickSlice();
        }}
        okText={ocMode === 'dual' ? '开始双配混拼' : '开始切片'}
        cancelText="取消"
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Space size={8} align="center">
            <Text strong>模式</Text>
            <Select
              style={{ width: 220 }}
              value={ocMode}
              onChange={(v) => setOcMode(v as 'normal' | 'dual')}
              options={[
                { value: 'normal', label: '常规（按当前候选/参数直出）' },
                { value: 'dual', label: '双配混拼（高光+正片两条流水）' },
              ]}
            />
          </Space>
          {ocMode === 'dual' ? (
            <>
              <Alert
                type="info"
                showIcon
                message="双配混拼：自动重跑一轮双配选点（正片批 + 高光批一次产出），每条成品 = 高光×2 + 正片×1（高光在前，先钩住再展开），条数按正片自动。钩子按现有配置拼接。"
              />
              <Space size={6} align="center" wrap>
                <Text strong style={{ fontSize: 12 }}>高光时长</Text>
                <InputNumber size="small" min={1} max={60} value={ocHlMin} onChange={(v) => setOcHlMin(v ?? 5)} style={{ width: 70 }} />
                <Text type="secondary">~</Text>
                <InputNumber size="small" min={2} max={60} value={ocHlMax} onChange={(v) => setOcHlMax(v ?? 10)} style={{ width: 70 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              </Space>
              <Space size={6} align="center" wrap>
                <Text strong style={{ fontSize: 12 }}>正片时长</Text>
                <InputNumber size="small" min={30} max={600} value={ocMainMin} onChange={(v) => setOcMainMin(v ?? 120)} style={{ width: 80 }} />
                <Text type="secondary">~</Text>
                <InputNumber size="small" min={60} max={600} value={ocMainMax} onChange={(v) => setOcMainMax(v ?? 240)} style={{ width: 80 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                提交后自动重跑选点（约 10-30 分钟）再自动切片，全程无需人工介入。
              </Text>
            </>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              免审核直接出片：自动把所有候选片段（含待审核）直接切割成成品视频。
            </Text>
          )}
        </Space>
      </Modal>

    </div>
  );
};

export default EpisodeDetail;