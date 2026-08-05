import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

client.interceptors.response.use(
  (response) => {
    return response.data;
  },
  (error) => {
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求超时，请稍后重试'));
    }
    if (error.response) {
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
