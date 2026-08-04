import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
client.interceptors.request.use(
  (config) => {
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
client.interceptors.response.use(
  (response) => {
    const res = response.data;
    if (res.code !== 0 && res.code !== undefined) {
      const error = new Error(res.message || '请求失败') as Error & { code: number };
      error.code = res.code;
      return Promise.reject(error);
    }
    return res;
  },
  (error) => {
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求超时，请稍后重试'));
    }
    if (error.response) {
      const { status } = error.response;
      switch (status) {
        case 400:
          return Promise.reject(new Error('请求参数错误'));
        case 404:
          return Promise.reject(new Error('请求的资源不存在'));
        case 500:
          return Promise.reject(new Error('服务器内部错误'));
        default:
          return Promise.reject(new Error(`请求失败 (${status})`));
      }
    }
    if (error.message?.includes('Network Error')) {
      return Promise.reject(new Error('网络连接失败，请检查网络'));
    }
    return Promise.reject(error);
  }
);

export default client;