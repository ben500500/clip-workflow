import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Statistic, Table, Tag, Typography, Spin, Alert, Space, Empty,
} from 'antd';
import {
  ProjectOutlined, VideoCameraOutlined, ScissorOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import type { Project, ProjectStats } from '../types';
import { formatRelativeTime, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<ProjectStats | null>(null);

  useEffect(() => {
    projectApi
      .getStats()
      .then(setStats)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '获取统计失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} tip="加载中..." />;
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
        <a onClick={() => navigate(`/projects/${record.id}`)}>{name}</a>
      ),
    },
    {
      title: '剧集数',
      dataIndex: 'episode_count',
      key: 'episode_count',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (date: string) => <Text type="secondary">{formatRelativeTime(date)}</Text>,
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>仪表盘</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="总项目数" value={stats?.total_projects || 0} prefix={<ProjectOutlined />} suffix="个" valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="进行中" value={stats?.active_projects || 0} prefix={<VideoCameraOutlined />} suffix="个" valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="总剧集数" value={stats?.total_episodes || 0} prefix={<VideoCameraOutlined />} suffix="个" valueStyle={{ color: '#722ed1' }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="切片总数" value={stats?.total_slices || 0} prefix={<ScissorOutlined />} suffix="个" valueStyle={{ color: '#fa8c16' }} />
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="处理进度" size="small">
            <Statistic title="已处理剧集" value={stats?.processed_episodes || 0} suffix={`/ ${stats?.total_episodes || 0} 集`} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="快捷操作" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <a onClick={() => navigate('/projects')}>短剧切片 →</a>
              <a onClick={() => navigate('/publish')}>发布管理 →</a>
            </Space>
          </Card>
        </Col>
      </Row>
      <Card title="最近项目" size="small">
        {stats?.recent_projects?.length ? (
          <Table rowKey="id" columns={recentColumns} dataSource={stats.recent_projects} pagination={false} size="small" scroll={{ x: 560 }} />
        ) : (
          <Empty description="暂无项目" />
        )}
      </Card>
    </div>
  );
};

export default Dashboard;
