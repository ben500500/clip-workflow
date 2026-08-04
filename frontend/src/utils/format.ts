import dayjs from 'dayjs';

/**
 * 格式化文件大小
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const size = parseFloat((bytes / Math.pow(k, i)).toFixed(2));
  return `${size} ${units[i]}`;
}

/**
 * 格式化时长（秒 -> HH:MM:SS 或 MM:SS）
 */
export function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  if (h > 0) {
    return `${pad(h)}:${pad(m)}:${pad(s)}`;
  }
  return `${pad(m)}:${pad(s)}`;
}

/**
 * 格式化时间戳
 */
export function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  return dayjs(dateStr).format('YYYY-MM-DD HH:mm:ss');
}

/**
 * 格式化日期
 */
export function formatDate(dateStr: string): string {
  if (!dateStr) return '-';
  return dayjs(dateStr).format('YYYY-MM-DD');
}

/**
 * 格式化相对时间
 */
export function formatRelativeTime(dateStr: string): string {
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

  const diffMonths = now.diff(target, 'month');
  if (diffMonths < 12) return `${diffMonths}个月前`;

  return formatDate(dateStr);
}

/**
 * 格式化百分比
 */
export function formatPercent(value: number, decimals: number = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * 格式化置信度，显示为百分比
 */
export function formatConfidence(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/**
 * 格式化时间范围（秒 -> HH:MM:SS - HH:MM:SS）
 */
export function formatTimeRange(startSeconds: number, endSeconds: number): string {
  return `${formatDuration(startSeconds)} - ${formatDuration(endSeconds)}`;
}

/**
 * 获取状态对应的颜色
 */
export function getStatusColor(status: string): string {
  const colorMap: Record<string, string> = {
    active: '#52c41a',
    completed: '#1677ff',
    archived: '#d9d9d9',
    pending: '#faad14',
    running: '#1677ff',
    approved: '#52c41a',
    rejected: '#ff4d4f',
    adjusted: '#722ed1',
    failed: '#ff4d4f',
    uploaded: '#1677ff',
    clips_detected: '#52c41a',
    intervals_detected: '#52c41a',
    slicing: '#faad14',
    published: '#52c41a',
  };
  return colorMap[status] || '#d9d9d9';
}

/**
 * 获取状态对应的中文标签
 */
export function getStatusLabel(status: string): string {
  const labelMap: Record<string, string> = {
    active: '进行中',
    completed: '已完成',
    archived: '已归档',
    pending: '待处理',
    running: '运行中',
    approved: '已通过',
    rejected: '已拒绝',
    adjusted: '已调整',
    failed: '失败',
    uploaded: '已上传',
    clips_detected: '已选点',
    intervals_detected: '已检测区间',
    slicing: '切片中',
    published: '已发布',
    hash: '哈希去重',
    perceptual: '感知去重',
    content: '内容去重',
  };
  return labelMap[status] || status;
}

/**
 * 截断文本
 */
export function truncateText(text: string, maxLength: number = 50): string {
  if (!text || text.length <= maxLength) return text || '-';
  return `${text.slice(0, maxLength)}...`;
}