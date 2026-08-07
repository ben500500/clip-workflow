import React, { useEffect, useState } from 'react';
import {
  Card, Table, Typography, Spin, Alert, Space, Row, Col, Button, message,
  Statistic, Divider, InputNumber, Modal,
} from 'antd';
import {
  ClearOutlined, CloudServerOutlined, DatabaseOutlined, FolderOpenOutlined,
} from '@ant-design/icons';
import { maintenanceApi } from '../api/monitor';

const { Title, Text } = Typography;

const Maintenance: React.FC = () => {
  const [status, setStatus] = useState<{ archive_days: number; minio_lifecycle_days: number; temp_cleanup_hours: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [archiveDays, setArchiveDays] = useState<number | null>(null);
  const [cleanupHours, setCleanupHours] = useState<number | null>(null);
  const [archiveResult, setArchiveResult] = useState<any>(null);
  const [cleanupResult, setCleanupResult] = useState<any>(null);
  const [lifecycleResult, setLifecycleResult] = useState<any>(null);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const s = await maintenanceApi.getStatus();
      setStatus(s);
      setArchiveDays(s.archive_days);
      setCleanupHours(s.temp_cleanup_hours);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleArchive = async () => {
    Modal.confirm({
      title: '确认归档',
      content: `将删除超过 ${archiveDays ?? status?.archive_days ?? 90} 天的看板数据（video_metrics 等），确定继续？`,
      okText: '执行归档',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        try {
          const res = await maintenanceApi.runArchive(archiveDays ?? undefined);
          setArchiveResult(res);
          message.success('归档完成');
        } catch (err: unknown) {
          message.error(err instanceof Error ? err.message : '归档失败');
        }
      },
    });
  };

  const handleCleanup = async () => {
    try {
      const res = await maintenanceApi.runCleanup(cleanupHours ?? 24);
      setCleanupResult(res);
      message.success(`清理完成，共 ${res.cleaned} 个文件，释放 ${res.freed_mb} MB`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '清理失败');
    }
  };

  const handleLifecycle = async () => {
    Modal.confirm({
      title: '确认设置生命周期',
      content: `将为 MinIO 各 bucket 设置未访问超过 ${status?.minio_lifecycle_days ?? 90} 天的对象转低频存储策略，确定继续？`,
      okText: '应用',
      cancelText: '取消',
      async onOk() {
        try {
          const res = await maintenanceApi.runMinioLifecycle();
          setLifecycleResult(res);
          message.success('生命周期策略已应用');
        } catch (err: unknown) {
          message.error(err instanceof Error ? err.message : '设置失败');
        }
      },
    });
  };

  const archiveDeletedRows = archiveResult?.deleted
    ? Object.entries(archiveResult.deleted).map(([table, count]) => ({ table, count }))
    : [];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>运维与性能优化</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        数据归档 · 临时文件清理 · MinIO 存储生命周期（三期）
      </Text>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="数据归档天数" value={status?.archive_days ?? 90} suffix="天" />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="MinIO 生命周期" value={status?.minio_lifecycle_days ?? 90} suffix="天" />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="临时文件保留" value={status?.temp_cleanup_hours ?? 24} suffix="小时" />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card
            size="small"
            title={<Space><DatabaseOutlined /> 数据归档</Space>}
            extra={<Button type="link" size="small" loading={loading} onClick={handleArchive}>执行</Button>}
          >
            <Text type="secondary">归档超过指定天数的看板数据（video_metrics / ad_metrics / 漏斗快照等），保持主表轻量，提升查询性能。</Text>
            <Divider style={{ margin: '12px 0' }} />
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                <Text>归档阈值（天）</Text>
                <InputNumber value={archiveDays} onChange={setArchiveDays} min={1} max={3650} style={{ width: 120 }} />
              </Space>
              {archiveResult && (
                <Alert
                  type="info"
                  showIcon
                  message={`归档完成，截止 ${archiveResult.cutoff}`}
                  description={
                    <Table
                      rowKey="table"
                      size="small"
                      pagination={false}
                      dataSource={archiveDeletedRows}
                      scroll={{ x: 260 }}
                      columns={[
                        { title: '表', dataIndex: 'table' },
                        { title: '删除行数', dataIndex: 'count' },
                      ]}
                    />
                  }
                />
              )}
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card
            size="small"
            title={<Space><FolderOpenOutlined /> 临时文件清理</Space>}
            extra={<Button type="link" size="small" loading={loading} onClick={handleCleanup}>执行</Button>}
          >
            <Text type="secondary">清理任务完成后遗留的本地临时文件（切片输出、下载的源视频、上传缓存）。</Text>
            <Divider style={{ margin: '12px 0' }} />
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                <Text>保留时长（小时）</Text>
                <InputNumber value={cleanupHours} onChange={setCleanupHours} min={1} max={720} style={{ width: 120 }} />
              </Space>
              {cleanupResult && (
                <Alert
                  type="success"
                  showIcon
                  message={`清理完成：${cleanupResult.cleaned} 个文件，释放 ${cleanupResult.freed_mb} MB`}
                />
              )}
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card
            size="small"
            title={<Space><CloudServerOutlined /> MinIO 生命周期</Space>}
            extra={<Button type="link" size="small" loading={loading} onClick={handleLifecycle}>应用</Button>}
          >
            <Text type="secondary">为 MinIO 各 bucket 设置生命周期策略：未访问超过 {status?.minio_lifecycle_days ?? 90} 天的对象自动转低频存储，降低存储成本。</Text>
            <Divider style={{ margin: '12px 0' }} />
            {lifecycleResult && (
              <Alert
                type="success"
                showIcon
                message="生命周期策略已应用"
                description={`生效 bucket：${lifecycleResult.buckets?.join(', ') || '无'}`}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Maintenance;
