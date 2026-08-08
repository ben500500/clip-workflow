import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Typography, Space, Button, Input, Tag, Table, Modal,
  Popconfirm, message, Alert, Empty, Tabs, AutoComplete, Tooltip, Divider,
} from 'antd';
import {
  ThunderboltOutlined, CopyOutlined, DeleteOutlined, ReloadOutlined,
  ClearOutlined, CheckOutlined, FileTextOutlined, TagsOutlined,
  CommentOutlined, PictureOutlined, HighlightOutlined, SendOutlined,
} from '@ant-design/icons';
import {
  publishMaterialApi,
  type PublishMaterial as PublishMaterialType,
  type PublishMaterialRecord,
} from '../api/publishMaterial';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

// 发布平台预设
const PLATFORM_OPTIONS = [
  { value: '抖音' },
  { value: '视频号' },
  { value: '快手' },
  { value: '小红书' },
  { value: '抖音 + 视频号' },
];

// 题材预设（与提示词生成页签保持一致）
const THEME_OPTIONS = [
  { value: '都市逆袭爽文' },
  { value: '职场逆袭' },
  { value: '战神归来' },
  { value: '赘婿逆袭' },
  { value: '豪门霸总' },
  { value: '重生复仇' },
  { value: '穿越古装' },
  { value: '玄幻修仙' },
  { value: '甜宠' },
  { value: '萌宝团宠' },
  { value: '悬疑反转' },
  { value: '家庭伦理' },
  { value: '轻喜搞笑' },
  { value: '神医圣手' },
  { value: '民国风云' },
];

// 示例剧情梗概（可一键填充）
const EXAMPLE_STORIES: Record<string, string> = {
  赘婿逆袭:
    '男主赘婿，入赘豪门三年受尽羞辱。岳父生日宴上当众让他滚出去，男主站起来解开西装扣子，露出隐藏身份，全场下跪震惊。女主哭着求他回头，男主撕碎婚书霸气离场。',
  被开除当天中十个亿:
    '女主在集团公司勤勤恳恳干了八年，因不肯替总监背锅被当场开除。被赶出公司大门的瞬间收到银行短信，中了十个亿。曾经赶走她的总监正好路过，当场傻眼。',
};

const PublishMaterialTab: React.FC = () => {
  // ── 生成表单 ──
  const [story, setStory] = useState('');
  const [title, setTitle] = useState('');
  const [theme, setTheme] = useState('');
  const [tone, setTone] = useState('');
  const [platform, setPlatform] = useState('');
  const [extra, setExtra] = useState('');
  const [generating, setGenerating] = useState(false);

  // 生成结果
  const [result, setResult] = useState<PublishMaterialType | null>(null);
  const [resultModel, setResultModel] = useState<string | null>(null);
  const [resultRecordId, setResultRecordId] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string>('');

  // 历史
  const [records, setRecords] = useState<PublishMaterialRecord[]>([]);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [previewRecord, setPreviewRecord] = useState<PublishMaterialRecord | null>(null);

  // 配文版本切换
  const [captionVersion, setCaptionVersion] = useState<'suspense_hook' | 'concise_viral' | 'emotional'>('suspense_hook');

  // ── 加载历史 ──
  const fetchRecords = useCallback(async (silent = false) => {
    if (!silent) setLoadingRecords(true);
    try {
      const list = await publishMaterialApi.listMaterials(50);
      setRecords(list);
    } catch (err: unknown) {
      if (!silent) message.error(err instanceof Error ? err.message : '获取生成历史失败');
    } finally {
      if (!silent) setLoadingRecords(false);
    }
  }, []);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  // ── 生成发布素材 ──
  const handleGenerate = async () => {
    if (!story.trim()) {
      message.warning('请先输入短剧剧情梗概');
      return;
    }
    setGenerating(true);
    setCopiedKey('');
    try {
      const res = await publishMaterialApi.generate({
        story: story.trim(),
        title: title.trim() || undefined,
        theme: theme.trim() || undefined,
        tone: tone.trim() || undefined,
        platform: platform.trim() || undefined,
        extra_requirements: extra.trim() || undefined,
        save: true,
      });
      setResult(res.material);
      setResultModel(res.model || null);
      setResultRecordId(res.record_id || null);
      message.success(res.message || '发布素材生成成功');
      fetchRecords(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async (key: string, textToCopy: string) => {
    // 非 HTTPS 环境（http://IP 访问）navigator.clipboard 不可用，需降级方案
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(textToCopy);
        setCopiedKey(key);
        message.success('已复制到剪贴板');
        setTimeout(() => setCopiedKey(''), 2000);
        return;
      }
      // 降级：textarea + execCommand('copy')，兼容 http://IP 部署环境
      const textarea = document.createElement('textarea');
      textarea.value = textToCopy;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (ok) {
        setCopiedKey(key);
        message.success('已复制到剪贴板');
        setTimeout(() => setCopiedKey(''), 2000);
      } else {
        message.error('复制失败，请手动选择复制');
      }
    } catch {
      message.error('复制失败，请手动选择复制');
    }
  };

  const clearForm = () => {
    setStory('');
    setTitle('');
    setTheme('');
    setTone('');
    setPlatform('');
    setExtra('');
    setResult(null);
    setResultModel(null);
    setResultRecordId(null);
  };

  const deleteRecord = async (recordId: string) => {
    try {
      const res = await publishMaterialApi.deleteMaterial(recordId);
      message.success(res.message);
      fetchRecords();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // ── 生成一段可复制发布的完整文案（短标题 + 配文 + 标签 + 神评） ──
  const buildFullCopy = (m: PublishMaterialType, version?: keyof PublishMaterialType['captions']) => {
    const v = version || captionVersion;
    const caption = m.captions?.[v] || '';
    const tags = Object.values(m.tags || {}).flat().join(' ');
    const comments = (m.comments || []).map((c) => `${c.type}：${c.content}`).join('\n');
    return [
      `【短标题】${m.short_title || ''}`,
      ``,
      `【配文·${versionLabel(v)}】`,
      caption,
      ``,
      `【话题标签】`,
      tags,
      ``,
      `【置顶互动神评】`,
      comments,
    ].join('\n');
  };

  const versionLabel = (v: string) => {
    const map: Record<string, string> = {
      suspense_hook: '悬念钩子版',
      concise_viral: '精简爆款版',
      emotional: '情绪爽文版',
    };
    return map[v] || v;
  };

  // ── 渲染单个素材内容（短标题 / 配文 / 标签 / 神评） ──
  const renderMaterialContent = (m: PublishMaterialType, showCopy = true) => (
    <div>
      {/* 短标题 */}
      <Card size="small" title={<span><PictureOutlined /> 短标题（封面用，8-18字）</span>} style={{ marginBottom: 12 }}>
        <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text strong style={{ fontSize: 16 }}>{m.short_title || '-'}</Text>
          {showCopy && m.short_title && (
            <Button
              size="small"
              icon={copiedKey === 'title' ? <CheckOutlined /> : <CopyOutlined />}
              onClick={() => handleCopy('title', m.short_title!)}
            >
              {copiedKey === 'title' ? '已复制' : '复制'}
            </Button>
          )}
        </Space>
      </Card>

      {/* 三款视频配文 */}
      <Card
        size="small"
        title={<span><HighlightOutlined /> 三款视频配文（任选其一）</span>}
        style={{ marginBottom: 12 }}
        extra={
          showCopy && (
            <Button
              size="small"
              icon={copiedKey === 'all' ? <CheckOutlined /> : <CopyOutlined />}
              onClick={() => handleCopy('all', buildFullCopy(m))}
            >
              {copiedKey === 'all' ? '已复制' : '复制全套'}
            </Button>
          )
        }
      >
        <Tabs
          size="small"
          activeKey={captionVersion}
          onChange={(k) => setCaptionVersion(k as typeof captionVersion)}
          items={[
            {
              key: 'suspense_hook',
              label: '悬念钩子版',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Text style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.captions?.suspense_hook || '-'}</Text>
                  {showCopy && m.captions?.suspense_hook && (
                    <Button
                      size="small"
                      icon={copiedKey === 'cap_suspense_hook' ? <CheckOutlined /> : <CopyOutlined />}
                      onClick={() => handleCopy('cap_suspense_hook', m.captions!.suspense_hook)}
                    >
                      {copiedKey === 'cap_suspense_hook' ? '已复制' : '复制'}
                    </Button>
                  )}
                </Space>
              ),
            },
            {
              key: 'concise_viral',
              label: '精简爆款版',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Text style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.captions?.concise_viral || '-'}</Text>
                  {showCopy && m.captions?.concise_viral && (
                    <Button
                      size="small"
                      icon={copiedKey === 'cap_concise_viral' ? <CheckOutlined /> : <CopyOutlined />}
                      onClick={() => handleCopy('cap_concise_viral', m.captions!.concise_viral)}
                    >
                      {copiedKey === 'cap_concise_viral' ? '已复制' : '复制'}
                    </Button>
                  )}
                </Space>
              ),
            },
            {
              key: 'emotional',
              label: '情绪爽文版',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Text style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.captions?.emotional || '-'}</Text>
                  {showCopy && m.captions?.emotional && (
                    <Button
                      size="small"
                      icon={copiedKey === 'cap_emotional' ? <CheckOutlined /> : <CopyOutlined />}
                      onClick={() => handleCopy('cap_emotional', m.captions!.emotional)}
                    >
                      {copiedKey === 'cap_emotional' ? '已复制' : '复制'}
                    </Button>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {/* 成套话题标签 */}
      <Card size="small" title={<span><TagsOutlined /> 成套话题标签（6-8个）</span>} style={{ marginBottom: 12 }}>
        {Object.entries(m.tags || {}).length === 0 ? (
          <Text type="secondary">-</Text>
        ) : (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {Object.entries(m.tags || {}).map(([group, tags]) => (
              <Space key={group} wrap>
                <Tag color="blue">{group}</Tag>
                {(tags || []).map((t, i) => (
                  <Tag key={i} color="geekblue">{t}</Tag>
                ))}
              </Space>
            ))}
            {showCopy && (
              <Button
                size="small"
                icon={copiedKey === 'tags' ? <CheckOutlined /> : <CopyOutlined />}
                onClick={() => handleCopy('tags', Object.values(m.tags || {}).flat().join(' '))}
              >
                {copiedKey === 'tags' ? '已复制' : '复制标签'}
              </Button>
            )}
          </Space>
        )}
      </Card>

      {/* 三条置顶互动神评 */}
      <Card size="small" title={<span><CommentOutlined /> 三条置顶互动神评</span>}>
        {(m.comments || []).length === 0 ? (
          <Text type="secondary">-</Text>
        ) : (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {(m.comments || []).map((c, i) => (
              <div
                key={i}
                style={{
                  background: '#fafafa',
                  border: '1px solid #f0f0f0',
                  borderRadius: 8,
                  padding: '8px 12px',
                }}
              >
                <Space style={{ marginBottom: 4 }}>
                  <Tag color={i === 0 ? 'orange' : i === 1 ? 'purple' : 'cyan'}>
                    {c.type || `神评${i + 1}`}
                  </Tag>
                </Space>
                <Text style={{ fontSize: 13, display: 'block' }}>{c.content || '-'}</Text>
              </div>
            ))}
            {showCopy && (
              <Button
                size="small"
                icon={copiedKey === 'comments' ? <CheckOutlined /> : <CopyOutlined />}
                onClick={() =>
                  handleCopy(
                    'comments',
                    (m.comments || []).map((c) => `${c.type}：${c.content}`).join('\n')
                  )
                }
              >
                {copiedKey === 'comments' ? '已复制' : '复制神评'}
              </Button>
            )}
          </Space>
        )}
      </Card>
    </div>
  );

  // ── 历史表格列 ──
  const recordColumns = [
    {
      title: '短标题',
      key: 'short_title',
      width: 220,
      ellipsis: true,
      render: (_: unknown, r: PublishMaterialRecord) => (
        <Text style={{ fontSize: 13, fontWeight: 500 }}>{r.material?.short_title || '-'}</Text>
      ),
    },
    {
      title: '剧情梗概（摘要）',
      dataIndex: 'story',
      key: 'story',
      ellipsis: true,
      render: (s: string) => (
        <Text style={{ fontSize: 13 }}>{s.length > 60 ? `${s.slice(0, 60)}…` : s}</Text>
      ),
    },
    {
      title: '题材 / 基调',
      key: 'theme_tone',
      width: 150,
      render: (_: unknown, r: PublishMaterialRecord) => (
        <Space size={4} wrap>
          {r.theme ? <Tag>{r.theme}</Tag> : null}
          {r.tone ? <Tag color="orange">{r.tone}</Tag> : null}
          {!r.theme && !r.tone ? <Text type="secondary" style={{ fontSize: 12 }}>-</Text> : null}
        </Space>
      ),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 110,
      render: (p: string | null) => (p ? <Tag color="green">{p}</Tag> : '-'),
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
      width: 120,
      ellipsis: true,
      render: (m: string | null) => (m ? <Text style={{ fontSize: 12 }}>{m}</Text> : '-'),
    },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (d: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, r: PublishMaterialRecord) => (
        <Space size="small" wrap>
          <Button size="small" onClick={() => setPreviewRecord(r)}>
            查看
          </Button>
          <Popconfirm
            title="删除该条发布素材记录？"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => deleteRecord(r.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* ── 1. 发布素材生成 ── */}
      <Card size="small" title="① 生成短剧发布素材">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="输出结构严格顺序：短标题 → 三款视频配文（悬念钩子/精简爆款/情绪爽文）→ 成套话题标签（通用+垂直+长尾，6-8个）→ 三条置顶互动神评（调侃/感慨/脑洞）。全部贴合抖音、视频号短剧调性，侧重反转、爽点、悬念。模型复用 AutoClip 中配置的大模型。"
          />

          {/* 剧情梗概输入 */}
          <div>
            <Space style={{ marginBottom: 6 }}>
              <Text strong>短剧剧情梗概：</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                可粘贴剧情梗概、已生成的 Seedance 提示词或短剧标题
              </Text>
            </Space>
            <TextArea
              rows={5}
              placeholder="在此输入短剧剧情梗概（主角、冲突、反转、结局）…"
              value={story}
              onChange={(e) => setStory(e.target.value)}
            />
            <Space wrap style={{ marginTop: 6 }}>
              {Object.entries(EXAMPLE_STORIES).map(([name, s]) => (
                <Button
                  key={name}
                  size="small"
                  icon={<FileTextOutlined />}
                  onClick={() => setStory(s)}
                >
                  填充示例：{name}
                </Button>
              ))}
            </Space>
          </div>

          {/* 可选参数 */}
          <Space wrap align="start">
            <Space>
              <Text>短剧标题：</Text>
              <Input
                style={{ width: 160 }}
                placeholder="可选"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </Space>
            <Space>
              <Text>题材：</Text>
              <AutoComplete
                style={{ width: 160 }}
                value={theme}
                onChange={setTheme}
                options={THEME_OPTIONS}
                placeholder="选择或输入题材"
                allowClear
              />
            </Space>
            <Space>
              <Text>平台：</Text>
              <AutoComplete
                style={{ width: 150 }}
                value={platform}
                onChange={setPlatform}
                options={PLATFORM_OPTIONS}
                placeholder="抖音/视频号等"
                allowClear
              />
            </Space>
          </Space>
          <div>
            <Text>补充要求：</Text>
            <Input
              placeholder="可选，如：突出反转爽点、语言更口语化、标签加 #战神归来"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              style={{ width: 520 }}
            />
          </div>

          {/* 操作 */}
          <Space wrap>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={generating}
              onClick={handleGenerate}
            >
              生成发布素材
            </Button>
            <Button icon={<ClearOutlined />} onClick={clearForm}>
              清空
            </Button>
          </Space>

          {/* 生成结果 */}
          {result && (
            <Card size="small" type="inner" title="生成结果">
              <Space style={{ marginBottom: 8 }} wrap>
                {resultModel && <Tag color="cyan">模型：{resultModel}</Tag>}
                {resultRecordId && <Tag color="green">已保存到历史</Tag>}
              </Space>
              {renderMaterialContent(result)}
            </Card>
          )}
        </Space>
      </Card>

      {/* ── 生成历史 ── */}
      <Card
        size="small"
        title="发布素材生成历史"
        extra={
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => fetchRecords()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          loading={loadingRecords}
          dataSource={records}
          columns={recordColumns}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 1000 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无生成记录，先在上方生成一条吧"
              />
            ),
          }}
        />
      </Card>

      {/* ── 素材详情弹窗 ── */}
      <Modal
        title="发布素材详情"
        open={!!previewRecord}
        footer={null}
        width={880}
        onCancel={() => setPreviewRecord(null)}
        destroyOnClose
      >
        {previewRecord && (
          <div>
            <Space style={{ marginBottom: 12 }} wrap>
              {previewRecord.theme && <Tag>{previewRecord.theme}</Tag>}
              {previewRecord.tone && <Tag color="orange">{previewRecord.tone}</Tag>}
              {previewRecord.platform && <Tag color="green">{previewRecord.platform}</Tag>}
              {previewRecord.model && <Tag color="cyan">{previewRecord.model}</Tag>}
              <Text type="secondary" style={{ fontSize: 12 }}>
                {formatDateTime(previewRecord.created_at)}
              </Text>
            </Space>

            <Card size="small" title="剧情梗概" style={{ marginBottom: 12 }}>
              <Text style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{previewRecord.story}</Text>
            </Card>

            {renderMaterialContent(previewRecord.material)}

            <Divider />
            <Space style={{ marginTop: 8 }}>
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={() => handleCopy('preview_all', buildFullCopy(previewRecord.material))}
              >
                复制全套发布文案
              </Button>
            </Space>
          </div>
        )}
      </Modal>
    </Space>
  );
};

export default PublishMaterialTab;
