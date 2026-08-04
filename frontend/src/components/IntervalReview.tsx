import React, { useState } from 'react';
import {
  Table,
  Button,
  Tag,
  Space,
  Card,
  Row,
  Col,
  Statistic,
  message,
  Typography,
  Tooltip,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { DetectedInterval } from '../types';
import { formatDuration, formatTimeRange, getStatusColor, getStatusLabel, formatConfidence } from '../utils/format';

const { Text } = Typography;

interface IntervalReviewProps {
  intervals: DetectedInterval[];
  loading?: boolean;
  onBatchUpdate?: (data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) => Promise<void>;
  onUpdate?: (id: number, data: Partial<DetectedInterval>) => Promise<void>;
}

const IntervalReview: React.FC<IntervalReviewProps> = ({
  intervals,
  loading = false,
  onBatchUpdate,
  onUpdate,
}) => {
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  const handleBatchApprove = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的区间');
      return;
    }
    try {
      await onBatchUpdate?.({ ids: selectedRowKeys as number[], status: 'approved' });
      message.success(`已通过 ${selectedRowKeys.length} 个区间`);
      setSelectedRowKeys([]);
    } catch {
      message.error('批量操作失败');
    }
  };

  const handleBatchReject = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的区间');
      return;
    }
    try {
      await onBatchUpdate?.({ ids: selectedRowKeys as number[], status: 'rejected' });
      message.success(`已拒绝 ${selectedRowKeys.length} 个区间`);
      setSelectedRowKeys([]);
    } catch {
      message.error('批量操作失败');
    }
  };

  const columns = [
    {
      title: '序号',
      key: 'index',
      width: 60,
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      title: '标签',
      dataIndex: 'label',
      key: 'label',
      width: 120,
      ellipsis: true,
      render: (label: string) => <Text strong>{label}</Text>,
    },
    {
      title: '类型',
      dataIndex: 'interval_type',
      key: 'interval_type',
      width: 100,
      render: (type: string) => <Tag color="purple">{type}</Tag>,
    },
    {
      title: '时间范围',
      key: 'time_range',
      width: 200,
      render: (_: unknown, record: DetectedInterval) => {
        const start = record.adjusted_start ?? record.start_time;
        const end = record.adjusted_end ?? record.end_time;
        return <Text code>{formatTimeRange(start, end)}</Text>;
      },
    },
    {
      title: '时长',
      key: 'duration',
      width: 80,
      render: (_: unknown, record: DetectedInterval) => {
        const start = record.adjusted_start ?? record.start_time;
        const end = record.adjusted_end ?? record.end_time;
        return formatDuration(end - start);
      },
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      key: 'confidence',
      width: 100,
      render: (val: number) => (
        <Tag color={val >= 0.8 ? 'green' : val >= 0.5 ? 'orange' : 'red'}>
          {formatConfidence(val)}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: unknown, record: DetectedInterval) => (
        <Space size="small">
          {record.status === 'pending' && (
            <>
              <Tooltip title="通过">
                <Button
                  type="link"
                  size="small"
                  icon={<CheckCircleOutlined />}
                  onClick={() => onUpdate?.(record.id, { status: 'approved' })}
                >
                  通过
                </Button>
              </Tooltip>
              <Tooltip title="拒绝">
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<CloseCircleOutlined />}
                  onClick={() => onUpdate?.(record.id, { status: 'rejected' })}
                >
                  拒绝
                </Button>
              </Tooltip>
            </>
          )}
        </Space>
      ),
    },
  ];

  const totalCount = intervals.length;
  const approvedCount = intervals.filter((i) => i.status === 'approved').length;
  const rejectedCount = intervals.filter((i) => i.status === 'rejected').length;
  const pendingCount = intervals.filter((i) => i.status === 'pending').length;

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总计" value={totalCount} suffix="个" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="待审核"
              value={pendingCount}
              valueStyle={{ color: '#faad14' }}
              suffix="个"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已通过"
              value={approvedCount}
              valueStyle={{ color: '#52c41a' }}
              suffix="个"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已拒绝"
              value={rejectedCount}
              valueStyle={{ color: '#ff4d4f' }}
              suffix="个"
            />
          </Card>
        </Col>
      </Row>

      <div
        style={{
          marginBottom: 12,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Space>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={handleBatchApprove}
          >
            批量通过
          </Button>
          <Button
            danger
            icon={<CloseCircleOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={handleBatchReject}
          >
            批量拒绝
          </Button>
          {selectedRowKeys.length > 0 && (
            <Text type="secondary">已选择 {selectedRowKeys.length} 项</Text>
          )}
        </Space>
        <Button
          icon={<ThunderboltOutlined />}
          onClick={() => {
            const pending = intervals.filter((i) => i.status === 'pending');
            if (pending.length === 0) {
              message.info('没有待处理的区间');
              return;
            }
            onBatchUpdate?.({ ids: pending.map((i) => i.id), status: 'approved' });
            message.success(`已一键通过 ${pending.length} 个区间`);
          }}
        >
          一键通过全部
        </Button>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={intervals}
        loading={loading}
        size="middle"
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
          getCheckboxProps: (record) => ({
            disabled: record.status !== 'pending',
          }),
        }}
        pagination={{
          pageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个区间`,
        }}
        scroll={{ x: 900 }}
      />
    </div>
  );
};

export default IntervalReview;