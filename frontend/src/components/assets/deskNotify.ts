/**
 * 桌面通知（用户口径 2026-11-09）：后台任务完成时提醒，**页面在后台也能收到**。
 *
 * 三条纪律：
 * - 权限只在用户点开关时申请（自动弹授权会被浏览器拦、体验也差）；
 * - 开关状态存 localStorage，用户关掉就真的不再弹（不靠浏览器权限单独决定）；
 * - 浏览器不支持 / 用户拒绝时全部静默降级——页内 toast 照旧，不影响任务本身。
 */
import type { AssetJobInfo } from '../../api/assets';

const LS_KEY = 'asset-desk-notify';

/**
 * 浏览器是否**可能**给出通知权限。
 *
 * ⚠️ 除 API 存在外还必须满足**安全上下文**（HTTPS 或 localhost）：内网 HTTP
 * （如 http://192.168.1.163）下 Chrome/Edge 的 Notification.permission 恒为
 * denied、requestPermission() 直接返回 denied 不弹框——这正是"点了没反应、
 * 不知道怎么设置"的根因，界面必须把它诊断出来并给出解决路径。
 */
export const deskNotifySecure = (): boolean =>
  typeof window !== 'undefined' && window.isSecureContext === true;

export const deskNotifySupported = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.Notification !== 'undefined' &&
  deskNotifySecure();

/** 开关开着且浏览器已授权 */
export const deskNotifyEnabled = (): boolean =>
  deskNotifySupported() &&
  window.Notification.permission === 'granted' &&
  localStorage.getItem(LS_KEY) === '1';

export type DeskNotifyState = 'on' | 'off' | 'denied' | 'insecure' | 'unsupported';

export const deskNotifyState = (): DeskNotifyState => {
  if (typeof window === 'undefined' || typeof window.Notification === 'undefined') return 'unsupported';
  if (!deskNotifySecure()) return 'insecure';
  if (window.Notification.permission === 'denied') return 'denied';
  return deskNotifyEnabled() ? 'on' : 'off';
};

/** 用户点开关：申请权限并记住选择。返回最终状态。 */
export const toggleDeskNotify = async (): Promise<DeskNotifyState> => {
  // 2026-11-11 评审（前端席 P1）：内网 HTTP 下原先统一回 'unsupported'，把精心写的
  // 'insecure' 诊断分支变成死代码。区分开：浏览器压根没有 Notification API 才是
  // unsupported；有 API 但不是安全上下文，如实回 insecure（界面会指路解决步骤）。
  if (typeof window === 'undefined' || typeof window.Notification === 'undefined') return 'unsupported';
  if (!deskNotifySecure()) return 'insecure';
  if (deskNotifyEnabled()) {
    localStorage.setItem(LS_KEY, '0');
    return 'off';
  }
  const perm = await window.Notification.requestPermission();
  if (perm === 'granted') {
    localStorage.setItem(LS_KEY, '1');
    // 立刻发一条，确认通路（也顺便让用户看到通知长什么样）
    try {
      new window.Notification('桌面通知已开启', {
        body: '后台任务完成时会在这里提醒你，关掉页面也能收到',
        tag: 'desk-notify-hello',
      });
    } catch {
      /* 通知构造失败（部分浏览器限制）——不影响主流程 */
    }
    return 'on';
  }
  localStorage.setItem(LS_KEY, '0');
  return perm === 'denied' ? 'denied' : 'off';
};

/** 任务终态 → 桌面通知（开关关着/无权限时静默跳过） */
export const notifyJobSettled = (job: AssetJobInfo): void => {
  if (!deskNotifyEnabled()) return;
  const ok = job.status === 'succeeded';
  const interrupted = job.status === 'interrupted';
  // 11-10 口径③：原来这里裸写「后台任务完成」——投板跑完其实只是挂上板，片子还在豆包
  // 那边出（几十分钟），一线看桌面通知以为片儿到手了，去成片墙一看是空的。
  // 现在标题说清是**这一步**跑完，正文跟上海那边同一句 `done_note`（在哪看下一步）。
  const title = ok
    ? `✅「${job.kind_label}」这一步跑完了`
    : interrupted ? '⚠️ 后台任务被打断' : '❌ 后台任务失败';
  const head = `「${job.kind_label}」${job.status_label}`;
  const detail = job.error ? `：${job.error.slice(0, 80)}` : '';
  const body = ok && job.done_note ? `${head}｜${job.done_note}` : `${head}${detail}`;
  try {
    const n = new window.Notification(title, {
      body,
      tag: `asset-job-${job.id}`,
      // 失败/打断不自动消失（requireInteraction 仅部分浏览器支持），成功自动消失
      requireInteraction: !ok,
      silent: ok,
    });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    /* 静默降级 */
  }
};
