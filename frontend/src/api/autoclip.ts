import client from './client';
import type { AutoClipConfig, AutoClipRunRecord, ClipCandidate } from '../types';

export const autoclipApi = {
  saveLlmModel: (payload: { name: string; model: string; api_base?: string; api_key?: string }) =>
    client.post('/autoclip/llm-models', payload) as Promise<{ ok: boolean; count: number }>,

  llmTest: (payload: { model?: string; api_base?: string; api_key?: string; name?: string }) =>
    client.post('/autoclip/llm-test', payload) as Promise<{
      ok: boolean; latency_ms: number; reply?: string; error?: string;
    }>,

  llmModels: () =>
    client.get('/autoclip/llm-models') as Promise<{ name: string; model: string; api_base?: string }[]>,

  run: (episodeId: string, config?: AutoClipConfig) =>
    client.post(`/episodes/${episodeId}/autoclip/run`, { config }) as Promise<{
      celery_task_id: string;
      autoclip_project_id?: string;
      message: string;
    }>,

  history: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/autoclip/history`) as Promise<AutoClipRunRecord[]>,

  deleteHistory: (episodeId: string, runId: string) =>
    client.delete(`/episodes/${episodeId}/autoclip/history/${runId}`) as Promise<{ message: string; run_id: string; cleared_results?: boolean }>,

  progress: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/autoclip/progress`) as Promise<{
      status: string;
      progress: number;
      message: string;
      error_message?: string | null;
    }>,

  getCandidates: (episodeId: string, minScore?: number) =>
    client.get(`/episodes/${episodeId}/autoclip/clips`, { params: { min_score: minScore } }) as Promise<ClipCandidate[]>,

  updateCandidate: (id: string, data: Partial<ClipCandidate>) =>
    client.put(`/clips/${id}`, data) as Promise<ClipCandidate>,

  regenerate: (episodeId: string, config?: AutoClipConfig) =>
    client.post(`/episodes/${episodeId}/autoclip/regenerate`, { config }) as Promise<{
      celery_task_id: string;
      autoclip_project_id?: string;
      message: string;
    }>,
};
