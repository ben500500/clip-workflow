import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Drawer, Input, Modal, Popconfirm, Radio, Space, Switch, Table, Tag, Typography, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { assetApi } from '../../api/assets';
import type {
  AssetOverlayParams, AssetOverlayPreset, AssetOverlayScope, OverlayPresetListResult,
} from '../../api/assets';
import { HelpDot, MonoText } from './AssetBits';
import {
  OverlayParamsEditor, emptyOverlay, overlayBriefText, overlayIsEmpty,
} from './AssetOverlayBits';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
  /** 管理员才能把预设放开给全员（后端 403 的口径，界面先把选项收掉） */
  isAdmin: boolean;
  /** 选定一套后带回给调用方（组合导出屏用；纯管理预设时可以不传） */
  onPick?: (preset: AssetOverlayPreset) => void;
}

interface Draft {
  id: string | null;
  name: string;
  scope: AssetOverlayScope;
  note: string;
  params: AssetOverlayParams;
}

const blankDraft = (): Draft => ({ id: null, name: '', scope: 'user', note: '', params: emptyOverlay() });

const toDraft = (p: AssetOverlayPreset): Draft => ({
  id: p.id,
  name: p.name,
  scope: p.scope,
  note: p.note || '',
  params: { badges: p.params?.badges || [], text_overlays: p.params?.text_overlays || [] },
});

/**
 * 叠加预设抽屉（11-24 需求三 S4）。
 *
 * 预设＝「角标图 ＋ 固定文字」存成一套反复选。三条口径必须在界面上说清楚，
 * 都是一线会当成 bug 报的东西：
 *
 * 1. **改预设不回改历史片子**。组合导出把当时的参数快照写进了产物行
 *    （`asset_outputs.compose_meta`），所以对账以快照为准。改完预设以为老片子跟着变，
 *    是这张界面最容易引起的误会。
 * 2. **停用不是删除**。历史片子还认得当时用的哪套，所以后端只置 `active=false`；
 *    已停用的默认不列，勾「看已停用的」才出来，且选不了。
 * 3. **空壳存不了**。既没角标也没文字的那套＝「不叠加」，存进去会变成一个
 *    看着能选、选了等于没选的选项。
 *
 * 读侧：个人预设只有自己和管理员看得见，共享（全员可选）预设全员能用；
 * 设成共享只有管理员可以（后端 403）。
 */
const AssetOverlayPresetDrawer: React.FC<Props> = ({ open, onClose, isAdmin, onPick }) => {
  const [data, setData] = useState<OverlayPresetListResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);

  const fetch = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setData(await assetApi.listOverlayPresets(includeInactive));
    } catch (e) {
      setLoadError((e as Error).message || '预设列表读不到');
    } finally {
      setLoading(false);
    }
  }, [includeInactive]);

  useEffect(() => {
    if (open) void fetch();
  }, [open, fetch]);

  const rows = data?.items || [];

  const save = async () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      message.warning('先给这套预设起个名（比如「剧名＋后果自负」）');
      return;
    }
    if (overlayIsEmpty(draft.params)) {
      message.warning('至少加一个角标或一行字——什么都不叠的那套不用存，选「不叠加」就行');
      return;
    }
    setBusy(true);
    try {
      const body = {
        name: draft.name.trim(),
        scope: draft.scope,
        params: draft.params,
        note: draft.note.trim() || undefined,
      };
      const saved = draft.id
        ? await assetApi.updateOverlayPreset(draft.id, body)
        : await assetApi.createOverlayPreset(body);
      message.success(draft.id ? `已更新「${saved.name}」（已出过的片子不会跟着变）` : `已存好「${saved.name}」`);
      setDraft(null);
      void fetch();
    } catch (e) {
      // 409 同名 / 400 空壳 / 403 非管理员设共享，后端话术已经带指路，原样回显最有用
      message.error((e as Error).message || '保存失败', 8);
    } finally {
      setBusy(false);
    }
  };

  const columns: ColumnsType<AssetOverlayPreset> = useMemo(
    () => [
      {
        title: '名称',
        dataIndex: 'name',
        width: 170,
        render: (v: string, r) => (
          <Space direction="vertical" size={0}>
            <Text strong style={{ fontSize: 13 }}>{v}</Text>
            {!r.active && <Tag>已停用</Tag>}
          </Space>
        ),
      },
      {
        title: '叠什么',
        dataIndex: 'summary',
        render: (v: string, r) => (
          <Space direction="vertical" size={0}>
            <Text style={{ fontSize: 12 }}>{v || '不叠加'}</Text>
            {r.note && (
              <Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: r.note }}>
                {r.note}
              </Text>
            )}
          </Space>
        ),
      },
      {
        title: '谁能用',
        dataIndex: 'scope',
        width: 130,
        render: (v: string, r) =>
          v === 'shared' ? (
            <Tag color="blue">全员可选</Tag>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>仅自己{r.owner_name ? `（${r.owner_name}）` : ''}</Text>
          ),
      },
      {
        title: '操作',
        key: 'ops',
        width: 190,
        render: (_: unknown, r) => (
          <Space size={4}>
            {!!onPick && r.active && (
              <Button size="small" type="link" onClick={() => { onPick(r); onClose(); }}>
                用这套
              </Button>
            )}
            <Button size="small" type="link" icon={<EditOutlined />} onClick={() => setDraft(toDraft(r))}>
              编辑
            </Button>
            {r.active ? (
              <Popconfirm
                title="停用这套预设？"
                description={
                  <span style={{ fontSize: 12 }}>
                    停用不是删除：以前用它出的片子仍认得当时叠的是什么，
                    只是以后选不到了。要找回原样，进编辑另存一套即可。
                  </span>
                }
                okText="停用"
                cancelText="先不停"
                onConfirm={async () => {
                  try {
                    const res = await assetApi.deactivateOverlayPreset(r.id);
                    message.success(res.message || `已停用「${r.name}」`);
                    void fetch();
                  } catch (e) {
                    message.error((e as Error).message || '停用没成', 8);
                  }
                }}
              >
                <Button size="small" type="link" danger icon={<DeleteOutlined />}>
                  停用
                </Button>
              </Popconfirm>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>已停用，选不了</Text>
            )}
          </Space>
        ),
      },
    ],
    [fetch, onPick, onClose],
  );

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={draft ? 860 : 720}
      title={
        <Space size={6}>
          叠加预设
          <HelpDot text="一套预设＝固定那几个角标图和固定文字，出片时选一下就行，不用每批重调。个人预设只有自己能看见；「全员可选」要管理员来设。改预设不会回改已经出过的片子——那些片子存的是当时的参数快照。" />
        </Space>
      }
      extra={(
        <Space size={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>看已停用的</Text>
          <Switch size="small" checked={includeInactive} onChange={setIncludeInactive} />
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void fetch()} />
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setDraft(blankDraft())}>
            新建一套
          </Button>
        </Space>
      )}
    >
      {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 12 }} />}
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{
          emptyText: '还没有预设。角标图要先传到素材库（图片类型），再回来「新建一套」挑图。',
        }}
      />
      {!!rows.length && (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          共 {rows.length} 套（{rows.filter((r) => r.scope === 'shared').length} 套全员可选）。
          历史片子以「当时的快照」对账，改这里不会回改它们。
        </Text>
      )}

      <Modal
        open={!!draft}
        width={820}
        title={draft?.id ? `编辑预设：${draft.name}` : '新建一套叠加预设'}
        okText={draft?.id ? '保存修改' : '存这套'}
        okButtonProps={{ loading: busy, icon: <SaveOutlined /> }}
        onOk={save}
        onCancel={() => setDraft(null)}
        destroyOnClose
        maskClosable={false}
      >
        {draft && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap size={12}>
              <Input
                style={{ width: 240 }}
                maxLength={60}
                placeholder="预设名，如「剧名＋后果自负」"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
              <Radio.Group
                value={draft.scope}
                onChange={(e) => setDraft({ ...draft, scope: e.target.value as AssetOverlayScope })}
              >
                <Radio value="user">仅自己</Radio>
                <Radio value="shared" disabled={!isAdmin}>全员可选</Radio>
              </Radio.Group>
            </Space>
            {!isAdmin && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                「全员可选」只有管理员能设——共享出去会影响别人的出片外观。
              </Text>
            )}
            <Input
              maxLength={500}
              placeholder="备注：这套用在什么片上（选不出的时候靠它认）"
              value={draft.note}
              onChange={(e) => setDraft({ ...draft, note: e.target.value })}
            />

            <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12 }}>
              <Space size={6} style={{ marginBottom: 8 }}>
                <Text strong>这套叠什么</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>现在：{overlayBriefText(draft.params)}</Text>
              </Space>
              <OverlayParamsEditor
                active
                value={draft.params}
                onChange={(params) => setDraft({ ...draft, params })}
                positions={data?.positions}
                limits={{
                  maxBadges: data?.max_badges ?? 6,
                  maxTexts: data?.max_text_overlays ?? 6,
                  maxChars: data?.max_text_chars ?? 30,
                }}
              />
            </div>

            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
              存下来之后，组合导出那一屏选一下就能用；也可以在现场调完再「另存为预设」。
              已出过的片子存的是当时的参数快照，改这里不回改它们。
              预设 id：<MonoText>{draft.id || '（新建，保存后生成）'}</MonoText>
            </Paragraph>
          </Space>
        )}
      </Modal>
    </Drawer>
  );
};

export default AssetOverlayPresetDrawer;
