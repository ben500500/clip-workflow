import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Statistic, Table, Tag, Typography, Spin, Alert, Space, Progress,
} from 'antd';
import {
  MoneyCollectOutlined, EyeOutlined, TeamOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { DashboardOverview, FunnelData, TrendPoint, VideoMetric } from '../types';
import { formatDate, formatPercent } from '../utils/format';

const { Title } = Typography;

const DashboardOverview: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [topVideos, setTopVideos] = useState<VideoMetric[]>([]);

  useEffect(() => {
    Promise.all([
      dashboardApi.getOverview(),
      dashboardApi.getTrend(),
      dashboardApi.getFunnel(),
      dashboardApi.getTopVideos({ limit: 5 }),
    ])
      .then(([o, t, f, v]) => {
        setOverview(o);
        setTrend(t);
        setFunnel(f);
        setTopVideos(v);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const maxPlay = Math.max(1, ...trend.map((t) => t.play_count));

  const funnelSteps = [
    { label: '播放', value: funnel?.total_play || 0, rate: null as number | null },
    { label: '跳转', value: funnel?.jump_click || 0, rate: funnel?.jump_rate ?? 0 },
    { label: '小程序 UV', value: funnel?.mini_program_uv || 0, rate: funnel?.play_rate ?? 0 },
    { label: '广告曝光', value: funnel?.ad_exposure_uv || 0, rate: funnel?.exposure_rate ?? 0 },
    { label: '收益', value: funnel?.revenue || 0, rate: null as number | null },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>数据总览</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="今日收益" value={overview?.today_revenue || 0} precision={2} prefix={<MoneyCollectOutlined />} suffix="元" valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="本周收益" value={overview?.week_revenue || 0} precision={2} suffix="元" valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="累计播放" value={overview?.total_play || 0} prefix={<EyeOutlined />} suffix="次" valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="小程序 UV" value={overview?.total_uv || 0} prefix={<TeamOutlined />} suffix="人" valueStyle={{ color: '#722ed1' }} /></Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={16}>
          <Card size="small" title="播放趋势（近 30 天）">
            {trend.length === 0 ? (
              <Typography.Text type="secondary">暂无数据</Typography.Text>
            ) : (
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 180 }}>
                {trend.map((t) => (
                  <div key={t.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                    <div
                      title={`${t.date}: ${t.play_count} 次播放`}
                      style={{
                        width: '100%',
                        maxWidth: 18,
                        height: `${Math.max(4, (t.play_count / maxPlay) * 140)}px`,
                        background: '#1677ff',
                        borderRadius: 3,
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
            <Space wrap style={{ marginTop: 8 }}>
              <Tag>最近: {trend.length ? formatDate(trend[trend.length - 1].date) : '-'}</Tag>
              <Tag>最高播放: {Math.max(0, ...trend.map((t) => t.play_count))}</Tag>
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card size="small" title="IAA 漏斗">
            {funnelSteps.map((step, i) => (
              <div key={step.label} style={{ marginBottom: 12 }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <span>{i + 1}. {step.label}</span>
                  <b>{step.value.toLocaleString()}{step.label === '收益' ? ' 元' : ''}</b>
                </Space>
                {i < funnelSteps.length - 1 && step.rate !== null && (
                  <Progress percent={Math.min(100, step.rate)} size="small" />
                )}
              </div>
            ))}
          </Card>
        </Col>
      </Row>
      <Card size="small" title="TOP 视频">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={topVideos}
          columns={[
            { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => t || '-' },
            { title: '播放', dataIndex: 'play_count', key: 'play_count', width: 110 },
            { title: '完播率', dataIndex: 'finish_rate', key: 'finish_rate', width: 110, render: (v: number) => formatPercent((v ?? 0) * 100) },
            { title: '跳转', dataIndex: 'jump_click_count', key: 'jump_click_count', width: 100 },
            { title: '归因收益', dataIndex: 'attributed_revenue', key: 'attributed_revenue', width: 120, render: (v: number) => `${v || 0} 元` },
            { title: '日期', dataIndex: 'publish_date', key: 'publish_date', width: 110, render: (d: string) => formatDate(d) },
          ]}
        />
      </Card>
    </div>
  );
};

export default DashboardOverview;
