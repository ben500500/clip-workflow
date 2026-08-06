import React, { useEffect, useState, useRef, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, Spin, Alert, message, Popconfirm, InputNumber, Progress,
  Tooltip,
} from 'antd';
import {
  ArrowLeftOutlined, CheckOutlined, CloseOutlined, ReloadOutlined,
  PlayCircleOutlined, PauseCircleOutlined, ThunderboltOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { autoclipApi } from '../api/autoclip';
import { projectApi } from '../api/projects';
import type { ClipCandidate } from '../types';
import { formatDuration, formatDateTime, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

// ─── 视频预览组件 ─────────────────────────────────────
const VideoPreview: React.FC<{
  videoUrl: string;
  clip: ClipCandidate;
}> = ({ videoUrl, clip }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);

  const startTime = clip.adjusted_start ?? clip.start_time ?? 0;
  const endTime = clip.adjusted_end ?? clip.end_time ?? 0;

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      video.pause();
    } else {
      video.currentTime = startTime;
      video.play().catch(() => {});
      setPlaying(true);
    }
  }, [playing, startTime]);

  const onTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    setCurrentTime(video.currentTime);
    if (video.currentTime >= endTime) {
      video.pause();
      setPlaying(false);
    }
  }, [endTime]);

  const onPause = useCallback(() => {
    setPlaying(false);
  }, []);

  return (
    <div style={{ position: 'relative' }}>
      <video
        ref={videoRef}
        src={videoUrl}
        style={{ width: '100%', maxHeight: 300, borderRadius: 8, background: '#000' }}
        onTimeUpdate={onTimeUpdate}
        onPause={onPause}
        onEnded={() => setPlaying(false)}
        controls={false}
        preload="auto"
      />
      <Space style={{ marginTop: 8 }}>
        <Button
          size="small"
          type="primary"
          icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          onClick={togglePlay}
        >
          {playing ? '暂停' : `预览片段 (${formatDuration(startTime)} - ${formatDuration(endTime)})`}
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          当前: {formatDuration(currentTime)} / {formatDuration(endTime)}
        </Text>
      </Space>
    </div>
  );
};

// ─── 主组件 ───────────────────────────────────────────
const ClipReview: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [clips, setClips] = useState<ClipCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [expandedRowKeys, setExpandedRowKeys] = useState<React.Key[]>([]);

  const fetchClips = async () => {
    setLoading(true);
    try {
      const list = await autoclipApi.getCandidates(episodeId || '');
      setClips(list);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取选点失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchVideoUrl = async () => {
    try {
      const res = await projectApi.getVideoUrl(episodeId || '');
      setVideoUrl(res.url);
    } catch {
      // 视频获取失败不阻塞，预览区域会显示提示
    }
  };

  useEffect(() => {
    fetchClips();
    fetchVideoUrl();
  }, [episodeId]);

  // ─── 更新单个片段状态 ───────────────────────────────
  const updateStatus = async (clip: ClipCandidate, status: string) => {
    try {
      await autoclipApi.updateCandidate(clip.id, { status });
      message.success(status === 'accepted' ? '已通过' : '已拒绝');
      fetchClips();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '更新失败');
    }
  };

  // ─── 批量通过/拒绝 ──────────────────────────────────
  const batchUpdate = async (status: string) => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的片段');
      return;
    }
    setBatchLoading(true);
    try {
      const actions = selectedRowKeys.map((key) =>
        autoclipApi.updateCandidate(key as string, { status })
      );
      await Promise.all(actions);
      message.success(`已批量${status === 'accepted' ? '通过' : '拒绝'} ${selectedRowKeys.length} 个片段`);
      setSelectedRowKeys([]);
      fetchClips();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量操作失败');
    } finally {
      setBatchLoading(false);
    }
  };

  // ─── 一键全部通过/拒绝 ──────────────────────────────
  const batchAllUpdate = async (status: string) => {
    setBatchLoading(true);
    try {
      const pendingClips = clips.filter((c) => c.status === 'pending');
      const actions = pendingClips.map((c) =>
        autoclipApi.updateCandidate(c.id, { status })
      );
      await Promise.all(actions);
      message.success(`已一键${status === 'accepted' ? '通过' : '拒绝'} ${pendingClips.length} 个片段`);
      fetchClips();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量操作失败');
    } finally {
      setBatchLoading(false);
    }
  };

  // ─── 调整时间 ───────────────────────────────────────
  const adjust = async (clip: ClipCandidate, field: 'adjusted_start' | 'adjusted_end', value: number | null) => {
    try {
      await autoclipApi.updateCandidate(clip.id, { status: 'adjusted', [field]: value });
      fetchClips();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '调整失败');
    }
  };

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

  // ─── 统计 ───────────────────────────────────────────
  const pendingCount = clips.filter((c) => c.status === 'pending').length;
  const acceptedCount = clips.filter((c) => c.status === 'accepted').length;
  const rejectedCount = clips.filter((c) => c.status === 'rejected').length;
  const allReviewed = pendingCount === 0 && clips.length > 0;

  // ─── 点击标题展开行 ─────────────────────────────────
  const onTitleClick = (clipId: string) => {
    const isExpanded = expandedRowKeys.includes(clipId);
    if (isExpanded) {
      setExpandedRowKeys(expandedRowKeys.filter((k) => k !== clipId));
    } else {
      setExpandedRowKeys([...expandedRowKeys, clipId]);
    }
  };

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }

  const columns = [
    { title: '序号', dataIndex: 'clip_index', key: 'clip_index', width: 70 },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (title: string, c: ClipCandidate) => (
        <a
          onClick={() => onTitleClick(c.id)}
          style={{ cursor: 'pointer', color: expandedRowKeys.includes(c.id) ? '#1677ff' : undefined }}
        >
          {title || `片段 ${c.clip_index ?? '-'}`}
        </a>
      ),
    },
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
    { title: '评分', dataIndex: 'score', key: 'score', width: 80 },
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
      {/* ── 顶部操作栏 ── */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${episodeId}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>片段审核</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchClips}>刷新</Button>
      </Space>

      {/* ── 统计信息 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <Text>总计: <strong>{clips.length}</strong> 个片段</Text>
          <Text><Tag color="blue">待审核: {pendingCount}</Tag></Text>
          <Text><Tag color="green">已通过: {acceptedCount}</Tag></Text>
          <Text><Tag color="red">已拒绝: {rejectedCount}</Tag></Text>
          {allReviewed && (
            <Text style={{ color: '#52c41a' }}>
              <CheckCircleOutlined /> 所有片段已审核完成
            </Text>
          )}
        </Space>
      </Card>

      {/* ── 批量操作栏 ── */}
      {clips.length > 0 && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Text strong>批量操作:</Text>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={batchLoading}
              onClick={() => batchUpdate('accepted')}
              disabled={selectedRowKeys.length === 0}
            >
              批量通过 ({selectedRowKeys.length})
            </Button>
            <Button
              danger
              icon={<CloseOutlined />}
              loading={batchLoading}
              onClick={() => batchUpdate('rejected')}
              disabled={selectedRowKeys.length === 0}
            >
              批量拒绝 ({selectedRowKeys.length})
            </Button>
            <Button
              icon={<CheckCircleOutlined />}
              onClick={() => batchAllUpdate('accepted')}
              loading={batchLoading}
              disabled={pendingCount === 0}
            >
              一键全部通过 ({pendingCount})
            </Button>
            <Popconfirm
              title="一键拒绝所有待审核片段"
              description="拒绝后需要重新运行选点来生成新的候选片段"
              onConfirm={() => batchAllUpdate('rejected')}
              okText="确定拒绝"
              cancelText="取消"
            >
              <Button
                danger
                icon={<CloseOutlined />}
                loading={batchLoading}
                disabled={pendingCount === 0}
              >
                一键全部拒绝
              </Button>
            </Popconfirm>
          </Space>
        </Card>
      )}

      {/* ── 审核完成后的操作提示 ── */}
      {allReviewed && acceptedCount === 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<ExclamationCircleOutlined />}
          message="所有片段已被拒绝"
          description={
            <Space direction="vertical" size={4}>
              <Text>当前没有可用的候选片段进行切片。您可以：</Text>
              <Space>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  onClick={() => navigate(`/episodes/${episodeId}`)}
                >
                  返回重新运行选点
                </Button>
                <Button onClick={() => { fetchClips(); fetchVideoUrl(); }}>
                  刷新重试
                </Button>
              </Space>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* ── 片段列表 ── */}
      {error ? (
        <Alert type="warning" message="暂无选点结果" description={error} showIcon />
      ) : (
        <Card size="small">
          <Table
            rowKey="id"
            columns={columns}
            dataSource={clips}
            pagination={false}
            size="small"
            rowSelection={{
              selectedRowKeys,
              onChange: (keys) => setSelectedRowKeys(keys),
              getCheckboxProps: (c: ClipCandidate) => ({
                disabled: c.status !== 'pending',
              }),
            }}
            expandable={{
              expandedRowKeys,
              onExpandedRowsChange: (keys: readonly React.Key[]) =>
                setExpandedRowKeys([...keys] as string[]),
              expandedRowRender: (c: ClipCandidate) => {
                // 计算片段时长用于显示
                const clipDuration = c.duration || 0;
                const startTime = c.adjusted_start ?? c.start_time ?? 0;
                const endTime = c.adjusted_end ?? c.end_time ?? 0;
                const actualDuration = endTime - startTime;

                return (
                  <div style={{ padding: '8px 0' }}>
                    {/* 推荐理由 */}
                    <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        <Text strong><CheckCircleOutlined style={{ color: '#1677ff', marginRight: 6 }} />推荐理由</Text>
                        <Text>{c.recommend_reason || '暂无推荐理由'}</Text>
                        {c.content && (
                          <>
                            <Text strong style={{ marginTop: 8 }}>内容摘要</Text>
                            <Text>{c.content}</Text>
                          </>
                        )}
                        {c.outline && (
                          <>
                            <Text strong style={{ marginTop: 8 }}>大纲</Text>
                            <Text>{c.outline}</Text>
                          </>
                        )}
                      </Space>
                    </Card>

                    {/* 片段信息 */}
                    <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        <Text strong>片段信息</Text>
                        <Space wrap>
                          <Text type="secondary">评分: {c.score ?? '-'}</Text>
                          <Text type="secondary">原始时长: {formatDuration(clipDuration)}</Text>
                          <Text type="secondary">调整后时长: {formatDuration(actualDuration)}</Text>
                          <Text type="secondary">创建时间: {formatDateTime(c.created_at)}</Text>
                        </Space>
                      </Space>
                    </Card>

                    {/* 视频预览 */}
                    {videoUrl ? (
                      <Card size="small" style={{ background: '#fafafa' }} title="视频预览">
                        <VideoPreview videoUrl={videoUrl} clip={c} />
                      </Card>
                    ) : (
                      <Alert type="info" message="视频预览不可用，请确保视频文件已上传" showIcon style={{ marginBottom: 8 }} />
                    )}
                  </div>
                );
              },
            }}
          />
        </Card>
      )}
    </div>
  );
};

export default ClipReview;