import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Typography, Space, Button, Input, Radio, Tag, Table, Modal,
  Popconfirm, message, Steps, Alert, Empty, Tabs,
} from 'antd';
import {
  ThunderboltOutlined, CopyOutlined, DeleteOutlined, ReloadOutlined,
  ClearOutlined, VideoCameraOutlined, FileTextOutlined, CheckOutlined,
} from '@ant-design/icons';
import { shortdramaApi, type ShortdramaPromptRecord } from '../api/shortdrama';
import Watermark from './Watermark';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

// 示例文案（可一键填充，便于快速体验）
const EXAMPLE_SCRIPTS: Record<string, string> = {
  被开除当天中十个亿:
    `【第1集】
（画外音旁白）我叫林晚，在盛世集团勤勤恳恳干了八年，却因为不肯替总监背锅，被当场开除。
（对白）总监：林晚，这锅你不背也得背，不然明天别来了！
（对白）林晚：我不背，事实就是你把项目做砸了。
（对白）总监：你被解雇了！保安，送她出去！
（画外音旁白）就在我被赶出公司大门的瞬间，手机突然收到一条银行短信——
（对白）林晚：个、十、百、千、万……十个亿？！这怎么可能！
（画外音旁白）而当年那个把我赶出公司的总监，此刻正站在我面前，脸上写满了错愕。`,
};

const ShortDrama: React.FC = () => {
  // ── 提示词生成表单 ──
  const [text, setText] = useState('');
  const [duration, setDuration] = useState<number>(15);
  const [theme, setTheme] = useState('');
  const [tone, setTone] = useState('');
  const [characters, setCharacters] = useState('');
  const [extra, setExtra] = useState('');
  const [generating, setGenerating] = useState(false);

  // 生成结果
  const [resultPrompt, setResultPrompt] = useState('');
  const [resultModel, setResultModel] = useState<string | null>(null);
  const [resultRecordId, setResultRecordId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // 历史
  const [records, setRecords] = useState<ShortdramaPromptRecord[]>([]);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [previewRecord, setPreviewRecord] = useState<ShortdramaPromptRecord | null>(null);

  // ── 加载历史 ──
  const fetchRecords = useCallback(async (silent = false) => {
    if (!silent) setLoadingRecords(true);
    try {
      const list = await shortdramaApi.listPrompts(50);
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

  // ── 生成提示词 ──
  const handleGenerate = async () => {
    if (!text.trim()) {
      message.warning('请先输入短剧文案');
      return;
    }
    setGenerating(true);
    setCopied(false);
    try {
      const res = await shortdramaApi.generate({
        text: text.trim(),
        duration,
        theme: theme.trim() || undefined,
        tone: tone.trim() || undefined,
        characters: characters.trim() || undefined,
        extra_requirements: extra.trim() || undefined,
        save: true,
      });
      setResultPrompt(res.prompt);
      setResultModel(res.model || null);
      setResultRecordId(res.record_id || null);
      message.success(res.message || '提示词生成成功');
      fetchRecords(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async (textToCopy: string) => {
    try {
      await navigator.clipboard.writeText(textToCopy);
      message.success('已复制到剪贴板');
    } catch {
      message.error('复制失败，请手动选择复制');
    }
  };

  const clearForm = () => {
    setText('');
    setTheme('');
    setTone('');
    setCharacters('');
    setExtra('');
    setResultPrompt('');
    setResultModel(null);
    setResultRecordId(null);
  };

  const deleteRecord = async (recordId: string) => {
    try {
      const res = await shortdramaApi.deletePrompt(recordId);
      message.success(res.message);
      fetchRecords();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // ── 历史表格列 ──
  const recordColumns = [
    {
      title: '时长',
      dataIndex: 'duration',
      key: 'duration',
      width: 70,
      render: (d: number) => <Tag color={d === 10 ? 'blue' : 'purple'}>{d}s</Tag>,
    },
    {
      title: '文案（摘要）',
      dataIndex: 'source_text',
      key: 'source_text',
      ellipsis: true,
      render: (s: string) => (
        <Text style={{ fontSize: 13 }}>{s.length > 80 ? `${s.slice(0, 80)}…` : s}</Text>
      ),
    },
    {
      title: '题材 / 基调',
      key: 'theme_tone',
      width: 160,
      render: (_: unknown, r: ShortdramaPromptRecord) => (
        <Space size={4} wrap>
          {r.theme ? <Tag>{r.theme}</Tag> : null}
          {r.tone ? <Tag color="orange">{r.tone}</Tag> : null}
          {!r.theme && !r.tone ? <Text type="secondary" style={{ fontSize: 12 }}>-</Text> : null}
        </Space>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
      width: 130,
      ellipsis: true,
      render: (m: string | null) => (m ? <Text style={{ fontSize: 12 }}>{m}</Text> : '-'),
    },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (d: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(d)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, r: ShortdramaPromptRecord) => (
        <Space size="small">
          <Button size="small" onClick={() => setPreviewRecord(r)}>
            查看
          </Button>
          <Popconfirm
            title="删除该条生成记录？"
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

  const promptTabContent = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* ── 1. 提示词生成 ── */}
      <Card size="small" title="① 生成 Seedance 提示词">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="根据《Seedance短剧视频生成提示词模板》七段结构生成：题材基调 / 故事 / 场景人物 / 镜头执行 / 音频 / 画面风格 / 性别声明。模型借用 AutoClip 中配置的大模型。"
          />

          {/* 时长 */}
          <Space wrap>
            <Text strong>视频时长：</Text>
            <Radio.Group
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 10, label: '10 秒' },
                { value: 15, label: '15 秒' },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              10s：3s 钩子 / 4s 铺垫 / 3s 反转；15s：3s 钩子 / 6s 铺垫 / 6s 反转
            </Text>
          </Space>

          {/* 文案输入 */}
          <div>
            <Space style={{ marginBottom: 6 }}>
              <Text strong>短剧文案：</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                对白 / 旁白原文，生成时将逐字锁定、禁止模型扩写
              </Text>
            </Space>
            <TextArea
              rows={8}
              placeholder="在此输入短剧文案（对白用【角色】标注、旁白标注（画外音旁白）），支持 10s / 15s 剧情…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <Space wrap style={{ marginTop: 6 }}>
              {Object.entries(EXAMPLE_SCRIPTS).map(([name, script]) => (
                <Button
                  key={name}
                  size="small"
                  icon={<FileTextOutlined />}
                  onClick={() => setText(script)}
                >
                  填充示例：{name}
                </Button>
              ))}
            </Space>
          </div>

          {/* 可选参数 */}
          <Space wrap>
            <Text>题材：</Text>
            <Input
              placeholder="如：职场逆袭爽文"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              style={{ width: 150 }}
            />
            <Text>基调：</Text>
            <Input
              placeholder="如：先压抑后爽快"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              style={{ width: 150 }}
            />
            <Text>角色：</Text>
            <Input
              placeholder="如：林晚，女，28岁，职业装；总监，男，40岁，西装"
              value={characters}
              onChange={(e) => setCharacters(e.target.value)}
              style={{ width: 300 }}
            />
          </Space>
          <div>
            <Text>补充要求：</Text>
            <Input
              placeholder="可选，如：结尾反转要夸张、全程不要镜头晃动"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              style={{ width: 460 }}
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
              生成提示词
            </Button>
            <Button icon={<ClearOutlined />} onClick={clearForm}>
              清空
            </Button>
          </Space>

          {/* 生成结果 */}
          {resultPrompt && (
            <Card size="small" type="inner" title="生成结果">
              <Space style={{ marginBottom: 8 }} wrap>
                <Tag color={duration === 10 ? 'blue' : 'purple'}>{duration}s 模板</Tag>
                {resultModel && <Tag color="cyan">模型：{resultModel}</Tag>}
                {resultRecordId && <Tag color="green">已保存到历史</Tag>}
                <Button
                  size="small"
                  type="primary"
                  icon={copied ? <CheckOutlined /> : <CopyOutlined />}
                  onClick={async () => {
                    await handleCopy(resultPrompt);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                >
                  {copied ? '已复制' : '复制提示词'}
                </Button>
              </Space>
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  background: '#fafafa',
                  border: '1px solid #f0f0f0',
                  borderRadius: 8,
                  padding: 12,
                  fontSize: 13,
                  maxHeight: 420,
                  overflow: 'auto',
                }}
              >
                {resultPrompt}
              </pre>
            </Card>
          )}
        </Space>
      </Card>

      {/* ── 生成历史 ── */}
      <Card
        size="small"
        title="提示词生成历史"
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
          scroll={{ x: 920 }}
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
    </Space>
  );

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Title level={4} style={{ margin: 0 }}>
          <VideoCameraOutlined /> 短片制作
        </Title>
        <Tag color="green">v6 新增</Tag>
      </Space>

      {/* ── 工作流 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          size="small"
          current={-1}
          items={[
            { title: '输入文案', description: '对白/旁白原文' },
            { title: '生成提示词', description: '复用 AutoClip 模型' },
            { title: 'Seedance 生成', description: '10s / 15s 竖屏' },
            { title: '去水印出片', description: '「去水印」页签完成' },
          ]}
        />
      </Card>

      <Tabs
        defaultActiveKey="prompt"
        items={[
          {
            key: 'prompt',
            label: (
              <span>
                <ThunderboltOutlined /> ① 提示词生成
              </span>
            ),
            children: promptTabContent,
          },
          {
            key: 'watermark',
            label: (
              <span>
                <ClearOutlined /> ② 去水印
              </span>
            ),
            children: <Watermark />,
          },
        ]}
      />

      {/* ── 提示词详情弹窗 ── */}
      <Modal
        title="提示词详情"
        open={!!previewRecord}
        footer={null}
        width={820}
        onCancel={() => setPreviewRecord(null)}
        destroyOnClose
      >
        {previewRecord && (
          <div>
            <Space style={{ marginBottom: 8 }} wrap>
              <Tag color={previewRecord.duration === 10 ? 'blue' : 'purple'}>
                {previewRecord.duration}s
              </Tag>
              {previewRecord.theme && <Tag>{previewRecord.theme}</Tag>}
              {previewRecord.tone && <Tag color="orange">{previewRecord.tone}</Tag>}
              {previewRecord.model && <Tag color="cyan">{previewRecord.model}</Tag>}
              <Text type="secondary" style={{ fontSize: 12 }}>
                {formatDateTime(previewRecord.created_at)}
              </Text>
            </Space>
            <Text strong>原始文案：</Text>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                background: '#fafafa',
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                padding: 10,
                fontSize: 12,
                maxHeight: 160,
                overflow: 'auto',
              }}
            >
              {previewRecord.source_text}
            </pre>
            <Text strong>生成的提示词：</Text>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                background: '#fafafa',
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                padding: 10,
                fontSize: 13,
                maxHeight: 400,
                overflow: 'auto',
              }}
            >
              {previewRecord.prompt_text}
            </pre>
            <Space style={{ marginTop: 8 }}>
              <Button
                type="primary"
                icon={<CopyOutlined />}
                onClick={() => handleCopy(previewRecord!.prompt_text)}
              >
                复制提示词
              </Button>
            </Space>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default ShortDrama;
