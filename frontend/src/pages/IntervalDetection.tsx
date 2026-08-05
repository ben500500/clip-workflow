import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, Spin, Alert, message, InputNumber, Select, Modal, Form, Input, Popconfirm,
} from 'antd';
import { ArrowLeftOutlined, PlusOutlined, DeleteOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { intervalApi } from '../api/intervals';
import type { DetectedInterval } from '../types';
import { formatDuration, getStatusColor, getStatusLabel } from '../utils/format';

const { Title } = Typography;

const IntervalDetection: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [intervals, setIntervals] = useState<DetectedInterval[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchIntervals = async () => {
    setLoading(true);
    try {
      const list = await intervalApi.list(episodeId || '');
      setIntervals(list);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取区间失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIntervals();
  }, [episodeId]);

  const toggle = async (id: string) => {
    try {
      await intervalApi.toggle(id);
      fetchIntervals();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '操作失败');
    }
  };

  const remove = async (id: string) => {
    try {
      await intervalApi.remove(id);
      message.success('已删除');
      fetchIntervals();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  const createManual = async () => {
    try {
      const values = await form.validateFields();
      await intervalApi.create({ episode_id: episodeId || '', ...values, source: 'manual' });
      message.success('已创建');
      setModalOpen(false);
      fetchIntervals();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '创建失败');
    }
  };

  const columns = [
    { title: '类型', dataIndex: 'interval_type', key: 'interval_type', width: 120, render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '区间',
      key: 'range',
      width: 200,
      render: (_: unknown, r: DetectedInterval) => `${formatDuration(r.start_time)} - ${formatDuration(r.end_time)}`,
    },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 100 },
    { title: '标签', dataIndex: 'label', key: 'label', ellipsis: true },
    { title: '来源', dataIndex: 'source', key: 'source', width: 90 },
    {
      title: '启用',
      key: 'enabled',
      width: 90,
      render: (_: unknown, r: DetectedInterval) => (
        <Tag color={r.enabled ? 'green' : 'default'}>{r.enabled ? '启用' : '停用'}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, r: DetectedInterval) => (
        <Space size="small">
          <Button size="small" onClick={() => toggle(r.id)}>{r.enabled ? '停用' : '启用'}</Button>
          <Popconfirm title="确定删除该区间？" onConfirm={() => remove(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${episodeId}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>区间检测</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchIntervals}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>手动添加</Button>
      </Space>
      <Card size="small">
        <Table rowKey="id" columns={columns} dataSource={intervals} loading={loading} pagination={false} size="small" />
      </Card>
      <Modal title="手动添加区间" open={modalOpen} onOk={createManual} onCancel={() => setModalOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="interval_type" label="类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'credits', label: '片尾字幕' },
                { value: 'static', label: '静止画面' },
                { value: 'watermark', label: '水印' },
                { value: 'custom', label: '自定义' },
              ]}
            />
          </Form.Item>
          <Form.Item name="start_time" label="开始秒" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="end_time" label="结束秒" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="label" label="标签"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default IntervalDetection;
