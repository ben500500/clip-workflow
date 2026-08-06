import client from './client';
import type { Publication, SliceOutput } from '../types';

export const previewApi = {
  getFrames: (outputId: string) =>
    client.get(`/outputs/${outputId}/preview/frames`) as Promise<{
      output_id: string;
      frames: { key: string; url: string | null; size?: number; note?: string }[];
      count: number;
    }>,

  getVideoUrl: (outputId: string) =>
    client.get(`/outputs/${outputId}/preview/video`) as Promise<{
      url: string;
      file_name: string | null;
      duration: number | null;
      file_size: number | null;
      expires_in_seconds: number;
    }>,

  download: (outputId: string) =>
    client.get(`/outputs/${outputId}/download`) as Promise<unknown>,

  batchDownload: (outputIds: string[]) =>
    client.post(
      '/outputs/batch-download',
      { output_ids: outputIds },
      { timeout: 600000 }
    ) as Promise<{
      files: { output_id: string; file_name: string; url: string }[];
    }>,

  getPublications: (outputId: string) =>
    client.get(`/outputs/${outputId}/publications`) as Promise<Publication[]>,

  createPublication: (outputId: string, data: Partial<Publication>) =>
    client.post(`/outputs/${outputId}/publications`, data) as Promise<Publication>,

  updatePublication: (id: string, data: Partial<Publication>) =>
    client.put(`/publications/${id}`, data) as Promise<Publication>,
};

export type { SliceOutput };
