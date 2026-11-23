import React, { useEffect, useState } from 'react';
import {
  Card, Table, Button, Space, Typography, message, Modal, Form, Input, Tag, Select, InputNumber, Tooltip, Alert, Popconfirm, Switch,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons';
import { configApi } from '../api/config';
import type { PlatformProfile, SystemConfig } from '../types';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;

const Settings: React.FC = () => {
  const [configs, setConfigs] = useState<SystemConfig[]>([]);
  const [profiles, setProfiles] = useState<PlatformProfile[]>([]);
  const [presets, setPresets] = useState<Record<string, Array<{ label: string; target_resolution: string; target_bitrate: string }>>>({});
  const [profileModal, setProfileModal] = useState(false);
  const [configModal, setConfigModal] = useState(false);
  const [editing, setEditing] = useState<PlatformProfile | null>(null);
  const [editingConfig, setEditingConfig] = useState<SystemConfig | null>(null);
  const [configForm] = Form.useForm();
  const [profileForm] = Form.useForm();
  const selectedPlatform = Form.useWatch('platform', profileForm) as string | undefined;
  const [asrMethod, setAsrMethod] = useState<string>('whisper');
  const [asrSaving, setAsrSaving] = useState(false);
  const [remotionEnabled, setRemotionEnabled] = useState(false);
  const [remotionSaving, setRemotionSaving] = useState(false);
  // AI 选点 LLM 网关配置（llm_config）：llm_api_base / llm_model / llm_api_key
  const [llmBase, setLlmBase] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmKey, setLlmKey] = useState('');
  const [llmKeySet, setLlmKeySet] = useState(false); // 库里是否已存密钥
  const [llmSaving, setLlmSaving] = useState(false);
  // 模型仓库（llm_config.models）：供选点界面「选点模型」下拉的命名模型列表
  const [llmRepoEntries, setLlmRepoEntries] = useState<{ name: string; model: string; api_base?: string; api_key?: string }[]>([]);
  const [llmNewEntry, setLlmNewEntry] = useState<{ name: string; model: string; api_base: string; api_key: string }>({ name: '', model: '', api_base: '', api_key: '' });

  const fetchAll = () => {
    configApi.getAll().then((list) => {
      setConfigs(list);
      const a = list.find((c: SystemConfig) => c.key === 'asr_method');
      if (a) setAsrMethod(String(a.value));
      const re = list.find((c: SystemConfig) => c.key === 'remotion_enabled');
      setRemotionEnabled(re ? re.value === true || String(re.value).toLowerCase() === 'true' : false);
      const lc = list.find((c: SystemConfig) => c.key === 'llm_config');
      const lv = (lc && typeof lc.value === 'object' && lc.value ? lc.value : {}) as Record<string, unknown>;
      setLlmBase(typeof lv.llm_api_base === 'string' ? lv.llm_api_base : '');
      setLlmModel(typeof lv.llm_model === 'string' ? lv.llm_model : '');
      setLlmKeySet(Boolean(lv.llm_api_key));
      const models = Array.isArray(lv.models) ? lv.models : [];
      setLlmRepoEntries(models.map((m: Record<string, unknown>) => ({
        name: String(m.name || ''), model: String(m.model || ''),
        api_base: String(m.api_base || ''), api_key: m.api_key ? '●已保存' : '',
      })));
    }).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
    configApi.getPlatformProfiles().then(setProfiles).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
    configApi.getPlatformPresets().then((r) => setPresets(r.presets || {})).catch(() => undefined);
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const saveConfig = async (key: string, value: unknown) => {
    try {
      await configApi.update(key, value);
      message.success('配置已保存');
      setConfigModal(false);
      setEditingConfig(null);
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleConfigEdit = (config: SystemConfig) => {
    setEditingConfig(config);
    const val = typeof config.value === 'object' && config.value !== null
      ? JSON.stringify(config.value, null, 2)
      : String(config.value ?? '');
    configForm.setFieldsValue({ value: val });
    setConfigModal(true);
  };

  const handleConfigSave = async () => {
    try {
      const values = await configForm.validateFields();
      if (!editingConfig) return;
      const raw = values.value;
      try {
        if (typeof editingConfig.value === 'object' && editingConfig.value !== null) {
          const parsed = JSON.parse(raw);
          await saveConfig(editingConfig.key, parsed);
        } else {
          await saveConfig(editingConfig.key, raw);
        }
      } catch {
        message.error('JSON 格式错误，请检查输入内容');
      }
    } catch {
      // 表单验证未通过，忽略
    }
  };

  const saveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      const payload = {
        ...values,
        dedupe_config: values.dedupe_config ? JSON.parse(values.dedupe_config) : null,
      };
      if (editing) {
        await configApi.updatePlatformProfile(editing.id, payload);
        message.success('配置已更新');
      } else {
        await configApi.createPlatformProfile(payload);
        message.success('配置已创建');
      }
      setProfileModal(false);
      fetchAll();
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        message.error('去重配置必须是合法 JSON');
        return;
      }
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  // 恢复配置默认值（全局配置）
  const handleConfigReset = async (config: SystemConfig) => {
    try {
      await configApi.resetDefault(config.key);
      message.success(`配置 ${config.key} 已恢复默认值`);
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '恢复默认失败');
    }
  };

  // 恢复平台去重配置默认值（含去重 JSON、分辨率、码率）
  const handleProfileReset = async (profile: PlatformProfile) => {
    try {
      await configApi.resetPlatformProfileDefault(profile.id);
      message.success(`配置 ${profile.name} 已恢复默认值`);
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '恢复默认失败');
    }
  };

  // 选择平台快捷分辨率/码率预设
  const applyPreset = (platform: string, preset: { label: string; target_resolution: string; target_bitrate: string }) => {
    profileForm.setFieldsValue({
      target_resolution: preset.target_resolution,
      target_bitrate: preset.target_bitrate,
    });
  };

  // 切换 ASR 引擎（语音识别）
  const handleAsrChange = async (value: string) => {
    setAsrMethod(value);
    setAsrSaving(true);
    try {
      await configApi.update('asr_method', value);
      message.success('ASR 引擎已切换为：' + value);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '切换失败');
    } finally {
      setAsrSaving(false);
    }
  };

  // 保存 AI 选点 LLM 网关配置（合并保留未知字段；密钥留空=保持原值不变）
  const handleLlmSave = async () => {
    setLlmSaving(true);
    try {
      const existing = configs.find((c: SystemConfig) => c.key === 'llm_config');
      const base = (existing && typeof existing.value === 'object' && existing.value ? existing.value : {}) as Record<string, unknown>;
      const next: Record<string, unknown> = { ...base };
      if (llmRepoEntries.length > 0) {
        next.models = llmRepoEntries
          .filter((e) => e.name.trim() && e.model.trim())
          .map((e) => ({
            name: e.name.trim(), model: e.model.trim(), api_base: e.api_base?.trim() || '',
            api_key: e.api_key && !e.api_key.startsWith('●') ? e.api_key : (base as Record<string, never> && 0, undefined),
          }));
        // api_key 占位（●已保存）保留原值：从 base.models 按名回填
        const baseModels = Array.isArray(base.models) ? base.models : [];
        next.models = (next.models as { name: string; api_key?: string }[]).map((e) => {
          if (e.api_key === undefined) {
            const old = baseModels.find((o: Record<string, unknown>) => o.name === e.name);
            e.api_key = old && old.api_key ? String(old.api_key) : undefined;
          }
          return e;
        }).filter((e) => e.api_key !== undefined || true);
      } else {
        next.models = [];
      }
      if (llmBase.trim()) next.llm_api_base = llmBase.trim(); else delete next.llm_api_base;
      if (llmModel.trim()) next.llm_model = llmModel.trim(); else delete next.llm_model;
      if (llmKey.trim()) next.llm_api_key = llmKey.trim();
      await configApi.update('llm_config', next);
      setLlmKeySet(Boolean(next.llm_api_key));
      setLlmKey('');
      message.success('AI 选点 LLM 配置已保存（热更，下次选点生效）');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setLlmSaving(false);
    }
  };

  const handleRemotionToggle = async (checked: boolean) => {
    setRemotionEnabled(checked);
    setRemotionSaving(true);
    try {
      await configApi.update('remotion_enabled', checked);
      message.success(checked ? 'Remotion 渲染已开启' : 'Remotion 渲染已关闭');
    } catch (err: unknown) {
      setRemotionEnabled(!checked);
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setRemotionSaving(false);
    }
  };

  const renderConfigValue = (config: SystemConfig) => {
    const displayText = typeof config.value === 'object' && config.value !== null
      ? JSON.stringify(config.value, null, 2)
      : String(config.value ?? '');

    const isLongText = displayText.length > 80;
    const display = isLongText ? displayText.substring(0, 80) + '…' : displayText;

    return (
      <Space>
        <Tooltip title={isLongText ? displayText : undefined}>
          <Text
            style={{
              fontFamily: 'monospace',
              fontSize: 12,
              maxWidth: 400,
              display: 'inline-block',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {display}
          </Text>
        </Tooltip>
        <Button size="small" icon={<EditOutlined />} onClick={() => handleConfigEdit(config)}>编辑</Button>
        <Popconfirm title="确认恢复默认值？" description="该配置项将恢复为系统默认值" onConfirm={() => handleConfigReset(config)}>
          <Button size="small" icon={<ReloadOutlined />}>恢复默认</Button>
        </Popconfirm>
      </Space>
    );
  };

  const configColumns = [
    { title: '配置项', dataIndex: 'key', key: 'key', width: 200, render: (k: string) => <Tag>{k}</Tag> },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      width: 360,
      render: (d: string) => d ? (
        <Text type="secondary" style={{ fontSize: 12, display: 'inline-block', whiteSpace: 'pre-wrap' }}>{d}</Text>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>—</Text>
      ),
    },
    {
      title: '值',
      key: 'value',
      width: 340,
      render: (_: unknown, c: SystemConfig) => renderConfigValue(c),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 150,
      render: (d: string) => formatDateTime(d),
    },
  ];

  const profileColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 100, render: (p: string) => <Tag>{p}</Tag> },
    { title: '说明', dataIndex: 'description', key: 'description', width: 260, render: (d: string) => d ? <Text type="secondary" style={{ fontSize: 12 }}>{d}</Text> : <Text type="secondary" style={{ fontSize: 12 }}>—</Text> },
    { title: '目标分辨率', dataIndex: 'target_resolution', key: 'target_resolution', width: 110, render: (v: string) => v || '-' },
    { title: '目标码率', dataIndex: 'target_bitrate', key: 'target_bitrate', width: 110, render: (v: string) => v || '-' },
    { title: '最大时长', dataIndex: 'max_duration', key: 'max_duration', width: 100, render: (v: number) => v ?? '-' },
    {
      title: '操作',
      key: 'action',
      width: 240,
      render: (_: unknown, p: PlatformProfile) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditing(p);
            profileForm.setFieldsValue({
              name: p.name,
              platform: p.platform,
              description: p.description ?? '',
              target_resolution: p.target_resolution,
              target_bitrate: p.target_bitrate,
              max_duration: p.max_duration,
              dedupe_config: p.dedupe_config ? JSON.stringify(p.dedupe_config, null, 2) : '',
            });
            setProfileModal(true);
          }}>编辑</Button>
          <Popconfirm title="确认恢复默认？" description="去重 JSON、分辨率、码率将恢复为内置默认值" onConfirm={() => handleProfileReset(p)}>
            <Button size="small" icon={<ReloadOutlined />}>恢复默认</Button>
          </Popconfirm>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={async () => {
            try {
              await configApi.deletePlatformProfile(p.id);
              message.success('已删除');
              fetchAll();
            } catch (err: unknown) {
              message.error(err instanceof Error ? err.message : '删除失败');
            }
          }}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1200, overflow: 'hidden' }}>
      <Title level={4} style={{ marginBottom: 16 }}>系统设置</Title>
      <Card title="ASR 引擎（语音识别）" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            选择切片字幕使用的语音识别引擎。切换立即生效（下次生成字幕时采用），无需重启服务。
          </Text>
          <Select
            value={asrMethod}
            loading={asrSaving}
            style={{ width: 360 }}
            onChange={handleAsrChange}
            options={[
              { value: 'aliyun_speech', label: '阿里云 ASR（qwen3-asr-flash，需 DASHSCOPE_API_KEY）' },
              { value: 'whisper', label: '本地 Whisper（faster-whisper，无需 API Key）' },
              { value: 'funasr_local', label: '本地 FunASR (SenseVoice) — 已安装，CPU 推理无需 API Key' },
            ]}
          />
          {asrMethod === 'funasr_local' && (
            <Alert
              type="success"
              showIcon
              message="FunASR 运行时已安装（SenseVoice-Small + fsmn-vad + ct-punc，CPU 推理，无需 API Key）。切换后下次生成字幕即采用。"
            />
          )}
        </Space>
      </Card>
      <Card title="AI 选点 LLM（网关）" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            选点用的文本 LLM（OpenAI 兼容网关）。在剧集详情页「选片线」的「选点模型」选择
            「跟随系统设置」时即使用此处配置；选择 MiMo/qwen 预设时按预设覆盖模型与地址。
            密钥留空表示保持已存值不变。
          </Text>
          <Space wrap align="center">
            <Text strong style={{ fontSize: 13 }}>API 地址</Text>
            <Input
              style={{ width: 320 }}
              placeholder="如 https://dashscope.aliyuncs.com/compatible-mode/v1"
              value={llmBase}
              onChange={(e) => setLlmBase(e.target.value)}
            />
            <Text strong style={{ fontSize: 13 }}>模型名</Text>
            <Input
              style={{ width: 220 }}
              placeholder="如 qwen-plus / mimo-v2.6-flash"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
            />
          </Space>
          <Space wrap align="center">
            <Text strong style={{ fontSize: 13 }}>API 密钥</Text>
            <Input.Password
              style={{ width: 320 }}
              placeholder={llmKeySet ? '已保存（留空保持不变）' : '留空则沿用部署侧 .env 的 LLM_API_KEY'}
              value={llmKey}
              onChange={(e) => setLlmKey(e.target.value)}
            />
            <Button type="primary" loading={llmSaving} onClick={handleLlmSave}>保存 LLM 配置</Button>
          </Space>
          <div style={{ borderTop: '1px dashed #e8e8e8', paddingTop: 12, marginTop: 4 }}>
            <Text strong style={{ fontSize: 13 }}>模型仓库（保存多个命名模型，供选点界面下拉选择）</Text>
            {llmRepoEntries.length > 0 && (
              <Table
                size="small"
                style={{ marginTop: 8 }}
                pagination={false}
                rowKey={(r) => r.name}
                dataSource={llmRepoEntries}
                columns={[
                  { title: '名称', dataIndex: 'name', width: 160,
                    render: (v: string, _r, idx: number) => (
                      <Input size="small" value={v} onChange={(e) => setLlmRepoEntries((prev) => prev.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))} />) },
                  { title: '模型名', dataIndex: 'model', width: 180,
                    render: (v: string, _r, idx: number) => (
                      <Input size="small" value={v} onChange={(e) => setLlmRepoEntries((prev) => prev.map((x, i) => (i === idx ? { ...x, model: e.target.value } : x)))} />) },
                  { title: 'API 地址', dataIndex: 'api_base',
                    render: (v: string, _r, idx: number) => (
                      <Input size="small" value={v} onChange={(e) => setLlmRepoEntries((prev) => prev.map((x, i) => (i === idx ? { ...x, api_base: e.target.value } : x)))} />) },
                  { title: 'API 密钥', dataIndex: 'api_key', width: 200,
                    render: (v: string, _r, idx: number) => (
                      <Input.Password size="small" placeholder={v ? '已保存（留空保持不变）' : '可选'} value={v} onChange={(e) => setLlmRepoEntries((prev) => prev.map((x, i) => (i === idx ? { ...x, api_key: e.target.value } : x)))} />) },
                  { title: '', width: 60,
                    render: (_v: unknown, _r: unknown, idx: number) => (
                      <Button size="small" danger type="text" onClick={() => setLlmRepoEntries((prev) => prev.filter((_, i) => i !== idx))}>删除</Button>) },
                ]}
              />
            )}
            <Space wrap align="center" style={{ marginTop: 8 }}>
              <Input size="small" placeholder="名称（如 通义qwen）" style={{ width: 160 }} value={llmNewEntry.name}
                onChange={(e) => setLlmNewEntry((p) => ({ ...p, name: e.target.value }))} />
              <Input size="small" placeholder="模型名" style={{ width: 180 }} value={llmNewEntry.model}
                onChange={(e) => setLlmNewEntry((p) => ({ ...p, model: e.target.value }))} />
              <Input size="small" placeholder="API 地址（可选）" style={{ width: 240 }} value={llmNewEntry.api_base}
                onChange={(e) => setLlmNewEntry((p) => ({ ...p, api_base: e.target.value }))} />
              <Input.Password size="small" placeholder="API 密钥（可选）" style={{ width: 180 }} value={llmNewEntry.api_key}
                onChange={(e) => setLlmNewEntry((p) => ({ ...p, api_key: e.target.value }))} />
              <Button size="small" icon={<PlusOutlined />} disabled={!llmNewEntry.name.trim() || !llmNewEntry.model.trim()}
                onClick={() => { setLlmRepoEntries((prev) => [...prev, { ...llmNewEntry }]); setLlmNewEntry({ name: '', model: '', api_base: '', api_key: '' }); }}>
                添加模型
              </Button>
            </Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              保存后，剧集详情页「选片线 · 选点模型」下拉即可选择这些命名模型；密钥由服务端保管，不下发前端。
            </Text>
          </div>
        </Space>
      </Card>
      <Card title="Remotion 渲染（高光混剪增强）" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            开启后，切片勾选「Remotion 混剪增强」时将使用 Remotion 引擎渲染增强版高光混剪
            （片头标题卡 + 段间转场 + 字幕叠加 + 段标题 + 片尾卡），替代裸 concat 拼接。
            关闭即回退 ffmpeg 原链路，零侵入。
          </Text>
          <Space align="center">
            <Switch
              checked={remotionEnabled}
              loading={remotionSaving}
              onChange={handleRemotionToggle}
            />
            <Text strong style={{ fontSize: 13 }}>Remotion 渲染{remotionEnabled ? '已开启' : '已关闭'}</Text>
          </Space>
          <Alert
            type={remotionEnabled ? 'success' : 'info'}
            showIcon
            message={remotionEnabled
              ? 'Remotion 渲染已启用：新切片任务勾选「Remotion 混剪增强」即走增强渲染（独立 worker，渲染约需数分钟）。'
              : 'Remotion 渲染已关闭：所有切片走 ffmpeg 原链路，不受影响。'}
          />
        </Space>
      </Card>
      <Card size="small" title="全局配置" style={{ marginBottom: 16 }}>
        <Table
          rowKey="key"
          columns={configColumns}
          dataSource={configs}
          pagination={false}
          size="small"
          scroll={{ x: 1080 }}
        />
      </Card>
      <Card
        size="small"
        title="平台去重配置"
        extra={
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => {
            setEditing(null);
            profileForm.resetFields();
            setProfileModal(true);
          }}>新增配置</Button>
        }
      >
        <Table
          rowKey="id"
          columns={profileColumns}
          dataSource={profiles}
          pagination={false}
          size="small"
          scroll={{ x: 1020 }}
        />
      </Card>

      {/* 编辑全局配置弹窗 */}
      <Modal
        title={editingConfig ? `编辑配置: ${editingConfig.key}` : '编辑配置'}
        open={configModal}
        onOk={handleConfigSave}
        onCancel={() => {
          setConfigModal(false);
          setEditingConfig(null);
        }}
        destroyOnClose
        width={600}
      >
        <Form form={configForm} layout="vertical">
          {editingConfig?.description && (
            <Alert type="info" showIcon style={{ marginBottom: 12 }} message={editingConfig.description} />
          )}
          <Form.Item
            name="value"
            label="配置值"
            rules={[{ required: true, message: '请输入配置值' }]}
          >
            <Input.TextArea
              rows={8}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
              placeholder="请输入配置值…"
            />
          </Form.Item>
          {editingConfig && typeof editingConfig.value === 'object' && editingConfig.value !== null && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              提示：该配置项为 JSON 格式，请确保输入合法的 JSON 字符串
            </Text>
          )}
        </Form>
      </Modal>

      {/* 编辑平台配置弹窗 */}
      <Modal
        title={editing ? '编辑平台配置' : '新增平台配置'}
        open={profileModal}
        onOk={saveProfile}
        onCancel={() => setProfileModal(false)}
        destroyOnClose
        width={560}
      >
        <Form form={profileForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={3} placeholder="填写该配置的用途说明（可选）" /></Form.Item>
          <Form.Item name="target_resolution" label="目标分辨率"><Input placeholder="1280x720" /></Form.Item>
          <Form.Item name="target_bitrate" label="目标码率"><Input placeholder="2500k" /></Form.Item>
          <Form.Item label="快捷选择（按平台常见分辨率/码率）">
            <Space wrap>
              {(presets[selectedPlatform || ''] || []).map((p2) => (
                <Button key={p2.label} size="small" onClick={() => applyPreset(selectedPlatform || '', p2)}>
                  {p2.label}
                </Button>
              ))}
            </Space>
          </Form.Item>
          <Form.Item name="max_duration" label="最大时长（秒）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="dedupe_config" label="去重配置 JSON"
            extra={<Text type="secondary" style={{ fontSize: 12 }}>新体系：preset（light/standard/heavy 基础档位）+ manual（逐项覆盖四层去重手段：crop/hflip/speed/saturation/gamma/contrast/brightness/noise/scanline/vignette/roll_band/jitter/sharpen/watermark）。未填 manual 时沿用 preset 预设。用于降低平台查重风险。</Text>}
          ><Input.TextArea rows={6} style={{ fontFamily: 'monospace' }} placeholder='{"preset": "standard", "manual": {"sharpen": 0.8}}' /></Form.Item>
          <Form.Item label=" ">
            <Button size="small" icon={<ReloadOutlined />} onClick={() => {
              // 恢复默认去重 JSON 示例
              profileForm.setFieldsValue({
                dedupe_config: JSON.stringify({
                  preset: 'standard',
                  manual: { speed: 1.05, sharpen: 0.8 },
                }, null, 2),
              });
            }}>恢复去重 JSON 默认值</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Settings;