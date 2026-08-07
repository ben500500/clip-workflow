import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Statistic, Table, Tag, Typography, Spin, Alert, Space, Progress, DatePicker, Select,
} from 'antd';
import {
  MoneyCollectOutlined, EyeOutlined, TeamOutlined, ThunderboltOutlined, WarningOutlined,
} from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { DashboardOverview as OverviewType, FunnelData, TrendPoint, VideoMetric } from '../types';
import { formatDate, formatPercent } from '../utils/format';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const DashboardOverview: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<OverviewType | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [topVideos, setTopVideos] = useState<VideoMetric[]>([]);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(29, 'day'), dayjs(),
  ]);

  useEffect(() => {
    setLoading(true);
    const start = dateRange[0].format('YYYY-MM-DD');
    const end = dateRange[1].format('YYYY-MM-DD');
    Promise.all([
      dashboardApi.getOverview(),
      dashboardApi.getTrend({ start_date: start, end_date: end }),
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
  }, [dateRange]);

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const maxPlay = Math.max(1, ...trend.map((t) => t.play_count));
  const maxRevenue = Math.max(0.01, ...trend.map((t) => t.revenue));

  // Calculate alerts
  const alertsList: string[] = [];
  if (overview && overview.ecpm < 10) {
    alertsList.push(`eCPM 偏低 (¥${overview.ecpm})，建议检查广告填充率`);
  }
  if (overview && overview.revenue_per_uv < 0.01) {
    alertsList.push('单UV收益偏低，建议优化引流质量');
  }
  if (funnel && funnel.jump_rate < 5) {
    alertsList.push(`跳转率仅 ${funnel.jump_rate.toFixed(1)}%，建议优化视频引导`);
  }
  if (funnel && funnel.play_rate < 30) {
    alertsList.push(`开播率仅 ${funnel.play_rate.toFixed(1)}%，建议检查小程序入口`);
  }

  const funnelSteps = funnel
    ? [
        { label: '播放', value: funnel.total_play, rate: null as number | null },
        { label: '跳转', value: funnel.jump_click, rate: funnel.jump_rate },
        { label: '小程序 UV', value: funnel.mini_program_uv, rate: null as number | null },
        { label: '广告曝光', value: funnel.ad_exposure_uv, rate: funnel.exposure_rate },
        { label: '收益', value: funnel.revenue, rate: null as number | null },
      ]
    : [];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>数据总览</Title>
        <RangePicker
          value={dateRange}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) setDateRange([dates[0], dates[1]]);
          }}
          allowClear={false}
        />
      </div>

      {/* L1: 核心指标卡片 */}
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

      {/* 二级指标 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="eCPM" value={overview?.ecpm || 0} precision={2} prefix={<ThunderboltOutlined />} suffix="元" valueStyle={{ fontSize: 18 }} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="单UV收益" value={overview?.revenue_per_uv || 0} precision={4} suffix="元" valueStyle={{ fontSize: 18 }} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="今日 UV" value={overview?.today_uv || 0} suffix="人" valueStyle={{ fontSize: 18 }} />
          </Card>
        </Col>
      </Row>

      {/* 趋势图 + 漏斗 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={16}>
          <Card size="small" title="收益趋势（近 30 天）">
            {trend.length === 0 ? (
              <Text type="secondary">暂无数据</Text>
            ) : (
              <div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 160 }}>
                  {trend.map((t) => (
                    <div key={t.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <div
                        title={`¥${t.revenue}`}
                        style={{
                          width: '100%', maxWidth: 20,
                          height: `${Math.max(4, (t.revenue / maxRevenue) * 130)}px`,
                          background: 'linear-gradient(to top, #fa8c16, #ffc53d)',
                          borderRadius: '3px 3px 0 0',
                        }}
                      />
                    </div>
                  ))}
                </div>
                <Space wrap style={{ marginTop: 8 }}>
                  <Tag>最近: {trend.length ? formatDate(trend[trend.length - 1].date) : '-'}</Tag>
                  <Tag color="orange">最高收益: ¥{Math.max(0, ...trend.map((t) => t.revenue)).toFixed(2)}</Tag>
                </Space>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card size="small" title="IAA 漏斗">
            {funnelSteps.length === 0 ? (
              <Text type="secondary">暂无数据</Text>
            ) : (
              funnelSteps.map((step, i) => (
                <div key={step.label} style={{ marginBottom: 12 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <span>{i + 1}. {step.label}</span>
                    <b>{step.value.toLocaleString()}{step.label === '收益' ? ' 元' : ''}</b>
                  </Space>
                  {i < funnelSteps.length - 1 && step.rate !== null && (
                    <Progress percent={Math.min(100, step.rate!)} size="small" format={() => `${(step.rate ?? 0).toFixed(1)}%`} />
                  )}
                </div>
              ))
            )}
          </Card>
        </Col>
      </Row>

      {/* TOP5 视频 + 预警列表 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card size="small" title="今日 TOP5 视频（按收益）">
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={topVideos}
              scroll={{ x: 680 }}
              columns={[
                { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => t || '-' },
                { title: '播放', dataIndex: 'play_count', key: 'play_count', width: 90 },
                { title: '完播率', dataIndex: 'finish_rate', key: 'finish_rate', width: 90, render: (v: number) => formatPercent((v ?? 0) * 100) },
                { title: '跳转', dataIndex: 'jump_click_count', key: 'jump_click_count', width: 80 },
                { title: '归因收益', dataIndex: 'attributed_revenue', key: 'attributed_revenue', width: 110, render: (v: number) => <span style={{ color: '#fa8c16', fontWeight: 600 }}>¥{(v || 0).toFixed(2)}</span> },
                { title: '日期', dataIndex: 'publish_date', key: 'publish_date', width: 110, render: (d: string) => formatDate(d) },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card size="small" title={<><WarningOutlined style={{ color: '#faad14' }} /> 预警</>}>
            {alertsList.length === 0 ? (
              <Text type="secondary">暂无预警，所有指标正常</Text>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {alertsList.map((alert, i) => (
                  <Alert key={i} type="warning" message={alert} showIcon style={{ padding: '8px 12px' }} />
                ))}
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default DashboardOverview;