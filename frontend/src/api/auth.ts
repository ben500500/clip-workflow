import client from './client';
import type { User, LoginResponse } from '../types';

export const authApi = {
  login: (username: string, password: string) =>
    client.post('/auth/login', { username, password }) as Promise<LoginResponse>,

  getMe: () => client.get('/auth/me') as Promise<User>,

  register: (data: { username: string; password: string; display_name?: string; role?: string }) =>
    client.post('/auth/register', data) as Promise<User>,

  getUsers: () => client.get('/auth/users') as Promise<User[]>,

  updateUserRole: (id: string, role: string) =>
    client.put(`/auth/users/${id}/role`, { role }) as Promise<User>,
};