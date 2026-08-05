import dayjs from 'dayjs';

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes < 0) return '-';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const k = 1024;
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), units.length - 1);
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  if (h > 0) return `${pad(h)}:${pad(m)}:${pad(s)}`;
  return `${pad(m)}:${pad(s)}`;
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return dayjs(dateStr).format('YYYY-MM-DD HH:mm:ss');
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return dayjs(dateStr).format('YYYY-MM-DD');
}

export function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  const now = dayjs();
  const target = dayjs(dateStr);
  const diffMinutes = now.diff(target, 'minute');
  if (diffMinutes < 1) return '刚刚';
  if (diffMinutes < 60) return `${diffMinutes}分钟前`;
  const diffHours = now.diff(target, 'hour');
  if (diffHours < 24) return `${diffHours}小时前`;
  const diffDays = now.diff(target, 'day');
  if (diffDays < 30) return `${diffDays}天前`;
  return formatDate(dateStr);
}

export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined) return '-';
  return `${Number(value).toFixed(decimals)}%`;
}

export function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    draft: '#8c8c8c',
    processing: '#1677ff',
    completed: '#52c41a',
    archived: '#d9d9d9',
    uploaded: '#1677ff',
    clips_detected: '#13c2c2',
    intervals_detected: '#722ed1',
    slicing: '#fa8c16',
    failed: '#ff4d4f',
    pending: '#faad14',
    pending_confirm: '#faad14',
    running: '#1677ff',
    publishing: '#1677ff',
    published: '#52c41a',
    cancelled: '#8c8c8c',
    accepted: '#52c41a',
    rejected: '#ff4d4f',
    adjusted: '#722ed1',
    enabled: '#52c41a',
    disabled: '#d9d9d9',
    success: '#52c41a',
  };
  return map[status] || '#d9d9d9';
}

export function getStatusLabel(status: string): string {
  const map: Record<string, string> = {
    draft: '草稿',
    processing: '处理中',
    completed: '已完成',
    archived: '已归档',
    uploaded: '已上传',
    clips_detected: '已选点',
    intervals_detected: '已检测',
    slicing: '切片中',
    failed: '失败',
    pending: '待处理',
    pending_confirm: '待确认',
    running: '运行中',
    publishing: '发布中',
    published: '已发布',
    cancelled: '已取消',
    accepted: '已通过',
    rejected: '已拒绝',
    adjusted: '已调整',
    enabled: '启用',
    disabled: '停用',
    success: '成功',
  };
  return map[status] || status;
}

export function truncateText(text: string | null | undefined, maxLength = 50): string {
  if (!text) return '-';
  return text.length <= maxLength ? text : `${text.slice(0, maxLength)}...`;
}
