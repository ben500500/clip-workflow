import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Typography, Spin, Alert, Select, Space, Row, Col, InputNumber, Button, message,
} from 'antd';
import { dashboardApi } from '../api/dashboard';
import type { VideoMetric } from '../types';
import { formatDate, formatPercent } from '../utils/format';

const { Title } = Typography;

const ContentAnalysis: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoMetric[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState('play_count');
  const [ranking, setRanking] = useState<VideoMetric[]>([]);

  const fetchVideos = async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getVideos({ page, page_size: pageSize, sort_by: sortBy });
      setVideos(res.items);
      setTotal(res.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVideos();
  }, [page, pageSize, sortBy]);

  useEffect(() => {
    dashboardApi.getVideoRanking({ sort_by: 'play_count', limit: 10 }).then(setRanking).catch(() => undefined);
  }, []);

  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>内容分析</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={17}>
          <Card size="small" title="视频数据" extra={
            <Space>
              <span>排序</span>
              <Select value={sortBy} onChange={setSortBy} style={{ width: 140 }}
                options={[
                  { value: 'play_count', label: '播放量' },
                  { value: 'finish_rate', label: '完播率' },
                  { value: 'like_count', label: '点赞' },
                  { value: 'jump_click_count', label: '跳转' },
                  { value: 'attributed_revenue', label: '归因收益' },
                ]}
              />
              <Button onClick={fetchVideos}>刷新</Button>
            </Space>
          }>
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={videos}
              columns={[
                { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => t || '-' },
                { title: '视频ID', dataIndex: 'video_id', key: 'video_id', width: 130, ellipsis: true },
                { title: '播放', dataIndex: 'play_count', key: 'play_count', width: 90 },
                { title: '完播率', dataIndex: 'finish_rate', key: 'finish_rate', width: 90, render: (v: number) => formatPercent((v ?? 0) * 100) },
                { title: '点赞', dataIndex: 'like_count', key: 'like_count', width: 80 },
                { title: '评论', dataIndex: 'comment_count', key: 'comment_count', width: 80 },
                { title: '跳转', dataIndex: 'jump_click_count', key: 'jump_click_count', width: 80 },
                { title: '归因UV', dataIndex: 'attributed_uv', key: 'attributed_uv', width: 90 },
                { title: '收益', dataIndex: 'attributed_revenue', key: 'attributed_revenue', width: 100, render: (v: number) => `${v || 0} 元` },
                { title: '类型', dataIndex: 'content_type', key: 'content_type', width: 90, render: (v: string) => v ? <Tag>{v}</Tag> : '-' },
                { title: '日期', dataIndex: 'publish_date', key: 'publish_date', width: 110, render: (d: string) => formatDate(d) },
              ]}
              pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: true,
                onChange: (p, ps) => { setPage(p); setPageSize(ps); },
              }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={7}>
          <Card size="small" title="播放排行 TOP10">
            <Space direction="vertical" style={{ width: '100%' }}>
              {ranking.map((v, i) => (
                <div key={v.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {i + 1}. {v.title || v.video_id || '-'}
                  </span>
                  <b>{v.play_count}</b>
                </div>
              ))}
              {ranking.length === 0 && <Typography.Text type="secondary">暂无数据</Typography.Text>}
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default ContentAnalysis;
