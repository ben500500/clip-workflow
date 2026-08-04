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
  Form,
  InputNumber,
  Select,
  Descriptions,
  Divider,
  Empty,
} from 'antd';
import {
  ArrowLeftOutlined,
  NodeIndexOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { intervalApi } from '../api/intervals';
import IntervalReviewComponent from '../components/IntervalReview';
import type { Episode, DetectedInterval, IntervalDetectionConfig } from '../types';
import { getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

const IntervalDetectionPage: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const eid = Number(episodeId);

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [intervals, setIntervals] = useState<DetectedInterval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [configForm] = Form.useForm();

  useEffect(() => {
    fetchData();
  }, [eid]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
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
      const res = await intervalApi.getIntervals(eid);
      setIntervals(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取数据失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDetect = async () => {
    setDetecting(true);
    try {
      let config: Partial<IntervalDetectionConfig> | undefined;
      if (showConfig) {
        config = await configForm.validateFields();
      }
      await intervalApi.detect(eid, config);
      message.success('区间检测已启动');
      setTimeout(() => fetchData(), 2000);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '启动检测失败');
    } finally {
      setDetecting(false);
    }
  };

  const handleUpdate = async (id: number, data: Partial<DetectedInterval>) => {
    try {
      await intervalApi.updateInterval(id, data);
      message.success('更新成功');
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleBatchUpdate = async (data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) => {
    try {
      await intervalApi.batchUpdateIntervals(data);
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
          { title: '区间检测' },
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
              区间检测 - {episode?.title}
            </Title>
          </Space>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<SettingOutlined />}
              onClick={() => setShowConfig(!showConfig)}
            >
              {showConfig ? '隐藏配置' : '检测配置'}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchData}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<NodeIndexOutlined />}
              loading={detecting}
              onClick={handleDetect}
            >
              {detecting ? '检测中...' : '开始检测'}
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
            <Descriptions.Item label="区间数">
              {intervals.length} 个
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {showConfig && (
        <Card size="small" title="区间检测配置" style={{ marginBottom: 16 }}>
          <Form
            form={configForm}
            layout="vertical"
            style={{ maxWidth: 600 }}
            initialValues={{
              min_interval_duration: 10,
              max_interval_duration: 600,
              merge_threshold: 5,
              min_silence_duration: 1,
              voice_activity_threshold: 0.5,
              detect_modes: ['silence', 'scene_change'],
            }}
          >
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item name="min_interval_duration" label="最小区间时长(秒)">
                  <InputNumber min={1} max={3600} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="max_interval_duration" label="最大区间时长(秒)">
                  <InputNumber min={1} max={7200} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="merge_threshold" label="合并阈值(秒)">
                  <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="min_silence_duration" label="最小静音时长(秒)">
                  <InputNumber min={0.1} max={30} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="voice_activity_threshold" label="语音活动阈值">
                  <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="detect_modes" label="检测模式">
                  <Select
                    mode="multiple"
                    placeholder="选择检测模式"
                    options={[
                      { label: '静音检测', value: 'silence' },
                      { label: '场景切换', value: 'scene_change' },
                      { label: '语音活动', value: 'voice_activity' },
                      { label: '内容分析', value: 'content_analysis' },
                    ]}
                  />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Card>
      )}

      {intervals.length > 0 ? (
        <IntervalReviewComponent
          intervals={intervals}
          loading={loading}
          onUpdate={handleUpdate}
          onBatchUpdate={handleBatchUpdate}
        />
      ) : (
        <Card>
          <Empty description="暂无区间数据">
            <Button
              type="primary"
              icon={<NodeIndexOutlined />}
              loading={detecting}
              onClick={handleDetect}
            >
              开始区间检测
            </Button>
          </Empty>
        </Card>
      )}
    </div>
  );
};

export default IntervalDetectionPage;