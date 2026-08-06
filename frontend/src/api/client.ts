import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器：自动携带 Authorization header
client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器：401 时尝试用 refresh_token 无感刷新
let refreshing = false;
let pendingQueue: Array<(token: string | null) => void> = [];

const refreshAccessToken = async (): Promise<string | null> => {
  try {
    const resp = await axios.post(
      '/api/auth/refresh',
      {},
      { withCredentials: true, timeout: 15000 }
    );
    const data = resp.data as { access_token: string };
    return data.access_token || null;
  } catch {
    return null;
  }
};

client.interceptors.response.use(
  (response) => {
    return response.data;
  },
  async (error) => {
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求超时，请稍后重试'));
    }
    if (error.response) {
      const status = error.response.status;

      // 401 未授权：尝试无感刷新
      if (status === 401 && !error.config?.__isRetry && !error.config?.url?.includes('/auth/')) {
        // 没有 access_token 时直接跳转登录
        if (!localStorage.getItem('auth_token')) {
          if (window.location.pathname !== '/login') {
            window.location.href = '/login';
          }
          const detail = error.response.data?.detail || '未登录或登录已过期';
          return Promise.reject(new Error(detail));
        }

        try {
          // 多个并发 401 只触发一次刷新
          if (!refreshing) {
            refreshing = true;
            const newToken = await refreshAccessToken();
            refreshing = false;
            pendingQueue.forEach((resolve) => resolve(newToken));
            pendingQueue = [];

            if (newToken) {
              localStorage.setItem('auth_token', newToken);
              error.config.__isRetry = true;
              error.config.headers.Authorization = `Bearer ${newToken}`;
              return client(error.config);
            }
            // 刷新失败：清除并跳转登录
            localStorage.removeItem('auth_token');
            if (window.location.pathname !== '/login') {
              window.location.href = '/login';
            }
            return Promise.reject(new Error('登录已过期，请重新登录'));
          }
          // 刷新进行中，排队等待
          return new Promise((resolve, reject) => {
            pendingQueue.push((newToken) => {
              if (newToken) {
                localStorage.setItem('auth_token', newToken);
                error.config.__isRetry = true;
                error.config.headers.Authorization = `Bearer ${newToken}`;
                resolve(client(error.config));
              } else {
                reject(new Error('登录已过期，请重新登录'));
              }
            });
          });
        } catch (refreshErr) {
          localStorage.removeItem('auth_token');
          if (window.location.pathname !== '/login') {
            window.location.href = '/login';
          }
          return Promise.reject(new Error('登录已过期，请重新登录'));
        }
      }

      const detail =
        error.response.data?.detail ||
        error.response.data?.message ||
        error.response.statusText ||
        '请求失败';
      return Promise.reject(new Error(detail));
    }
    if (error.message?.includes('Network Error')) {
      return Promise.reject(new Error('网络连接失败，请检查服务是否已启动'));
    }
    return Promise.reject(new Error(error.message || '请求失败'));
  }
);

export default client;
