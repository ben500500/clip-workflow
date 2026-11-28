import React, { useState } from 'react';
import { Button, Space, message } from 'antd';
import { createRoot } from 'react-dom/client';
import AssetOutputWall from '../src/components/assets/AssetOutputWall';
import { assetApi } from '../src/api/assets';

/** 只承载真实业务组件；所有网络时序由 5199 mock 控制，不替代组件逻辑。 */
export default function FailedDeleteHarness() {
  const material = new URLSearchParams(window.location.search).get('role') === 'material';
  const currentUserId = '00000000-0000-4000-8000-000000000099';
  const [mounted, setMounted] = useState(true);
  const [tab, setTab] = useState<'wall' | 'other'>('wall');
  const [epoch, setEpoch] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);
  const produce = async () => {
    try {
      await assetApi.produceFromScripts({ script_ids: ['00000000-0000-4000-8000-0000000000s1'], board_total: 1 });
      setReloadToken((n) => n + 1);
      message.success('投板已受理');
    } catch (error) {
      message.error((error as Error).message);
    }
  };
  return (
    <div style={{ padding: 16 }}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button data-testid="fd-tab-wall" onClick={() => setTab('wall')}>墙页签</Button>
        <Button data-testid="fd-tab-other" onClick={() => setTab('other')}>其他页签</Button>
        <Button data-testid="fd-reload" onClick={() => setReloadToken((n) => n + 1)}>触发真实 GET</Button>
        <Button data-testid="fd-remount" onClick={() => setEpoch((n) => n + 1)}>remount 组件</Button>
        <Button data-testid="fd-unmount" onClick={() => setMounted(false)}>卸载组件</Button>
        <Button data-testid="fd-mount" onClick={() => setMounted(true)}>挂载组件</Button>
        <Button data-testid="fd-produce" onClick={() => void produce()}>模拟投豆包</Button>
      </Space>
      <div data-testid="fd-mounted" data-value={mounted ? '1' : '0'} data-tab={tab}>
        {mounted && tab === 'wall' && (
          <AssetOutputWall
            key={epoch}
            ownerDefault="all"
            active
            reloadToken={reloadToken}
            canCancel
            canCancelOthers={!material}
            currentUserId={currentUserId}
            includeCreating
          />
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<FailedDeleteHarness />);
