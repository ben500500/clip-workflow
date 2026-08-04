import React, { useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Typography,
  Space,
  Select,
  Button,
  Drawer,
  Descriptions,
  Row,
  Col,
  Statistic,
  Input,
  Segmented,
} from 'antd';
import {
  BarChartOutlined,
  UnorderedListOutlined,
  SearchOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { VideoMetric } from '../types';

const { Title, Text } = Typography;

// ========== Mock 数据 ==========

const mockVideos: VideoMetric[] = [
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
    traffic_method: '社交推荐',
    publish_time_slot: '晚间',
    play_level: 'S',
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
    traffic_method: '社交推荐',
    publish_time_slot: '午间',
    play_level: 'A',
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
    traffic_method: '算法推荐',
    publish_time_slot: '晚间',
    play_level: 'A',
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
    traffic_method: '社交推荐',
    publish_time_slot: '下午',
    play_level: 'B',
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
    traffic_method: '算法推荐',
    publish_time_slot: '上午',
    play_level: 'B',
    production_cost: 0,
  },
  {
    id: 'v6',
    title: '校园青春 - 第六集：毕业季',
    publish_date: '2024-03-10',
    account_id: 'acc1',
    play_count: 95000,
    finish_rate: 0.48,
    like_count: 4200,
    comment_count: 980,
    share_count: 2100,
    favorite_count: 1800,
    social_recommend_ratio: 0.38,
    jump_click_count: 980,
    jump_click_rate: 0.010,
    attributed_uv: 750,
    attributed_revenue: 135.20,
    content_type: '校园',
    drama_id: 'drama6',
    traffic_method: '搜索',
    publish_time_slot: '晚间',
    play_level: 'C',
    production_cost: 0,
  },
];

const contentTypes = ['全部', '霸总', '复仇', '都市', '豪门', '穿越', '校园'];
const timeSlots = ['全部', '上午', '午间', '下午', '晚间'];
const playLevels = ['全部', 'S', 'A', 'B', 'C'];

// ========== 组件 ==========

const ContentAnalysis: React.FC = () => {
  const [viewMode, setViewMode] = useState<string>('列表');
  const [contentType, setContentType] = useState('全部');
  const [timeSlot, setTimeSlot] = useState('全部');
  const [playLevel, setPlayLevel] = useState('全部');
  const [searchText, setSearchText] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState<VideoMetric | null>(null);

  // 过滤数据
  const filteredData = mockVideos.filter((v) => {
    if (contentType !== '全部' && v.content_type !== contentType) return false;
    if (timeSlot !== '全部' && v.publish_time_slot !== timeSlot) return false;
    if (playLevel !== '全部' && v.play_level !== playLevel) return false;
    if (searchText && !v.title.includes(searchText)) return false;
    return true;
  });

  // 排序数据（排行榜模式）
  const rankingData = [...filteredData].sort((a, b) => b.attributed_revenue - a.attributed_revenue);

  const displayData = viewMode === '排行' ? rankingData : filteredData;

  // 查看详情
  const handleViewDetail = (record: VideoMetric) => {
    setSelectedVideo(record);
    setDrawerOpen(true);
  };

  // 播放等级颜色
  const playLevelColor: Record<string, string> = {
    S: 'red',
    A: 'orange',
    B: 'blue',
    C: 'default',
  };

  // ========== 表格列 ==========

  const columns: ColumnsType<VideoMetric> = [
    {
      title: '视频标题',
      dataIndex: 'title',
      key: 'title',
      width: 250,
      ellipsis: true,
    },
    {
      title: '内容类型',
      dataIndex: 'content_type',
      key: 'content_type',
      width: 90,
    },
    {
      title: '播放量',
      dataIndex: 'play_count',
      key: 'play_count',
      width: 110,
      sorter: (a, b) => a.play_count - b.play_count,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '完播率',
      dataIndex: 'finish_rate',
      key: 'finish_rate',
      width: 90,
      sorter: (a, b) => a.finish_rate - b.finish_rate,
      render: (val: number) => `${(val * 100).toFixed(1)}%`,
    },
    {
      title: '点赞',
      dataIndex: 'like_count',
      key: 'like_count',
      width: 90,
      sorter: (a, b) => a.like_count - b.like_count,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '分享',
      dataIndex: 'share_count',
      key: 'share_count',
      width: 90,
      sorter: (a, b) => a.share_count - b.share_count,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '跳转点击',
      dataIndex: 'jump_click_count',
      key: 'jump_click_count',
      width: 100,
      sorter: (a, b) => a.jump_click_count - b.jump_click_count,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '跳转率',
      dataIndex: 'jump_click_rate',
      key: 'jump_click_rate',
      width: 90,
      sorter: (a, b) => a.jump_click_rate - b.jump_click_rate,
      render: (val: number) => `${(val * 100).toFixed(2)}%`,
    },
    {
      title: '归因UV',
      dataIndex: 'attributed_uv',
      key: 'attributed_uv',
      width: 100,
      sorter: (a, b) => a.attributed_uv - b.attributed_uv,
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '归因收入',
      dataIndex: 'attributed_revenue',
      key: 'attributed_revenue',
      width: 110,
      sorter: (a, b) => a.attributed_revenue - b.attributed_revenue,
      render: (val: number) => `¥${val.toFixed(2)}`,
    },
    {
      title: '等级',
      dataIndex: 'play_level',
      key: 'play_level',
      width: 70,
      render: (level: string) => (
        <Tag color={playLevelColor[level] || 'default'}>{level}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      fixed: 'right',
      render: (_: unknown, record: VideoMetric) => (
        <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(record)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>
        <BarChartOutlined style={{ marginRight: 8 }} />
        内容分析
      </Title>

      {/* 筛选区 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]} align="middle">
          <Col>
            <Space>
              <Input
                placeholder="搜索视频标题"
                prefix={<SearchOutlined />}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                allowClear
                style={{ width: 220 }}
              />
              <Select
                value={contentType}
                onChange={setContentType}
                style={{ width: 120 }}
                options={contentTypes.map((t) => ({ value: t, label: t === '全部' ? '全部类型' : t }))}
              />
              <Select
                value={timeSlot}
                onChange={setTimeSlot}
                style={{ width: 120 }}
                options={timeSlots.map((t) => ({ value: t, label: t === '全部' ? '全部时段' : t }))}
              />
              <Select
                value={playLevel}
                onChange={setPlayLevel}
                style={{ width: 120 }}
                options={playLevels.map((t) => ({ value: t, label: t === '全部' ? '全部等级' : `${t}级` }))}
              />
            </Space>
          </Col>
          <Col flex="auto" style={{ textAlign: 'right' }}>
            <Segmented
              value={viewMode}
              onChange={(val) => setViewMode(val as string)}
              options={[
                { value: '列表', icon: <UnorderedListOutlined />, label: '列表' },
                { value: '排行', icon: <BarChartOutlined />, label: '排行' },
              ]}
            />
          </Col>
        </Row>
      </Card>

      {/* 数据表格 */}
      <Card size="small">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={displayData}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          scroll={{ x: 1400 }}
          size="middle"
        />
      </Card>

      {/* 视频详情抽屉 */}
      <Drawer
        title="视频详情"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={640}
      >
        {selectedVideo && (
          <div>
            <Title level={5}>{selectedVideo.title}</Title>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 24 }}>
              <Descriptions.Item label="发布日期">{selectedVideo.publish_date}</Descriptions.Item>
              <Descriptions.Item label="内容类型">{selectedVideo.content_type || '-'}</Descriptions.Item>
              <Descriptions.Item label="短剧ID">{selectedVideo.drama_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="流量来源">{selectedVideo.traffic_method || '-'}</Descriptions.Item>
              <Descriptions.Item label="发布时段">{selectedVideo.publish_time_slot || '-'}</Descriptions.Item>
              <Descriptions.Item label="播放等级">
                <Tag color={playLevelColor[selectedVideo.play_level || ''] || 'default'}>
                  {selectedVideo.play_level || '-'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            <Title level={5}>播放数据</Title>
            <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
              <Col span={8}>
                <Statistic title="播放量" value={selectedVideo.play_count} />
              </Col>
              <Col span={8}>
                <Statistic title="完播率" value={(selectedVideo.finish_rate * 100).toFixed(1)} suffix="%" />
              </Col>
              <Col span={8}>
                <Statistic title="社交推荐占比" value={(selectedVideo.social_recommend_ratio * 100).toFixed(1)} suffix="%" />
              </Col>
            </Row>

            <Title level={5}>互动数据</Title>
            <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
              <Col span={6}>
                <Statistic title="点赞" value={selectedVideo.like_count} />
              </Col>
              <Col span={6}>
                <Statistic title="评论" value={selectedVideo.comment_count} />
              </Col>
              <Col span={6}>
                <Statistic title="分享" value={selectedVideo.share_count} />
              </Col>
              <Col span={6}>
                <Statistic title="收藏" value={selectedVideo.favorite_count} />
              </Col>
            </Row>

            <Title level={5}>转化数据</Title>
            <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
              <Col span={8}>
                <Statistic title="跳转点击" value={selectedVideo.jump_click_count} />
              </Col>
              <Col span={8}>
                <Statistic title="跳转率" value={(selectedVideo.jump_click_rate * 100).toFixed(2)} suffix="%" />
              </Col>
              <Col span={8}>
                <Statistic title="归因UV" value={selectedVideo.attributed_uv} />
              </Col>
            </Row>

            <Card size="small" style={{ background: '#f6ffed', borderColor: '#b7eb8f' }}>
              <Statistic
                title="归因收入"
                value={selectedVideo.attributed_revenue}
                precision={2}
                prefix="¥"
                valueStyle={{ color: '#3f8600' }}
              />
            </Card>
          </div>
        )}
      </Drawer>
    </div>
  );
};

export default ContentAnalysis;
