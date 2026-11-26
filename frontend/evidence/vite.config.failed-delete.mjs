import react from '@vitejs/plugin-react';
import { execFileSync } from 'node:child_process';
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';

const ROOT = '/tmp/clip-material-produce-fix';
const STATE = '/tmp/failed-delete-state.json';
const MODE = '/tmp/failed-delete-mode.txt';
const REFRESH_MODE = '/tmp/failed-delete-refresh-mode.txt';
const HITS = '/tmp/failed-delete-hits.log';
const EVENTS = '/tmp/failed-delete-events.jsonl';
const CONTROL = '/tmp/failed-delete-control.json';
const inflightPath = '/api/assets/outputs/inflight';
const cancelPath = '/api/assets/productions/';
const A = '00000000-0000-4000-8000-000000000001';
const B = '00000000-0000-4000-8000-000000000002';

const row = (id, error, status = 'failed') => ({
  production_id: id, bucket: status === 'failed' ? 'failed' : 'generating', status,
  hook_code: id === A ? 'ZZ901' : 'ZZ902',
  asset_id: '5df558e7-e88e-4cf8-a225-88f8cfea8827', asset_code: 'AS-24DC5D8D',
  asset_title: '失败删单·隔离验收', batch_id: null, batch_code: null,
  owner_name: 'admin', board_tid: `CDP-${id.slice(-1)}`, board_name: '失败删单验收', board_total: 1,
  board_date: '2026-11-26T08:00:00+00:00', board_last_status: status,
  board_last_check_at: '2026-11-26T08:20:00+00:00', attempts: 1,
  dispatched_at: '2026-11-26T08:00:00+00:00', minutes_since_dispatch: 20,
  created_at: '2026-11-26T08:00:00+00:00', error,
  failed_at: status === 'failed' ? '2026-11-26T08:20:00+00:00' : null,
  minutes_since_failed: status === 'failed' ? 1 : null,
});

const seed = () => ({
  items: [row(A, '内容审核未通过：角色卡不符'), row(B, '生成失败：隔离验收错误路径')],
  inflight_total: 0, failed_total: 2, failed_older: 0,
  failed_window_hours: 24, slow_after_minutes: 45,
});
const scenarios = {
  default: seed,
  mixed: () => ({ ...seed(), items: [row(A, '内容审核未通过：角色卡不符'), row(B, '在途隔离验收', 'running')], inflight_total: 1 }),
  twoGenerating: () => ({ ...seed(), items: [row(A, '在途隔离验收 A', 'running'), row(B, '在途隔离验收 B', 'queued')], inflight_total: 2, failed_total: 0 }),
};
const readJson = (path, fallback) => { try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return fallback; } };
const readText = (path, fallback) => { try { return readFileSync(path, 'utf8').trim(); } catch { return fallback; } };
const writeJson = (path, value) => writeFileSync(path, JSON.stringify(value));
const event = (value) => appendFileSync(EVENTS, `${JSON.stringify({ at: Date.now(), ...value })}\n`);
const json = (res, status, body) => {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(body));
};
const reset = (scenario = 'default') => {
  writeJson(STATE, (scenarios[scenario] || scenarios.default)());
  writeFileSync(MODE, 'ok');
  writeFileSync(REFRESH_MODE, 'ok');
  writeFileSync(HITS, '');
  writeFileSync(EVENTS, '');
  writeJson(CONTROL, { role: 'admin', can_review: true, can_produce: true, gets: [], posts: [] });
};

try { reset(); } catch {}

function stubFailedDelete() {
  const install = (server) => {
    server.middlewares.use((req, res, next) => {
      const url = String(req.url || '');
      if (req.method === 'POST' && url === '/__fd/reset') {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', () => {
          try { reset(JSON.parse(body || '{}').scenario); } catch { reset(); }
          json(res, 200, { ok: true });
        });
        return;
      }
      if (req.method === 'POST' && url === '/__fd/control') {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', () => {
          const patch = JSON.parse(body || '{}');
          writeJson(CONTROL, { ...readJson(CONTROL, {}), ...patch });
          json(res, 200, readJson(CONTROL, {}));
        });
        return;
      }
      if (req.method === 'GET' && url === '/__fd/events') {
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(readFileSync(EVENTS, 'utf8').trim().split('\n').filter(Boolean).map((line) => JSON.parse(line)).map((line) => JSON.stringify(line)).join('\n'));
        return;
      }
      if (url === '/__fd/harness') {
        res.statusCode = 200;
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.end('<!doctype html><html><head><meta charset="UTF-8"><title>FD race harness</title></head><body><div id="root"></div><script type="module">import RefreshRuntime from "/@react-refresh";RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>(type)=>type;window.__vite_plugin_react_preamble_installed__=true;</script><script type="module" src="/evidence/failed-delete-harness.tsx"></script></body></html>');
        return;
      }
      if (req.method === 'GET' && url.startsWith('/api/auth/me')) {
        const c = readJson(CONTROL, {});
        json(res, 200, {
          id: '00000000-0000-4000-8000-000000000099', username: c.role === 'admin' ? 'admin' : c.role,
          role: c.role || 'admin', is_active: true,
          can_review: c.can_review !== false, can_produce: c.can_produce !== false,
        });
        return;
      }
      if (req.method === 'GET' && url.startsWith(inflightPath)) {
        const c = readJson(CONTROL, {});
        const queue = Array.isArray(c.gets) ? c.gets : [];
        const legacyRefresh = readText(REFRESH_MODE, 'ok');
        const plan = queue.length ? queue.shift()
          : legacyRefresh === 'error' ? { status: 503, detail: '隔离验收：删单后的刷新失败' }
            : legacyRefresh === 'stale' ? { snapshot: 'seed' } : {};
        if (queue.length !== (Array.isArray(c.gets) ? c.gets.length : 0)) writeJson(CONTROL, { ...c, gets: queue });
        const captured = readJson(STATE, seed());
        event({ kind: 'get-start', url, plan });
        const respond = () => {
          if (plan.status) {
            event({ kind: 'get-end', status: plan.status });
            json(res, plan.status, { detail: plan.detail || '隔离验收：GET 失败' });
            return;
          }
          const source = plan.snapshot === 'seed' ? seed()
            : plan.snapshot === 'mixed' ? scenarios.mixed()
              : plan.snapshot === 'live' ? readJson(STATE, seed()) : captured;
          let items = [...(source.items || [])];
          const omit = Array.isArray(plan.omit) ? plan.omit : [];
          items = items.filter((item) => !omit.includes(item.production_id));
          if (Number.isFinite(plan.limit)) items = items.slice(0, plan.limit);
          const body = plan.counts && typeof plan.counts === 'object'
            ? { ...source, ...plan.counts, items }
            : {
                ...source, items,
                inflight_total: source.inflight_total ?? source.items.filter((i) => i.bucket !== 'failed').length,
                failed_total: source.failed_total ?? source.items.filter((i) => i.bucket === 'failed').length,
              };
          event({ kind: 'get-end', status: 200, ids: items.map((i) => i.production_id) });
          json(res, 200, body);
        };
        if (plan.delay) setTimeout(respond, plan.delay); else respond();
        return;
      }
      if (req.method === 'POST' && url.startsWith(cancelPath) && url.endsWith('/cancel')) {
        const id = url.slice(cancelPath.length).split('/')[0];
        const c = readJson(CONTROL, {});
        const queue = Array.isArray(c.posts) ? c.posts : [];
        const plan = queue.length ? queue.shift() : {};
        if (queue.length !== (Array.isArray(c.posts) ? c.posts.length : 0)) writeJson(CONTROL, { ...c, posts: queue });
        const mode = plan.mode || readText(MODE, 'ok');
        appendFileSync(HITS, `${id} ${mode}\n`);
        event({ kind: 'post-start', id, mode, plan });
        const details = {
          forbidden: [403, '无投产权限：隔离验收 403'],
          missing: [404, '生产单不存在：隔离验收 404'],
          conflict: [409, '状态已变化：隔离验收 409'],
          error: [409, '删单失败：隔离验收错误路径'],
          server: [500, '服务暂时不可用：隔离验收 500'],
        };
        const respond = () => {
          if (details[mode]) {
            const [status, detail] = details[mode];
            event({ kind: 'post-end', id, mode, status });
            json(res, status, { detail });
            return;
          }
          if (plan.status) {
            event({ kind: 'post-end', id, mode, status: plan.status });
            json(res, plan.status, { detail: plan.detail || '隔离验收失败' });
            return;
          }
          const state = readJson(STATE, seed());
          const found = state.items.find((x) => x.production_id === id);
          if (!found) {
            event({ kind: 'post-end', id, mode, status: 404 });
            json(res, 404, { detail: '生产单不存在' });
            return;
          }
          state.items = state.items.filter((x) => x.production_id !== id);
          writeJson(STATE, state);
          event({ kind: 'post-end', id, mode, status: 200 });
          json(res, 200, { ok: true, id, status: 'cancelled', error: `${found.error}；成片墙人工删单` });
        };
        // timeout 保留旧基线兼容：仍然返回 409；专项用 plan.status + delay 制造真实 60s 超时。
        if (mode === 'timeout' && !plan.delay && !plan.status) {
          event({ kind: 'post-end', id, mode, status: 409 });
          json(res, 409, { detail: '删单失败：隔离验收错误路径' });
          return;
        }
        if (plan.delay) setTimeout(respond, plan.delay); else respond();
        return;
      }
      if (url.startsWith('/api/')) {
        json(res, 200, req.method === 'GET' ? [] : {});
        return;
      }
      next();
    });
  };
  return { name: 'cdp-stub-failed-delete', configureServer: install, configurePreviewServer: install };
}

// A/B 反向验证仍从 git show HEAD 取组件源码，但保留原文件路径，避免改动业务文件或相对导入。
const headWall = process.env.FD_VARIANT === 'head'
  ? execFileSync('git', ['show', 'HEAD:frontend/src/components/assets/AssetOutputWall.tsx'], { cwd: ROOT, encoding: 'utf8' })
  : null;

export default {
  plugins: [react(), stubFailedDelete(), ...(headWall ? [{
    name: 'fd-head-component-ab',
    enforce: 'pre',
    transform(code, id) {
      if (id.replace(/\\/g, '/').endsWith('/frontend/src/components/assets/AssetOutputWall.tsx')) return headWall;
    },
  }] : [])],
  server: { host: '127.0.0.1', port: 5199, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true } } },
  preview: { host: '127.0.0.1', port: 5199, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true } } },
};
