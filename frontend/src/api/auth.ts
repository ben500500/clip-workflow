import client from './client';
import type { User, LoginResponse } from '../types';

export const authApi = {
  login: (username: string, password: string) =>
    client.post('/auth/login', { username, password }, { withCredentials: true }) as Promise<LoginResponse>,

  refresh: () =>
    client.post('/auth/refresh', {}, { withCredentials: true }) as Promise<{ access_token: string }>,

  logout: () =>
    client.post('/auth/logout', {}, { withCredentials: true }) as Promise<{ ok: boolean }>,

  getMe: () => client.get('/auth/me') as Promise<User>,

  register: (data: { username: string; password: string; display_name?: string; role?: string }) =>
    client.post('/auth/register', data) as Promise<User>,

  getUsers: () => client.get('/auth/users') as Promise<User[]>,

  updateUserRole: (id: string, role: string) =>
    client.put(`/auth/users/${id}/role`, { role }) as Promise<User>,

  toggleUserActive: (id: string) =>
    client.put(`/auth/users/${id}/toggle`) as Promise<User>,

  updateProfile: (data: { display_name?: string; old_password?: string; new_password?: string }) =>
    client.put('/auth/profile', data) as Promise<User>,
};
