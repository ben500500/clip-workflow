import React, { useState } from 'react';
import { Button, Space } from 'antd';
import { createRoot } from 'react-dom/client';
import AssetOutputWall from '../src/components/assets/AssetOutputWall';

/** 只承载真实业务组件；所有网络时序由 5199 mock 控制，不替代组件逻辑。 */
export default function FailedDeleteHarness() {
  const [mounted, setMounted] = useState(true);
  const [tab, setTab] = useState<'wall' | 'other'>('wall');
  const [epoch, setEpoch] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);
  return (
    <div style={{ padding: 16 }}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button data-testid="fd-tab-wall" onClick={() => setTab('wall')}>墙页签</Button>
        <Button data-testid="fd-tab-other" onClick={() => setTab('other')}>其他页签</Button>
        <Button data-testid="fd-reload" onClick={() => setReloadToken((n) => n + 1)}>触发真实 GET</Button>
        <Button data-testid="fd-remount" onClick={() => setEpoch((n) => n + 1)}>remount 组件</Button>
        <Button data-testid="fd-unmount" onClick={() => setMounted(false)}>卸载组件</Button>
        <Button data-testid="fd-mount" onClick={() => setMounted(true)}>挂载组件</Button>
      </Space>
      <div data-testid="fd-mounted" data-value={mounted ? '1' : '0'} data-tab={tab}>
        {mounted && tab === 'wall' && (
          <AssetOutputWall key={epoch} ownerDefault="all" active reloadToken={reloadToken} canCancel />
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<FailedDeleteHarness />);
