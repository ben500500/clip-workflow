import React, { useState, useEffect } from 'react';
import { Layout, Menu, Avatar, Dropdown, theme, Modal } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import {
  DashboardOutlined,
  ProjectOutlined,
  SettingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  SendOutlined,
  BarChartOutlined,
  LogoutOutlined,
  UserSwitchOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';

const { Header, Sider, Content } = Layout;

const menuItems = [
  {
    key: '/dashboard',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: '/projects',
    icon: <ProjectOutlined />,
    label: '项目管理',
  },
  {
    key: '/publish',
    icon: <SendOutlined />,
    label: '发布管理',
  },
  {
    key: 'analytics-sub',
    icon: <BarChartOutlined />,
    label: '数据看板',
    children: [
      { key: '/analytics/overview', label: '总览' },
      { key: '/analytics/content', label: '内容分析' },
      { key: '/analytics/monetization', label: '短剧变现' },
      { key: '/analytics/funnel', label: '转化漏斗' },
      { key: '/analytics/ecosystem', label: '生态联动' },
      { key: '/analytics/import', label: '数据录入' },
      { key: '/analytics/settings', label: '看板设置' },
    ],
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: '系统设置',
  },
];

const AppLayout: React.FC = () => {
  const [collapsed, setCollapsed] = React.useState(false);
  const [openKeys, setOpenKeys] = React.useState<string[]>([]);
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();

  // 计算当前选中的菜单项，支持嵌套路由祖先匹配
  const getSelectedKey = (pathname: string): string => {
    if (pathname.startsWith('/analytics/')) return pathname;
    if (pathname.startsWith('/projects/')) return '/projects';
    if (pathname.startsWith('/episodes/')) return '/projects';
    return pathname;
  };
  const selectedKey = getSelectedKey(location.pathname) || '/dashboard';

  // 自动展开包含当前路由的子菜单
  useEffect(() => {
    if (location.pathname.startsWith('/analytics')) {
      setOpenKeys((prev) => (prev.includes('analytics-sub') ? prev : [...prev, 'analytics-sub']));
    }
  }, [location.pathname]);

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
  };

  const userMenuItems = [
    { key: 'profile', label: '个人中心', icon: <UserSwitchOutlined /> },
    { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, danger: true },
  ];

  const handleUserMenuClick = ({ key }: { key: string }) => {
    if (key === 'profile') {
      Modal.info({
        title: '个人中心',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>管理员账户</p>
            <p>暂未开放个人设置功能</p>
          </div>
        ),
        okText: '确定',
      });
    } else if (key === 'logout') {
      Modal.confirm({
        title: '确认退出',
        icon: <ExclamationCircleOutlined />,
        content: '确定要退出登录吗？',
        okText: '退出',
        cancelText: '取消',
        onOk() {
          // TODO: 清除登录状态后跳转
          navigate('/dashboard');
          window.location.reload();
        },
      });
    }
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        style={{
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          background: token.colorBgContainer,
          borderRight: `1px solid ${token.colorBorderSecondary}`,
        }}
        width={220}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            cursor: 'pointer',
          }}
          onClick={() => navigate('/dashboard')}
        >
          <VideoCameraOutlined style={{ fontSize: 28, color: token.colorPrimary }} />
          {!collapsed && (
            <span
              style={{
                marginLeft: 10,
                fontSize: 18,
                fontWeight: 600,
                color: token.colorText,
              }}
            >
              Clip Workflow
            </span>
          )}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={collapsed ? [] : openKeys}
          onOpenChange={setOpenKeys}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ borderRight: 'none', marginTop: 4 }}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 220, transition: 'margin-left 0.2s' }}>
        <Header
          style={{
            padding: '0 24px',
            background: token.colorBgContainer,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            height: 64,
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <div
            style={{ fontSize: 18, cursor: 'pointer', color: token.colorText }}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
          <Dropdown menu={{ items: userMenuItems, onClick: handleUserMenuClick }}>
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span style={{ color: token.colorTextSecondary }}>管理员</span>
            </div>
          </Dropdown>
        </Header>
        <Content
          style={{
            margin: 24,
            minHeight: 280,
            background: token.colorBgLayout,
            borderRadius: token.borderRadius,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
};

export default AppLayout;