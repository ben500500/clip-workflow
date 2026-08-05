import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, Spin, message, Select, Alert, Modal, Form, Input, DatePicker,
} from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined, DownloadOutlined, LinkOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi } from '../api/slice';
import { previewApi } from '../api/preview';
import type { Publication, SliceOutput, SliceTask } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title } = Typography;

const OutputPreview: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<SliceTask[]>([]);
  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [pubModal, setPubModal] = useState(false);
  const [pubForm] = Form.useForm();
  const [currentOutput, setCurrentOutput] = useState<string | null>(null);

  useEffect(() => {
    sliceApi
      .listTasks(episodeId || '')
      .then(setTasks)
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
  }, [episodeId]);

  const loadTask = async (taskId: string) => {
    setSelectedTask(taskId);
    setOutputs([]);
    setVideoUrl(null);
    setPublications([]);
    try {
      const list = await sliceApi.getOutputs(taskId);
      setOutputs(list);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取输出失败');
    }
  };

  const selectOutput = async (output: SliceOutput) => {
    setCurrentOutput(output.id);
    try {
      const video = await previewApi.getVideoUrl(output.id);
      setVideoUrl(video.url);
      const pubs = await previewApi.getPublications(output.id);
      setPublications(pubs);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载预览失败');
    }
  };

  const outputColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name' },
    { title: '大小', dataIndex: 'file_size', key: 'file_size', width: 110, render: (s: number) => formatFileSize(s) },
    { title: '时长', dataIndex: 'duration', key: 'duration', width: 100, render: (d: number) => formatDuration(d) },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作',
      key: 'action',
      width: 230,
      render: (_: unknown, o: SliceOutput) => (
        <Space size="small">
          <Button size="small" icon={<PlayCircleOutlined />} onClick={() => selectOutput(o)}>预览</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => window.open(`/api/outputs/${o.id}/download`, '_blank')}>下载</Button>
          <Button size="small" icon={<LinkOutlined />} onClick={() => { setCurrentOutput(o.id); pubForm.resetFields(); setPubModal(true); }}>登记发布</Button>        </Space>
      ),
    },
  ];

  const pubColumns = [
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 120 },
    { title: '链接', dataIndex: 'publish_url', key: 'publish_url', ellipsis: true, render: (u: string) => u ? <a href={u} target="_blank" rel="noreferrer">{u}</a> : '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag> },
    { title: '发布时间', dataIndex: 'publish_time', key: 'publish_time', width: 170, render: (d: string) => formatDateTime(d) },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${episodeId}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>成品预览</Title>
      </Space>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <span>选择切片任务：</span>
          <Select
            style={{ width: 320 }}
            placeholder="选择任务查看输出"
            value={selectedTask ?? undefined}
            onChange={loadTask}
            options={tasks.map((t) => ({ value: t.id, label: `${t.mode} / ${getStatusLabel(t.status || '')} / ${formatDateTime(t.created_at)}` }))}
          />
        </Space>
      </Card>
      {selectedTask && (
        <Card size="small" title="切片输出" style={{ marginBottom: 16 }}>
          <Table rowKey="id" columns={outputColumns} dataSource={outputs} pagination={false} size="small" />
        </Card>
      )}
      {videoUrl && (
        <Card size="small" title="视频预览" style={{ marginBottom: 16 }}>
          <video src={videoUrl} controls style={{ width: '100%', maxHeight: 420, background: '#000' }} />
        </Card>
      )}
      {currentOutput && (
        <Card size="small" title="发布记录">
          <Table rowKey="id" columns={pubColumns} dataSource={publications} pagination={false} size="small" />
        </Card>
      )}
      <Modal
        title="登记发布记录"
        open={pubModal}
        onOk={async () => {
          try {
            const values = await pubForm.validateFields();
            await previewApi.createPublication(currentOutput || '', {
              platform: values.platform,
              publish_url: values.publish_url,
              status: values.status || 'published',
              publish_time: values.publish_time ? values.publish_time.toISOString() : undefined,
              operator: values.operator,
            });
            message.success('已登记');
            setPubModal(false);
            if (currentOutput) {
              const pubs = await previewApi.getPublications(currentOutput);
              setPublications(pubs);
            }
          } catch (err: unknown) {
            if (err && typeof err === 'object' && 'errorFields' in err) return;
            message.error(err instanceof Error ? err.message : '登记失败');
          }
        }}
        onCancel={() => setPubModal(false)}
        destroyOnClose
      >
        <Form form={pubForm} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="publish_url" label="发布链接"><Input /></Form.Item>
          <Form.Item name="status" label="状态" initialValue="published">
            <Select options={[{ value: 'published', label: '已发布' }, { value: 'pending', label: '待发布' }, { value: 'rejected', label: '已拒绝' }]} />
          </Form.Item>
          <Form.Item name="publish_time" label="发布时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="operator" label="操作人"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default OutputPreview;
