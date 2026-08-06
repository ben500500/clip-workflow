import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Typography, Spin, Alert, Select, Space, Row, Col, InputNumber, Button, message, Modal, Input,
} from 'antd';
import { dashboardApi } from '../api/dashboard';
import type { VideoMetric } from '../types';
import { formatDate, formatPercent } from '../utils/format';

const { Title, Text } = Typography;

const ContentAnalysis: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoMetric[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState('play_count');
  const [ranking, setRanking] = useState<VideoMetric[]>([]);

  // 视频标签编辑状态
  const [tagVideo, setTagVideo] = useState<VideoMetric | null>(null);
  const [tagInput, setTagInput] = useState('');
  const [tagList, setTagList] = useState<string[]>([]);

  const openTagEditor = (video: VideoMetric) => {
    setTagVideo(video);
    setTagList(Array.isArray(video.tags) ? [...video.tags] : []);
    setTagInput('');
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t) return;
    if (!tagList.includes(t)) {
      setTagList([...tagList, t]);
    }
    setTagInput('');
  };

  const saveTags = async () => {
    if (!tagVideo) return;
    try {
      await dashboardApi.updateVideoTags(tagVideo.id, tagList);
      message.success('标签已保存');
      setTagVideo(null);
      fetchVideos();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

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
                {
                  title: '标签', key: 'tags', width: 160,
                  render: (_, v: VideoMetric) => (
                    <Space size={4} wrap>
                      {Array.isArray(v.tags) && v.tags.length > 0 ? (
                        v.tags.slice(0, 3).map((t) => <Tag key={t} color="blue">{t}</Tag>)
                      ) : (
                        <Text type="secondary">无</Text>
                      )}
                      <Button size="small" type="link" onClick={() => openTagEditor(v)}>编辑</Button>
                    </Space>
                  ),
                },
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

      {/* 标签编辑弹窗（视频标签系统） */}
      <Modal
        title={`编辑标签：${tagVideo?.title || tagVideo?.video_id || ''}`}
        open={!!tagVideo}
        onOk={saveTags}
        onCancel={() => setTagVideo(null)}
        okText="保存"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onPressEnter={addTag}
              placeholder="输入标签后回车或点击添加"
            />
            <Button type="primary" onClick={addTag}>添加</Button>
          </Space.Compact>
          <div>
            {tagList.length === 0 ? (
              <Text type="secondary">暂无标签</Text>
            ) : (
              tagList.map((t) => (
                <Tag
                  key={t}
                  color="blue"
                  closable
                  style={{ marginBottom: 8 }}
                  onClose={() => setTagList(tagList.filter((x) => x !== t))}
                >
                  {t}
                </Tag>
              ))
            )}
          </div>
        </Space>
      </Modal>
    </div>
  );
};

export default ContentAnalysis;
