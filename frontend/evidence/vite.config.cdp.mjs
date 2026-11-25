import react from '@vitejs/plugin-react';
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';

const PRODUCE = '/api/assets/scripts/produce';
const MODE = '/tmp/produce-mode.txt';
const HITS = '/tmp/produce-hits.log';
writeFileSync(MODE, 'off');
try { writeFileSync(HITS, ''); } catch {}

const fakeOk = () => ({
  production_ids: ['00000000-0000-0000-0000-000000000001'],
  results: [{
    script_id: '00000000-0000-0000-0000-0000000000s1',
    code: 'CDP-V-FAKE', ok: true,
    production_id: '00000000-0000-0000-0000-000000000001',
    hook_code: 'ZZ999', error: null,
  }],
  dispatch: { queued: true, job_id: 'cdp-fake-job' },
  message: '已投出 1 个脚本（每个出 3 版）——豆包出片约 25 分钟，成片回到成片墙',
});
const fakeBlocked = () => ({ detail: '一条都没投出去：（门禁用假回执）号池余额不够，本条没投出去' });

function stubProduce() {
  const install = (server) => {
    server.middlewares.use((req, res, next) => {
      if (req.method !== 'POST' || !String(req.url || '').startsWith(PRODUCE)) return next();
      let mode = 'off';
      try { mode = readFileSync(MODE, 'utf8').trim(); } catch {}
      if (mode === 'off') return next();
      appendFileSync(HITS, Date.now() + ' ' + mode + '\n');
      const blocked = mode === 'blocked';
      const body = JSON.stringify(blocked ? fakeBlocked() : fakeOk());
      res.statusCode = blocked ? 400 : 200;
      res.setHeader('Content-Type', 'application/json');
      res.setHeader('Content-Length', Buffer.byteLength(body));
      res.end(body);
    });
  };
  return { name: 'cdp-stub-produce', configureServer: install, configurePreviewServer: install };
}

const proxy = { '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true } };

export default {
  plugins: [react(), stubProduce()],
  server: { host: '127.0.0.1', port: 5199, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 5199, strictPort: true, proxy },
};
