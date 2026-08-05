import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Typography, Spin, Alert, Progress, Space, Tag, Table, Statistic,
} from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { FunnelData, FunnelCompareData } from '../types';
import { formatDate, formatPercent } from '../utils/format';

const { Title, Text } = Typography;

const FunnelAnalysis: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [funnelTrend, setFunnelTrend] = useState<FunnelData[]>([]);
  const [compare, setCompare] = useState<FunnelCompareData | null>(null);

  useEffect(() => {
    Promise.all([
      dashboardApi.getFunnelTrend(),
      dashboardApi.getFunnelCompare(),
    ])
      .then(([trend, cmp]) => {
        setFunnelTrend(trend);
        setCompare(cmp);
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

  const latestFunnel = funnelTrend.length > 0 ? funnelTrend[funnelTrend.length - 1] : null;

  const funnelSteps = latestFunnel
    ? [
        { label: '播放', value: latestFunnel.total_play, rate: null as number | null },
        { label: '跳转', value: latestFunnel.jump_click, rate: latestFunnel.jump_rate },
        { label: '小程序 UV', value: latestFunnel.mini_program_uv, rate: null as number | null },
        { label: '开播', value: latestFunnel.drama_play_uv, rate: latestFunnel.play_rate },
        { label: '广告曝光', value: latestFunnel.ad_exposure_uv, rate: latestFunnel.exposure_rate },
        { label: '收益', value: latestFunnel.revenue, rate: null as number | null },
      ]
    : [];

  const renderChange = (change: number) => {
    if (change > 0) return <Tag color="green"><ArrowUpOutlined /> {change}%</Tag>;
    if (change < 0) return <Tag color="red"><ArrowDownOutlined /> {Math.abs(change)}%</Tag>;
    return <Tag>持平</Tag>;
  };

  const trendColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 110, render: (d: string) => formatDate(d) },
    { title: '播放', dataIndex: 'total_play', key: 'total_play', width: 90 },
    { title: '跳转', dataIndex: 'jump_click', key: 'jump_click', width: 80 },
    { title: '跳转率', dataIndex: 'jump_rate', key: 'jump_rate', width: 90, render: (v: number) => formatPercent(v) },
    { title: '小程序UV', dataIndex: 'mini_program_uv', key: 'mini_program_uv', width: 100 },
    { title: '开播UV', dataIndex: 'drama_play_uv', key: 'drama_play_uv', width: 90 },
    { title: '开播率', dataIndex: 'play_rate', key: 'play_rate', width: 90, render: (v: number) => formatPercent(v) },
    { title: '广告曝光UV', dataIndex: 'ad_exposure_uv', key: 'ad_exposure_uv', width: 110 },
    { title: '曝光率', dataIndex: 'exposure_rate', key: 'exposure_rate', width: 90, render: (v: number) => formatPercent(v) },
    { title: '收益', dataIndex: 'revenue', key: 'revenue', width: 100, render: (v: number) => `¥${(v || 0).toFixed(2)}` },
    { title: '千次播放收益', dataIndex: 'revenue_per_1000_play', key: 'revenue_per_1000_play', width: 120, render: (v: number) => `¥${(v || 0).toFixed(2)}` },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>转化漏斗</Title>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card size="small" title="全链路漏斗">
            {funnelSteps.length === 0 ? (
              <Text type="secondary">暂无数据</Text>
            ) : (
              <div style={{ padding: '8px 0' }}>
                {funnelSteps.map((step, i) => (
                  <div key={step.label} style={{ marginBottom: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <Space>
                        <span style={{
                          display: 'inline-flex', width: 22, height: 22, borderRadius: '50%',
                          background: '#1677ff', color: '#fff', alignItems: 'center', justifyContent: 'center',
                          fontSize: 12, fontWeight: 600,
                        }}>{i + 1}</span>
                        <Text strong>{step.label}</Text>
                      </Space>
                      <Text strong>{typeof step.value === 'number' ? step.value.toLocaleString() : '-'}{step.label === '收益' ? ' 元' : ''}</Text>
                    </div>
                    {step.rate !== null && (
                      <div style={{ paddingLeft: 30 }}>
                        <Progress
                          percent={Math.min(100, step.rate!)}
                          size="small"
                          format={() => `${(step.rate ?? 0).toFixed(1)}%`}
                        />
                      </div>
                    )}
                    {i < funnelSteps.length - 1 && (
                      <div style={{ textAlign: 'center', margin: '4px 0' }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>▼</Text>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="本周 vs 上周对比">
            {compare ? (
              <div>
                <Row gutter={[16, 16]}>
                  <Col span={12}>
                    <Statistic
                      title="跳转率"
                      value={compare.this_week.avg_jump_rate}
                      suffix={`% (上周 ${compare.last_week.avg_jump_rate}%)`}
                      valueStyle={{ fontSize: 20 }}
                    />
                    <div style={{ marginTop: 4 }}>{renderChange(compare.changes.jump_rate_change)}</div>
                  </Col>
                  <Col span={12}>
                    <Statistic
                      title="开播率"
                      value={compare.this_week.avg_play_rate}
                      suffix={`% (上周 ${compare.last_week.avg_play_rate}%)`}
                      valueStyle={{ fontSize: 20 }}
                    />
                    <div style={{ marginTop: 4 }}>{renderChange(compare.changes.play_rate_change)}</div>
                  </Col>
                </Row>
                <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                  <Col span={12}>
                    <Statistic
                      title="曝光率"
                      value={compare.this_week.avg_exposure_rate}
                      suffix={`% (上周 ${compare.last_week.avg_exposure_rate}%)`}
                      valueStyle={{ fontSize: 20 }}
                    />
                    <div style={{ marginTop: 4 }}>{renderChange(compare.changes.exposure_rate_change)}</div>
                  </Col>
                  <Col span={12}>
                    <Statistic
                      title="总收益"
                      value={compare.this_week.total_revenue}
                      precision={2}
                      suffix={`元 (上周 ¥${compare.last_week.total_revenue})`}
                      valueStyle={{ fontSize: 20, color: '#fa8c16' }}
                    />
                    <div style={{ marginTop: 4 }}>{renderChange(compare.changes.revenue_change)}</div>
                  </Col>
                </Row>
              </div>
            ) : (
              <Text type="secondary">暂无对比数据</Text>
            )}
          </Card>
        </Col>
      </Row>

      <Card size="small" title="漏斗趋势">
        <Table
          rowKey="date"
          size="small"
          columns={trendColumns}
          dataSource={funnelTrend}
          pagination={{ pageSize: 15 }}
        />
      </Card>
    </div>
  );
};

export default FunnelAnalysis;