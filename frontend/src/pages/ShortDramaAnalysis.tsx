import React, { useEffect, useState, useMemo } from 'react';
import {
  Card, Row, Col, Statistic, Table, Tag, Typography, Spin, Alert, Space, DatePicker, Select, Tabs, Tooltip, Button,
} from 'antd';
import {
  PlayCircleOutlined, EyeOutlined, RiseOutlined, LinkOutlined, MoneyCollectOutlined,
} from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { ShortDramaAnalysisRow, ShortDramaSummary, ShortDramaTopic } from '../types';
import { formatDate, formatPercent } from '../utils/format';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const PLATFORM_LABELS: Record<string, string> = {
  wechat_channel: '视频号',
  douyin: '抖音',
  kuaishou: '快手',
};

const PLATFORM_OPTIONS = [
  { value: '', label: '全部平台' },
  { value: 'wechat_channel', label: '视频号' },
  { value: 'douyin', label: '抖音' },
  { value: 'kuaishou', label: '快手' },
];

/** 单格最多展示 3 个标签，超出显示 +N（点击展开完整列表），避免挤压相邻列 */
const TagCell: React.FC<{ tags?: string[]; max?: number }> = ({ tags, max = 3 }) => {
  const list = tags || [];
  if (list.length === 0) return <Text type="secondary">-</Text>;
  const shown = list.slice(0, max);
  const rest = list.length - shown.length;
  return (
    <Space size={[4, 4]} wrap>
      {shown.map((t) => (
        <Tag key={t} color="blue" style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {t}
        </Tag>
      ))}
      {rest > 0 && (
        <Tooltip title={list.slice(max).join('，')}>
          <Tag color="default">+{rest}</Tag>
        </Tooltip>
      )}
    </Space>
  );
};

const ShortDramaAnalysis: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [platform, setPlatform] = useState<string>('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(29, 'day'), dayjs(),
  ]);
  const [summary, setSummary] = useState<ShortDramaSummary | null>(null);
  const [items, setItems] = useState<ShortDramaAnalysisRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [topics, setTopics] = useState<ShortDramaTopic[]>([]);
  const pageSize = 20;

  const fetchData = (targetPlatform: string, start: string, end: string, targetPage: number) => {
    setLoading(true);
    const params = {
      platform: targetPlatform || undefined,
      start_date: start,
      end_date: end,
      page: targetPage,
      page_size: pageSize,
    };
    Promise.all([
      dashboardApi.getShortDramaSummary({ platform: targetPlatform || undefined, start_date: start, end_date: end }),
      dashboardApi.getShortDramaAnalysis(params),
      dashboardApi.getShortDramaTopics({ platform: targetPlatform || undefined, start_date: start, end_date: end, limit: 10 }),
    ])
      .then(([s, a, t]) => {
        setSummary(s);
        setItems(a.items);
        setTotal(a.total);
        setTopics(t);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const start = dateRange[0].format('YYYY-MM-DD');
    const end = dateRange[1].format('YYYY-MM-DD');
    fetchData(platform, start, end, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platform, dateRange]);

  const columns = useMemo(() => [
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 90,
      fixed: 'left' as const,
      render: (p: string | null) => (p ? <Tag color={p === 'wechat_channel' ? 'green' : p === 'douyin' ? 'geekblue' : 'purple'}>{PLATFORM_LABELS[p] || p}</Tag> : '-'),
    },
    {
      title: '账号',
      dataIndex: 'account_name',
      key: 'account_name',
      width: 110,
      ellipsis: true,
      render: (a: string | null) => a || '-',
    },
    {
      title: '视频标题',
      dataIndex: 'title',
      key: 'title',
      width: 200,
      ellipsis: true,
      render: (t: string | null) => t || '-',
    },
    {
      title: '发布时间',
      dataIndex: 'publish_date',
      key: 'publish_date',
      width: 110,
      render: (d: string | null) => formatDate(d),
    },
    {
      title: '文案摘要',
      key: 'source_text',
      width: 200,
      ellipsis: true,
      render: (_: unknown, r: ShortDramaAnalysisRow) =>
        r.generation?.source_text ? <Tooltip title={r.generation.source_text}><span>{r.generation.source_text}</span></Tooltip> : '-',
    },
    {
      title: '时长',
      key: 'duration',
      width: 80,
      render: (_: unknown, r: ShortDramaAnalysisRow) =>
        r.generation?.duration ? <Text>{r.generation.duration}s</Text> : '-',
    },
    {
      title: '题材/基调',
      key: 'theme_tone',
      width: 130,
      ellipsis: true,
      render: (_: unknown, r: ShortDramaAnalysisRow) =>
        r.generation?.theme || r.generation?.tone
          ? <Text>{[r.generation.theme, r.generation.tone].filter(Boolean).join(' · ')}</Text>
          : '-',
    },
    {
      title: '短标题',
      key: 'short_title',
      width: 140,
      ellipsis: true,
      render: (_: unknown, r: ShortDramaAnalysisRow) => r.generation?.short_title || '-',
    },
    {
      title: '话题标签',
      key: 'material_tags',
      width: 220,
      render: (_: unknown, r: ShortDramaAnalysisRow) => <TagCell tags={r.generation?.material_tags} />,
    },
    { title: '播放', dataIndex: 'play_count', key: 'play_count', width: 90, align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '完播率', dataIndex: 'finish_rate', key: 'finish_rate', width: 90, align: 'right' as const, render: (v: number) => formatPercent(v) },
    { title: '点赞', dataIndex: 'like_count', key: 'like_count', width: 80, align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '评论', dataIndex: 'comment_count', key: 'comment_count', width: 80, align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '转发', dataIndex: 'share_count', key: 'share_count', width: 80, align: 'right' as const, render: (v: number) => v.toLocaleString() },
    {
      title: '跳转',
      dataIndex: 'jump_click_count',
      key: 'jump_click_count',
      width: 90,
      align: 'right' as const,
      render: (v: number, r: ShortDramaAnalysisRow) =>
        r.platform === 'wechat_channel' ? v.toLocaleString() : '-',
    },
    {
      title: '归因收益',
      dataIndex: 'attributed_revenue',
      key: 'attributed_revenue',
      width: 100,
      align: 'right' as const,
      render: (v: number) => `¥${v.toFixed(2)}`,
    },
  ], []);

  if (loading && items.length === 0) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const tabPanes = [
    { key: '', label: '汇总' },
    { key: 'wechat_channel', label: '视频号' },
    { key: 'douyin', label: '抖音' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 8 }}>
        <Title level={4} style={{ margin: 0 }}>短片分析</Title>
        <Space wrap>
          <Select
            value={platform}
            style={{ width: 130 }}
            options={PLATFORM_OPTIONS}
            onChange={(v) => { setPlatform(v); setPage(1); }}
          />
          <RangePicker
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setDateRange([dates[0], dates[1]]);
                setPage(1);
              }
            }}
            allowClear={false}
          />
          <Button onClick={() => { const start = dateRange[0].format('YYYY-MM-DD'); const end = dateRange[1].format('YYYY-MM-DD'); fetchData(platform, start, end, 1); }}>刷新</Button>
        </Space>
      </div>

      {/* KPI 卡 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="发布条数" value={summary?.published_count || 0} prefix={<PlayCircleOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="总播放" value={summary?.total_play || 0} prefix={<EyeOutlined />} suffix="次" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="平均完播率" value={summary?.avg_finish_rate || 0} precision={1} prefix={<RiseOutlined />} suffix="%" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card><Statistic title="总跳转(视频号)" value={summary?.total_jump_click || 0} prefix={<LinkOutlined />} suffix="次" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <Card><Statistic title="归因收益" value={summary?.attributed_revenue || 0} precision={2} prefix={<MoneyCollectOutlined />} suffix="元" valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
      </Row>

      <Tabs
        activeKey={platform}
        onChange={(k) => { setPlatform(k); setPage(1); }}
        items={tabPanes.map((p) => ({ key: p.key, label: p.label }))}
      />

      {/* 综合数据表 */}
      <Card size="small" title={`短视频数据表（共 ${total} 条）`} style={{ marginBottom: 16 }}>
        <Table
          rowKey="video_metric_id"
          columns={columns}
          dataSource={items}
          loading={loading}
          size="small"
          scroll={{ x: 1800 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: false,
            onChange: (p) => { setPage(p); const start = dateRange[0].format('YYYY-MM-DD'); const end = dateRange[1].format('YYYY-MM-DD'); fetchData(platform, start, end, p); },
          }}
        />
      </Card>

      {/* 右侧话题标签 TOP */}
      <Card size="small" title="话题标签 TOP 10" style={{ marginBottom: 16 }}>
        {topics.length === 0 ? (
          <Text type="secondary">暂无话题数据</Text>
        ) : (
          <Space size={[8, 8]} wrap>
            {topics.map((t, idx) => (
              <Tag key={t.tag} color={idx < 3 ? 'volcano' : 'blue'}>#{t.tag} × {t.count}</Tag>
            ))}
          </Space>
        )}
      </Card>
    </div>
  );
};

export default ShortDramaAnalysis;
