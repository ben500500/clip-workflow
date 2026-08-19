#!/usr/bin/env node
/**
 * 方案A：本机 Mac 发布执行器（真实 Edge + 家庭 IP）
 *
 * 职责：轮询 163 的 executor=local 待发布任务 → MinIO/presigned 下载视频 →
 *       连接本机真实 Edge（独立 profile）→ 打开视频号助手发布页 → 上传（file chooser）→
 *       填标题/描述 → 截图 → 自动发布 → 回调 163 更新状态。
 *
 * 用法：
 *   node executor.js --once          # 处理一个任务后退出
 *   node executor.js                 # 常驻轮询（默认）
 *   node executor.js --login-only    # 只打开 Edge 并导航到登录页（用于首次扫码）
 *   node executor.js --list          # 列出当前 pending 的 local 任务
 *
 * 配置：同目录 .env（见 .env.example）
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { promisify } = require('util');
const crypto = require('crypto');
const { chromium } = require('playwright');


/* ───────────────────────── 配置加载 ───────────────────────── */
function loadEnv() {
  const env = {};
  const p = path.join(__dirname, '.env');
  if (fs.existsSync(p)) {
    for (const line of fs.readFileSync(p, 'utf8').split('\n')) {
      const m = line.match(/^([A-Z_]+)=(.*)$/);
      if (m) env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
    }
  }
  return {
    API_BASE: env.API_BASE || 'http://192.168.1.163',
    JWT_SECRET: env.JWT_SECRET || '',
    USER_ID: env.USER_ID || '',
    BROWSER_PROFILE_DIR: env.BROWSER_PROFILE_DIR || path.join(os.homedir(), '.workbuddy', 'pw-publish-profile'),
    WORK_DIR: env.WORK_DIR || '/tmp/executor-work',
    POLL_INTERVAL: parseInt(env.POLL_INTERVAL || '15', 10),
    AUTO_PUBLISH: (env.AUTO_PUBLISH || 'true') === 'true',
    LOGIN_WAIT_SEC: parseInt(env.LOGIN_WAIT_SEC || '150', 10),
    CREATOR_URL: 'https://channels.weixin.qq.com/platform/post/create',
  };
}

/* ───────────────────────── 工具 ───────────────────────── */
const log = (tag, msg) => console.log(`[${new Date().toISOString()}] [${tag}] ${msg}`);

function makeJWT(payload, secret) {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const header = enc({ alg: 'HS256', typ: 'JWT' });
  const now = Math.floor(Date.now() / 1000);
  const body = enc({ ...payload, type: 'access', exp: now + 3600, iat: now });
  const sig = crypto.createHmac('sha256', secret).update(`${header}.${body}`).digest('base64url');
  return `${header}.${body}.${sig}`;
}

function authHeaders(cfg) {
  const token = makeJWT({ sub: cfg.USER_ID }, cfg.JWT_SECRET);
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

async function apiGet(cfg, p) {
  const r = await fetch(cfg.API_BASE + p, { headers: authHeaders(cfg), timeout: 30000 });
  if (!r.ok) throw new Error(`GET ${p} -> ${r.status} ${await r.text().catch(() => '')}`);
  return r.json();
}

async function apiPost(cfg, p, body) {
  const r = await fetch(cfg.API_BASE + p, {
    method: 'POST',
    headers: authHeaders(cfg),
    body: JSON.stringify(body),
    timeout: 30000,
  });
  if (!r.ok) throw new Error(`POST ${p} -> ${r.status} ${await r.text().catch(() => '')}`);
  return r.json();
}

async function callbackResult(cfg, taskId, payload) {
  try {
    const r = await apiPost(cfg, `/api/publish/tasks/${taskId}/executor-result`, payload);
    log('CALLBACK', `task ${taskId} -> ${payload.status} OK`);
    return r;
  } catch (e) {
    log('CALLBACK', `task ${taskId} -> ${payload.status} FAILED: ${e.message}`);
    return null;
  }
}

async function downloadFile(url, dest) {
  const r = await fetch(url, { timeout: 120000 });
  if (!r.ok) throw new Error(`download ${url} -> ${r.status}`);
  const buf = Buffer.from(await r.arrayBuffer());
  fs.writeFileSync(dest, buf);
  return buf.length;
}

/* ───────────────────────── 浏览器管理（Playwright Chromium，真实窗口） ───────────────────────── */
// 不依赖系统 Edge 第二实例（GPU 冲突/最小化点击失效/偶发崩溃），改用 Playwright 自带 Chromium：
// headful 真实可见窗口 + 持久化 profile（扫码一次长期有效）+ 家庭 IP，生命周期完全可控。
let _ctx = null;

async function ensureBrowser(cfg) {
  if (_ctx && !_ctx.browser().isConnected()) _ctx = null;
  if (_ctx) return _ctx;
  fs.mkdirSync(cfg.BROWSER_PROFILE_DIR, { recursive: true });
  fs.mkdirSync(cfg.WORK_DIR, { recursive: true });
  log('BROWSER', `启动 Playwright Chromium（headful，profile=${cfg.BROWSER_PROFILE_DIR}）`);
  _ctx = await chromium.launchPersistentContext(cfg.BROWSER_PROFILE_DIR, {
    headless: false,
    args: ['--no-sandbox', '--disable-gpu', '--disable-software-rasterizer', '--disable-dev-shm-usage'],
    viewport: null,
    locale: 'zh-CN',
  });
  return _ctx;
}

/* ───────────────────────── 页面操作 ───────────────────────── */
async function connectPage(cfg) {
  const ctx = await ensureBrowser(cfg);
  let page = ctx.pages().find((p) => p.url().includes('channels.weixin.qq.com'));
  if (!page) page = ctx.pages()[0] || (await ctx.newPage());
  // 视频号助手发布页是 iframe 结构：主 frame 是壳（platform/post/create），
  // 真正的内容在 iframe（micro/content/post/create）——所有表单操作必须走 iframe。
  let iframe = null;
  for (let i = 0; i < 10 && !iframe; i++) {
    iframe = page.frames().find((f) => f.url().includes('micro/content/post'));
    if (!iframe) await page.waitForTimeout(500);
  }
  return { ctx, page, iframe };
}

// 点掉新手引导浮层（只点「我知道了」；「取消/保存」等是表单组件按钮，绝不能误点）
async function closeModals(page, iframe) {
  for (const f of [iframe, page]) {
    if (!f) continue;
    try {
      const clicked = await f.evaluate(() => {
        const done = [];
        const all = [...document.querySelectorAll('button, [role=button]')];
        for (const el of all) {
          const t = (el.innerText || el.textContent || '').trim();
          if (t === '我知道了') { el.click(); done.push(t); }
        }
        return done;
      });
      if (clicked.length) log('MODAL', `关闭引导浮层: ${clicked.length} 个`);
    } catch (e) { /* ignore */ }
  }
  await page.waitForTimeout(500);
}

// 复刻 163 publish_service._wait_for_upload：等真实 video 预览出现（带时长）——查 iframe 内
async function waitForUpload(iframe, timeoutSec = 600) {
  log('UPLOAD', '等待上传完成（iframe video 预览出现）...');
  const deadline = Date.now() + timeoutSec * 1000;
  while (Date.now() < deadline) {
    try {
      const info = await iframe.evaluate(() => {
        const v = document.querySelector('video[src], video source[src], [class*="preview"] video');
        if (!v) return null;
        const src = v.src || (v.querySelector('source') && v.querySelector('source').src) || '';
        return { ready: v.readyState, dur: v.duration || 0, src: src.slice(0, 80) };
      });
      if (info && info.src && info.ready >= 2 && info.dur > 0) {
        log('UPLOAD', `上传完成：duration=${info.dur}s`);
        await iframe.waitForTimeout(3000);
        return true;
      }
    } catch (e) { /* 页面可能还在跳转 */ }
    await iframe.waitForTimeout(3000);
  }
  throw new Error('上传超时（无 video 预览）');
}

async function uploadVideo(page, iframe, videoPath) {
  await page.waitForTimeout(3000);
  let uploaded = false;
  try {
    // 优先：点击 ant-upload 上传区触发 file chooser 并 set_files（最接近真人；filechooser 在 page 级）
    const zone = iframe.locator("[class*='upload'], [class*='upload-area'], [class*='upload-box']").first();
    const fcPromise = page.waitForEvent('filechooser', { timeout: 15000 }).catch(() => null);
    try {
      await zone.click({ timeout: 10000 });
    } catch (e) {
      log('UPLOAD', `上传区点击失败: ${e.message}`);
    }
    const fc = await fcPromise;
    if (fc) {
      await fc.setFiles(videoPath);
      uploaded = true;
      log('UPLOAD', 'file chooser set_files 注入成功');
    } else {
      log('UPLOAD', '未捕获 file chooser，走 input setInputFiles 兜底');
    }
  } catch (e) {
    log('UPLOAD', `file chooser 路径异常: ${e.message}`);
  }
  if (!uploaded) {
    try {
      // 直接对视频 accept 的 input 注入（iframe 内唯一 input[type=file]）
      await iframe.locator("input[type='file'][accept*='video']").first().setInputFiles(videoPath, { timeout: 60000 });
      uploaded = true;
      log('UPLOAD', 'input[type=file] setInputFiles 注入成功');
    } catch (e) {
      throw new Error('找不到视频上传 input');
    }
  }
  await waitForUpload(iframe);
}

// 简化风险探测：常见风控/限制文案
const RISK_PATTERNS = [
  { re: /操作过于频繁|频繁|稍后再试/, type: 'upload_limited' },
  { re: /环境异常|风险|异常登录|不安全/, type: 'env_risk' },
  { re: /重新登录|登录已过期|请登录/, type: 'need_login' },
  { re: /内容涉嫌|违规|审核不通过/, type: 'content_blocked' },
];

async function probeRisk(iframe) {
  try {
    const text = await iframe.evaluate(() => document.body.innerText.slice(0, 20000));
    for (const p of RISK_PATTERNS) {
      if (p.re.test(text)) return p.type;
    }
  } catch (e) { /* ignore */ }
  return null;
}

async function isLoginPage(page) {
  const url = page.url();
  if (url.includes('login') || url.includes('safety')) return true;
  const html = await page.content().catch(() => '');
  return /login|扫码登录|二维码/.test(html.slice(0, 20000)) && !url.includes('post/create');
}

async function waitForLogin(page, cfg) {
  const deadline = Date.now() + cfg.LOGIN_WAIT_SEC * 1000;
  log('LOGIN', '检测到未登录，请在 Edge 窗口中用手机微信扫码登录视频号助手...');
  while (Date.now() < deadline) {
    await page.waitForTimeout(3000);
    const url = page.url();
    if (url.includes('post/create')) {
      log('LOGIN', '登录成功（已进入发布页）');
      return true;
    }
    // 刷新登录页触发状态确认
    if (Date.now() > deadline - 10000) break;
  }
  return false;
}

/* ───────────────────────── 发布流程 ───────────────────────── */
async function publishOne(cfg, task) {
  const taskId = task.id;
  const outputId = task.output_id;
  const title = task.title || '视频';
  const desc = task.description || '';
  log('TASK', `开始处理 ${taskId} output=${outputId} title=${title}`);

  // 1. 领取
  await callbackResult(cfg, taskId, { status: 'processing' });

  // 2. 查 output → file_key / presigned_url
  let outInfo;
  try {
    outInfo = await apiGet(cfg, `/api/slice-outputs/${outputId}`);
  } catch (e) {
    await callbackResult(cfg, taskId, { status: 'failed', error_message: `查 output 失败: ${e.message}` });
    return;
  }
  if (!outInfo.presigned_url && !outInfo.file_key) {
    await callbackResult(cfg, taskId, { status: 'failed', error_message: 'output 无下载地址' });
    return;
  }

  // 3. 下载视频（优先 presigned URL，无需 MinIO 签名）
  const safeName = `${taskId.slice(0, 8)}_${Date.now()}.mp4`;
  const localVideo = path.join(cfg.WORK_DIR, safeName);
  try {
    fs.mkdirSync(cfg.WORK_DIR, { recursive: true });
    const url = outInfo.presigned_url || `http://192.168.1.163:9000/sliced/${outInfo.file_key}`;
    const size = await downloadFile(url, localVideo);
    log('DOWNLOAD', `视频下载完成 ${(size / 1024 / 1024).toFixed(1)}MB`);
  } catch (e) {
    await callbackResult(cfg, taskId, { status: 'failed', error_message: `下载视频失败: ${e.message}` });
    return;
  }

  // 4. Edge + 发布页
  let ctx, page, iframe;
  try {
    await ensureBrowser(cfg);
    ({ ctx, page, iframe } = await connectPage(cfg));
    await page.goto(cfg.CREATOR_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(3000);
    // iframe 可能因导航重建，重新获取
    iframe = page.frames().find((f) => f.url().includes('micro/content/post'));
    if (!iframe) {
      for (let i = 0; i < 8 && !iframe; i++) { await page.waitForTimeout(500); iframe = page.frames().find((f) => f.url().includes('micro/content/post')); }
    }
    if (!iframe) throw new Error('未找到发布页 iframe');
    await closeModals(page, iframe);
    log('PAGE', `发布页就绪 url=${page.url().slice(0, 60)}`);
  } catch (e) {
    await callbackResult(cfg, taskId, { status: 'failed', error_message: `打开发布页失败: ${e.message}` });
    return;
  }

  try {
    // 5. 登录检查（本机 Edge profile 首次需扫码）
    if (await isLoginPage(page)) {
      const ok = await waitForLogin(page, cfg);
      if (!ok) {
        await callbackResult(cfg, taskId, {
          status: 'failed',
          error_message: '等待扫码登录超时（首次使用需在本机 Edge 扫码登录视频号助手）',
          risk_type: 'need_login',
        });
        return;
      }
      iframe = page.frames().find((f) => f.url().includes('micro/content/post'));
    }

    // 6. 上传前风险探测 + 关弹窗
    await closeModals(page, iframe);
    const preRisk = await probeRisk(iframe);
    if (preRisk) {
      await callbackResult(cfg, taskId, { status: 'failed', error_message: `pre-upload risk: ${preRisk}`, risk_type: preRisk });
      return;
    }

    // 7. 上传
    await uploadVideo(page, iframe, localVideo);
    await closeModals(page, iframe);

    // 8. 填标题/描述（iframe 内）
    try {
      const titleBox = iframe.locator("input[placeholder*='标题']").first();
      await titleBox.click({ timeout: 8000 });
      await titleBox.fill(title.slice(0, 60));
      log('FORM', `标题已填: ${title.slice(0, 30)}`);
    } catch (e) {
      log('FORM', `填标题失败(继续): ${e.message}`);
    }
    if (desc) {
      try {
        // 描述区：视频号是富文本/文本域，尝试 contenteditable
        const descBox = iframe.locator("[contenteditable='true'], textarea").first();
        await descBox.click({ timeout: 8000 });
        await descBox.fill(desc.slice(0, 1000));
        log('FORM', '描述已填');
      } catch (e) {
        log('FORM', `填描述失败(继续): ${e.message}`);
      }
    }

    // 9. 截图（iframe 内）
    try {
      const shot = path.join(cfg.WORK_DIR, `${taskId.slice(0, 8)}_shot.png`);
      await iframe.screenshot({ path: shot, fullPage: false });
      log('SHOT', `截图: ${shot}`);
    } catch (e) { log('SHOT', `截图失败: ${e.message}`); }

    // 10. 发布（AUTO_PUBLISH=false 时停在待确认）
    if (cfg.AUTO_PUBLISH) {
      await closeModals(page, iframe);
      const publishBtn = iframe.getByRole('button', { name: /发表|发\s*布/, exact: false }).first();
      await publishBtn.click({ timeout: 10000 });
      log('PUBLISH', '已点击发表按钮，等待结果...');
      await page.waitForTimeout(6000);
      // 发表后可能出现确认弹窗/成功提示
      await closeModals(page, iframe);
      const riskAfter = await probeRisk(iframe);
      if (riskAfter) {
        await callbackResult(cfg, taskId, { status: 'failed', error_message: `发布后风险: ${riskAfter}`, risk_type: riskAfter });
        return;
      }
      const finalUrl = page.url();
      await callbackResult(cfg, taskId, { status: 'completed', published_url: finalUrl });
      log('TASK', `✅ 任务完成: ${taskId}`);
    } else {
      await callbackResult(cfg, taskId, { status: 'pending_confirm' });
      log('TASK', `任务停在待确认: ${taskId}`);
    }
  } catch (e) {
    const risk = await probeRisk(iframe).catch(() => null);
    await callbackResult(cfg, taskId, {
      status: 'failed',
      error_message: `${e.message}${risk ? ` (risk=${risk})` : ''}`,
      risk_type: risk || undefined,
    });
    log('TASK', `❌ 任务失败: ${taskId} -> ${e.message}`);
  } finally {
    try { await ctx.close(); } catch (e) { /* ignore */ }
    try { fs.unlinkSync(localVideo); } catch (e) { /* keep for debug */ }
  }
}

/* ───────────────────────── 主循环 ───────────────────────── */
async function listPending(cfg) {
  const tasks = await apiGet(cfg, '/api/publish/tasks?executor=local&status=pending&platform=wechat_channel');
  return Array.isArray(tasks) ? tasks : [];
}

async function main() {
  const cfg = loadEnv();
  const args = process.argv.slice(2);
  if (args.includes('--list')) {
    const tasks = await listPending(cfg);
    console.log(`pending local 任务: ${tasks.length}`);
    for (const t of tasks) console.log(` - ${t.id} | ${t.title} | output=${t.output_id}`);
    return;
  }
  if (args.includes('--login-only')) {
    await ensureBrowser(cfg);
    const { ctx, page } = await connectPage(cfg);
    await page.goto(cfg.CREATOR_URL, { waitUntil: 'domcontentloaded' });
    log('LOGIN', '已打开视频号助手，请扫码登录（Edge 窗口会显示）');
    const ok = await waitForLogin(page, cfg);
    log('LOGIN', ok ? '登录成功' : '等待超时');
    await ctx.close();
    return;
  }
  if (args.includes('--once')) {
    const tasks = await listPending(cfg);
    if (!tasks.length) { log('POLL', '无待处理任务'); return; }
    await publishOne(cfg, tasks[0]);
    return;
  }
  log('POLL', `开始轮询 163 local 任务（间隔 ${cfg.POLL_INTERVAL}s，AUTO_PUBLISH=${cfg.AUTO_PUBLISH}）`);
  while (true) {
    try {
      const tasks = await listPending(cfg);
      if (tasks.length) {
        log('POLL', `发现 ${tasks.length} 个待处理任务`);
        for (const t of tasks) await publishOne(cfg, t);
      }
    } catch (e) {
      log('POLL', `轮询出错: ${e.message}`);
    }
    await new Promise((r) => setTimeout(r, cfg.POLL_INTERVAL * 1000));
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
