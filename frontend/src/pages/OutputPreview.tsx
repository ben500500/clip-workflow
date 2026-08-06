import React, { useEffect, useState, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Select, Modal, Form, Input, DatePicker, Popconfirm, Alert,
} from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined, DownloadOutlined, LinkOutlined, CloudDownloadOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi } from '../api/slice';
import { previewApi } from '../api/preview';
import type { Publication, SliceOutput, SliceTask } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

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

  // 多选批量下载
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchDownloading, setBatchDownloading] = useState(false);

  // 任务/输出加载竞态防护：重复进入页面或快速切换任务时，
  // 以最后一次请求为准，避免旧响应把列表重复/覆盖回去
  const taskLoadSeqRef = useRef(0);
  const outputLoadSeqRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const seq = ++taskLoadSeqRef.current;
    sliceApi
      .listTasks(episodeId || '')
      .then((list) => {
        if (mountedRef.current && seq === taskLoadSeqRef.current) {
          // 完全替换而非追加，确保重复进入页面不会让任务列表重复
          setTasks(list);
        }
      })
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
  }, [episodeId]);

  const loadTask = async (taskId: string) => {
    const seq = ++outputLoadSeqRef.current;
    setSelectedTask(taskId);
    setOutputs([]);
    setVideoUrl(null);
    setPublications([]);
    setSelectedRowKeys([]);
    try {
      const list = await sliceApi.getOutputs(taskId);
      if (mountedRef.current && seq === outputLoadSeqRef.current) {
        // 完全替换，避免重复加载时列表叠加
        setOutputs(list);
      }
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

  // ─── 多选批量下载 ─────────────────────────────
  const downloadSelected = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先勾选要下载的切片');
      return;
    }
    setBatchDownloading(true);
    try {
      const blob = await previewApi.batchDownload(selectedRowKeys as string[]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `切片批量下载_${selectedRowKeys.length}个_${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 1000);
      message.success(`已开始下载 ${selectedRowKeys.length} 个切片（ZIP 打包）`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量下载失败');
    } finally {
      setBatchDownloading(false);
    }
  };

  const outputColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
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
          <Button size="small" icon={<LinkOutlined />} onClick={() => { setCurrentOutput(o.id); pubForm.resetFields(); setPubModal(true); }}>登记发布</Button>
        </Space>
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
        <Space wrap>
          <span>选择切片任务：</span>
          <Select
            style={{ width: 320 }}
            placeholder="选择任务查看输出"
            value={selectedTask ?? undefined}
            onChange={loadTask}
            options={tasks.map((t) => ({ value: t.id, label: `${t.mode} / ${getStatusLabel(t.status || '')} / ${formatDateTime(t.created_at)}` }))}
          />
          {selectedTask && outputs.length > 0 && (
            <Popconfirm
              title={`确定下载选中的 ${selectedRowKeys.length} 个切片？`}
              description="将打包为一个 ZIP 文件下载"
              onConfirm={downloadSelected}
              okText="下载"
              cancelText="取消"
              disabled={selectedRowKeys.length === 0}
            >
              <Button
                type="primary"
                icon={<CloudDownloadOutlined />}
                loading={batchDownloading}
                disabled={selectedRowKeys.length === 0}
              >
                批量下载选中 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
        </Space>
      </Card>
      {selectedTask && (
        <Card size="small" title={`切片输出（共 ${outputs.length} 个）`} style={{ marginBottom: 16 }}>
          {outputs.length > 0 ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message={
                  <Text style={{ fontSize: 12 }}>
                    勾选左侧复选框可一次选择多个切片，然后点击顶部「批量下载选中」打包下载。
                  </Text>
                }
              />
              <Table
                rowKey="id"
                columns={outputColumns}
                dataSource={outputs}
                pagination={false}
                size="small"
                rowSelection={{
                  selectedRowKeys,
                  onChange: (keys) => setSelectedRowKeys(keys),
                }}
              />
            </>
          ) : (
            <Text type="secondary">该任务暂无输出文件</Text>
          )}
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
