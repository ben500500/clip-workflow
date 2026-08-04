import React, { useEffect, useState } from 'react';
import {
  Card,
  Tabs,
  Button,
  Space,
  Typography,
  Spin,
  Alert,
  Row,
  Col,
  Statistic,
  Descriptions,
  Tag,
  message,
  Breadcrumb,
  Empty,
} from 'antd';
import {
  ArrowLeftOutlined,
  ThunderboltOutlined,
  ScissorOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate, Link } from 'react-router-dom';
import type { Episode, ClipCandidate, DetectedInterval, SliceTask, SliceOutput } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';
import ClipReviewComponent from '../components/ClipReview';
import IntervalReview from '../components/IntervalReview';
import TaskProgress from '../components/TaskProgress';
import { autoclipApi } from '../api/autoclip';
import { intervalApi } from '../api/intervals';
import { sliceApi } from '../api/slice';
import { previewApi } from '../api/preview';

const { Title, Text } = Typography;

const EpisodeDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const episodeId = Number(id);

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('clips');

  // Clip candidates state
  const [candidates, setCandidates] = useState<ClipCandidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [detecting, setDetecting] = useState(false);

  // Intervals state
  const [intervals, setIntervals] = useState<DetectedInterval[]>([]);
  const [intervalsLoading, setIntervalsLoading] = useState(false);
  const [detectingIntervals, setDetectingIntervals] = useState(false);

  // Slice tasks state
  const [sliceTasks, setSliceTasks] = useState<SliceTask[]>([]);
  const [sliceTasksLoading, setSliceTasksLoading] = useState(false);
  const [selectedTask, setSelectedTask] = useState<SliceTask | null>(null);

  // Outputs state
  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [outputsLoading, setOutputsLoading] = useState(false);

  useEffect(() => {
    fetchEpisode();
  }, [episodeId]);

  const fetchEpisode = async () => {
    setLoading(true);
    setError(null);
    try {
      // Mock episode data for now
      setEpisode({
        id: episodeId,
        project_id: 1,
        title: `剧集 #${episodeId}`,
        file_path: '/path/to/video.mp4',
        file_size: 1024 * 1024 * 500,
        duration: 3600,
        status: 'uploaded',
        clip_count: 0,
        interval_count: 0,
        slice_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as Episode);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取剧集详情失败');
    } finally {
      setLoading(false);
    }
  };

  // ========== AutoClip operations ==========
  const handleDetectClips = async () => {
    setDetecting(true);
    try {
      await autoclipApi.detect(episodeId);
      message.success('AutoClip 检测任务已启动');
      // Poll for results
      setTimeout(() => fetchCandidates(), 2000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动检测失败');
    } finally {
      setDetecting(false);
    }
  };

  const fetchCandidates = async () => {
    setCandidatesLoading(true);
    try {
      const res = await autoclipApi.getCandidates(episodeId);
      setCandidates(res.data);
    } catch (err: unknown) {
      // Silently handle - may not have results yet
    } finally {
      setCandidatesLoading(false);
    }
  };

  const handleClipUpdate = async (id: number, data: Partial<ClipCandidate>) => {
    try {
      await autoclipApi.updateCandidate(id, data);
      message.success('选点状态已更新');
      fetchCandidates();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleClipBatchUpdate = async (data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) => {
    try {
      await autoclipApi.batchUpdateCandidates(data);
      fetchCandidates();
    } catch (err: unknown) {
      throw err;
    }
  };

  // ========== Interval operations ==========
  const handleDetectIntervals = async () => {
    setDetectingIntervals(true);
    try {
      await intervalApi.detect(episodeId);
      message.success('区间检测任务已启动');
      setTimeout(() => fetchIntervals(), 2000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动检测失败');
    } finally {
      setDetectingIntervals(false);
    }
  };

  const fetchIntervals = async () => {
    setIntervalsLoading(true);
    try {
      const res = await intervalApi.getIntervals(episodeId);
      setIntervals(res.data);
    } catch {
      // Silently handle
    } finally {
      setIntervalsLoading(false);
    }
  };

  const handleIntervalUpdate = async (id: number, data: Partial<DetectedInterval>) => {
    try {
      await intervalApi.updateInterval(id, data);
      message.success('区间状态已更新');
      fetchIntervals();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleIntervalBatchUpdate = async (data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) => {
    try {
      await intervalApi.batchUpdateIntervals(data);
      fetchIntervals();
    } catch (err: unknown) {
      throw err;
    }
  };

  // ========== Slice operations ==========
  const handleStartSlice = async () => {
    try {
      const approvedCandidates = candidates.filter((c) => c.status === 'approved');
      const approvedIntervals = intervals.filter((i) => i.status === 'approved');
      if (approvedCandidates.length === 0 && approvedIntervals.length === 0) {
        message.warning('没有已通过的选点或区间，请先审核');
        return;
      }
      await sliceApi.start({
        episode_id: episodeId,
        candidate_ids: approvedCandidates.map((c) => c.id),
        interval_ids: approvedIntervals.map((i) => i.id),
      });
      message.success('切片任务已启动');
      setTimeout(() => fetchSliceTasks(), 2000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动切片失败');
    }
  };

  const fetchSliceTasks = async () => {
    setSliceTasksLoading(true);
    try {
      const res = await sliceApi.getTasks(episodeId);
      setSliceTasks(res.data);
    } catch {
      // Silently handle
    } finally {
      setSliceTasksLoading(false);
    }
  };

  // ========== Tab items ==========
  const tabItems = [
    {
      key: 'clips',
      label: (
        <span>
          <ThunderboltOutlined /> 智能选点
        </span>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={detecting}
                onClick={handleDetectClips}
              >
                {detecting ? '检测中...' : '开始 AutoClip 检测'}
              </Button>
              {candidates.length > 0 && (
                <Text type="secondary">共 {candidates.length} 个候选选点</Text>
              )}
            </Space>
            {candidates.length === 0 && !candidatesLoading && (
              <Text type="secondary">点击"开始 AutoClip 检测"启动智能选点</Text>
            )}
          </div>
          {candidates.length > 0 || candidatesLoading ? (
            <ClipReviewComponent
              candidates={candidates}
              loading={candidatesLoading}
              onUpdate={handleClipUpdate}
              onBatchUpdate={handleClipBatchUpdate}
            />
          ) : (
            <Empty description="暂未检测，请点击上方按钮开始" />
          )}
        </div>
      ),
    },
    {
      key: 'intervals',
      label: (
        <span>
          <NodeIndexOutlined /> 区间检测
        </span>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Button
                type="primary"
                icon={<NodeIndexOutlined />}
                loading={detectingIntervals}
                onClick={handleDetectIntervals}
              >
                {detectingIntervals ? '检测中...' : '开始区间检测'}
              </Button>
              {intervals.length > 0 && (
                <Text type="secondary">共 {intervals.length} 个检测区间</Text>
              )}
            </Space>
          </div>
          {intervals.length > 0 || intervalsLoading ? (
            <IntervalReview
              intervals={intervals}
              loading={intervalsLoading}
              onUpdate={handleIntervalUpdate}
              onBatchUpdate={handleIntervalBatchUpdate}
            />
          ) : (
            <Empty description="暂未检测，请点击上方按钮开始" />
          )}
        </div>
      ),
    },
    {
      key: 'slice',
      label: (
        <span>
          <ScissorOutlined /> 切片任务
        </span>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Button
                type="primary"
                icon={<ScissorOutlined />}
                onClick={handleStartSlice}
              >
                启动切片
              </Button>
              <Button onClick={fetchSliceTasks} loading={sliceTasksLoading}>
                刷新任务列表
              </Button>
            </Space>
          </div>
          {selectedTask && (
            <TaskProgress
              task={selectedTask}
              visible
              onCancel={async () => {
                if (selectedTask) {
                  try {
                    await sliceApi.cancelTask(selectedTask.id);
                    message.success('任务已取消');
                    fetchSliceTasks();
                  } catch {
                    message.error('取消任务失败');
                  }
                }
              }}
              onRetry={async () => {
                if (selectedTask) {
                  try {
                    await sliceApi.retryFailed(selectedTask.id);
                    message.success('已重试失败项');
                    fetchSliceTasks();
                  } catch {
                    message.error('重试失败');
                  }
                }
              }}
            />
          )}
          {sliceTasks.length === 0 && !selectedTask && (
            <Empty description="暂无切片任务，请先完成选点审核后启动切片">
              <Button type="primary" icon={<ScissorOutlined />} onClick={handleStartSlice}>
                启动切片
              </Button>
            </Empty>
          )}
        </div>
      ),
    },
    {
      key: 'output',
      label: (
        <span>
          <PlayCircleOutlined /> 成品预览
        </span>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Button
                icon={<DownloadOutlined />}
                onClick={async () => {
                  setOutputsLoading(true);
                  try {
                    const res = await previewApi.getOutputs(episodeId);
                    setOutputs(res.data);
                  } catch {
                    message.error('获取成品列表失败');
                  } finally {
                    setOutputsLoading(false);
                  }
                }}
              >
                刷新成品列表
              </Button>
            </Space>
          </div>
          {outputs.length === 0 && (
            <Empty description="暂无成品，请先完成切片任务">
              {sliceTasks.length === 0 && (
                <Button type="primary" icon={<ScissorOutlined />} onClick={handleStartSlice}>
                  启动切片
                </Button>
              )}
            </Empty>
          )}
        </div>
      ),
    },
  ];

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (error || !episode) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">项目管理</Link> },
          { title: <Link to={`/projects/${episode.project_id}`}>项目详情</Link> },
          { title: episode.title },
        ]}
        style={{ marginBottom: 16 }}
      />

      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${episode.project_id}`)}>
              返回
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              {episode.title}
            </Title>
          </Space>
        </Col>
      </Row>

      {/* 剧集信息 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
          <Descriptions.Item label="剧集ID">{episode.id}</Descriptions.Item>
          <Descriptions.Item label="时长">{formatDuration(episode.duration)}</Descriptions.Item>
          <Descriptions.Item label="文件大小">{formatFileSize(episode.file_size)}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={getStatusColor(episode.status)}>{getStatusLabel(episode.status)}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={8}>
          <Card size="small">
            <Statistic title="选点数" value={episode.clip_count} suffix="个" />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small">
            <Statistic title="区间数" value={episode.interval_count} suffix="个" />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small">
            <Statistic title="切片数" value={episode.slice_count} suffix="个" />
          </Card>
        </Col>
      </Row>

      {/* Tab 内容 */}
      <Card size="small">
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
        />
      </Card>
    </div>
  );
};

export default EpisodeDetail;