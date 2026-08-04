import React, { useEffect, useRef, useState } from 'react';
import { Card, Progress, Tag, Timeline, Typography, Space, Alert, Button, Steps } from 'antd';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
  ClockCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import type { SliceTask, TaskProgressEvent } from '../types';
import { formatDateTime, getStatusColor, getStatusLabel } from '../utils/format';

const { Text } = Typography;

interface TaskProgressProps {
  task: SliceTask | null;
  visible: boolean;
  events?: TaskProgressEvent[];
  onCancel?: () => void;
  onRetry?: () => void;
}

const TaskProgress: React.FC<TaskProgressProps> = ({
  task,
  visible,
  events = [],
  onCancel,
  onRetry,
}) => {
  if (!visible || !task) return null;

  const isRunning = task.status === 'running';
  const isPending = task.status === 'pending';
  const isCompleted = task.status === 'completed';
  const isFailed = task.status === 'failed';
  const progress = task.progress || 0;

  const currentStep = isPending
    ? 0
    : isRunning
      ? 1
      : isCompleted
        ? 2
        : isFailed
          ? 2
          : 0;

  const stepItems = [
    {
      title: '等待中',
      description: '任务已加入队列',
      status: (isPending && !isRunning) ? 'process' as const : (currentStep > 0 ? 'finish' as const : 'wait' as const),
      icon: currentStep === 0 && isPending ? <LoadingOutlined /> : <ClockCircleOutlined />,
    },
    {
      title: '处理中',
      description: '正在执行切片任务',
      status: isRunning ? 'process' as const : (currentStep > 1 ? 'finish' as const : 'wait' as const),
      icon: isRunning ? <LoadingOutlined /> : (currentStep > 1 ? <CheckCircleFilled /> : <ClockCircleOutlined />),
    },
    {
      title: isCompleted ? '已完成' : '已完成',
      description: isCompleted ? '切片任务执行完毕' : (isFailed ? '任务执行失败' : ''),
      status: isCompleted ? 'finish' as const : (isFailed ? 'error' as const : 'wait' as const),
      icon: isCompleted ? <CheckCircleFilled /> : (isFailed ? <CloseCircleFilled /> : <ClockCircleOutlined />),
    },
  ];

  return (
    <Card
      title={
        <Space>
          <span>切片任务 #{task.id}</span>
          <Tag color={getStatusColor(task.status)}>
            {getStatusLabel(task.status)}
          </Tag>
        </Space>
      }
      size="small"
      style={{ marginBottom: 16 }}
      extra={
        <Space>
          {isRunning && onCancel && (
            <Button size="small" danger onClick={onCancel}>
              取消任务
            </Button>
          )}
          {isFailed && onRetry && (
            <Button size="small" type="primary" onClick={onRetry}>
              重试失败项
            </Button>
          )}
        </Space>
      }
    >
      {/* 进度条 */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <Text strong>总体进度</Text>
          <Text type="secondary">{progress}%</Text>
        </div>
        <Progress
          percent={progress}
          status={isFailed ? 'exception' : isRunning ? 'active' : 'success'}
          strokeColor={isCompleted ? '#52c41a' : undefined}
        />
      </div>

      {/* 详细统计 */}
      <div style={{ display: 'flex', gap: 32, marginBottom: 20 }}>
        <div>
          <Text type="secondary">总剪辑数</Text>
          <div><Text strong>{task.total_clips || 0}</Text></div>
        </div>
        <div>
          <Text type="secondary" style={{ color: '#1677ff' }}>已完成</Text>
          <div><Text strong style={{ color: '#1677ff' }}>{task.completed_clips || 0}</Text></div>
        </div>
        <div>
          <Text type="secondary" style={{ color: '#ff4d4f' }}>失败</Text>
          <div><Text strong style={{ color: '#ff4d4f' }}>{task.failed_clips || 0}</Text></div>
        </div>
      </div>

      {/* 步骤 */}
      <Steps
        current={currentStep}
        items={stepItems}
        style={{ marginBottom: 16 }}
        size="small"
      />

      {/* 错误信息 */}
      {isFailed && task.error_message && (
        <Alert
          type="error"
          message="错误信息"
          description={task.error_message}
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 事件时间线 */}
      {events.length > 0 && (
        <div>
          <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
            实时事件
          </Text>
          <Timeline
            items={events.slice(-10).reverse().map((event) => ({
              color: event.status === 'completed' ? 'green' : event.status === 'failed' ? 'red' : 'blue',
              children: (
                <div>
                  <Text>{event.message}</Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {formatDateTime(event.timestamp)}
                  </Text>
                </div>
              ),
            }))}
          />
        </div>
      )}

      {/* 时间信息 */}
      <div style={{ marginTop: 12, display: 'flex', gap: 24 }}>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>创建时间</Text>
          <br />
          <Text style={{ fontSize: 12 }}>{formatDateTime(task.created_at)}</Text>
        </div>
        {task.started_at && (
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>开始时间</Text>
            <br />
            <Text style={{ fontSize: 12 }}>{formatDateTime(task.started_at)}</Text>
          </div>
        )}
        {task.completed_at && (
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>完成时间</Text>
            <br />
            <Text style={{ fontSize: 12 }}>{formatDateTime(task.completed_at)}</Text>
          </div>
        )}
      </div>
    </Card>
  );
};

export default TaskProgress;