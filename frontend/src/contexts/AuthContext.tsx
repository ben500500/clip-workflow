import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { User, Role } from '../types';
import { authApi } from '../api/auth';

// 角色对应的菜单权限映射
const ROLE_PERMISSIONS: Record<Role, string[]> = {
  admin: ['*'], // 所有菜单
  operator: [
    '/dashboard',
    '/projects',
    '/batch-slice',
    '/watermark',
    '/resource-download',
    '/channel-accounts',
    '/variant-matrix',
    'analytics-sub',
    '/analytics/overview',
    '/analytics/shortdrama',
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
    '/channel-accounts',
    '/publish',
    '/variant-matrix',
    'analytics-sub',
    '/analytics/overview',
    '/analytics/shortdrama',
    '/analytics/content',
    '/analytics/import',
    '/profile',
  ],
  material: [
    '/dashboard',
    '/projects',
    '/batch-slice',
    '/watermark',
    '/resource-download',
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

  // 主动续期：access_token 默认 30 分钟过期，后台页面/空闲时若一直不发起
  // 带鉴权的请求，不会触发 401 无感刷新，导致一段时间不操作后被强制登出。
  // 这里每 20 分钟用 refresh_token（HttpOnly Cookie）静默续签一次，
  // 保证登录态在 refresh_token 有效期内（7 天）持续有效。
  useEffect(() => {
    if (!token) return;
    const REFRESH_INTERVAL_MS = 20 * 60 * 1000; // 20 分钟 < 30 分钟 access_token 有效期
    const refresh = async () => {
      try {
        const res = await authApi.refresh();
        if (res.access_token) {
          localStorage.setItem('auth_token', res.access_token);
          setToken(res.access_token);
        }
      } catch {
        // 静默失败：refresh_token 失效时才由后续 401 统一处理跳登录
      }
    };
    const timer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [token]);

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