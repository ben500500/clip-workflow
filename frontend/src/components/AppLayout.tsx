import React, { useState, useEffect, useMemo } from 'react';
import { Layout, Menu, Avatar, Dropdown, theme, Modal, Tag } from 'antd';
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
import { useAuth } from '../contexts/AuthContext';
import type { MenuProps } from 'antd';

const { Header, Sider, Content } = Layout;

const allMenuItems = [
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
    key: '/profile',
    icon: <UserOutlined />,
    label: '个人中心',
  },
  {
    key: '/user-management',
    icon: <UserSwitchOutlined />,
    label: '用户管理',
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: '系统设置',
  },
];

// 角色显示名称映射
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  operator: '运营人员',
  publisher: '发布人员',
  material: '素材人员',
};

const AppLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();
  const { user, logout, hasPermission } = useAuth();

  // 根据用户角色动态过滤菜单项
  const filteredMenuItems = useMemo(() => {
    return allMenuItems
      .map((item) => {
        // 如果用户没有访问该菜单的权限，则移除
        if (!hasPermission(item.key)) return null;

        // 处理子菜单
        if (item.children) {
          const filteredChildren = item.children.filter((child) => hasPermission(child.key));
          if (filteredChildren.length === 0) return null;
          return { ...item, children: filteredChildren };
        }

        return item;
      })
      .filter(Boolean) as MenuProps['items'];
  }, [hasPermission]);

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

  // 当前菜单可见时自动展开子菜单
  useEffect(() => {
    if (filteredMenuItems) {
      const hasAnalytics = filteredMenuItems.some(
        (item) => item && 'key' in item && item.key === 'analytics-sub'
      );
      if (!hasAnalytics) {
        setOpenKeys((prev) => prev.filter((k) => k !== 'analytics-sub'));
      }
    }
  }, [filteredMenuItems]);

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
  };

  const handleUserMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'profile') {
      navigate('/profile');
    } else if (key === 'logout') {
      Modal.confirm({
        title: '确认退出',
        icon: <LogoutOutlined />,
        content: '确定要退出登录吗？',
        okText: '退出',
        cancelText: '取消',
        onOk() {
          logout();
          navigate('/login');
        },
      });
    }
  };

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'profile',
      label: '个人中心',
      icon: <UserSwitchOutlined />,
    },
    { type: 'divider' },
    {
      key: 'logout',
      label: '退出登录',
      icon: <LogoutOutlined />,
      danger: true,
    },
  ];

  const displayName = user?.username || '用户';
  const displayRole = user?.role ? ROLE_LABELS[user.role] || user.role : '';

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
          items={filteredMenuItems}
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
              <span style={{ color: token.colorTextSecondary }}>
                {displayName}
                {displayRole ? ` (${displayRole})` : ''}
              </span>
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