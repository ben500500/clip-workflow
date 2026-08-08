import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Card, Typography, Space, Button, Select, Table, Progress, Tag, Modal,
  Popconfirm, Checkbox, Tooltip, message, Input, Alert, Radio, Spin, Empty,
} from 'antd';
import {
  UploadOutlined, PlayCircleOutlined, DownloadOutlined, DeleteOutlined,
  PlusOutlined, ReloadOutlined, VideoCameraOutlined, ClearOutlined,
  InboxOutlined,
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
};

interface PendingFile {
  uploadId: string;
  fileName: string;
  fileSize: number;
  sourceFileKey: string;
  uploadPercent: number;
}

const STATUS_LABELS: Record<string, string> = {
  pending: '等待处理',
  running: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const Watermark: React.FC = () => {
  const [engine, setEngine] = useState<'remove_ai' | 'seedance' | 'seedance_wm'>('seedance_wm');
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

  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [taskName, setTaskName] = useState('');
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
            },
          ]);
        })
        .catch((err: unknown) => {
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
    setPendingFiles((prev) => prev.filter((f) => f.uploadId !== uploadId));
  };

  const clearPending = () => setPendingFiles([]);

  // ─── 提交任务 ───
  const submitTask = async () => {
    if (pendingFiles.length === 0) {
      message.warning('请先上传至少一个视频');
      return;
    }
    setRunning(true);
    try {
      const params: {
        engine: 'remove_ai' | 'seedance' | 'seedance_wm';
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
      } = {
        engine,
        files: pendingFiles.map((f) => f.sourceFileKey),
        name: taskName.trim() || undefined,
      };
      if (engine === 'remove_ai') {
        params.mark = mark;
        params.backend = backend;
        params.temporal_consistency = temporal;
        if (region.trim()) params.region = region.trim();
      } else if (engine === 'seedance') {
        params.region = region.trim() || undefined;
        params.backend = seedanceBackend;
        params.segments = segments;
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
      setPendingFiles([]);
      setTaskName('');
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
        <Tag color={e === 'remove_ai' ? 'blue' : e === 'seedance' ? 'purple' : 'geekblue'} style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.engine_display}</Tag>
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
      width: 200,
      render: (_: unknown, t: WatermarkTaskItem) => (
        <Space size="small">
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
                { value: 'seedance_wm', label: ENGINE_HELP.seedance_wm.label },
                { value: 'remove_ai', label: ENGINE_HELP.remove_ai.label },
                { value: 'seedance', label: ENGINE_HELP.seedance.label },
              ]}
            />
            <div style={{ marginTop: 8 }}>
              <Alert
                type="info"
                showIcon
                message={ENGINE_HELP[engine]?.desc}
                style={{ maxWidth: 900 }}
              />
            </div>
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

          {/* 任务名称 */}
          <Space>
            <Text>任务名称：</Text>
            <Input
              placeholder="可选，默认按引擎自动命名"
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              style={{ width: 260 }}
            />
          </Space>

          {/* 文件上传：可拖放式 */}
          <div>
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
                padding: '28px 16px',
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
              <p style={{ fontSize: 40, margin: 0 }}>
                <InboxOutlined style={{ color: '#1677ff' }} />
              </p>
              <p style={{ margin: '4px 0', color: 'rgba(0,0,0,0.88)' }}>
                点击或拖放视频文件到此处上传
              </p>
              <p style={{ margin: 0, color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                支持多选 / 批量拖放，格式 mp4 / avi / mov / mkv / webm
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
            <Space wrap style={{ marginTop: 12 }}>
              <Button
                icon={<UploadOutlined />}
                loading={uploading}
                onClick={() => fileInputRef.current?.click()}
              >
                选择视频（可多选，批量上传）
              </Button>
              {pendingFiles.length > 0 && (
                <>
                  <Button icon={<ClearOutlined />} onClick={clearPending}>
                    清空待处理 ({pendingFiles.length})
                  </Button>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    loading={running}
                    onClick={submitTask}
                  >
                    提交去水印任务
                  </Button>
                </>
              )}
            </Space>

            {pendingFiles.length > 0 && (
              <Table
                size="small"
                rowKey="uploadId"
                style={{ marginTop: 12 }}
                pagination={false}
                dataSource={pendingFiles}
                scroll={{ x: 520 }}
                columns={[
                  {
                    title: '文件名',
                    dataIndex: 'fileName',
                    key: 'fileName',
                    render: (n: string) => <Text style={{ fontSize: 13 }}>{n}</Text>,
                  },
                  {
                    title: '大小',
                    dataIndex: 'fileSize',
                    key: 'fileSize',
                    width: 120,
                    render: (s: number) => formatFileSize(s),
                  },
                  {
                    title: '上传状态',
                    dataIndex: 'uploadPercent',
                    key: 'uploadPercent',
                    width: 160,
                    render: (p: number) => (
                      <Tag color={p >= 100 ? 'green' : 'processing'}>
                        {p >= 100 ? '已上传' : '上传中'}
                      </Tag>
                    ),
                  },
                  {
                    title: '操作',
                    key: 'action',
                    width: 80,
                    render: (_: unknown, f: PendingFile) => (
                      <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => removePendingFile(f.uploadId)}
                      />
                    ),
                  },
                ]}
              />
            )}
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
