import client from './client';
import type { AlertEvent, AlertRule } from '../types';

export const monitorApi = {
  getHealth: () =>
    client.get('/monitor/health') as Promise<{
      status: string;
      service: string;
      checks: Record<string, { status: string; error?: string; usage_percent?: number }>;
    }>,

  getMetrics: () =>
    client.get('/monitor/metrics') as Promise<Record<string, number>>,

  getAlertRules: () =>
    client.get('/monitor/alerts/rules') as Promise<AlertRule[]>,

  getAlertRuleMeta: () =>
    client.get('/monitor/alerts/rules/meta') as Promise<{ metric: string; description: string }[]>,

  createAlertRule: (data: Partial<AlertRule>) =>
    client.post('/monitor/alerts/rules', data) as Promise<AlertRule>,

  updateAlertRule: (id: string, data: Partial<AlertRule>) =>
    client.put(`/monitor/alerts/rules/${id}`, data) as Promise<AlertRule>,

  deleteAlertRule: (id: string) =>
    client.delete(`/monitor/alerts/rules/${id}`) as Promise<unknown>,

  getAlertEvents: (params?: { level?: string; limit?: number }) =>
    client.get('/monitor/alerts/events', { params }) as Promise<AlertEvent[]>,

  runAlertCheck: () =>
    client.post('/monitor/alerts/check') as Promise<{ checked: number; triggered: number; notified: number; errors: string[] }>,
};

export const maintenanceApi = {
  getStatus: () =>
    client.get('/maintenance/status') as Promise<{
      archive_days: number;
      minio_lifecycle_days: number;
      temp_cleanup_hours: number;
    }>,

  runArchive: (days?: number) =>
    client.post('/maintenance/archive', { days }) as Promise<{ cutoff: string; deleted: Record<string, number>; errors: string[] }>,

  runCleanup: (maxAgeHours?: number) =>
    client.post('/maintenance/cleanup-temp', { max_age_hours: maxAgeHours ?? 24 }) as Promise<{ cleaned: number; freed_mb: number; errors: string[] }>,

  runMinioLifecycle: () =>
    client.post('/maintenance/minio-lifecycle') as Promise<{ buckets: string[]; errors: string[] }>,
};
