import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Select, Progress, Popconfirm, Tooltip, Alert, Switch, InputNumber, Input, Upload, List, Image as AntImage,
} from 'antd';
import { UploadOutlined, PlusOutlined, DeleteOutlined as DelIcon } from '@ant-design/icons';
import { ArrowLeftOutlined, PlayCircleOutlined, ReloadOutlined, StopOutlined, InfoCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, DeleteOutlined, DesktopOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi, type BadgeItem } from '../api/slice';
import ErrorHint from '../components/ErrorHint';
import type { SliceOutput, SliceTask } from '../types';
import { formatDateTime, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

// 切片模式说明
// 角标位置选项（六角）：左上/中上/右上/左下/中下/右下
const BADGE_POSITIONS = [
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
    desc: '切割时进行画面相似度检测，去除重复片段。适合批量发布到多个平台，减少限流风险。',
  },
  scrub: {
    label: '挖洞模式',
    desc: '在去重基础上随机挖洞（替换为纯色帧），使每个输出片段指纹更独特。适合高频发布场景，降低平台查重处罚。',
  },
};

const SliceTasks: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<SliceTask[]>([]);
  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [currentTask, setCurrentTask] = useState<string | null>(null);
  const [mode, setMode] = useState('fast');
  const [engine, setEngine] = useState('worker');
  // 自定义文字水印开关与参数
  const [watermarkEnabled, setWatermarkEnabled] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [watermarkFontSize, setWatermarkFontSize] = useState(28);
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.5);
  const [watermarkPosition, setWatermarkPosition] = useState('bottom');
  // 图片角标列表：每个含 file_key（上传后 MinIO key）、position（位置）、width（可选宽度）、offset（可选偏移）、opacity（可选透明度）
  const [badges, setBadges] = useState<Array<BadgeItem & { name: string; preview: string }>>([]);
  const [badgeUploading, setBadgeUploading] = useState(false);
  // 角标默认尺寸（px）：角标未单独设 width 时生效；0=保持原图尺寸
  const [badgeDefaultWidth, setBadgeDefaultWidth] = useState<number>(0);
  // ── 竖屏转横屏智能裁切开关与参数 ──
  const [vert2horizEnabled, setVert2horizEnabled] = useState(false);
  const [vert2horizMode, setVert2horizMode] = useState<'fixed' | 'dynamic'>('fixed');
  const [vert2horizRatio, setVert2horizRatio] = useState(0.5625);
  const [vert2horizOutputSize, setVert2horizOutputSize] = useState('1280x720');
  const [vert2horizDetectInterval, setVert2horizDetectInterval] = useState(2);
  const [vert2horizSmoothWindow, setVert2horizSmoothWindow] = useState(15);
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

  const runSlice = async () => {
    setRunning(true);
    try {
      const res = await sliceApi.run(episodeId || '', mode, {
        engine,
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
    { title: '输出数', dataIndex: 'output_count', key: 'output_count', width: 80 },
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

  // 单个下载：用隐藏 a 标签 + download 属性直接触发浏览器下载，
  // 避免 window.open 跳转到新标签页播放视频导致后续下载被中断。
  const downloadOne = (o: SliceOutput) => {
    if (!o.id) {
      message.warning('暂无下载地址');
      return;
    }
    const a = document.createElement('a');
    a.href = `/api/outputs/${o.id}/download`;
    a.download = o.file_name || `output_${o.id}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
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
          <Select value={mode} onChange={setMode} style={{ width: 140 }}
            options={[
              { value: 'fast', label: '快速模式' },
              { value: 'dedupe', label: '去重模式' },
              { value: 'scrub', label: '挖洞模式' },
            ]}
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
          {/* 自定义文字水印开关 */}
          <Switch
            size="small"
            checked={watermarkEnabled}
            onChange={setWatermarkEnabled}
            checkedChildren="水印开"
            unCheckedChildren="水印"
          />
          {watermarkEnabled && (
            <>
              <Input
                size="small"
                style={{ width: 160 }}
                placeholder="水印文字（留空=标题+日期）"
                value={watermarkText}
                onChange={(e) => setWatermarkText(e.target.value)}
              />
              <Tooltip title="水印字号">
                <InputNumber
                  size="small"
                  min={12}
                  max={120}
                  value={watermarkFontSize}
                  onChange={(v) => setWatermarkFontSize(v ?? 28)}
                  style={{ width: 70 }}
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
                  style={{ width: 90 }}
                  addonBefore="透明"
                  addonAfter="%"
                />
              </Tooltip>
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
            </>
          )}
          {/* 竖屏转横屏智能裁切开关 */}
          <Switch
            size="small"
            checked={vert2horizEnabled}
            onChange={setVert2horizEnabled}
            checkedChildren="转横屏开"
            unCheckedChildren="转横屏"
          />
          {vert2horizEnabled && (
            <>
              <Select
                size="small"
                style={{ width: 120 }}
                value={vert2horizMode}
                onChange={setVert2horizMode}
                options={[
                  { value: 'fixed', label: '固定裁切' },
                  { value: 'dynamic', label: '动态跟踪' },
                ]}
              />
              <Input
                size="small"
                style={{ width: 100 }}
                value={vert2horizOutputSize}
                onChange={(e) => setVert2horizOutputSize(e.target.value)}
                placeholder="1280x720"
              />
              <Tooltip title="裁切高度比例（默认 9/16）">
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
              </Tooltip>
              {vert2horizMode === 'dynamic' && (
                <>
                  <Tooltip title="人脸检测间隔帧数">
                    <InputNumber
                      size="small"
                      min={1}
                      max={30}
                      value={vert2horizDetectInterval}
                      onChange={(v) => setVert2horizDetectInterval(v ?? 2)}
                      style={{ width: 80 }}
                      addonBefore="间隔"
                    />
                  </Tooltip>
                  <Tooltip title="平滑窗口大小（帧）">
                    <InputNumber
                      size="small"
                      min={1}
                      max={60}
                      value={vert2horizSmoothWindow}
                      onChange={(v) => setVert2horizSmoothWindow(v ?? 15)}
                      style={{ width: 80 }}
                      addonBefore="平滑"
                    />
                  </Tooltip>
                </>
              )}
            </>
          )}

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

          <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runSlice}>新建切片任务</Button>
          <Button icon={<ReloadOutlined />} onClick={() => fetchTasks()}>刷新</Button>
        </Space>
      </Card>

      {/* ── 任务列表 ── */}
      <Card size="small" title="任务列表" style={{ marginBottom: 16 }}>
        <Table rowKey="id" columns={columns} dataSource={tasks} loading={loading} pagination={false} size="small" scroll={{ x: 1100 }} />
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