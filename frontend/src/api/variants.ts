import client from './client';

export interface VariantFingerprint {
  algorithm: string;
  hash_value?: string | null;
  duration?: number | null;
}

export interface VariantMatrixItem {
  id: string;
  variant_index: number;
  status: string;
  file_name?: string | null;
  file_key?: string | null;
  phash_distance?: number | null;
  audio_distance?: number | null;
  seg_distance?: number | null;
  structural_diff?: Record<string, unknown> | null;
  collision: boolean;
  collision_reason?: string | null;
  account_id?: string | null;
  created_at?: string;
}

export interface VariantGroup {
  variant_group_id: string;
  base_output_id: string;
  base_file_name?: string | null;
  created_at?: string;
  variants: VariantMatrixItem[];
}

export interface VariantMatrix {
  variant_groups: VariantGroup[];
  thresholds: Record<string, number>;
}

export interface VariantDetail extends VariantMatrixItem {
  variant_group_id?: string | null;
  dedupe_config?: Record<string, unknown> | null;
  fingerprints: VariantFingerprint[];
}

export interface VariantVerifyResult {
  safe: boolean;
  distances: Record<string, number>;
  reason?: string;
}

export const variantsApi = {
  matrix: () => client.get('/variant-matrix') as Promise<VariantMatrix>,

  detail: (id: string) => client.get(`/variants/${id}`) as Promise<VariantDetail>,

  generate: (data: { output_id: string; count?: number; dedupe_config?: Record<string, unknown>; thresholds?: Record<string, unknown> }) =>
    client.post('/variants/generate', data) as Promise<{ task_id: string; output_id: string; count: number }>,

  verify: (id: string) =>
    client.post(`/variants/${id}/verify`) as Promise<VariantVerifyResult>,

  bind: (id: string, account_id?: string | null) =>
    client.post(`/variants/${id}/bind`, { variant_id: id, account_id }) as Promise<{ variant_id: string; account_id: string | null }>,

  updateThresholds: (data: Partial<Record<'phash' | 'audio' | 'seg' | 'combined', number>>) =>
    client.put('/variant-thresholds', data) as Promise<Record<string, number>>,
};
