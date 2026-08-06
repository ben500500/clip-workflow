import React from 'react';
import { Tooltip, Typography } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface ErrorHintProps {
  /** 完整错误信息（可多行） */
  error: string;
  /** 悬停提示的标题，默认展示完整内容 */
  title?: React.ReactNode;
  /** 感叹号颜色，默认红色 */
  color?: string;
}

/**
 * 错误信息提示：紧凑展示一个红色感叹号，鼠标悬停后显示完整错误内容。
 * 用于“运行出错时列出关键错误信息，但不占用页面空间”的场景。
 */
const ErrorHint: React.FC<ErrorHintProps> = ({ error, title, color = '#ff4d4f' }) => {
  if (!error) return null;
  return (
    <Tooltip
      title={
        <div style={{ maxWidth: 420, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {title ?? error}
        </div>
      }
      overlayStyle={{ maxWidth: 480 }}
    >
      <Text style={{ color, fontSize: 14, cursor: 'help', lineHeight: 1 }}>
        <ExclamationCircleOutlined style={{ marginRight: 4 }} />
        <Text type="danger" style={{ fontSize: 12 }}>运行出错</Text>
      </Text>
    </Tooltip>
  );
};

export default ErrorHint;
