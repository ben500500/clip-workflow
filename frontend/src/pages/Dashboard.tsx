import React, { useEffect, useState } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Typography,
  Spin,
  Alert,
  Space,
  List,
  Empty,
} from 'antd';
import {
  ProjectOutlined,
  VideoCameraOutlined,
  ScissorOutlined,
  CheckCircleOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import type { Project } from '../types';
import {
  formatDateTime,
  formatRelativeTime,
  getStatusColor,
  getStatusLabel,
} from '../utils/format';

const { Title, Text } = Typography;

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<{
    total_projects: number;
    active_projects: number;
    total_episodes: number;
    processed_episodes: number;
    total_slices: number;
    recent_projects: Project[];
  } | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await projectApi.getStats();
      setStats(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取统计数据失败');
    } finally {
      setLoading(false);
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

  const recentColumns = [
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: Project) => (
        <a onClick={() => navigate(`/projects/${record.id}`)}>
          {name}
        </a>
      ),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 100,
      render: (platform: string) => <Tag>{platform}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '剧集数',
      dataIndex: 'total_episodes',
      key: 'total_episodes',
      width: 80,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (date: string) => (
        <Text type="secondary">{formatRelativeTime(date)}</Text>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>
        仪表盘
      </Title>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="总项目数"
              value={stats?.total_projects || 0}
              prefix={<ProjectOutlined />}
              valueStyle={{ color: '#1677ff' }}
              suffix="个"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="进行中"
              value={stats?.active_projects || 0}
              prefix={<VideoCameraOutlined />}
              valueStyle={{ color: '#52c41a' }}
              suffix="个"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="总剧集数"
              value={stats?.total_episodes || 0}
              prefix={<VideoCameraOutlined />}
              valueStyle={{ color: '#722ed1' }}
              suffix="个"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="切片总数"
              value={stats?.total_slices || 0}
              prefix={<ScissorOutlined />}
              valueStyle={{ color: '#fa8c16' }}
              suffix="个"
            />
          </Card>
        </Col>
      </Row>

      {/* 处理进度 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="处理进度" size="small">
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title="剧集总数"
                  value={stats?.total_episodes || 0}
                  suffix="集"
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="已处理"
                  value={stats?.processed_episodes || 0}
                  suffix={`/ ${stats?.total_episodes || 0} 集`}
                  valueStyle={{ color: '#52c41a' }}
                  prefix={<CheckCircleOutlined />}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="快捷操作" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Card.Grid
                hoverable
                style={{ width: '50%', textAlign: 'center', cursor: 'pointer' }}
                onClick={() => navigate('/projects')}
              >
                <ProjectOutlined style={{ fontSize: 24, color: '#1677ff' }} />
                <div>项目管理</div>
              </Card.Grid>
              <Card.Grid
                hoverable
                style={{ width: '50%', textAlign: 'center', cursor: 'pointer' }}
                onClick={() => navigate('/settings')}
              >
                <ScissorOutlined style={{ fontSize: 24, color: '#52c41a' }} />
                <div>系统设置</div>
              </Card.Grid>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 最近项目 */}
      <Card
        title="最近项目"
        size="small"
        extra={
          <a onClick={() => navigate('/projects')}>
            查看全部 <ArrowRightOutlined />
          </a>
        }
      >
        {stats?.recent_projects && stats.recent_projects.length > 0 ? (
          <Table
            rowKey="id"
            columns={recentColumns}
            dataSource={stats.recent_projects}
            pagination={false}
            size="small"
            onRow={(record) => ({
              onClick: () => navigate(`/projects/${record.id}`),
              style: { cursor: 'pointer' },
            })}
          />
        ) : (
          <Empty description="暂无项目" />
        )}
      </Card>
    </div>
  );
};

export default Dashboard;