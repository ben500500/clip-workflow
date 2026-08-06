import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Select, Progress, Popconfirm, Tooltip, Alert,
} from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined, ReloadOutlined, StopOutlined, InfoCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, DeleteOutlined, DesktopOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi } from '../api/slice';
import type { SliceOutput, SliceTask } from '../types';
import { formatDateTime, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

// 切片模式说明
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
      const res = await sliceApi.run(episodeId || '', mode, { engine });
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
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true, render: (e: string) => e ? <Tooltip title={e}><Text type="danger" style={{ fontSize: 12 }} ellipsis>{e}</Text></Tooltip> : '-' },
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
            window.open(`/api/outputs/${o.id}/preview/video`, '_blank');
          }}>预览</Button>
          <Button size="small" onClick={() => window.open(`/api/outputs/${o.id}/download`, '_blank')}>下载</Button>
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
          <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runSlice}>新建切片任务</Button>
          <Button icon={<ReloadOutlined />} onClick={() => fetchTasks()}>刷新</Button>
        </Space>
      </Card>

      {/* ── 任务列表 ── */}
      <Card size="small" title="任务列表" style={{ marginBottom: 16 }}>
        <Table rowKey="id" columns={columns} dataSource={tasks} loading={loading} pagination={false} size="small" />
      </Card>

      {currentTask && (
        <Card size="small" title={`输出文件（任务 ${currentTask}）`}>
          <Table rowKey="id" columns={outputColumns} dataSource={outputs} pagination={false} size="small" />
        </Card>
      )}
    </div>
  );
};

export default SliceTasks;