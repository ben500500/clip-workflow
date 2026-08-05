import React, { useEffect, useState, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, Spin, Alert, message, Popconfirm, InputNumber, Select,
} from 'antd';
import { ArrowLeftOutlined, CheckOutlined, CloseOutlined, ReloadOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { autoclipApi } from '../api/autoclip';
import type { ClipCandidate } from '../types';
import { formatDuration, formatDateTime, getStatusColor, getStatusLabel } from '../utils/format';

const { Title } = Typography;

const ClipReview: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [clips, setClips] = useState<ClipCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchClips = async () => {
    setLoading(true);
    try {
      const list = await autoclipApi.getCandidates(episodeId || '');
      setClips(list);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取选点失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClips();
  }, [episodeId]);

  const updateStatus = async (clip: ClipCandidate, status: string) => {
    try {
      await autoclipApi.updateCandidate(clip.id, { status });
      message.success('已更新');
      fetchClips();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '更新失败');
    }
  };

  const adjust = async (clip: ClipCandidate, field: 'adjusted_start' | 'adjusted_end', value: number | null) => {
    try {
      await autoclipApi.updateCandidate(clip.id, { status: 'adjusted', [field]: value });
      fetchClips();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '调整失败');
    }
  };

  // 防抖：停止输入 500ms 后再提交
  const adjustTimers = useRef<Map<string, number>>(new Map());
  const adjustDebounced = (clip: ClipCandidate, field: 'adjusted_start' | 'adjusted_end', value: number | null) => {
    const key = `${clip.id}-${field}`;
    const prev = adjustTimers.current.get(key);
    if (prev) window.clearTimeout(prev);
    const timer = window.setTimeout(() => {
      adjustTimers.current.delete(key);
      adjust(clip, field, value);
    }, 500);
    adjustTimers.current.set(key, timer);
  };

  useEffect(() => {
    const timers = adjustTimers.current;
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
    };
  }, []);

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }

  const columns = [
    { title: '序号', dataIndex: 'clip_index', key: 'clip_index', width: 70 },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '时间区间',
      key: 'range',
      width: 220,
      render: (_: unknown, c: ClipCandidate) => (
        <Space size={4}>
          <InputNumber
            size="small"
            value={c.adjusted_start ?? c.start_time ?? 0}
            onChange={(v) => adjustDebounced(c, 'adjusted_start', v)}
            style={{ width: 90 }}
          />
          <span>-</span>
          <InputNumber
            size="small"
            value={c.adjusted_end ?? c.end_time ?? 0}
            onChange={(v) => adjustDebounced(c, 'adjusted_end', v)}
            style={{ width: 90 }}
          />
        </Space>
      ),
    },
    { title: '时长', key: 'duration', width: 90, render: (_: unknown, c: ClipCandidate) => formatDuration(c.duration) },
    { title: '评分', dataIndex: 'score', key: 'score', width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: unknown, c: ClipCandidate) => (
        <Space size="small">
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => updateStatus(c, 'accepted')}>通过</Button>
          <Popconfirm title="确定拒绝该片段？" onConfirm={() => updateStatus(c, 'rejected')}>
            <Button size="small" danger icon={<CloseOutlined />}>拒绝</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${episodeId}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>片段审核</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchClips}>刷新</Button>
      </Space>
      {error ? (
        <Alert type="warning" message="暂无选点结果" description={error} showIcon />
      ) : (
        <Card size="small">
          <Table rowKey="id" columns={columns} dataSource={clips} pagination={false} size="small"
            expandable={{
              expandedRowRender: (c: ClipCandidate) => (
                <div>
                  <p><b>推荐理由：</b>{c.recommend_reason || '-'}</p>
                  <p><b>内容：</b>{c.content || '-'}</p>
                  <p><b>大纲：</b>{c.outline || '-'}</p>
                  <p><b>创建时间：</b>{formatDateTime(c.created_at)}</p>
                </div>
              ),
            }}
          />
        </Card>
      )}
    </div>
  );
};

export default ClipReview;
