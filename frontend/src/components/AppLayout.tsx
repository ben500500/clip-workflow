import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Layout, Menu, Avatar, Dropdown, theme, Modal, Tag, Badge, Spin, Switch, List, message, Button, Typography, Space } from 'antd';
import {
  ApiOutlined,
  DashboardOutlined,
  ProjectOutlined,
  SettingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  SendOutlined,
  PlayCircleOutlined,
  BarChartOutlined,
  LogoutOutlined,
  UserSwitchOutlined,
  VideoCameraOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PoweroffOutlined,
  ClearOutlined,
  WarningOutlined,
  CloudDownloadOutlined,
  ContactsOutlined,
  ThunderboltOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { sliceApi } from '../api/slice';
import type { MenuProps } from 'antd';
import type { WorkerNode } from '../types';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const allMenuItems = [
  {
    key: '/dashboard',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: '/projects',
    icon: <ProjectOutlined />,
    label: '短剧切片',
  },
  {
    key: '/batch-slice',
    icon: <PlayCircleOutlined />,
    label: '批量切片',
  },
  {
    key: '/watermark',
    icon: <ClearOutlined />,
    label: '短片制作',
  },
  {
    key: '/resource-download',
    icon: <CloudDownloadOutlined />,
    label: '资源下载',
  },
  {
    key: '/publish',
    icon: <SendOutlined />,
    label: '发布管理',
  },
  {
    key: '/variant-matrix',
    icon: <ThunderboltOutlined />,
    label: '变体矩阵',
  },
  {
    key: '/channel-accounts',
    icon: <ContactsOutlined />,
    label: '视频号列表',
  },
  {
    key: '/dramas',
    icon: <FolderOpenOutlined />,
    label: '剧目库',
  },
  {
    key: '/workers',
    icon: <ApiOutlined />,
    label: 'Worker 节点',
  },
  {
    key: '/monitor',
    icon: <WarningOutlined />,
    label: '监控告警',
  },
  {
    key: '/maintenance',
    icon: <ClearOutlined />,
    label: '运维优化',
  },
  {
    key: 'analytics-sub',
    icon: <BarChartOutlined />,
    label: '数据看板',
    children: [
      { key: '/analytics/overview', label: '总览' },
      { key: '/analytics/shortdrama', label: '短片分析' },
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

// ─── Header 中的 Worker 节点状态图标组件 ───────────────────
const WorkerStatusIcon: React.FC = () => {
  const [workers, setWorkers] = useState<WorkerNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const { token } = theme.useToken();

  const fetchWorkers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await sliceApi.listWorkers();
      setWorkers(data);
    } catch {
      // 静默失败
    } finally {
      setLoading(false);
    }
  }, []);

  // 挂载后立即拉取一次节点状态，无需点击才显示；
  // 并定时轮询保持图标角标/颜色实时更新
  useEffect(() => {
    fetchWorkers();
    const timer = window.setInterval(fetchWorkers, 15000);
    return () => window.clearInterval(timer);
  }, [fetchWorkers]);

  const toggleWorker = async (node: WorkerNode, enabled: boolean) => {
    setToggling(node.node_id);
    try {
      if (enabled) {
        const res = await sliceApi.enableWorker(node.node_id);
        message.success(res.message);
      } else {
        const res = await sliceApi.disableWorker(node.node_id);
        message.success(res.message);
      }
      fetchWorkers();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setToggling(null);
    }
  };

  // 打开下拉时刷新一次节点状态
  const onOpenChange = (open: boolean) => {
    if (open) fetchWorkers();
  };

  const onlineCount = workers.filter((w) => w.status === 'online' && w.enabled !== false).length;
  const totalCount = workers.length;

  const icon =
    totalCount === 0 ? (
      <ApiOutlined style={{ fontSize: 18, color: '#999' }} />
    ) : onlineCount > 0 ? (
      <Badge count={onlineCount} size="small" offset={[-2, 2]}>
        <ApiOutlined style={{ fontSize: 18, color: '#52c41a' }} />
      </Badge>
    ) : (
      <Badge count={totalCount} size="small" offset={[-2, 2]}>
        <ApiOutlined style={{ fontSize: 18, color: '#ff4d4f' }} />
      </Badge>
    );

  const content = loading ? (
    <div style={{ width: 300, padding: 16, textAlign: 'center' }}>
      <Spin size="small" />
    </div>
  ) : (
    <div style={{ width: 320, maxHeight: 420, overflow: 'auto', padding: 8 }}>
      {workers.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '16px 0', color: '#999' }}>
          暂无 Worker 节点
        </div>
      ) : (
        <List
          size="small"
          dataSource={workers}
          renderItem={(node) => {
            const online = node.status === 'online';
            const enabled = node.enabled !== false;
            return (
              <List.Item
                style={{ padding: '8px 4px' }}
                actions={[
                  <Switch
                    key="sw"
                    size="small"
                    checked={enabled}
                    loading={toggling === node.node_id}
                    onChange={(v) => toggleWorker(node, v)}
                    checkedChildren="开"
                    unCheckedChildren="关"
                  />,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space size={6}>
                      <Text style={{ fontSize: 13 }}>{node.node_id}</Text>
                      {!enabled ? (
                        <Tag icon={<PoweroffOutlined />} style={{ marginInlineEnd: 0 }}>已停用</Tag>
                      ) : online ? (
                        <Tag color="success" icon={<CheckCircleOutlined />} style={{ marginInlineEnd: 0 }}>在线</Tag>
                      ) : (
                        <Tag color="error" icon={<CloseCircleOutlined />} style={{ marginInlineEnd: 0 }}>离线</Tag>
                      )}
                    </Space>
                  }
                  description={
                    <Space size={4} style={{ fontSize: 12 }}>
                      {node.ip && node.ip !== 'unknown' ? <Text type="secondary" style={{ fontSize: 12 }}>{node.ip}</Text> : null}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {node.current_tasks || 0}/{node.max_concurrent || 2} 任务
                      </Text>
                      <Text type="success" style={{ fontSize: 12 }}>完成 {node.total_tasks_completed || 0}</Text>
                      <Text type="danger" style={{ fontSize: 12 }}>失败 {node.total_tasks_failed || 0}</Text>
                    </Space>
                  }
                />
              </List.Item>
            );
          }}
        />
      )}
      <div style={{ textAlign: 'center', paddingTop: 4 }}>
        <Button type="link" size="small" onClick={() => window.location.assign('/workers')}>
          前往节点管理 →
        </Button>
      </div>
    </div>
  );

  return (
    <Dropdown
      dropdownRender={() => (
        // 白色底色容器：避免弹开后面没有背景看不清内容
        <div
          style={{
            background: token.colorBgElevated,
            borderRadius: 8,
            boxShadow: token.boxShadowSecondary,
            border: `1px solid ${token.colorBorderSecondary}`,
            overflow: 'hidden',
          }}
        >
          {content}
        </div>
      )}
      trigger={['click']}
      placement="bottomRight"
      onOpenChange={onOpenChange}
    >
      <div style={{ cursor: 'pointer', padding: '0 8px', display: 'flex', alignItems: 'center' }} title="Worker 节点状态">
        {icon}
      </div>
    </Dropdown>
  );
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
          <Space>
            {/* Worker 节点状态图标（系统菜单栏） */}
            <WorkerStatusIcon />
            <Dropdown menu={{ items: userMenuItems, onClick: handleUserMenuClick }}>
              <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Avatar size="small" icon={<UserOutlined />} />
                <span style={{ color: token.colorTextSecondary }}>
                  {displayName}
                  {displayRole ? ` (${displayRole})` : ''}
                </span>
              </div>
            </Dropdown>
          </Space>
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