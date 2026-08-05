import React from 'react';
import {
  Card, Descriptions, Tag, Typography, Space, Avatar, Divider,
} from 'antd';
import { UserOutlined, VideoCameraOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import { ROLE_OPTIONS } from '../types';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;

const Profile: React.FC = () => {
  const { user } = useAuth();

  if (!user) {
    return null;
  }

  const roleLabel = ROLE_OPTIONS.find((r) => r.value === user.role)?.label || user.role;

  return (
    <div style={{ maxWidth: 800 }}>
      <Title level={4} style={{ marginBottom: 16 }}>个人中心</Title>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%', textAlign: 'center', padding: '24px 0' }}>
          <Avatar size={72} icon={<UserOutlined />} style={{ backgroundColor: '#1677ff' }} />
          <Space direction="vertical" size={0} style={{ textAlign: 'center' }}>
            <Title level={4} style={{ margin: 0 }}>{user.display_name || user.username}</Title>
            <Text type="secondary">{user.username}</Text>
          </Space>
          <Tag color={user.role === 'admin' ? 'red' : 'blue'} style={{ fontSize: 14, padding: '2px 12px' }}>
            {roleLabel}
          </Tag>
        </Space>
      </Card>

      <Card size="small" title="账号信息">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="用户 ID">
            <Text copyable style={{ fontSize: 12 }}>{user.id}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="用户名">{user.username}</Descriptions.Item>
          <Descriptions.Item label="显示名称">{user.display_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={user.role === 'admin' ? 'red' : 'blue'}>{roleLabel}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            {user.is_active ? (
              <Tag color="green">启用</Tag>
            ) : (
              <Tag color="red">禁用</Tag>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{user.created_at ? formatDateTime(user.created_at) : '-'}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{user.updated_at ? formatDateTime(user.updated_at) : '-'}</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
};

export default Profile;