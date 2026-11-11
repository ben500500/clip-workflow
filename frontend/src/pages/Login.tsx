import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, Space } from 'antd';
import { UserOutlined, LockOutlined, VideoCameraOutlined } from '@ant-design/icons';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const { Title, Text } = Typography;

// 2026-11-11 评审（三席同报 P0）：登录落位按角色——素材/运营直达素材库，别落切片仪表盘。
// ⚠️ 顶部「已登录自动跳转」的 <Navigate> 也必须走同一helper：login() 里 setUser 会立刻
// 触发重渲染，抢先跳 /dashboard，把 handleSubmit 里的角色落位整个吃掉（R2 实测就栽在这）。
const landingFor = (role?: string): string =>
  role === 'material' || role === 'operator' ? '/assets' : '/dashboard';

const Login: React.FC = () => {
  const { login, user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  // 如果已登录则自动跳转（同角色落位，见 landingFor 注释）
  if (!authLoading && user) {
    return <Navigate to={landingFor(user.role)} replace />;
  }

  const handleSubmit = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const u = await login(values.username, values.password);
      message.success('登录成功');
      // 2026-11-11 评审（三席同报 P0）：全员落仪表盘——素材/运营看到的全是切片指标，
      // 没人知道自己该去哪。按角色落位：素材/运营直达素材库，管理员留仪表盘。
      navigate(landingFor((u as { role?: string } | null | undefined)?.role), { replace: true });
    } catch (err) {
      const msg = err instanceof Error ? err.message : '登录失败，请检查用户名和密码';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        padding: 24,
      }}
    >
      <Card
        style={{
          width: 400,
          maxWidth: '100%',
          borderRadius: 12,
          boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
        }}
        styles={{ body: { padding: '40px 32px' } }}
      >
        <Space
          direction="vertical"
          size="large"
          style={{ width: '100%', textAlign: 'center' }}
        >
          <div>
            <VideoCameraOutlined
              style={{ fontSize: 48, color: '#1677ff', marginBottom: 16 }}
            />
            <Title level={3} style={{ margin: 0 }}>
              Clip Workflow
            </Title>
            <Text type="secondary">请登录以继续使用系统</Text>
          </div>

          <Form
            name="login"
            onFinish={handleSubmit}
            layout="vertical"
            size="large"
            style={{ textAlign: 'left' }}
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder="用户名"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                style={{ height: 44, fontSize: 16 }}
              >
                登 录
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </div>
  );
};

export default Login;