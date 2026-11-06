import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Drawer, Input, Space, Switch, Table, Tabs, Tag, Typography, message,
} from 'antd';
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetRiskLexicon } from '../../api/assets';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

/** 一行豁免规则：命中点被这个正则整个包住就不算命中。 */
interface ExemptRow {
  key: string;
  word: string;
  pattern: string;
}

const parseWords = (raw: string): string[] =>
  raw
    .split(/[\n,，、\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);

const uniq = (arr: string[]): string[] => Array.from(new Set(arr));

/**
 * 违禁词表配置抽屉。
 *
 * 这份词表就是审核台「自动检查」列那两行标签的来源：block 命中即不许过审、也导不出去，
 * warn 只提醒。词表存在 system_config（`asset_risk_lexicon`），
 * **改词不用发版**，但只有 admin 能改——它等于投板闸门，运营加词是加严，
 * 写错一个词会把一线正常文案全拦死。
 *
 * 三层要分清：
 *   defaults  内置默认表（出厂）
 *   override  运营自己配的（这一层是本页编辑的）
 *   effective 真正生效的（= defaults + override，或 override 整体替换）
 */
const RiskLexiconDrawer: React.FC<Props> = ({ open, onClose }) => {
  const [data, setData] = useState<AssetRiskLexicon | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [inherit, setInherit] = useState(true);
  const [blockText, setBlockText] = useState('');
  const [warnText, setWarnText] = useState('');
  const [exemptRows, setExemptRows] = useState<ExemptRow[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await assetApi.getRiskLexicon();
      setData(res);
      setInherit(res.override.inherit);
      setBlockText(res.override.block.join('\n'));
      setWarnText(res.override.warn.join('\n'));
      setExemptRows(
        Object.entries(res.override.exempt).map(([word, pattern], i) => ({
          key: `${word}-${i}`,
          word,
          pattern,
        })),
      );
    } catch (e) {
      message.error((e as Error).message || '读取违禁词表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  /** 保存后生效的词表预览（前端先算一遍，别让用户存完才发现继承关系搞反了）。 */
  const preview = useMemo(() => {
    const block = parseWords(blockText);
    const warn = parseWords(warnText);
    if (!data) return { block, warn };
    if (inherit) {
      return {
        block: uniq([...data.defaults.block, ...block]),
        warn: uniq([...data.defaults.warn, ...warn]),
      };
    }
    return { block, warn };
  }, [blockText, warnText, inherit, data]);

  const switchInherit = (checked: boolean) => {
    if (!checked && data) {
      // 从「追加」切到「整体替换」：不把当前生效词搬进来，
      // 一存就会把默认词整批丢掉（而且用户看不出少了什么）。
      setBlockText(preview.block.join('\n'));
      setWarnText(preview.warn.join('\n'));
    }
    setInherit(checked);
  };

  const restoreDefaults = () => {
    if (!data) return;
    setInherit(true);
    setBlockText('');
    setWarnText('');
    setExemptRows(
      Object.entries(data.defaults.exempt).map(([word, pattern], i) => ({
        key: `d-${word}-${i}`,
        word,
        pattern,
      })),
    );
    message.info('已填回默认值，保存后生效');
  };

  const save = async () => {
    setSaving(true);
    try {
      const exempt: Record<string, string> = {};
      exemptRows.forEach((r) => {
        const w = (r.word || '').trim();
        if (w) exempt[w] = (r.pattern || '').trim();
      });
      const res = await assetApi.updateRiskLexicon({
        block: parseWords(blockText),
        warn: parseWords(warnText),
        exempt,
        inherit,
      });
      (res.notes || []).forEach((n) => message.info(n));
      message.success('违禁词表已保存，下一次审核、生成生产单立即生效');
      await load();
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const canEdit = !!data?.can_edit;

  return (
    <Drawer
      title="违禁词表"
      width={720}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            重新读取
          </Button>
          {canEdit && (
            <Button type="primary" icon={<SaveOutlined />} onClick={save} loading={saving}>
              保存
            </Button>
          )}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="这份词表就是审核台「自动检查」列标签的来源"
        description={
          <div>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag color="red">不许用（block）</Tag>
              命中就<strong>过不了审、也导不出去</strong>（血腥色情违法歧视、医疗绝对化等）
            </Paragraph>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag color="orange">要注意（warn）</Tag>
              只留个提醒，人看一眼决定改不改（绝对化用语、夸大承诺等）
            </Paragraph>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag>例外写法</Tag>
              命中点被这个正则整个包住就不算命中（例如「第一」不拦「第一次」）
            </Paragraph>
            <Text type="secondary">
              词表存在系统配置里，改词不用发版；保存后立刻生效，不用等缓存过期。
            </Text>
          </div>
        }
      />

      {!canEdit && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="只读：改词表要管理员权限"
          description="这份词表管着过审和导出的关口，加词是收紧、写错会误伤正常文案，所以只有管理员能改。你在这里能看到拦你的到底是哪个词。"
        />
      )}

      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Switch checked={inherit} onChange={switchInherit} disabled={!canEdit} />
          <Text>
            在默认词表上<strong>{inherit ? '追加' : '整体替换'}</strong>
            {inherit ? '（默认词仍然生效，这里填的是新增的）' : '（默认词不再拦人，这里填什么就拦什么）'}
          </Text>
        </Space>
        {data && (
          <Text type="secondary">
            保存后生效：不许用 {preview.block.length} 个、要注意 {preview.warn.length} 个
            {data.has_override && `｜上次更新：${data.updated_at || '未知'}`}
          </Text>
        )}
      </Space>

      <Tabs
        style={{ marginTop: 8 }}
        items={[
          {
            key: 'block',
            label: (
              <span>
                不许用 <Tag color="red">{preview.block.length}</Tag>
              </span>
            ),
            children: (
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Text type="secondary">每行一个词，命中就过不了审、也导不出去。</Text>
                <Input.TextArea
                  rows={12}
                  value={blockText}
                  onChange={(e) => setBlockText(e.target.value)}
                  disabled={!canEdit}
                  placeholder={inherit ? '在这里加词（留空＝沿用默认表）' : '一行一个词'}
                />
                {inherit && data && (
                  <Text type="secondary">
                    默认表里已有的（不会被你清掉）：
                    {data.defaults.block.join('、')}
                  </Text>
                )}
              </Space>
            ),
          },
          {
            key: 'warn',
            label: (
              <span>
                要注意 <Tag color="orange">{preview.warn.length}</Tag>
              </span>
            ),
            children: (
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Text type="secondary">每行一个词，只留个提醒，不挡过审。</Text>
                <Input.TextArea
                  rows={10}
                  value={warnText}
                  onChange={(e) => setWarnText(e.target.value)}
                  disabled={!canEdit}
                  placeholder={inherit ? '在这里加词（留空＝沿用默认表）' : '一行一个词'}
                />
                {inherit && data && (
                  <Text type="secondary">
                    默认表里已有的：{data.defaults.warn.join('、')}
                  </Text>
                )}
              </Space>
            ),
          },
          {
            key: 'exempt',
            label: <span>例外写法</span>,
            children: (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Text type="secondary">
                  命中点被例外写法整个包住就不算命中。写法（正则）写错会被后端拒掉（保存时报错）。
                </Text>
                <Table
                  size="small"
                  rowKey="key"
                  pagination={false}
                  dataSource={exemptRows}
                  columns={[
                    {
                      title: '词',
                      dataIndex: 'word',
                      width: 160,
                      render: (_, r) => (
                        <Input
                          value={r.word}
                          disabled={!canEdit}
                          onChange={(e) =>
                            setExemptRows((prev) =>
                              prev.map((x) => (x.key === r.key ? { ...x, word: e.target.value } : x)),
                            )
                          }
                        />
                      ),
                    },
                    {
                      title: '例外写法',
                      dataIndex: 'pattern',
                      render: (_, r) => (
                        <Input
                          value={r.pattern}
                          disabled={!canEdit}
                          placeholder="例如：第一次|第一时间"
                          onChange={(e) =>
                            setExemptRows((prev) =>
                              prev.map((x) => (x.key === r.key ? { ...x, pattern: e.target.value } : x)),
                            )
                          }
                        />
                      ),
                    },
                    {
                      title: '',
                      width: 70,
                      render: (_, r) => (
                        <Button
                          size="small"
                          danger
                          disabled={!canEdit}
                          onClick={() => setExemptRows((prev) => prev.filter((x) => x.key !== r.key))}
                        >
                          删除
                        </Button>
                      ),
                    },
                  ]}
                />
                {canEdit && (
                  <Button
                    size="small"
                    onClick={() =>
                      setExemptRows((prev) => [
                        ...prev,
                        { key: `n-${Date.now()}-${prev.length}`, word: '', pattern: '' },
                      ])
                    }
                  >
                    加一条例外
                  </Button>
                )}
                {data && inherit && (
                  <Text type="secondary">
                    默认例外：{Object.entries(data.defaults.exempt).map(([w, p]) => `${w} → ${p}`).join('；')}
                  </Text>
                )}
              </Space>
            ),
          },
        ]}
      />

      {canEdit && (
        <Space style={{ marginTop: 16 }}>
          <Button onClick={restoreDefaults}>恢复默认</Button>
        </Space>
      )}
    </Drawer>
  );
};

export default RiskLexiconDrawer;
