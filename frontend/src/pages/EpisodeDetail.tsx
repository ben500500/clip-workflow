import React, { useEffect, useRef, useState } from 'react';
import {
  Card, Button, Space, Typography, Spin, Alert, Breadcrumb, Descriptions, Tag, message, Select, Row, Col, Progress,
  Steps, InputNumber, Tooltip, Popconfirm, Switch, Slider, Input, Table,
} from 'antd';
import {
  ArrowLeftOutlined, ThunderboltOutlined, RadarChartOutlined, ScissorOutlined,
  CheckCircleOutlined, ClockCircleOutlined, InfoCircleOutlined, PlayCircleOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { autoclipApi } from '../api/autoclip';
import { intervalApi } from '../api/intervals';
import { sliceApi } from '../api/slice';
import ErrorHint from '../components/ErrorHint';
import type { AutoClipRunRecord, Episode, IntervalHistoryItem, SliceTask } from '../types';
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
    detail: '在切割的同时对每个片段进行画面相似度检测，去除重复度高的内容片段。适用于需要批量发布到多个平台的场景，减少重复内容被平台限流的风险。',
  },
  scrub: {
    label: '挖洞模式',
    desc: '在去重基础上随机挖洞',
    detail: '在去重模式的基础上，进一步对片段中随机位置进行微小的画面挖洞处理（替换为纯色帧），使每个输出片段的指纹更加独特。适合高频发布场景，有效降低平台查重处罚。',
  },
};

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

const EpisodeDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const episodeId = id || '';

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detectMode, setDetectMode] = useState('credits');
  const [sliceMode, setSliceMode] = useState('fast');
  // ── 切片自定义文字水印开关与参数 ──
  const [watermarkEnabled, setWatermarkEnabled] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [watermarkFontSize, setWatermarkFontSize] = useState(28);
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.5);
  const [watermarkPosition, setWatermarkPosition] = useState('bottom');
  // ── 竖屏转横屏智能裁切开关与参数 ──
  const [vert2horizEnabled, setVert2horizEnabled] = useState(false);
  const [vert2horizMode, setVert2horizMode] = useState<'fixed' | 'dynamic'>('fixed');
  const [vert2horizRatio, setVert2horizRatio] = useState(0.5625);
  const [vert2horizOutputSize, setVert2horizOutputSize] = useState('1280x720');
  const [vert2horizDetectInterval, setVert2horizDetectInterval] = useState(2);
  const [vert2horizSmoothWindow, setVert2horizSmoothWindow] = useState(15);
  // 动态模式最小移动阈值（px）：越大越稳、越小越跟手
  const [vert2horizMinStep, setVert2horizMinStep] = useState(5);
  const [maxClips, setMaxClips] = useState(10);
  const [minScoreThreshold, setMinScoreThreshold] = useState<number | null>(null);
  const [minClipDuration, setMinClipDuration] = useState<number | null>(null);
  const [maxClipDuration, setMaxClipDuration] = useState<number | null>(null);
  const [autoclipProgress, setAutoclipProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
  const [autoclipRunning, setAutoclipRunning] = useState(false);
  const [detectRunning, setDetectRunning] = useState(false);
  const [detectProgress, setDetectProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null; interval_count?: number | null; interval_type?: string | null } | null>(null);
  const [detectResultCount, setDetectResultCount] = useState<number | null>(null);
  const [sliceRunning, setSliceRunning] = useState(false);
  const [sliceProgress, setSliceProgress] = useState<{ status: string; progress: number; message: string; error_message?: string | null } | null>(null);
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

  // ─── 一键切片（免审核直接出片） ──────────────────────
  const oneClickSlice = async () => {
    setOneClickSlicing(true);
    setOneClickProgress({ status: 'running', progress: 5, message: '正在提交一键切片任务…' });
    try {
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
        vert2horiz_min_step: vert2horizEnabled ? vert2horizMinStep : undefined,
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

  // ─── 启动切片 ───────────────────────────────────────
  const runSlice = async () => {
    setSliceRunning(true);
    setSliceProgress({ status: 'running', progress: 5, message: '正在提交切片任务…' });
    try {
      const res = await sliceApi.run(episodeId, sliceMode, {
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
        vert2horiz_min_step: vert2horizEnabled ? vert2horizMinStep : undefined,
      });
      message.success(res.message);
      fetchHistories();
      // 启动后轮询任务进度
      pollLatestSliceProgress(sliceMode, setSliceRunning, setSliceProgress);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动切片失败');
      setSliceRunning(false);
      setSliceProgress(null);
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
            <Tooltip title="设置 AI 选点推荐的最大片段数量，数量越多等待时间越长">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>选点个数:</Text>
                <InputNumber
                  size="small"
                  min={1}
                  max={100}
                  value={maxClips}
                  onChange={(v) => setMaxClips(v ?? 10)}
                  style={{ width: 70 }}
                />
              </Space>
            </Tooltip>
            <Tooltip title="设置候选片段入选的最低评分（0-100），留空则使用系统默认（60）">
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>入选评分:</Text>
                <InputNumber
                  size="small"
                  min={0}
                  max={100}
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
                  placeholder="秒"
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
                  placeholder="秒"
                  value={maxClipDuration}
                  onChange={(v) => setMaxClipDuration(v ?? null)}
                  style={{ width: 80 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>秒</Text>
              </Space>
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
                    ) : m || '-',
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
            <Select value={sliceMode} onChange={setSliceMode} style={{ width: 120 }}
              options={[
                { value: 'fast', label: '快速模式' },
                { value: 'dedupe', label: '去重模式' },
                { value: 'scrub', label: '挖洞模式' },
              ]}
            />
            <Button icon={<ScissorOutlined />} loading={sliceRunning} onClick={runSlice}>开始切片</Button>
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

          {/* ── 自定义文字水印开关 ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space>
                <Switch checked={watermarkEnabled} onChange={setWatermarkEnabled} size="small" />
                <Text strong style={{ fontSize: 13 }}>动态文字水印</Text>
                <Tooltip title="开启后会在切片成品视频上叠加动态文字水印（文字缓慢移动 + 透明度呼吸），可用于防搬运/标识来源。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
              </Space>
              {watermarkEnabled && (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space style={{ width: '100%' }} wrap>
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>水印文字:</Text>
                    <Input
                      size="small"
                      style={{ width: 220 }}
                      placeholder="留空默认：剧集标题 + 日期（支持 {title} {date} {datetime}）"
                      value={watermarkText}
                      onChange={(e) => setWatermarkText(e.target.value)}
                    />
                  </Space>
                  <Space style={{ width: '100%' }} wrap>
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>字号:</Text>
                    <InputNumber
                      size="small"
                      min={12}
                      max={120}
                      value={watermarkFontSize}
                      onChange={(v) => setWatermarkFontSize(v ?? 28)}
                      style={{ width: 80 }}
                    />
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>透明度:</Text>
                    <Slider
                      style={{ width: 120, margin: '0 8px' }}
                      min={5}
                      max={100}
                      value={Math.round(watermarkOpacity * 100)}
                      onChange={(v) => setWatermarkOpacity(v / 100)}
                    />
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{Math.round(watermarkOpacity * 100)}%</Text>
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>位置:</Text>
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
              )}
            </Space>
          </Card>

          {/* ── 竖屏转横屏智能裁切开关 ── */}
          <Card size="small" style={{ width: '100%' }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space>
                <Switch checked={vert2horizEnabled} onChange={setVert2horizEnabled} size="small" />
                <Text strong style={{ fontSize: 13 }}>竖屏转横屏</Text>
                <Tooltip title="开启后若素材为竖屏（9:16），切片前自动转为横屏（16:9）：固定裁切快速稳定，动态跟踪会逐帧检测人脸确保人物不出画。适用于发布到视频号横屏模式 / B站等横屏平台。">
                  <InfoCircleOutlined style={{ color: '#999', cursor: 'pointer' }} />
                </Tooltip>
              </Space>
              {vert2horizEnabled && (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space style={{ width: '100%' }} wrap>
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>裁切模式:</Text>
                    <Select
                      size="small"
                      style={{ width: 130 }}
                      value={vert2horizMode}
                      onChange={setVert2horizMode}
                      options={[
                        { value: 'fixed', label: '固定裁切（快）' },
                        { value: 'dynamic', label: '动态跟踪（准）' },
                      ]}
                    />
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>输出分辨率:</Text>
                    <Input
                      size="small"
                      style={{ width: 120 }}
                      value={vert2horizOutputSize}
                      onChange={(e) => setVert2horizOutputSize(e.target.value)}
                      placeholder="1280x720"
                    />
                    <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>裁切比例:</Text>
                    <InputNumber
                      size="small"
                      min={0.1}
                      max={1}
                      step={0.05}
                      value={vert2horizRatio}
                      onChange={(v) => setVert2horizRatio(v ?? 0.5625)}
                      style={{ width: 90 }}
                    />
                  </Space>
                  {vert2horizMode === 'dynamic' && (
                    <Space style={{ width: '100%' }} wrap>
                      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>检测间隔(帧):</Text>
                      <InputNumber
                        size="small"
                        min={1}
                        max={30}
                        value={vert2horizDetectInterval}
                        onChange={(v) => setVert2horizDetectInterval(v ?? 2)}
                        style={{ width: 80 }}
                      />
                      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>平滑窗口(帧):</Text>
                      <InputNumber
                        size="small"
                        min={1}
                        max={60}
                        value={vert2horizSmoothWindow}
                        onChange={(v) => setVert2horizSmoothWindow(v ?? 15)}
                        style={{ width: 80 }}
                      />
                      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>最小移动(px):</Text>
                      <InputNumber
                        size="small"
                        min={0}
                        max={30}
                        value={vert2horizMinStep}
                        onChange={(v) => setVert2horizMinStep(v ?? 5)}
                        style={{ width: 80 }}
                      />
                      <Text type="secondary" style={{ fontSize: 12 }}>动态模式较慢（约 3-5 分钟/10 分钟视频），固定模式仅需一遍 ffmpeg（约 30 秒）</Text>
                    </Space>
                  )}
                </Space>
              )}
            </Space>
          </Card>

          {/* 进度条：切片动作 tab 最底部 */}
          {renderProgress(sliceProgress)}
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
              scroll={{ x: 420 }}
              columns={[
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
                      <Text style={{ fontSize: 12 }}>产出 {t.output_count} 个成品</Text>
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
            onConfirm={oneClickSlice}
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
        </Space>
        {/* 一键切片实时进度条：任务进行中时展示在按钮下方 */}
        {renderProgress(oneClickProgress)}
      </Card>

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