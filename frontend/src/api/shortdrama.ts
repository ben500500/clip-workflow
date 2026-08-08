import client from './client';

export interface ShortdramaPromptRecord {
  id: string;
  source_text: string;
  duration: number;
  theme: string | null;
  tone: string | null;
  characters: string | null;
  extra_requirements: string | null;
  model: string | null;
  prompt_text: string;
  created_at: string;
}

export interface PromptGenerateParams {
  text: string;
  duration: number;
  theme?: string;
  tone?: string;
  characters?: string;
  extra_requirements?: string;
  save?: boolean;
}

export const shortdramaApi = {
  generate: (params: PromptGenerateParams) =>
    client.post('/shortdrama/prompt/generate', params) as Promise<{
      prompt: string;
      duration: number;
      model?: string | null;
      record_id?: string | null;
      message: string;
    }>,

  listPrompts: (limit = 50) =>
    client.get('/shortdrama/prompts', { params: { limit } }) as Promise<ShortdramaPromptRecord[]>,

  getPrompt: (recordId: string) =>
    client.get(`/shortdrama/prompts/${recordId}`) as Promise<ShortdramaPromptRecord>,

  deletePrompt: (recordId: string) =>
    client.delete(`/shortdrama/prompts/${recordId}`) as Promise<{ message: string; record_id: string }>,
};
