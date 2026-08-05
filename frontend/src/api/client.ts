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

client.interceptors.response.use(
  (response) => {
    return response.data;
  },
  (error) => {
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求超时，请稍后重试'));
    }
    if (error.response) {
      // 401 未授权：清除 token 并跳转登录页
      if (error.response.status === 401) {
        localStorage.removeItem('auth_token');
        // 仅在非登录请求时跳转，避免循环
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
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