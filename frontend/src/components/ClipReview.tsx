import React, { useEffect, useState } from 'react';
import {
  Table,
  Button,
  Tag,
  Space,
  Slider,
  Card,
  Row,
  Col,
  Statistic,
  Popconfirm,
  message,
  Typography,
  InputNumber,
  Tooltip,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  PauseCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { ClipCandidate } from '../types';
import { formatDuration, formatTimeRange, getStatusColor, getStatusLabel, formatConfidence } from '../utils/format';

const { Text } = Typography;

interface ClipReviewProps {
  candidates: ClipCandidate[];
  loading?: boolean;
  onBatchUpdate?: (data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) => Promise<void>;
  onUpdate?: (id: number, data: Partial<ClipCandidate>) => Promise<void>;
}

const ClipReview: React.FC<ClipReviewProps> = ({
  candidates,
  loading = false,
  onBatchUpdate,
  onUpdate,
}) => {
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [adjustStart, setAdjustStart] = useState<number>(0);
  const [adjustEnd, setAdjustEnd] = useState<number>(0);

  useEffect(() => {
    if (candidates.length > 0) {
      const first = candidates[0];
      setAdjustStart(first.adjusted_start ?? first.start_time);
      setAdjustEnd(first.adjusted_end ?? first.end_time);
    }
  }, [candidates]);

  const handleBatchApprove = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的选点');
      return;
    }
    try {
      await onBatchUpdate?.({ ids: selectedRowKeys as number[], status: 'approved' });
      message.success(`已通过 ${selectedRowKeys.length} 个选点`);
      setSelectedRowKeys([]);
    } catch (err) {
      message.error('批量操作失败');
    }
  };

  const handleBatchReject = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的选点');
      return;
    }
    try {
      await onBatchUpdate?.({ ids: selectedRowKeys as number[], status: 'rejected' });
      message.success(`已拒绝 ${selectedRowKeys.length} 个选点`);
      setSelectedRowKeys([]);
    } catch (err) {
      message.error('批量操作失败');
    }
  };

  const handleStartEdit = (record: ClipCandidate) => {
    setEditingId(record.id);
    setAdjustStart(record.adjusted_start ?? record.start_time);
    setAdjustEnd(record.adjusted_end ?? record.end_time);
  };

  const handleSaveAdjust = async (id: number) => {
    try {
      await onUpdate?.(id, {
        adjusted_start: adjustStart,
        adjusted_end: adjustEnd,
        status: 'adjusted',
      });
      message.success('调整已保存');
      setEditingId(null);
    } catch (err) {
      message.error('保存失败');
    }
  };

  const handleTimeAdjust = (record: ClipCandidate) => {
    setEditingId(record.id);
    setAdjustStart(record.adjusted_start ?? record.start_time);
    setAdjustEnd(record.adjusted_end ?? record.end_time);
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
      dataIndex: 'clip_type',
      key: 'clip_type',
      width: 100,
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: '时间范围',
      key: 'time_range',
      width: 200,
      render: (_: unknown, record: ClipCandidate) => {
        const start = record.adjusted_start ?? record.start_time;
        const end = record.adjusted_end ?? record.end_time;
        return (
          <Text code>
            {formatTimeRange(start, end)}
          </Text>
        );
      },
    },
    {
      title: '时长',
      key: 'duration',
      width: 80,
      render: (_: unknown, record: ClipCandidate) => {
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
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => text || '-',
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
      width: 200,
      render: (_: unknown, record: ClipCandidate) => (
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
          <Tooltip title="时间调整">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleTimeAdjust(record)}
            >
              调整
            </Button>
          </Tooltip>
        </Space>
      ),
    },
  ];

  // 统计
  const totalCount = candidates.length;
  const approvedCount = candidates.filter((c) => c.status === 'approved').length;
  const rejectedCount = candidates.filter((c) => c.status === 'rejected').length;
  const pendingCount = candidates.filter((c) => c.status === 'pending').length;

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

      {/* 时间调整面板 */}
      {editingId !== null && (
        <Card
          size="small"
          title={
            <Space>
              <EditOutlined />
              <span>时间调整</span>
            </Space>
          }
          style={{ marginBottom: 16 }}
          extra={
            <Space>
              <Button size="small" onClick={() => setEditingId(null)}>
                取消
              </Button>
              <Button
                type="primary"
                size="small"
                onClick={() => handleSaveAdjust(editingId)}
              >
                保存调整
              </Button>
            </Space>
          }
        >
          <Row gutter={24} align="middle">
            <Col span={10}>
              <div>
                <Text type="secondary">开始时间（秒）</Text>
                <InputNumber
                  min={0}
                  max={adjustEnd - 1}
                  value={adjustStart}
                  onChange={(val) => setAdjustStart(val ?? 0)}
                  style={{ width: '100%' }}
                  addonAfter={formatDuration(adjustStart)}
                />
              </div>
            </Col>
            <Col span={10}>
              <div>
                <Text type="secondary">结束时间（秒）</Text>
                <InputNumber
                  min={adjustStart + 1}
                  value={adjustEnd}
                  onChange={(val) => setAdjustEnd(val ?? 0)}
                  style={{ width: '100%' }}
                  addonAfter={formatDuration(adjustEnd)}
                />
              </div>
            </Col>
            <Col span={4}>
              <div>
                <Text type="secondary">时长</Text>
                <div>
                  <Text strong>{formatDuration(adjustEnd - adjustStart)}</Text>
                </div>
              </div>
            </Col>
          </Row>
          <div style={{ marginTop: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <Text type="secondary">{formatDuration(adjustStart)}</Text>
              <Text type="secondary">{formatDuration(adjustEnd)}</Text>
            </div>
            <Slider
              range
              min={0}
              max={Math.max(adjustEnd + 100, 3600)}
              value={[adjustStart, adjustEnd]}
              onChange={([s, e]) => {
                setAdjustStart(s);
                setAdjustEnd(e);
              }}
              tooltip={{ formatter: (val) => formatDuration(val ?? 0) }}
            />
          </div>
        </Card>
      )}

      {/* 批量操作栏 */}
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
            const pending = candidates.filter((c) => c.status === 'pending');
            if (pending.length === 0) {
              message.info('没有待处理的选点');
              return;
            }
            onBatchUpdate?.({
              ids: pending.map((c) => c.id),
              status: 'approved',
            });
            message.success(`已一键通过 ${pending.length} 个选点`);
          }}
        >
          一键通过全部
        </Button>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={candidates}
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
          showTotal: (total) => `共 ${total} 个选点`,
        }}
        scroll={{ x: 1000 }}
      />
    </div>
  );
};

export default ClipReview;