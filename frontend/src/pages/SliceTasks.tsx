import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, Spin, Alert, message, Select, Progress, Popconfirm,
} from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi } from '../api/slice';
import type { SliceOutput, SliceTask } from '../types';
import { formatDateTime, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title } = Typography;

const SliceTasks: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<SliceTask[]>([]);
  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [currentTask, setCurrentTask] = useState<string | null>(null);
  const [mode, setMode] = useState('fast');
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
      const res = await sliceApi.run(episodeId || '', mode, {});
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

  const columns = [
    { title: '模式', dataIndex: 'mode', key: 'mode', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (s: string, t: SliceTask) => (
        <Space direction="vertical" size={0}>
          <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>
          {t.status === 'running' && <Progress percent={t.progress} size="small" style={{ width: 100 }} />}
        </Space>
      ),
    },
    { title: '输出数', dataIndex: 'output_count', key: 'output_count', width: 90 },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true, render: (e: string) => e || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作',
      key: 'action',
      width: 240,
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
            if (!o.presigned_url) {
              message.warning('暂无预览地址');
              return;
            }
            window.open(o.presigned_url, '_blank');
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
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Select value={mode} onChange={setMode} style={{ width: 140 }}
            options={[
              { value: 'fast', label: '快速模式' },
              { value: 'dedupe', label: '去重模式' },
              { value: 'scrub', label: '挖洞模式' },
            ]}
          />
          <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runSlice}>新建切片任务</Button>
          <Button icon={<ReloadOutlined />} onClick={() => fetchTasks()}>刷新</Button>
        </Space>
      </Card>
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
