import client from './client';

// ========== 剧场（Theater）==========

export interface Theater {
  id: string;
  name: string;
  remark: string | null;
  operator_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface TheaterInput {
  name: string;
  remark?: string | null;
  operator_id?: string | null;
}

export const theaterApi = {
  // 剧场 CRUD
  list: (params?: { keyword?: string }) =>
    client.get('/theaters', { params }) as Promise<Theater[]>,
  get: (id: string) => client.get(`/theaters/${id}`) as Promise<Theater>,
  create: (data: TheaterInput) =>
    client.post('/theaters', data) as Promise<Theater>,
  update: (id: string, data: Partial<TheaterInput>) =>
    client.put(`/theaters/${id}`, data) as Promise<Theater>,
  remove: (id: string) => client.delete(`/theaters/${id}`) as Promise<void>,
};
