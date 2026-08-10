import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Card, Typography, Space, Button, Select, Table, Progress, Tag, Modal,
  Popconfirm, Checkbox, Tooltip, message, Input, Radio, Spin, Empty,
} from 'antd';
import {
  PlayCircleOutlined, DownloadOutlined, DeleteOutlined,
  PlusOutlined, ReloadOutlined, VideoCameraOutlined, ClearOutlined,
  InboxOutlined, SendOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import { watermarkApi, type WatermarkTaskDetail, type WatermarkTaskItem } from '../api/watermark';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

// ─── 引擎说明 ───
const ENGINE_HELP: Record<string, { label: string; desc: string }> = {
  remove_ai: {
    label: 'Remove AI Watermarks（RAiW）',
    desc: '支持 Sora / Veo / Seedance / Dola / Hailuo / Kling 等常见可见 AI 水印，同时清除 C2PA/EXIF 等 AI 元数据。自动扫描匹配，也可指定厂商。',
  },
  seedance: {
    label: 'Seedance 2.0 Watermark Remover',
    desc: '针对 Seedance "AI生成" 角标自动检测 + OpenCV TELEA 修补，无需 GPU，CPU 即可运行，也支持任意角落 logo/文字水印。',
  },
  seedance_wm: {
    label: 'Seedance 5-Stage Pipeline（seedance_wm）',
    desc: '集成自 ben500500/remover 仓库的 5 阶段流水线：抽帧 → 检测（matchTemplate/YOLO/OCR 降级链）→ mask → 修复（LaMa→cv2）+时序平滑 → 合成。支持分段检测与移动水印。',
  },
  remove_mask: {
    label: 'Remove Mask（ROI 经验库）',
    desc: '集成自 ben500500/remove-mask 仓库（同步 v11 更新）：处理前自动分析任意视频水印带（四角时间一致性热力图 + 边缘先验检测，修复右上 TR 等弱/淡色水印漏检），命中预置 ROI（含爷孙重逢，实测左上 TL + 右上 TR + 右下 BR，修复 TL 漏覆盖）时用人工精调框，其他视频自动检测、检测不到回退全角大框。ROI + cv2.inpaint（NS/TELEA）插值填充，支持 inpaint（插值修复）/ crop（裁切去水印）两种模式。提供按《引擎排名结论.md》排序的预设方案（ns_small_r5 最优）。',
  },
};

interface PendingFile {
  uploadId: string;
  fileName: string;
  fileSize: number;
  sourceFileKey: string;
  uploadPercent: number;
  // 来源提示词记录 id（提示词 → 去水印 → 发布 任务关联）
  promptRecordId?: string | null;
  // 签名播放地址（本地上传时为预览直链，导入时为后端返回的 presigned URL）
  url?: string | null;
}

// 从「短片制作」生成历史一键导入的成片视频
export interface ImportedVideo {
  sourceFileKey: string;
  fileName: string | null;
  fileSize: number | null;
  // 来源提示词记录 id（提示词 → 去水印 → 发布 任务关联）
  promptRecordId?: string | null;
  // 签名播放地址（用于待处理列表缩略图 / 悬停预览）
  url?: string | null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: '等待处理',
  running: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

// 任务名称：日期（YYYYMMDD）+ 4 位自增序列
// 序列按天自增（跨页面刷新通过 localStorage 续接，避免同秒重复），后端无 name 时用 Redis 兜底生成
const pad4 = (n: number) => String(n).padStart(4, '0');
const SEQ_STORAGE_KEY = 'watermark_task_seq';
const genTaskName = () => {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, '0');
  const day = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`;
  let seq = 0;
  try {
    const saved = localStorage.getItem(SEQ_STORAGE_KEY);
    if (saved) {
      const [s, savedDay] = saved.split('|');
      if (savedDay === day) seq = parseInt(s, 10) || 0;
    }
  } catch {
    /* 忽略 localStorage 异常 */
  }
  seq = (seq % 9999) + 1;
  try {
    localStorage.setItem(SEQ_STORAGE_KEY, `${seq}|${day}`);
  } catch {
    /* 忽略 localStorage 异常 */
  }
  return `${day}-${pad4(seq)}`;
};

const Watermark: React.FC<{
  imports?: ImportedVideo[];
  onImportsConsumed?: () => void;
  onGoToPublish?: (promptRecordId?: string | null) => void;
}> = ({ imports = [], onImportsConsumed, onGoToPublish }) => {
  const [engine, setEngine] = useState<'remove_ai' | 'seedance' | 'seedance_wm' | 'remove_mask'>('remove_mask');
  // RAiW 选项
  const [mark, setMark] = useState('auto');
  const [backend, setBackend] = useState('auto');
  const [temporal, setTemporal] = useState(true);
  // Seedance / seedance_wm 选项
  const [region, setRegion] = useState('');
  const [seedanceBackend, setSeedanceBackend] = useState('auto');
  const [segments, setSegments] = useState(4);
  // seedance_wm 专属选项
  const [detector, setDetector] = useState('matchTemplate');
  const [inpainter, setInpainter] = useState('auto');
  const [keepAudio, setKeepAudio] = useState(true);
  // remove_mask 专属选项
  const [maskRadius, setMaskRadius] = useState(5);
  const [maskIterations, setMaskIterations] = useState(1);
  const [maskScope, setMaskScope] = useState<'small' | 'large'>('small');
  const [maskMode, setMaskMode] = useState<'inpaint' | 'crop'>('inpaint');
  const [maskAlgo, setMaskAlgo] = useState<'ns' | 'telea'>('ns');
  const [maskPreset, setMaskPreset] = useState<string>('');

  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [taskName, setTaskName] = useState(genTaskName);
  const [running, setRunning] = useState(false);

  const [tasks, setTasks] = useState<WatermarkTaskItem[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([]);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [taskDetails, setTaskDetails] = useState<Record<string, WatermarkTaskDetail>>({});
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null);

  // 预览弹窗
  const [previewVideo, setPreviewVideo] = useState<{ url: string; title: string } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ─── 接收从「短片制作」历史一键导入的成片视频 ───
  useEffect(() => {
    if (imports.length === 0) return;
    setPendingFiles((prev) => {
      const existing = new Set(prev.map((f) => f.sourceFileKey));
      const next = [...prev];
      imports.forEach((imp) => {
        if (imp.sourceFileKey && !existing.has(imp.sourceFileKey)) {
          next.push({
            uploadId: `import-${Date.now()}-${next.length}-${Math.random().toString(36).slice(2, 8)}`,
            fileName: imp.fileName || imp.sourceFileKey.split('/').pop() || '导入视频',
            fileSize: imp.fileSize ?? 0,
            sourceFileKey: imp.sourceFileKey,
            uploadPercent: 100,
            promptRecordId: imp.promptRecordId || null,
            url: imp.url || null,
          });
        }
      });
      return next;
    });
    message.success(`已导入 ${imports.length} 条成片视频，可直接提交去水印`);
    if (onImportsConsumed) onImportsConsumed();
  }, [imports, onImportsConsumed]);

  // ─── 任务历史加载 ───
  const fetchTasks = useCallback(async (silent = false) => {
    if (!silent) setLoadingTasks(true);
    try {
      const list = await watermarkApi.listTasks();
      setTasks(list);
    } catch (err: unknown) {
      if (!silent) message.error(err instanceof Error ? err.message : '获取任务列表失败');
    } finally {
      if (!silent) setLoadingTasks(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const timer = window.setInterval(() => fetchTasks(true), 5000);
    return () => window.clearInterval(timer);
  }, [fetchTasks]);

  // 轮询展开任务详情（进度实时刷新）
  useEffect(() => {
    if (!expandedTaskId) return;
    const loadDetail = async () => {
      try {
        const detail = await watermarkApi.getTask(expandedTaskId);
        setTaskDetails((prev) => ({ ...prev, [expandedTaskId]: detail }));
      } catch {
        // 静默失败
      }
    };
    loadDetail();
    const timer = window.setInterval(loadDetail, 5000);
    return () => window.clearInterval(timer);
  }, [expandedTaskId]);

  // ─── 文件选择与上传 ───
  const handleSelectFiles = (files: FileList | File[]) => {
    const arr = Array.from(files);
    if (arr.length === 0) return;
    setUploading(true);
    let completed = 0;
    arr.forEach((file) => {
      // 生成本地预览地址（缩略图 / 悬停预览），上传失败时回收
      let objectUrl: string | null = null;
      try {
        objectUrl = URL.createObjectURL(file);
      } catch {
        objectUrl = null;
      }
      watermarkApi
        .upload(file, (pct) => {
          // 上传进度：用临时占位更新（简化处理，批量上传时按整体提示）
        })
        .then((res) => {
          setPendingFiles((prev) => [
            ...prev,
            {
              uploadId: res.upload_id,
              fileName: res.file_name,
              fileSize: res.file_size,
              sourceFileKey: res.source_file_key,
              uploadPercent: 100,
              url: objectUrl,
            },
          ]);
        })
        .catch((err: unknown) => {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          message.error(`上传 ${file.name} 失败：${err instanceof Error ? err.message : '未知错误'}`);
        })
        .finally(() => {
          completed += 1;
          if (completed === arr.length) {
            setUploading(false);
          }
        });
    });
  };

  const removePendingFile = (uploadId: string) => {
    setPendingFiles((prev) => {
      const target = prev.find((f) => f.uploadId === uploadId);
      if (target?.url && target.url.startsWith('blob:')) URL.revokeObjectURL(target.url);
      return prev.filter((f) => f.uploadId !== uploadId);
    });
  };

  const clearPending = () => {
    setPendingFiles((prev) => {
      prev.forEach((f) => {
        if (f.url && f.url.startsWith('blob:')) URL.revokeObjectURL(f.url);
      });
      return [];
    });
  };

  // ─── 提交任务 ───
  const submitTask = async () => {
    if (pendingFiles.length === 0) {
      message.warning('请先上传至少一个视频');
      return;
    }
    setRunning(true);
    try {
      const params: {
        engine: 'remove_ai' | 'seedance' | 'seedance_wm' | 'remove_mask';
        files: string[];
        name?: string;
        mark?: string;
        backend?: string;
        temporal_consistency?: boolean;
        region?: string;
        use_lama?: boolean;
        segments?: number;
        detector?: string;
        inpainter?: string;
        keep_audio?: boolean;
        radius?: number;
        iterations?: number;
        prompt_record_id?: string | null;
        scope?: 'small' | 'large';
        mode?: 'inpaint' | 'crop';
        algo?: 'ns' | 'telea';
        preset?: string;
      } = {
        engine,
        files: pendingFiles.map((f) => f.sourceFileKey),
        name: taskName.trim() || undefined,
      };
      // 携带来源提示词记录 id（提示词 → 去水印 → 发布 任务关联）
      const firstPromptId = pendingFiles.find((f) => f.promptRecordId)?.promptRecordId;
      if (firstPromptId) params.prompt_record_id = firstPromptId;
      if (engine === 'remove_ai') {
        params.mark = mark;
        params.backend = backend;
        params.temporal_consistency = temporal;
        if (region.trim()) params.region = region.trim();
      } else if (engine === 'seedance') {
        params.region = region.trim() || undefined;
        params.backend = seedanceBackend;
        params.segments = segments;
      } else if (engine === 'remove_mask') {
        params.region = region.trim() || undefined;
        params.radius = maskRadius;
        params.iterations = maskIterations;
        params.scope = maskScope;
        params.mode = maskMode;
        params.algo = maskAlgo;
        if (maskPreset) params.preset = maskPreset;
      } else {
        params.region = region.trim() || undefined;
        params.backend = seedanceBackend;
        params.segments = segments;
        if (detector) params.detector = detector;
        if (inpainter && inpainter !== 'auto') params.inpainter = inpainter;
        params.keep_audio = keepAudio;
      }
      const res = await watermarkApi.run(params);
      message.success(res.message);
      // 提交后回收本地 blob 预览地址
      setPendingFiles((prev) => {
        prev.forEach((f) => {
          if (f.url && f.url.startsWith('blob:')) URL.revokeObjectURL(f.url);
        });
        return [];
      });
      setTaskName(genTaskName());
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '提交任务失败');
    } finally {
      setRunning(false);
    }
  };

  // ─── 展开/收起任务 ───
  const toggleExpand = async (taskId: string) => {
    if (expandedTaskId === taskId) {
      setExpandedTaskId(null);
      return;
    }
    setExpandedTaskId(taskId);
    setLoadingDetail(taskId);
    try {
      const detail = await watermarkApi.getTask(taskId);
      setTaskDetails((prev) => ({ ...prev, [taskId]: detail }));
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载任务详情失败');
    } finally {
      setLoadingDetail(null);
    }
  };

  // ─── 去水印完成 → 发布：定位关联的提示词记录 id ───
  // 优先使用任务级 prompt_record_id；缺失时（历史任务/缓存数据）
  // 回退读取任务详情里子视频的来源提示词记录，保证链路一致
  const handleGoToPublish = async (task: WatermarkTaskItem) => {
    if (!onGoToPublish) return;
    let promptRecordId = task.prompt_record_id || null;
    if (!promptRecordId) {
      try {
        const detail = await watermarkApi.getTask(task.id);
        const fromVideo =
          (detail.videos || []).find((v) => v.prompt_record_id)?.prompt_record_id || null;
        promptRecordId = fromVideo;
      } catch {
        /* 详情读取失败时保持 null，发布页不会代入文案 */
      }
    }
    onGoToPublish(promptRecordId);
  };

  // ─── 重试：把失败/取消任务的源视频重新导入待处理列表 ───
  const retryTask = async (task: WatermarkTaskItem) => {
    try {
      const detail = await watermarkApi.getTask(task.id);
      const videos = detail.videos || [];
      const retriable = videos.filter((v) => v.status === 'failed' || v.status === 'cancelled');
      if (retriable.length === 0) {
        message.warning('该任务没有可重试的失败/取消视频');
        return;
      }
      setPendingFiles((prev) => {
        const existing = new Set(prev.map((f) => f.sourceFileKey));
        const next = [...prev];
        retriable.forEach((v) => {
          if (v.source_file_key && !existing.has(v.source_file_key)) {
            next.push({
              uploadId: `retry-${Date.now()}-${next.length}-${Math.random().toString(36).slice(2, 8)}`,
              fileName: v.file_name,
              fileSize: v.file_size ?? 0,
              sourceFileKey: v.source_file_key,
              uploadPercent: 100,
              promptRecordId: v.prompt_record_id || task.prompt_record_id || null,
              url: v.source_url || null,
            });
          }
        });
        return next;
      });
      message.success(`已将 ${retriable.length} 条源视频重新导入待处理列表，可直接提交去水印`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '重试失败，无法读取任务源视频');
    }
  };

  // ─── 删除操作 ───
  const deleteTask = async (taskId: string) => {
    try {
      const res = await watermarkApi.deleteTask(taskId);
      message.success(res.message);
      setSelectedTaskIds((prev) => prev.filter((id) => id !== taskId));
      if (expandedTaskId === taskId) setExpandedTaskId(null);
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除任务失败');
    }
  };

  const batchDelete = async () => {
    if (selectedTaskIds.length === 0) {
      message.warning('请先勾选要删除的任务');
      return;
    }
    try {
      const res = await watermarkApi.batchDeleteTasks(selectedTaskIds);
      message.success(res.message);
      setSelectedTaskIds([]);
      setExpandedTaskId(null);
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量删除失败');
    }
  };

  const deleteVideo = async (videoId: string, taskId: string) => {
    try {
      const res = await watermarkApi.deleteVideo(videoId);
      message.success(res.message);
      const detail = await watermarkApi.getTask(taskId);
      setTaskDetails((prev) => ({ ...prev, [taskId]: detail }));
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除视频失败');
    }
  };

  // ─── 下载操作 ───
  const downloadVideo = async (videoId: string) => {
    try {
      const res = await watermarkApi.downloadVideo(videoId);
      window.open(res.url, '_blank');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取下载链接失败');
    }
  };

  const downloadBatch = async (videoIds: string[], taskId: string) => {
    if (!videoIds.length) return;
    try {
      const res = await watermarkApi.batchDownload(videoIds);
      // 逐个打开直链（浏览器会拦截多个弹窗，用 iframe 方式触发更稳）
      res.files.forEach((f) => {
        const a = document.createElement('a');
        a.href = f.url;
        a.download = f.file_name;
        a.target = '_blank';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      });
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量下载失败');
    }
  };

  // ─── 任务表格列 ───
  const taskColumns = [
    {
      title: '引擎',
      dataIndex: 'engine',
      key: 'engine',
      width: 150,
      ellipsis: true,
      render: (e: string, t: WatermarkTaskItem) => (
        <Tag color={e === 'remove_ai' ? 'blue' : e === 'seedance' ? 'purple' : e === 'seedance_wm' ? 'geekblue' : 'cyan'} style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.engine_display}</Tag>
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (n: string, t: WatermarkTaskItem) => (
        <a
          style={{ cursor: 'pointer' }}
          onClick={(e) => {
            e.stopPropagation();
            toggleExpand(t.id);
          }}
        >
          {n || '-'}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (s: string, t: WatermarkTaskItem) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>
          {(s === 'running' || s === 'pending') && (
            <Progress percent={Math.round(t.progress)} size="small" status="active" style={{ width: 110 }} />
          )}
        </Space>
      ),
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 80,
      render: (p: number) => `${Math.round(p)}%`,
    },
    {
      title: '耗时',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 90,
      render: (d: number | null | undefined, t: WatermarkTaskItem) =>
        t.started_at ? formatDuration(t.duration_seconds ?? null) : '-',
    },
    {
      title: '视频',
      key: 'count',
      width: 150,
      render: (_: unknown, t: WatermarkTaskItem) => (
        <Text style={{ fontSize: 12 }}>
          共 {t.total_count} 条 · 完成 {t.completed_count} · 失败 {t.failed_count}
        </Text>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (d: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      render: (_: unknown, t: WatermarkTaskItem) => (
        <Space size="small">
          {t.status === 'completed' && onGoToPublish && (
            <Button
              size="small"
              type="primary"
              ghost
              icon={<SendOutlined />}
              onClick={() => handleGoToPublish(t)}
            >
              发布
            </Button>
          )}
          {(t.failed_count > 0 || t.status === 'failed' || t.status === 'cancelled') && (
            <Tooltip title="把该任务的失败/取消源视频重新导入待处理列表，可调整参数后再次提交">
              <Button size="small" icon={<ReloadOutlined />} onClick={() => retryTask(t)}>
                重试
              </Button>
            </Tooltip>
          )}
          <Button size="small" onClick={() => toggleExpand(t.id)}>
            {expandedTaskId === t.id ? '收起' : '展开'}
          </Button>
          <Popconfirm
            title="确定删除该任务？"
            description="将同时删除任务下所有视频的源文件与处理后文件"
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

  // ─── 任务下视频渲染 ───
  const renderVideos = (taskId: string) => {
    const detail = taskDetails[taskId];
    if (loadingDetail === taskId && !detail) {
      return (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      );
    }
    if (!detail) return null;
    const videos = detail.videos || [];

    if (videos.length === 0) {
      return <Empty description="暂无视频" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
    }

    const doneVideos = videos.filter((v) => v.status === 'completed');

    return (
      <div>
        <Space style={{ marginBottom: 12 }} wrap>
          <Text strong>本任务视频（{videos.length} 条）</Text>
          {doneVideos.length > 0 && (
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => downloadBatch(doneVideos.map((v) => v.id), taskId)}
            >
              批量下载已完成 ({doneVideos.length})
            </Button>
          )}
        </Space>
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={videos}
          scroll={{ x: 980 }}
          columns={[
            {
              title: '文件名',
              dataIndex: 'file_name',
              key: 'file_name',
              ellipsis: true,
              render: (n: string) => <Text style={{ fontSize: 13 }}>{n}</Text>,
            },
            {
              title: '大小',
              dataIndex: 'file_size',
              key: 'file_size',
              width: 100,
              render: (s: number | null, v) =>
                v.status === 'completed' && v.output_file_size
                  ? formatFileSize(v.output_file_size)
                  : formatFileSize(s),
            },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              width: 160,
              render: (s: string, v) => (
                <Space direction="vertical" size={0} style={{ width: '100%' }}>
                  <Tag color={getStatusColor(s)}>{STATUS_LABELS[s] || getStatusLabel(s)}</Tag>
                  {(s === 'running' || s === 'pending') && (
                    <Progress percent={Math.round(v.progress)} size="small" status="active" style={{ width: 120 }} />
                  )}
                </Space>
              ),
            },
            {
              title: '进度',
              dataIndex: 'progress',
              key: 'progress',
              width: 70,
              render: (p: number) => `${Math.round(p)}%`,
            },
            {
              title: '耗时',
              dataIndex: 'duration_seconds',
              key: 'duration_seconds',
              width: 90,
              render: (d: number | null | undefined, v) =>
                v.started_at ? formatDuration(v.duration_seconds ?? null) : '-',
            },
            {
              title: '错误',
              dataIndex: 'error_message',
              key: 'error_message',
              ellipsis: true,
              render: (e: string | null) =>
                e ? (
                  <Tooltip title={e}>
                    <Text type="danger" style={{ fontSize: 12 }}>{e}</Text>
                  </Tooltip>
                ) : (
                  '-'
                ),
            },
            {
              title: '操作',
              key: 'action',
              width: 220,
              render: (_: unknown, v) => (
                <Space size="small">
                  {v.status === 'completed' && v.output_url && (
                    <>
                      <Button
                        size="small"
                        icon={<PlayCircleOutlined />}
                        onClick={() =>
                          setPreviewVideo({ url: v.output_url!, title: v.file_name })
                        }
                      >
                        预览
                      </Button>
                      <Button
                        size="small"
                        icon={<DownloadOutlined />}
                        onClick={() => downloadVideo(v.id)}
                      >
                        下载
                      </Button>
                    </>
                  )}
                  {v.status === 'completed' && !v.output_url && (
                    <Text type="secondary" style={{ fontSize: 12 }}>处理完成</Text>
                  )}
                  <Popconfirm
                    title="删除该视频？"
                    description="将删除其源文件与处理后文件"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={() => deleteVideo(v.id, taskId)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </div>
    );
  };

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Title level={4} style={{ margin: 0 }}>
          <VideoCameraOutlined /> 去水印
        </Title>
        <Tag color="green">v4 新增</Tag>
      </Space>

      {/* ── 新建任务 ── */}
      <Card size="small" style={{ marginBottom: 16 }} title="新建去水印任务">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {/* 引擎切换 */}
          <div>
            <Text strong>选择处理引擎：</Text>
            <Radio.Group
              value={engine}
              onChange={(e) => setEngine(e.target.value)}
              style={{ marginLeft: 8 }}
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'remove_mask', label: ENGINE_HELP.remove_mask.label, desc: ENGINE_HELP.remove_mask.desc },
                { value: 'seedance_wm', label: ENGINE_HELP.seedance_wm.label, desc: ENGINE_HELP.seedance_wm.desc },
                { value: 'remove_ai', label: ENGINE_HELP.remove_ai.label, desc: ENGINE_HELP.remove_ai.desc },
                { value: 'seedance', label: ENGINE_HELP.seedance.label, desc: ENGINE_HELP.seedance.desc },
              ].map((o) => ({
                value: o.value,
                label: (
                  <Space size={4}>
                    {o.label}
                    <Tooltip title={o.desc}>
                      <ExclamationCircleOutlined style={{ color: '#faad14', cursor: 'help' }} />
                    </Tooltip>
                  </Space>
                ),
              }))}
            />
          </div>

          {/* 引擎参数 */}
          {engine === 'seedance_wm' ? (
            <Space wrap>
              <Text>手动水印区域（可选，x,y,w,h；留空自动检测）：</Text>
              <Input
                placeholder="如 10,5,120,60"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                style={{ width: 220 }}
              />
              <Text>修补算法（CPU）：</Text>
              <Select
                value={seedanceBackend}
                onChange={setSeedanceBackend}
                style={{ width: 240 }}
                options={[
                  { value: 'auto', label: '自动（推荐，LaMa→cv2 降级）' },
                  { value: 'lama', label: 'LaMa（最佳，需 torch/iopaint）' },
                  { value: 'migan', label: 'MI-GAN（需 remove-ai-watermarks）' },
                  { value: 'cv2', label: 'OpenCV TELEA（无需模型）' },
                ]}
              />
              <Text>检测器：</Text>
              <Select
                value={detector}
                onChange={setDetector}
                style={{ width: 200 }}
                options={[
                  { value: 'matchTemplate', label: 'matchTemplate（默认）' },
                  { value: 'yolov8_seg', label: 'YOLOv8-seg（需安装）' },
                  { value: 'paddleocr', label: 'PaddleOCR（需安装）' },
                ]}
              />
              <Text>修复器：</Text>
              <Select
                value={inpainter}
                onChange={setInpainter}
                style={{ width: 200 }}
                options={[
                  { value: 'auto', label: '自动（按 backend 映射）' },
                  { value: 'lama', label: 'lama' },
                  { value: 'cv2_telea', label: 'cv2_telea' },
                ]}
              />
              <Text>分段检测：</Text>
              <Select
                value={segments}
                onChange={setSegments}
                style={{ width: 180 }}
                options={[
                  { value: 4, label: '4 段（默认）' },
                  { value: 8, label: '8 段（水印会移动）' },
                  { value: 12, label: '12 段（频繁移动）' },
                  { value: 16, label: '16 段（高精度）' },
                ]}
              />
              <Checkbox checked={keepAudio} onChange={(e) => setKeepAudio(e.target.checked)}>
                保留原音轨
              </Checkbox>
              <Text type="secondary" style={{ fontSize: 12 }}>
                （移动水印时增大分段数，可分别覆盖不同时间段的位置）
              </Text>
            </Space>
          ) : engine === 'remove_ai' ? (
            <Space wrap>
              <Text>厂商水印标记：</Text>
              <Select
                value={mark}
                onChange={setMark}
                style={{ width: 140 }}
                options={[
                  { value: 'auto', label: '自动扫描' },
                  { value: 'sora', label: 'Sora' },
                  { value: 'veo', label: 'Veo' },
                  { value: 'seedance', label: 'Seedance' },
                  { value: 'dola', label: 'Dola' },
                  { value: 'hailuo', label: 'Hailuo' },
                  { value: 'kling', label: 'Kling' },
                ]}
              />
              <Text>修补算法：</Text>
              <Select
                value={backend}
                onChange={setBackend}
                style={{ width: 200 }}
                options={[
                  { value: 'auto', label: '自动（推荐，LaMa→MI-GAN→cv2）' },
                  { value: 'lama', label: 'LaMa-ONNX（最佳，CPU）' },
                  { value: 'migan', label: 'MI-GAN-ONNX（轻量，CPU）' },
                  { value: 'cv2', label: 'OpenCV（最差，不推荐）' },
                ]}
              />
              <Checkbox checked={temporal} onChange={(e) => setTemporal(e.target.checked)}>
                时间一致性（减少闪烁）
              </Checkbox>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                手动区域擦除（可选，x,y,w,h）：非厂商 logo / 自动检测无效时指定，如 10,5,120,60
              </Text>
              <Input
                placeholder="如 10,5,120,60；留空则自动扫描厂商水印"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                style={{ width: 260 }}
              />
            </Space>
          ) : engine === 'remove_mask' ? (
            <Space wrap>
              <Text>预设方案（按《引擎排名结论》排序）：</Text>
              <Select
                value={maskPreset || undefined}
                onChange={(v) => {
                  setMaskPreset(v || '');
                  // 预设覆盖单项参数
                  if (v) {
                    const m: Record<string, string> = {
                      ns_small_r5: 'ns', teela_small_r5: 'telea',
                      ns_small_r3: 'ns', teela_small_r3: 'telea',
                      ns_large_r3: 'ns', teela_large_r3: 'telea',
                    };
                    if (m[v]) setMaskAlgo(m[v] as 'ns' | 'telea');
                    if (v === 'crop_small' || v === 'crop_large') setMaskMode('crop');
                    if (v.includes('large')) setMaskScope('large');
                    else if (v !== 'auto') setMaskScope('small');
                    if (v.includes('r5')) setMaskRadius(5);
                    else if (v.includes('r3')) setMaskRadius(3);
                  }
                }}
                allowClear
                placeholder="默认：ns_small_r5（最优）"
                style={{ width: 260 }}
                options={[
                  { value: 'ns_small_r5', label: '① NS + small + r5（最优，87.1%）' },
                  { value: 'teela_small_r5', label: '② TELEA + small + r5（86.4%）' },
                  { value: 'ns_small_r3', label: '③ NS + small + r3（86.0%）' },
                  { value: 'ns_large_r3', label: '④ NS + large + r3（85.6%）' },
                  { value: 'teela_small_r3', label: '⑤ TELEA + small + r3（84.2%）' },
                  { value: 'teela_large_r3', label: '⑥ TELEA + large + r3（83.3%）' },
                  { value: 'auto', label: '⑦ 自动检测 ROI（兜底新视频）' },
                  { value: 'crop_small', label: '⑧ 裁切去水印 small（不推荐，损失大）' },
                  { value: 'crop_large', label: '⑨ 裁切去水印 large（不推荐）' },
                ]}
              />
              <Text>插值算法：</Text>
              <Select
                value={maskAlgo}
                onChange={setMaskAlgo}
                style={{ width: 200 }}
                options={[
                  { value: 'ns', label: 'NS（默认推荐，87.1%）' },
                  { value: 'telea', label: 'TELEA（86.4%）' },
                ]}
              />
              <Text>手动水印区域（可选，x,y,w,h；留空则按文件名匹配内置 ROI）：</Text>
              <Input
                placeholder="如 10,5,120,60；留空自动匹配内置 ROI"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                style={{ width: 240 }}
              />
              <Text>修补半径：</Text>
              <Select
                value={maskRadius}
                onChange={setMaskRadius}
                style={{ width: 200 }}
                options={[
                  { value: 3, label: '3' },
                  { value: 5, label: '5（推荐，排名最优）' },
                  { value: 8, label: '8（强修补）' },
                ]}
              />
              <Text>迭代次数：</Text>
              <Select
                value={maskIterations}
                onChange={setMaskIterations}
                style={{ width: 160 }}
                options={[
                  { value: 1, label: '1 次（默认）' },
                  { value: 2, label: '2 次' },
                  { value: 3, label: '3 次（更彻底）' },
                ]}
              />
              <Text>ROI 范围：</Text>
              <Select
                value={maskScope}
                onChange={setMaskScope}
                style={{ width: 220 }}
                options={[
                  { value: 'small', label: '小范围（默认，贴合水印文字）' },
                  { value: 'large', label: '大范围（整角大框，覆盖更彻底）' },
                ]}
              />
              <Text>去水印模式：</Text>
              <Select
                value={maskMode}
                onChange={setMaskMode}
                style={{ width: 240 }}
                options={[
                  { value: 'inpaint', label: '插值修复（默认，保留原构图）' },
                  { value: 'crop', label: '裁切去水印（等比缩放切掉水印）' },
                ]}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                （内置 ROI 覆盖 648BC321 / C0CC0472 / 0270150E / 3906E761；其他文件回退左上+右下通用 ROI；ROI 范围默认 small：收紧贴合水印文字、减少对画面的干预，若水印残留可切 large 整角覆盖。裁切模式：裁掉上下水印带后等比放大回原分辨率，无修复痕迹但构图有裁剪/放大）
              </Text>
            </Space>
          ) : (
            <Space wrap>
              <Text>手动水印区域（可选，x,y,w,h；留空自动检测）：</Text>
              <Input
                placeholder="如 10,5,120,60"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                style={{ width: 220 }}
              />
              <Text>修补算法（CPU）：</Text>
              <Select
                value={seedanceBackend}
                onChange={setSeedanceBackend}
                style={{ width: 240 }}
                options={[
                  { value: 'auto', label: '自动（推荐，LaMa→MI-GAN→cv2）' },
                  { value: 'lama', label: 'LaMa-ONNX（最佳，CPU）' },
                  { value: 'migan', label: 'MI-GAN-ONNX（轻量，CPU）' },
                  { value: 'cv2', label: 'OpenCV TELEA' },
                ]}
              />
              <Text>分段检测：</Text>
              <Select
                value={segments}
                onChange={setSegments}
                style={{ width: 180 }}
                options={[
                  { value: 4, label: '4 段（默认）' },
                  { value: 8, label: '8 段（水印会移动）' },
                  { value: 12, label: '12 段（频繁移动）' },
                  { value: 16, label: '16 段（高精度）' },
                ]}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                （水印在视频中移动时，分段检测能分别覆盖不同时间段的位置）
              </Text>
            </Space>
          )}

          {/* 任务名称：默认取日期 + 4 位自增序列，可修改 */}
          <Space>
            <Text>任务名称：</Text>
            <Input
              placeholder="默认取日期 + 4 位自增序列，可修改"
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              style={{ width: 260 }}
            />
          </Space>

          {/* 文件上传：左侧缩小拖放控件 + 右侧待处理视频缩略图（悬停预览） */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            {/* 左侧：缩小版拖放控件 */}
            <div style={{ width: 240, flexShrink: 0 }}>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'copy';
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    handleSelectFiles(e.dataTransfer.files);
                  }
                }}
                style={{
                  border: '1.5px dashed #d9d9d9',
                  borderRadius: 8,
                  padding: '18px 12px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  background: '#fafafa',
                  transition: 'border-color 0.2s, background 0.2s',
                }}
                onClick={() => fileInputRef.current?.click()}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = '#1677ff';
                  (e.currentTarget as HTMLDivElement).style.background = '#e6f4ff';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = '#d9d9d9';
                  (e.currentTarget as HTMLDivElement).style.background = '#fafafa';
                }}
              >
                <p style={{ fontSize: 26, margin: 0 }}>
                  <InboxOutlined style={{ color: '#1677ff' }} />
                </p>
                <p style={{ margin: '4px 0', color: 'rgba(0,0,0,0.88)', fontSize: 13 }}>
                  拖放 / 点击上传视频
                </p>
                <p style={{ margin: 0, color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                  mp4 / avi / mov / mkv / webm
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".mp4,.avi,.mov,.mkv,.webm,video/*"
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files) handleSelectFiles(e.target.files);
                  e.target.value = '';
                }}
              />
              <Space wrap style={{ marginTop: 10 }}>
                {pendingFiles.length > 0 && (
                  <Button size="small" icon={<ClearOutlined />} onClick={clearPending}>
                    清空 ({pendingFiles.length})
                  </Button>
                )}
              </Space>
            </div>

            {/* 右侧：待处理视频缩略图列表（鼠标移上去可预览） */}
            <div style={{ flex: 1, minWidth: 320 }}>
              <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }} wrap>
                <Text strong style={{ fontSize: 13 }}>
                  待处理视频（{pendingFiles.length}）
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>鼠标移到缩略图上可播放预览</Text>
                </Text>
                {pendingFiles.length > 0 && (
                  <Button
                    type="primary"
                    size="small"
                    icon={<PlusOutlined />}
                    loading={running}
                    onClick={submitTask}
                  >
                    提交去水印任务
                  </Button>
                )}
              </Space>
              {pendingFiles.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无待处理视频，从左侧上传或从「提示词生成」历史导入"
                  style={{ margin: '8px 0' }}
                />
              ) : (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                  {pendingFiles.map((f) => (
                    <div
                      key={f.uploadId}
                      style={{
                        width: 168,
                        border: '1px solid #f0f0f0',
                        borderRadius: 8,
                        overflow: 'hidden',
                        background: '#fff',
                        position: 'relative',
                      }}
                    >
                      <div
                        style={{
                          height: 96,
                          background: '#000',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          overflow: 'hidden',
                        }}
                        onMouseEnter={(e) => {
                          const v = (e.currentTarget as HTMLDivElement).querySelector('video');
                          if (v) {
                            v.muted = true;
                            v.play().catch(() => {});
                          }
                        }}
                        onMouseLeave={(e) => {
                          const v = (e.currentTarget as HTMLDivElement).querySelector('video');
                          if (v) v.pause();
                        }}
                      >
                        {f.url ? (
                          <video
                            src={f.url}
                            preload="metadata"
                            muted
                            playsInline
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                          />
                        ) : (
                          <VideoCameraOutlined style={{ color: '#fff', fontSize: 30 }} />
                        )}
                      </div>
                      <div style={{ padding: '6px 8px' }}>
                        <Tooltip title={f.fileName}>
                          <Text style={{ fontSize: 12, display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {f.fileName}
                          </Text>
                        </Tooltip>
                        <Space style={{ width: '100%', marginTop: 4, justifyContent: 'space-between' }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>{formatFileSize(f.fileSize)}</Text>
                          <Button
                            size="small"
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={() => removePendingFile(f.uploadId)}
                          />
                        </Space>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Space>
      </Card>

      {/* ── 任务历史 ── */}
      <Card
        size="small"
        title="任务历史"
        extra={
          <Space>
            {selectedTaskIds.length > 0 && (
              <>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已选 {selectedTaskIds.length} 个任务
                </Text>
                <Popconfirm
                  title={`批量删除选中的 ${selectedTaskIds.length} 个任务？`}
                  description="将同时删除其全部视频资源文件"
                  okText="删除"
                  okButtonProps={{ danger: true }}
                  cancelText="取消"
                  onConfirm={batchDelete}
                >
                  <Button size="small" danger icon={<DeleteOutlined />}>
                    批量删除
                  </Button>
                </Popconfirm>
              </>
            )}
            <Button size="small" icon={<ReloadOutlined />} onClick={() => fetchTasks()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          loading={loadingTasks}
          dataSource={tasks}
          columns={taskColumns}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 1080 }}
          rowSelection={{
            selectedRowKeys: selectedTaskIds,
            onChange: (keys) => setSelectedTaskIds(keys as string[]),
          }}
          expandable={{
            expandedRowKeys: expandedTaskId ? [expandedTaskId] : [],
            onExpand: (expanded, record) => {
              if (expanded) toggleExpand(record.id);
              else setExpandedTaskId(null);
            },
            expandedRowRender: (record) => renderVideos(record.id),
          }}
        />
      </Card>

      {/* ── 大浮窗播放 ── */}
      <Modal
        title={previewVideo?.title || '视频预览'}
        open={!!previewVideo}
        footer={null}
        width={900}
        onCancel={() => setPreviewVideo(null)}
        destroyOnClose
      >
        {previewVideo && (
          <video
            src={previewVideo.url}
            controls
            autoPlay
            style={{ width: '100%', maxHeight: 560, background: '#000' }}
          />
        )}
      </Modal>
    </div>
  );
};

export default Watermark;
