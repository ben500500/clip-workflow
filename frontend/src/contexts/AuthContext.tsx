import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { User, Role } from '../types';
import { authApi } from '../api/auth';

// 角色对应的菜单权限映射
const ROLE_PERMISSIONS: Record<Role, string[]> = {
  admin: ['*'], // 所有菜单
  operator: [
    '/dashboard',
    '/projects',
    'analytics-sub',
    '/analytics/overview',
    '/analytics/content',
    '/analytics/monetization',
    '/analytics/funnel',
    '/analytics/ecosystem',
    '/analytics/import',
    '/analytics/settings',
    '/profile',
    '/settings',
  ],
  publisher: [
    '/dashboard',
    '/publish',
    'analytics-sub',
    '/analytics/overview',
    '/analytics/content',
    '/analytics/import',
    '/profile',
  ],
  material: [
    '/dashboard',
    '/projects',
    '/profile',
  ],
};

interface AuthContextType {
  user: User | null;
  token: string | null;
  roles: Role[];
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  hasPermission: (menuKey: string) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('auth_token'));
  const [loading, setLoading] = useState<boolean>(true);
  const verifyingRef = useRef(false);

  // 组件挂载时从 localStorage 读取 token 并验证
  useEffect(() => {
    const savedToken = localStorage.getItem('auth_token');
    if (savedToken && !verifyingRef.current) {
      verifyingRef.current = true;
      authApi
        .getMe()
        .then((userData) => {
          setUser(userData);
          setToken(savedToken);
        })
        .catch(() => {
          // token 无效，清除
          localStorage.removeItem('auth_token');
          setToken(null);
          setUser(null);
        })
        .finally(() => {
          setLoading(false);
          verifyingRef.current = false;
        });
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await authApi.login(username, password);
    const accessToken = result.access_token;
    localStorage.setItem('auth_token', accessToken);
    setToken(accessToken);
    // 登录返回中已包含用户信息
    if (result.user) {
      setUser(result.user);
    } else {
      // 兼容旧版本：单独获取用户信息
      const userData = await authApi.getMe();
      setUser(userData);
    }
  }, []);

  const logout = useCallback(() => {
    // 调用后端吊销 refresh_token 会话（Token 黑名单）
    authApi.logout().catch(() => undefined);
    localStorage.removeItem('auth_token');
    setToken(null);
    setUser(null);
  }, []);

  const hasPermission = useCallback(
    (menuKey: string): boolean => {
      if (!user) return false;
      const permissions = ROLE_PERMISSIONS[user.role];
      if (!permissions) return false;
      // admin 拥有所有权限
      if (permissions.includes('*')) return true;
      return permissions.includes(menuKey);
    },
    [user]
  );

  const value: AuthContextType = {
    user,
    token,
    roles: user ? [user.role] : [],
    loading,
    login,
    logout,
    hasPermission,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;