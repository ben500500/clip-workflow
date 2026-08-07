import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Table, Typography, Spin, Alert, Statistic, DatePicker,
} from 'antd';
import { TeamOutlined, FileTextOutlined, ReadOutlined, LinkOutlined } from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { EcosystemMetric } from '../types';
import { formatDate } from '../utils/format';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const Ecosystem: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<EcosystemMetric[]>([]);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(29, 'day'), dayjs(),
  ]);

  useEffect(() => {
    setLoading(true);
    const start = dateRange[0].format('YYYY-MM-DD');
    const end = dateRange[1].format('YYYY-MM-DD');
    dashboardApi.getEcosystem({ start_date: start, end_date: end })
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [dateRange]);

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const totalArticles = data.reduce((s, d) => s + d.article_count, 0);
  const totalReads = data.reduce((s, d) => s + d.article_read_count, 0);
  const totalArticleUv = data.reduce((s, d) => s + d.mini_program_uv_from_article, 0);
  const totalWecomNew = data.reduce((s, d) => s + d.wecom_new_friends, 0);
  const totalWecomTotal = data.length > 0 ? data[data.length - 1].wecom_total_friends : 0;

  const columns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 110, render: (d: string) => formatDate(d) },
    { title: '发文数', dataIndex: 'article_count', key: 'article_count', width: 90 },
    { title: '阅读数', dataIndex: 'article_read_count', key: 'article_read_count', width: 100 },
    { title: '公众号导流UV', dataIndex: 'mini_program_uv_from_article', key: 'mini_program_uv_from_article', width: 130 },
    { title: '企微新增好友', dataIndex: 'wecom_new_friends', key: 'wecom_new_friends', width: 120 },
    { title: '企微总好友', dataIndex: 'wecom_total_friends', key: 'wecom_total_friends', width: 110 },
    { title: '企微来源', dataIndex: 'wecom_source', key: 'wecom_source', width: 100, render: (v: string) => v || '-' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>生态联动</Title>
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
          <Card><Statistic title="发文总数" value={totalArticles} prefix={<FileTextOutlined />} suffix="篇" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="总阅读数" value={totalReads} prefix={<ReadOutlined />} suffix="次" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="公众号导流 UV" value={totalArticleUv} prefix={<LinkOutlined />} suffix="人" valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="企微新增好友" value={totalWecomNew} prefix={<TeamOutlined />} suffix="人" valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
      </Row>

      <Card size="small" title="生态数据明细">
        {data.length === 0 ? (
          <Typography.Text type="secondary">暂无数据，请先导入生态数据</Typography.Text>
        ) : (
          <Table rowKey="id" size="small" columns={columns} dataSource={data} pagination={{ pageSize: 15 }} scroll={{ x: 760 }} />
        )}
      </Card>
    </div>
  );
};

export default Ecosystem;