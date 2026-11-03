import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Descriptions, Divider, Drawer, Empty, List, Modal, Space, Spin, Tabs, Tag, Tooltip, Typography, message,
} from 'antd';
import { CopyOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetDetailResponse, AssetSourceDownloadResult } from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import {
  AssetStatusTag, AuditStatusTag, ProductionStateTag, RiskTags, StageTags, MonoText, durationText, yuan,
} from './AssetBits';
import { HOOK_STYLE_LABELS } from '../../api/assets';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  assetId: string | null;
  onClose: () => void;
  /** 抽屉里收敛了反推任务或回源解析后，通知列表重取 */
  onChanged?: () => void;
  /** 只有 material/operator/admin 才显示「回源解析」按钮；后端仍按角色拦 */
  canProduce?: boolean;
}

/**
 * 素材详情抽屉：一条素材的全链路状态 + 候选文案 + 生产单 + 反推详规。
 *
 * 一个 `GET /assets/{id}` 就把这四块带回来（详情与列表共用同一套计数字段），
 * 所以这里不必再发三次请求、也不必判 nil。
 */
const AssetDetailDrawer: React.FC<Props> = ({ open, assetId, onClose, onChanged, canProduce }) => {
  const [data, setData] = useState<AssetDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resolveBusy, setResolveBusy] = useState(false);

  const fetchDetail = useCallback(async (id: string) => {
    setLoading(true);
    try {
      setData(await assetApi.getAsset(id));
    } catch (e) {
      message.error((e as Error).message || '加载素材详情失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && assetId) fetchDetail(assetId);
    if (!open) setData(null);
  }, [open, assetId, fetchDetail]);

  const refreshPrompt = async () => {
    if (!assetId) return;
    setBusy(true);
    try {
      const res = await assetApi.refreshAssetPrompt(assetId);
      setData((prev) => (prev ? { ...prev, asset: res.asset, prompt_task: res.prompt_task } : prev));
      message.success(res.duration_note || '已收敛反推任务状态');
      onChanged?.();
    } catch (e) {
      message.error((e as Error).message || '收敛失败（该素材可能还没有反推任务）');
    } finally {
      setBusy(false);
    }
  };

  /** 单条回源解析：0.01 元/次，是「想知道这条到底多长」的唯一显式口子 */
  const resolveOne = async () => {
    if (!assetId) return;
    setResolveBusy(true);
    try {
      const res = await assetApi.resolveAssets({ asset_ids: [assetId] });
      const item = res.results?.[0];
      if (!item) {
        message.info(res.message);
      } else if (item.ok) {
        Modal.info({
          title: `回源解析完成（本条实扣 ${yuan(item.charged)}）`,
          width: 580,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>时长：{item.duration ? `${Math.round(item.duration)}s` : '仍未取到'}</Text>
              <Text>渠道：{item.channel || '-'}</Text>
              {item.title && <Text>标题：{item.title}</Text>}
              {item.note && <Alert type="warning" showIcon message={item.note} />}
              {item.play_url && (
                <Paragraph copyable={{ text: item.play_url }} ellipsis={{ rows: 2 }}>
                  <MonoText>{item.play_url}</MonoText>
                </Paragraph>
              )}
            </Space>
          ),
        });
      } else {
        message.error(item.error || item.note || '回源解析未拿到结果');
      }
      await fetchDetail(assetId);
      onChanged?.();
    } catch (e) {
      message.error((e as Error).message || '回源解析失败');
    } finally {
      setResolveBusy(false);
    }
  };

  const showSource = async () => {
    if (!assetId) return;
    try {
      const res: AssetSourceDownloadResult = await assetApi.downloadAssetSource(assetId);
      if (res.url) {
        window.open(res.url, '_blank');
        message.success(`已打开直链（${res.mode}，${res.expires_in ?? 3600}s 内有效）`);
      } else {
        Modal.info({
          title: '这条素材不在自有桶',
          width: 580,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text>{res.note}</Text>
              {res.source_url && (
                <Paragraph copyable={{ text: res.source_url }}>
                  <MonoText>{res.source_url}</MonoText>
                </Paragraph>
              )}
            </Space>
          ),
        });
      }
    } catch (e) {
      message.error((e as Error).message || '取原片链接失败');
    }
  };

  const asset = data?.asset;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={880}
      title={
        asset ? (
          <Space>
            <MonoText>{asset.code}</MonoText>
            <AssetStatusTag status={asset.status} />
            <StageTags asset={asset} />
          </Space>
        ) : (
          '素材详情'
        )
      }
      extra={
        <Space>
          <Button icon={<DownloadOutlined />} onClick={showSource} disabled={!asset}>
            原片
          </Button>
          {asset?.stage_prompt === 'running' && (
            <Button icon={<ReloadOutlined />} loading={busy} onClick={refreshPrompt}>
              收敛反推
            </Button>
          )}
          {canProduce && asset?.source_kind === 'link' && asset?.duration === null && (
            <Tooltip title="doc/107 按次 0.01 元，会计入批次成本">
              <Button loading={resolveBusy} onClick={resolveOne}>
                回源解析拿时长
              </Button>
            </Tooltip>
          )}
        </Space>
      }
    >
      {loading && !asset ? (
        <Spin style={{ display: 'block', margin: '60px auto' }} />
      ) : !asset ? (
        <Empty description="没有详情" />
      ) : (
        <>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="标题" span={2}>
              {asset.title || <Text type="secondary">（反推成功后才有标题）</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="来路">
              <Tag>{asset.source_kind === 'link' ? '链接' : '文件'}</Tag>
              {asset.platform || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="时长">{durationText(asset.duration)}</Descriptions.Item>
            <Descriptions.Item label="分辨率">{asset.resolution || '-'}</Descriptions.Item>
            <Descriptions.Item label="反推档位">
              {asset.prompt_max_duration ? `${asset.prompt_max_duration}s` : '未定档'}
            </Descriptions.Item>
            <Descriptions.Item label="文件">{asset.file_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="大小">
              {asset.file_size ? `${(asset.file_size / 1024 / 1024).toFixed(1)} MB` : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="成本" span={2}>
              反推 {yuan(asset.cost_prompt)} ｜ 回源解析 {yuan(asset.cost_parse)}
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                （cost_produce 在 P0 无写入方、恒 0，是留给 P1 的口子，别当预算看）
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="导入时间">
              {parseServerTime(asset.created_at)?.format('YYYY-MM-DD HH:mm') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="反推任务">
              {data?.prompt_task ? String(data.prompt_task.status) : '未提交'}
            </Descriptions.Item>
            <Descriptions.Item label="来源链接" span={2}>
              {asset.source_url ? (
                <Paragraph copyable={{ text: asset.source_url }} style={{ marginBottom: 0 }}>
                  <a href={asset.source_url} target="_blank" rel="noreferrer">
                    <MonoText>{asset.source_url}</MonoText>
                  </a>
                </Paragraph>
              ) : (
                '-'
              )}
            </Descriptions.Item>
            {asset.note && (
              <Descriptions.Item label="备注" span={2}>
                <Text style={{ whiteSpace: 'pre-wrap' }}>{asset.note}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>

          <Tabs
            style={{ marginTop: 16 }}
            items={[
              {
                key: 'script',
                label: `反推详规${data?.prompt_script ? '' : '（未出）'}`,
                children: data?.prompt_script ? (
                  <>
                    <Space style={{ marginBottom: 8 }}>
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => {
                          navigator.clipboard.writeText(data.prompt_script || '');
                          message.success('已复制反推详规');
                        }}
                      >
                        复制
                      </Button>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        出文案的输入就是这段；审核时怀疑文案编造，回来对这里
                      </Text>
                    </Space>
                    <Paragraph
                      style={{
                        whiteSpace: 'pre-wrap',
                        background: '#fafafa',
                        padding: 12,
                        borderRadius: 6,
                        maxHeight: 460,
                        overflow: 'auto',
                        fontSize: 12,
                      }}
                    >
                      {data.prompt_script}
                    </Paragraph>
                  </>
                ) : (
                  <Empty description="还没有反推详规（先跑反推）" />
                ),
              },
              {
                key: 'summaries',
                label: `候选文案（${data?.summaries?.length ?? 0}）`,
                children: (
                  <List
                    size="small"
                    dataSource={data?.summaries || []}
                    locale={{ emptyText: '还没有候选文案' }}
                    renderItem={(s) => (
                      <List.Item key={s.id}>
                        <Space direction="vertical" size={2} style={{ width: '100%' }}>
                          <Space wrap>
                            <Tag>#{s.seq}</Tag>
                            <AuditStatusTag status={s.audit_status} />
                            {s.is_recommended && <Tag color="green">推荐</Tag>}
                            {s.style_tag && <Tag>{HOOK_STYLE_LABELS[s.style_tag] || s.style_tag}</Tag>}
                            {s.formula_tag && <Tag color="geekblue">{s.formula_tag}</Tag>}
                            <Text type="secondary">{s.word_count ?? '-'} 字</Text>
                            <RiskTags riskHit={s.risk_hit} />
                          </Space>
                          <Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 4, expandable: true, symbol: '展开' }}>
                            {s.text}
                          </Paragraph>
                          {s.consistency_ok === false && s.consistency_note && (
                            <Text type="warning" style={{ fontSize: 12 }}>
                              一致性不过：{s.consistency_note}
                            </Text>
                          )}
                          {s.reject_reason && (
                            <Text type="danger" style={{ fontSize: 12 }}>
                              理由：{s.reject_reason}
                            </Text>
                          )}
                          {s.text_before_edit && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              改前：{s.text_before_edit.slice(0, 60)}…
                            </Text>
                          )}
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
              {
                key: 'productions',
                label: `生产单（${data?.productions?.length ?? 0}）`,
                children: (
                  <List
                    size="small"
                    dataSource={data?.productions || []}
                    locale={{ emptyText: '还没有生产单' }}
                    renderItem={(p) => (
                      <List.Item key={p.id}>
                        <Space direction="vertical" size={2} style={{ width: '100%' }}>
                          <Space wrap>
                            <MonoText>{p.hook_code || '缺号'}</MonoText>
                            <Text>#{p.seq}</Text>
                            <ProductionStateTag status={p.status} />
                            <Text type="secondary">
                              板上 {p.board_name || '-'}｜total {p.board_total}｜投 {p.attempts} 次
                            </Text>
                            {p.drift && (
                              <Tag color="warning">漂移{p.drift_reason ? `：${p.drift_reason}` : ''}</Tag>
                            )}
                          </Space>
                          <Paragraph
                            type="secondary"
                            style={{ marginBottom: 0, fontSize: 12 }}
                            ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                          >
                            {p.prompt_text || '（正文为空：作废/失败单不外泄，看 status）'}
                          </Paragraph>
                          {p.dispatch_note && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              投放要求：{p.dispatch_note}
                            </Text>
                          )}
                          {p.error && (
                            <Text type="danger" style={{ fontSize: 12 }}>
                              {p.error}
                            </Text>
                          )}
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              },
            ]}
          />
          <Divider style={{ margin: '12px 0' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            链路：导入 → 反推提示词（智令）→ 钩子文案（AutoClip）→ 人工审核 → 生产单 → 导出板面 payload
            →（人工投板后回写投递状态）。P0 到生产单为止。
          </Text>
        </>
      )}
    </Drawer>
  );
};

/** 生产单状态标签（与生产单面板同一套色，两处显示不能打架） */

export default AssetDetailDrawer;
