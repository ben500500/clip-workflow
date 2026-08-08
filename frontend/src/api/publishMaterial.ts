import client from './client';

// 短剧发布素材（v7）：短标题 / 三款视频配文 / 成套话题标签 / 三条置顶互动神评
export interface PublishMaterial {
  short_title: string;
  captions: {
    suspense_hook: string;
    concise_viral: string;
    emotional: string;
  };
  tags: Record<string, string[]>;
  comments: Array<{ type: string; content: string }>;
}

export interface PublishMaterialRecord {
  id: string;
  story: string;
  title: string | null;
  theme: string | null;
  tone: string | null;
  platform: string | null;
  extra_requirements: string | null;
  model: string | null;
  material: PublishMaterial;
  created_at: string;
}

export interface PublishMaterialGenerateParams {
  story: string;
  title?: string;
  theme?: string;
  tone?: string;
  platform?: string;
  extra_requirements?: string;
  save?: boolean;
}

export const publishMaterialApi = {
  generate: (params: PublishMaterialGenerateParams) =>
    client.post('/shortdrama/publish-material/generate', params) as Promise<{
      material: PublishMaterial;
      model?: string | null;
      record_id?: string | null;
      message: string;
    }>,

  listMaterials: (limit = 50) =>
    client.get('/shortdrama/publish-materials', { params: { limit } }) as Promise<
      PublishMaterialRecord[]
    >,

  getMaterial: (recordId: string) =>
    client.get(`/shortdrama/publish-materials/${recordId}`) as Promise<PublishMaterialRecord>,

  deleteMaterial: (recordId: string) =>
    client.delete(`/shortdrama/publish-materials/${recordId}`) as Promise<{
      message: string;
      record_id: string;
    }>,
};
