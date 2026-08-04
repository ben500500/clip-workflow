import React, { useState } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Typography,
  Space,
  DatePicker,
  Select,
  Divider,
} from 'antd';
import {
  DollarOutlined,
  PlayCircleOutlined,
  TeamOutlined,
  RiseOutlined,
  FallOutlined,
  ThunderboltOutlined,
  FundOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { VideoMetric } from '../types';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

// ========== Mock 数据 ==========

const mockOverview = {
  today_revenue: 3256.80,
  week_revenue: 21450.50,
  total_play: 1580000,
  total_uv: 386000,
  ecpm: 45.20,
  revenue_per_uv: 0.056,
  today_revenue_change: 12.5,
  week_revenue_change: -3.2,
  total_play_change: 8.7,
};

const mockTopVideos: VideoMetric[] = [
  {
    id: 'v1',
    title: '霸总逆袭 - 第一集：命运的转折',
    publish_date: '2024-03-15',
    account_id: 'acc1',
    play_count: 258000,
    finish_rate: 0.72,
    like_count: 12500,
    comment_count: 3200,
    share_count: 8900,
    favorite_count: 5600,
    social_recommend_ratio: 0.65,
    jump_click_count: 4500,
    jump_click_rate: 0.017,
    attributed_uv: 3200,
    attributed_revenue: 580.50,
    content_type: '霸总',
    drama_id: 'drama1',
    production_cost: 0,
  },
  {
    id: 'v2',
    title: '甜蜜复仇 - 第二集：重逢',
    publish_date: '2024-03-14',
    account_id: 'acc1',
    play_count: 198000,
    finish_rate: 0.68,
    like_count: 9800,
    comment_count: 2100,
    share_count: 6500,
    favorite_count: 4200,
    social_recommend_ratio: 0.58,
    jump_click_count: 3200,
    jump_click_rate: 0.016,
    attributed_uv: 2400,
    attributed_revenue: 425.30,
    content_type: '复仇',
    drama_id: 'drama2',
    production_cost: 0,
  },
  {
    id: 'v3',
    title: '都市情缘 - 第三集：意外邂逅',
    publish_date: '2024-03-13',
    account_id: 'acc2',
    play_count: 165000,
    finish_rate: 0.61,
    like_count: 7600,
    comment_count: 1800,
    share_count: 4300,
    favorite_count: 3100,
    social_recommend_ratio: 0.52,
    jump_click_count: 2100,
    jump_click_rate: 0.013,
    attributed_uv: 1600,
    attributed_revenue: 298.00,
    content_type: '都市',
    drama_id: 'drama3',
    production_cost: 0,
  },
  {
    id: 'v4',
    title: '豪门恩怨 - 第四集：真相大白',
    publish_date: '2024-03-12',
    account_id: 'acc1',
    play_count: 142000,
    finish_rate: 0.58,
    like_count: 6200,
    comment_count: 1500,
    share_count: 3800,
    favorite_count: 2800,
    social_recommend_ratio: 0.48,
    jump_click_count: 1800,
    jump_click_rate: 0.013,
    attributed_uv: 1350,
    attributed_revenue: 245.80,
    content_type: '豪门',
    drama_id: 'drama4',
    production_cost: 0,
  },
  {
    id: 'v5',
    title: '重生之我在古代 - 第五集',
    publish_date: '2024-03-11',
    account_id: 'acc2',
    play_count: 120000,
    finish_rate: 0.55,
    like_count: 5400,
    comment_count: 1200,
    share_count: 3100,
    favorite_count: 2200,
    social_recommend_ratio: 0.42,
    jump_click_count: 1500,
    jump_click_rate: 0.012,
    attributed_uv: 1100,
    attributed_revenue: 198.60,
    content_type: '穿越',
    drama_id: 'drama5',
    production_cost: 0,
  },
];

const mockAccounts = [
  { value: 'all', label: '全部账号' },
  { value: 'acc1', label: '短剧精选' },
  { value: 'acc2', label: '热播剧场' },
];

// ========== 组件 ==========

const DashboardOverview: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState(dayjs());
  const [selectedAccount, setSelectedAccount] = useState('all');

  // 渲染趋势指标
  const renderTrend = (change?: number) => {
    if (change === undefined || change === null) return null;
    const isUp = change >= 0;
    return (
      <span style={{ fontSize: 12, marginLeft: 8, color: isUp ? '#3f8600' : '#cf1322' }}>
        {isUp ? <RiseOutlined /> : <FallOutlined />}
        {Math.abs(change)}%
      </span>
    );
  };

  // 顶部视频表格列
  const videoColumns: ColumnsType<VideoMetric> = [
    {
      title: '排名',
      key: 'rank',
      width: 60,
      render: (_: unknown, __: unknown, index: number) => (
        <Tag color={index < 3 ? 'orange' : 'default'}>{index + 1}</Tag>
      ),
    },
    {
      title: '视频标题',
      dataIndex: 'title',
      key: 'title',
      width: 280,
      ellipsis: true,
    },
    {
      title: '播放量',
      dataIndex: 'play_count',
      key: 'play_count',
      width: 120,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '完播率',
      dataIndex: 'finish_rate',
      key: 'finish_rate',
      width: 100,
      render: (val: number) => `${(val * 100).toFixed(1)}%`,
    },
    {
      title: '跳转点击',
      dataIndex: 'jump_click_count',
      key: 'jump_click_count',
      width: 110,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '跳转率',
      dataIndex: 'jump_click_rate',
      key: 'jump_click_rate',
      width: 100,
      render: (val: number) => `${(val * 100).toFixed(2)}%`,
    },
    {
      title: '归因UV',
      dataIndex: 'attributed_uv',
      key: 'attributed_uv',
      width: 100,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '归因收入',
      dataIndex: 'attributed_revenue',
      key: 'attributed_revenue',
      width: 120,
      render: (val: number) => `¥${val.toFixed(2)}`,
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>
        <FundOutlined style={{ marginRight: 8 }} />
        IAA 数据看板
      </Title>

      {/* 筛选栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <DatePicker
            value={selectedDate}
            onChange={(date) => date && setSelectedDate(date)}
            placeholder="选择日期"
            allowClear={false}
          />
          <Select
            value={selectedAccount}
            onChange={setSelectedAccount}
            options={mockAccounts}
            style={{ width: 160 }}
          />
        </Space>
      </Card>

      {/* 6个指标卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} lg={4}>
          <Card hoverable>
            <Statistic
              title="今日收入"
              value={mockOverview.today_revenue}
              precision={2}
              prefix={<DollarOutlined />}
              suffix="元"
              valueStyle={{ color: '#cf1322' }}
            />
            {renderTrend(mockOverview.today_revenue_change)}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card hoverable>
            <Statistic
              title="本周收入"
              value={mockOverview.week_revenue}
              precision={2}
              prefix={<DollarOutlined />}
              suffix="元"
              valueStyle={{ color: '#cf1322' }}
            />
            {renderTrend(mockOverview.week_revenue_change)}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card hoverable>
            <Statistic
              title="总播放量"
              value={mockOverview.total_play}
              prefix={<PlayCircleOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
            {renderTrend(mockOverview.total_play_change)}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card hoverable>
            <Statistic
              title="总UV"
              value={mockOverview.total_uv}
              prefix={<TeamOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card hoverable>
            <Statistic
              title="eCPM"
              value={mockOverview.ecpm}
              precision={2}
              prefix={<ThunderboltOutlined />}
              suffix="元"
              valueStyle={{ color: '#fa8c16' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card hoverable>
            <Statistic
              title="单UV收入"
              value={mockOverview.revenue_per_uv}
              precision={4}
              prefix={<DollarOutlined />}
              suffix="元"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 趋势图 & 漏斗图 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={14}>
          <Card title="收入趋势" size="small">
            <div
              style={{
                height: 320,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#fafafa',
                border: '1px dashed #d9d9d9',
                borderRadius: 8,
              }}
            >
              <Space direction="vertical" align="center">
                <FundOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />
                <Text type="secondary">ECharts 收入趋势图（待接入）</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  将展示近7/30天收入、播放量、UV、eCPM 趋势
                </Text>
              </Space>
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="转化漏斗" size="small">
            <div
              style={{
                height: 320,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#fafafa',
                border: '1px dashed #d9d9d9',
                borderRadius: 8,
              }}
            >
              <Space direction="vertical" align="center">
                <RiseOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />
                <Text type="secondary">漏斗可视化（待接入）</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  播放 → 跳转 → 小程序UV → 广告曝光 → 收入
                </Text>
              </Space>
            </div>
          </Card>
        </Col>
      </Row>

      {/* Top 5 视频 */}
      <Card title="Top 5 视频（按归因收入）" size="small">
        <Table
          rowKey="id"
          columns={videoColumns}
          dataSource={mockTopVideos}
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  );
};

export default DashboardOverview;
