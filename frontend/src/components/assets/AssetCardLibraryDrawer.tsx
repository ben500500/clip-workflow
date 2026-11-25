import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Drawer, Empty, Image, Input, Popconfirm, Space, Spin, Tag, Tooltip, Typography, Upload, message } from 'antd';
import { InboxOutlined, PictureOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetCard } from '../../api/assets';
import { aspectShortText } from './AssetBits';

const { Text } = Typography;

/**
 * 「角色卡」库抽屉（11-25 批 W）：图片不再当素材入库后的统一管理入口。
 *
 * 为什么是抽屉不是页签：卡只有「传/改名/删」三件事，没有一个"流程"值得占一整个页签；
 * 挑卡器（投产弹窗/开单屏）只管挑，管传管删的入口收在这里一处，和钩子原型字典同款布局。
 * 删卡的后端闸门（挂着生产单拒删）在这里只负责把 400 话术透传出来。
 */
const AssetCardLibraryDrawer: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const [cards, setCards] = useState<AssetCard[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [renaming, setRenaming] = useState<AssetCard | null>(null);
  const [renameText, setRenameText] = useState('');

  const load = useCallback(async (kw?: string) => {
    setLoading(true);
    try {
      const res = await assetApi.listCards({ q: kw || undefined, page_size: 300 });
      setCards(res.items || []);
      setTotal(res.total || 0);
    } catch (e) {
      message.error((e as Error).message || '卡库列表拉不到');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const uploadCard = async (file: File) => {
    setUploading(true);
    try {
      const res = await assetApi.uploadCards([file]);
      if (res.items?.length) {
        message.success(`已入卡库：${res.items.map((a) => a.name || a.file_name).join('、')}`);
        const warns = (res.image_notes || []).filter((n) => n.notes?.length);
        if (warns.length) {
          message.warning(
            warns.map((n) => `${n.file_name || '图片'}：${n.notes.join('；')}`).join(' ｜ '),
            8,
          );
        }
        await load(q);
      }
      (res.failed || []).forEach((f) => message.error(`${f.file_name} 没传上：${f.error}`));
    } catch (e) {
      message.error((e as Error).message || '角色卡上传失败');
    } finally {
      setUploading(false);
    }
    return false;
  };

  const doRename = async () => {
    if (!renaming) return;
    try {
      await assetApi.updateCard(renaming.id, { name: renameText });
      message.success('卡名改好了');
      setRenaming(null);
      await load(q);
    } catch (e) {
      message.error((e as Error).message || '改名没成功');
    }
  };

  const doDelete = async (a: AssetCard) => {
    try {
      const res = await assetApi.deleteCard(a.id);
      message.success(`已删除 ${res.code}`);
      await load(q);
    } catch (e) {
      message.error((e as Error).message || '删除没成功');
    }
  };

  return (
    <Drawer
      title={
        <Space>
          <PictureOutlined />
          角色卡库
          <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            共 {total} 张·投产时当画中人挂给豆包；不占素材列表、不计费
          </Text>
        </Space>
      }
      open={open}
      onClose={onClose}
      width={720}
      destroyOnClose
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Input.Search
            placeholder="按卡名／编号搜"
            allowClear
            style={{ width: 260 }}
            onSearch={(v) => {
              setQ(v);
              void load(v);
            }}
          />
          <Upload.Dragger
            accept="image/jpeg,image/png,image/webp"
            multiple
            showUploadList={false}
            disabled={uploading}
            style={{ padding: '2px 10px', width: 300 }}
            beforeUpload={(f) => {
              void uploadCard(f as unknown as File);
              return false;
            }}
          >
            <Text style={{ fontSize: 12 }}>
              {uploading ? '正在上传…' : '拖图片进来或点击上传（jpg/png，可多张）'}
            </Text>
          </Upload.Dragger>
        </Space>

        {loading && !cards.length ? (
          <Spin style={{ display: 'block', margin: '40px auto' }} />
        ) : !cards.length ? (
          <Empty description={q ? `没搜到「${q}」` : '卡库还是空的：拖一张三视图进来'} />
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {cards.map((a) => {
              const land = a.aspect?.orientation === 'landscape';
              return (
                <div
                  key={a.id}
                  style={{
                    width: 150,
                    border: `1px solid ${land ? '#ffa39e' : '#d9d9d9'}`,
                    borderRadius: 6,
                    padding: 6,
                    background: '#fff',
                  }}
                >
                  {a.preview_url ? (
                    <Image
                      src={a.preview_url}
                      alt={a.name}
                      style={{ width: '100%', height: 110, objectFit: 'contain', display: 'block', background: '#fafafa' }}
                    />
                  ) : (
                    <div
                      style={{
                        width: '100%', height: 110, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        border: '1px dashed #d9d9d9', color: '#bfbfbf', fontSize: 11,
                      }}
                    >
                      图打不开
                    </div>
                  )}
                  <Tooltip title={`${a.code}｜${a.file_name || ''}${a.note ? `｜${a.note}` : ''}`}>
                    <div style={{ fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 4 }}>
                      {a.name}
                    </div>
                  </Tooltip>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
                    <Tag color={land ? 'red' : a.aspect?.ratio ? 'green' : 'orange'} style={{ marginInlineEnd: 0 }}>
                      {aspectShortText(a.aspect)}
                    </Tag>
                    <Space size={0}>
                      <Button
                        size="small"
                        type="text"
                        onClick={() => {
                          setRenaming(a);
                          setRenameText(a.name);
                        }}
                      >
                        改名
                      </Button>
                      <Popconfirm
                        title={`删除 ${a.name}？`}
                        description="挂着它的生产单会先被拦下；确认卡没在用再删。"
                        onConfirm={() => void doDelete(a)}
                      >
                        <Button size="small" type="text" danger>
                          删
                        </Button>
                      </Popconfirm>
                    </Space>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {renaming && (
          <Alert
            type="info"
            showIcon
            message={
              <Space>
                改卡名（只影响显示，投板带的是图本身）：
                <Input
                  value={renameText}
                  style={{ width: 260 }}
                  onChange={(e) => setRenameText(e.target.value)}
                  onPressEnter={() => void doRename()}
                />
                <Button size="small" type="primary" onClick={() => void doRename()}>
                  保存
                </Button>
                <Button size="small" onClick={() => setRenaming(null)}>
                  取消
                </Button>
              </Space>
            }
          />
        )}
      </Space>
    </Drawer>
  );
};

export default AssetCardLibraryDrawer;
