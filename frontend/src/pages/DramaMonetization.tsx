import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Table, Tag, Typography, Spin, Alert, Select, Space, Statistic, Tabs, DatePicker,
} from 'antd';
import { MoneyCollectOutlined, EyeOutlined, ThunderboltOutlined, RiseOutlined } from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { MiniProgramMetric, AdMetric, DramaMetric, DramaDetail } from '../types';
import { formatDate, formatPercent } from '../utils/format';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const DramaMonetization: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [miniProgram, setMiniProgram] = useState<MiniProgramMetric[]>([]);
  const [ads, setAds] = useState<AdMetric[]>([]);
  const [dramas, setDramas] = useState<DramaMetric[]>([]);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(29, 'day'), dayjs(),
  ]);

  useEffect(() => {
    setLoading(true);
    const start = dateRange[0].format('YYYY-MM-DD');
    const end = dateRange[1].format('YYYY-MM-DD');
    Promise.all([
      dashboardApi.getMiniProgramMetrics({ start_date: start, end_date: end }),
      dashboardApi.getAdMetrics({ start_date: start, end_date: end }),
      dashboardApi.getDramaMetrics(),
    ])
      .then(([mp, ad, dr]) => {
        setMiniProgram(mp);
        setAds(ad);
        setDramas(dr);
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

  // Summary stats
  const totalRevenue = ads.reduce((s, a) => s + a.revenue, 0);
  const totalImpression = ads.reduce((s, a) => s + a.impression_count, 0);
  const totalMpUv = miniProgram.reduce((s, m) => s + m.uv, 0);
  const avgEcpm = totalImpression > 0 ? (totalRevenue / totalImpression) * 1000 : 0;

  const adColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 110, render: (d: string) => formatDate(d) },
    { title: '曝光量', dataIndex: 'impression_count', key: 'impression_count', width: 110 },
    { title: '点击量', dataIndex: 'click_count', key: 'click_count', width: 100 },
    { title: '点击率', dataIndex: 'ctr', key: 'ctr', width: 90, render: (v: number) => formatPercent((v ?? 0) * 100) },
    { title: 'eCPM', dataIndex: 'ecpm', key: 'ecpm', width: 90, render: (v: number) => `¥${(v || 0).toFixed(2)}` },
    { title: '收益', dataIndex: 'revenue', key: 'revenue', width: 110, render: (v: number) => <span style={{ color: '#fa8c16', fontWeight: 600 }}>¥{(v || 0).toFixed(2)}</span> },
    { title: '激励视频曝光', dataIndex: 'reward_video_impression', key: 'reward_video_impression', width: 120 },
    { title: '插屏曝光', dataIndex: 'interstitial_impression', key: 'interstitial_impression', width: 110 },
  ];

  const mpColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 110, render: (d: string) => formatDate(d) },
    { title: 'UV', dataIndex: 'uv', key: 'uv', width: 90 },
    { title: '新增用户', dataIndex: 'new_user_count', key: 'new_user_count', width: 100 },
    { title: '短剧播放', dataIndex: 'drama_play_count', key: 'drama_play_count', width: 110 },
    { title: '平均播放时长', dataIndex: 'avg_play_duration', key: 'avg_play_duration', width: 130, render: (v: number) => `${(v || 0).toFixed(1)}s` },
    { title: '完播率', dataIndex: 'drama_finish_rate', key: 'drama_finish_rate', width: 90, render: (v: number) => formatPercent((v ?? 0) * 100) },
  ];

  const dramaColumns = [
    { title: '剧集ID', dataIndex: 'drama_id', key: 'drama_id', width: 130, ellipsis: true },
    { title: '日期', dataIndex: 'date', key: 'date', width: 110, render: (d: string) => formatDate(d) },
    { title: 'UV', dataIndex: 'uv', key: 'uv', width: 80 },
    { title: '播放', dataIndex: 'play_count', key: 'play_count', width: 80 },
    { title: '完播率', dataIndex: 'finish_rate', key: 'finish_rate', width: 90, render: (v: number) => formatPercent((v ?? 0) * 100) },
    { title: '广告曝光', dataIndex: 'ad_impression', key: 'ad_impression', width: 110 },
    { title: '广告收益', dataIndex: 'ad_revenue', key: 'ad_revenue', width: 110, render: (v: number) => `¥${(v || 0).toFixed(2)}` },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>短剧变现</Title>
        <RangePicker
          value={dateRange}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) setDateRange([dates[0], dates[1]]);
          }}
          allowClear={false}
        />
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="广告总收益" value={totalRevenue} precision={2} prefix={<MoneyCollectOutlined />} suffix="元" valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="总曝光量" value={totalImpression} prefix={<EyeOutlined />} suffix="次" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="平均 eCPM" value={avgEcpm} precision={2} prefix={<ThunderboltOutlined />} suffix="元" valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="小程序 UV" value={totalMpUv} prefix={<RiseOutlined />} suffix="人" valueStyle={{ color: '#722ed1' }} /></Card>
        </Col>
      </Row>

      <Tabs
        defaultActiveKey="ads"
        items={[
          {
            key: 'ads',
            label: '广告数据',
            children: (
              <Card size="small">
                <Table rowKey="id" size="small" columns={adColumns} dataSource={ads} pagination={{ pageSize: 15 }} scroll={{ x: 860 }} />
              </Card>
            ),
          },
          {
            key: 'mini-program',
            label: '小程序数据',
            children: (
              <Card size="small">
                <Table rowKey="id" size="small" columns={mpColumns} dataSource={miniProgram} pagination={{ pageSize: 15 }} scroll={{ x: 640 }} />
              </Card>
            ),
          },
          {
            key: 'dramas',
            label: '分剧排行',
            children: (
              <Card size="small">
                <Table rowKey="id" size="small" columns={dramaColumns} dataSource={dramas} pagination={{ pageSize: 15 }} scroll={{ x: 720 }} />
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
};

export default DramaMonetization;