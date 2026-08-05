import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Result, Button } from 'antd';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';

// 路由到菜单 key 的映射
const ROUTE_TO_MENU_KEY: Record<string, string> = {
  '/dashboard': '/dashboard',
  '/projects': '/projects',
  '/publish': '/publish',
  '/profile': '/profile',
  '/user-management': '/user-management',
  '/settings': '/settings',
  '/analytics/overview': '/analytics/overview',
  '/analytics/content': '/analytics/content',
  '/analytics/monetization': '/analytics/monetization',
  '/analytics/funnel': '/analytics/funnel',
  '/analytics/ecosystem': '/analytics/ecosystem',
  '/analytics/import': '/analytics/import',
  '/analytics/settings': '/analytics/settings',
};

// 获取路由对应的菜单 key
const getMenuKeyFromPath = (pathname: string): string | null => {
  // 精确匹配
  if (ROUTE_TO_MENU_KEY[pathname]) return ROUTE_TO_MENU_KEY[pathname];

  // 前缀匹配：/projects/xxx, /episodes/xxx 等归为 /projects
  if (pathname.startsWith('/projects/')) return '/projects';
  if (pathname.startsWith('/episodes/')) return '/projects';
  if (pathname.startsWith('/analytics/')) return pathname; // 子路由精确匹配

  return null;
};

const ForbiddenPage: React.FC = () => {
  const navigate = useNavigate();
  return (
    <Result
      status="403"
      title="403"
      subTitle="抱歉，您没有权限访问此页面。"
      extra={
        <Button type="primary" onClick={() => navigate('/dashboard')}>
          返回首页
        </Button>
      }
    />
  );
};

interface AuthGuardProps {
  children: React.ReactNode;
}

const AuthGuard: React.FC<AuthGuardProps> = ({ children }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  // 等待认证状态加载完成
  if (loading) {
    return null; // 或者返回一个 loading 组件
  }

  // 未登录，跳转到登录页
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 检查当前路由是否有权限
  const menuKey = getMenuKeyFromPath(location.pathname);

  // 如果找不到对应的菜单 key，则允许访问（用于 NotFound 等页面）
  if (menuKey === null) {
    return <>{children}</>;
  }

  // 检查权限
  const { hasPermission } = useAuth();
  if (!hasPermission(menuKey)) {
    return <ForbiddenPage />;
  }

  return <>{children}</>;
};

export default AuthGuard;