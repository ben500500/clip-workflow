import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Card,
  Typography,
  Spin,
  Alert,
  Button,
  Space,
  Row,
  Col,
  Tag,
  Breadcrumb,
  message,
  Descriptions,
  Empty,
} from 'antd';
import {
  ArrowLeftOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { autoclipApi } from '../api/autoclip';
import ClipReviewComponent from '../components/ClipReview';
import type { Episode, ClipCandidate } from '../types';
import { formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

const ClipReviewPage: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const eid = Number(episodeId);

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [candidates, setCandidates] = useState<ClipCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);

  useEffect(() => {
    fetchData();
  }, [eid]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      // Mock episode data
      setEpisode({
        id: eid,
        project_id: 1,
        title: `剧集 #${eid}`,
        file_path: '',
        file_size: 0,
        duration: 0,
        status: 'uploaded',
        clip_count: 0,
        interval_count: 0,
        slice_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as Episode);
      const res = await autoclipApi.getCandidates(eid);
      setCandidates(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取数据失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDetect = async () => {
    setDetecting(true);
    try {
      await autoclipApi.detect(eid);
      message.success('AutoClip 检测已启动');
      setTimeout(() => fetchData(), 2000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动检测失败');
    } finally {
      setDetecting(false);
    }
  };

  const handleUpdate = async (id: number, data: Partial<ClipCandidate>) => {
    try {
      await autoclipApi.updateCandidate(id, data);
      message.success('更新成功');
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleBatchUpdate = async (data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) => {
    try {
      await autoclipApi.batchUpdateCandidates(data);
      message.success('批量操作成功');
      fetchData();
    } catch (err: unknown) {
      throw err;
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">项目管理</Link> },
          { title: <Link to={`/episodes/${eid}`}>剧集详情</Link> },
          { title: '选点审核' },
        ]}
        style={{ marginBottom: 16 }}
      />

      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${eid}`)}>
              返回
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              选点审核 - {episode?.title}
            </Title>
          </Space>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchData}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={detecting}
              onClick={handleDetect}
            >
              {detecting ? '检测中...' : '重新检测'}
            </Button>
          </Space>
        </Col>
      </Row>

      {episode && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Descriptions size="small" column={3}>
            <Descriptions.Item label="剧集">{episode.title}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={getStatusColor(episode.status)}>
                {getStatusLabel(episode.status)}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="选点数">
              {candidates.length} 个
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {candidates.length > 0 ? (
        <ClipReviewComponent
          candidates={candidates}
          loading={loading}
          onUpdate={handleUpdate}
          onBatchUpdate={handleBatchUpdate}
        />
      ) : (
        <Card>
          <Empty description="暂无选点数据">
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={detecting}
              onClick={handleDetect}
            >
              开始 AutoClip 检测
            </Button>
          </Empty>
        </Card>
      )}
    </div>
  );
};

export default ClipReviewPage;