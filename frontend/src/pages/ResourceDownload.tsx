import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Tabs, Form, Input, Select, Button, Table, Tag, message, Space,
  Typography, Progress, Popconfirm, Modal, Alert, Divider, Switch,
} from 'antd';
import {
  ImportOutlined, DownloadOutlined, SafetyCertificateOutlined,
  LinkOutlined, PlusOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { wechatDlApi, WechatDlTask, WechatDlAuth } from '../api/wechatDl';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ========== 状态展示辅助 ==========
const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '排队中' },
  parsing: { color: 'processing', label: '解析中' },
  downloading: { color: 'processing', label: '下载中' },
  uploading: { color: 'processing', label: '入库中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

const SOURCE_TYPE_META: Record<string, string> = {
  authorized: '已授权素材',
  self_owned: '自有账号',
};

// ========== 链接导入 Tab ==========
const ImportPanel: React.FC = () => {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [auths, setAuths] = useState<WechatDlAuth[]>([]);
  const [mode, setMode] = useState<'single' | 'batch'>('single');

  const loadAuths = useCallback(() => {
    wechatDlApi.getAuths().then((res) => setAuths(res.items || [])).catch(() => undefined);
  }, []);

  useEffect(() => { loadAuths(); }, [loadAuths]);

  const handleImport = async () => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      if (mode === 'single') {
        const res = await wechatDlApi.import({
          source_url: values.source_url.trim(),
          source_type: values.source_type || 'authorized',
          project_id: values.project_id || undefined,
          auth_id: values.auth_id || undefined,
          authorize_owner: values.authorize_owner,
          authorize_note: values.authorize_note,
        });
        message.success(`已创建下载任务（${res.message}）`);
      } else {
        const urls = (values.source_urls || [])
          .map((u: string) => u.trim())
          .filter(Boolean);
        if (urls.length === 0) {
          message.warning('请至少填写一个视频号分享链接');
          return;
        }
        const res = await wechatDlApi.importBatch({
          source_urls: urls,
          source_type: values.source_type || 'authorized',
          project_id: values.project_id || undefined,
          auth_id: values.auth_id || undefined,
          authorize_owner: values.authorize_owner,
          authorize_note: values.authorize_note,
        });
        message.success(`批量导入完成：${res.message}`);
        if (res.skipped_reasons?.length) {
          Modal.warning({
            title: `跳过 ${res.skipped} 条`,
            content: (
              <ul style={{ paddingLeft: 18, margin: 0 }}>
                {res.skipped_reasons.slice(0, 10).map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            ),
          });
        }
      }
      form.resetFields();
      form.setFieldsValue({ source_type: 'authorized' });
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '导入失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card size="small" title="导入视频号素材（URL 直链）">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="合规红线"
        description="导入「已授权第三方素材」必须绑定授权材料（选择已登记授权或填写授权备注），否则将被系统拦截（HTTP 403）。自有账号素材可选 self_owned 类型免授权材料。"
      />
      <Space style={{ marginBottom: 16 }}>
        <Button
          type={mode === 'single' ? 'primary' : 'default'}
          icon={<LinkOutlined />}
          onClick={() => { setMode('single'); form.resetFields(); form.setFieldsValue({ source_type: 'authorized' }); }}
        >
          单链接导入
        </Button>
        <Button
          type={mode === 'batch' ? 'primary' : 'default'}
          icon={<ImportOutlined />}
          onClick={() => { setMode('batch'); form.resetFields(); form.setFieldsValue({ source_type: 'authorized' }); }}
        >
          批量导入
        </Button>
      </Space>

      <Form
        form={form}
        layout="vertical"
        initialValues={{ source_type: 'authorized' }}
        style={{ maxWidth: 720 }}
      >
        {mode === 'single' ? (
          <Form.Item
            name="source_url"
            label="视频号分享链接"
            rules={[{ required: true, message: '请输入视频号分享链接' }]}
          >
            <Input placeholder="粘贴视频号分享链接，如 https://channels.weixin.qq.com/..." />
          </Form.Item>
        ) : (
          <Form.Item
            name="source_urls"
            label="视频号分享链接（每行一条）"
            rules={[{ required: true, message: '请输入至少一个链接' }]}
          >
            <TextArea
              rows={5}
              placeholder={'每行粘贴一个视频号分享链接\n支持一次批量导入最多 100 条'}
            />
          </Form.Item>
        )}

        <Form.Item name="source_type" label="素材类型">
          <Select
            options={[
              { value: 'authorized', label: '已授权第三方素材' },
              { value: 'self_owned', label: '自有账号素材' },
            ]}
          />
        </Form.Item>

        <Form.Item name="auth_id" label="绑定已登记授权（推荐）">
          <Select
            allowClear
            placeholder="选择已登记授权材料"
            options={auths.filter((a) => a.is_active).map((a) => ({
              value: a.id,
              label: `${a.owner || '未命名'}（${a.type || 'channel_auth'}）${a.note ? ' - ' + a.note : ''}`,
            }))}
          />
        </Form.Item>

        <Divider plain style={{ margin: '4px 0 16px' }}>或即时登记授权材料（文字备注通道）</Divider>

        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="authorize_owner" label="授权主体">
            <Input placeholder="如：XX 版权方" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item
            name="authorize_note"
            label="授权备注"
            style={{ flex: 1 }}
          >
            <TextArea placeholder="授权材料说明，如：已获授权书 2026-08（未填写则需选择上方已登记授权）" rows={2} />
          </Form.Item>
        </Space>

        <Button
          type="primary"
          icon={mode === 'single' ? <LinkOutlined /> : <ImportOutlined />}
          loading={busy}
          onClick={handleImport}
        >
          {mode === 'single' ? '提交导入' : '批量提交'}
        </Button>
      </Form>
    </Card>
  );
};

// ========== 下载任务 Tab ==========
const TaskListPanel: React.FC = () => {
  const [tasks, setTasks] = useState<WechatDlTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  const loadTasks = useCallback(() => {
    setLoading(true);
    wechatDlApi.getTasks(statusFilter ? { status: statusFilter, limit: 50 } : { limit: 50 })
      .then((res) => setTasks(res.items || []))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(() => { loadTasks(); }, [loadTasks]);

  // WebSocket 实时进度（P0 已实现，页面订阅刷新）
  useEffect(() => {
    const sockets = new Map<string, WebSocket>();
    tasks.forEach((t) => {
      if (['pending', 'parsing', 'downloading', 'uploading'].includes(t.status) && !sockets.has(t.id)) {
        let ws: WebSocket;
        try {
          const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
          ws = new WebSocket(`${proto}://${window.location.host}/ws/wechat-dl/${t.id}`);
          ws.onmessage = (ev) => {
            try {
              const data = JSON.parse(ev.data as string);
              setTasks((prev) => prev.map((p) =>
                p.id === data.task_id
                  ? { ...p, status: data.status, progress: data.progress, message: data.message, error_message: data.error_message }
                  : p
              ));
            } catch { /* ignore */ }
          };
          sockets.set(t.id, ws);
        } catch { /* ignore */ }
      }
    });
    return () => { sockets.forEach((ws) => { try { ws.close(); } catch { /* ignore */ } }); };
  }, [tasks.map((t) => t.id).join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns = [
    { title: '来源链接', dataIndex: 'source_url', key: 'source_url', ellipsis: true, render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text> },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string, r: WechatDlTask) => {
        const meta = STATUS_META[v] || { color: 'default', label: v };
        return (
          <Space direction="vertical" size={0} style={{ width: '100%' }}>
            <Tag color={meta.color}>{meta.label}</Tag>
            {r.progress != null && ['parsing', 'downloading', 'uploading'].includes(v) && (
              <Progress percent={Math.round(r.progress)} size="small" style={{ width: 120 }} />
            )}
          </Space>
        );
      },
    },
    {
      title: '类型', dataIndex: 'source_type', key: 'source_type', width: 110,
      render: (v: string) => <Tag color={v === 'self_owned' ? 'blue' : 'purple'}>{SOURCE_TYPE_META[v] || v}</Tag>,
    },
    {
      title: '授权来源', dataIndex: 'source_authorize', key: 'source_authorize', width: 160, ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '进度消息', dataIndex: 'message', key: 'message', ellipsis: true,
      render: (v: string | null, r: WechatDlTask) =>
        r.status === 'failed'
          ? <Text type="danger" style={{ fontSize: 12 }}>{r.error_message || v}</Text>
          : <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (d: string) => formatDateTime(d),
    },
  ];

  return (
    <Card
      size="small"
      title="下载任务"
      extra={
        <Space>
          <Select
            allowClear
            placeholder="状态过滤"
            style={{ width: 130 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={Object.entries(STATUS_META).map(([v, m]) => ({ value: v, label: m.label }))}
          />
          <Button size="small" icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={tasks}
        pagination={{ pageSize: 20 }}
        scroll={{ x: 1000 }}
      />
    </Card>
  );
};

// ========== 授权管理 Tab ==========
const AuthPanel: React.FC = () => {
  const [auths, setAuths] = useState<WechatDlAuth[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<WechatDlAuth | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(() => {
    setLoading(true);
    wechatDlApi.getAuths().then((res) => setAuths(res.items || [])).catch(() => undefined).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ authorize_type: 'channel_auth', is_active: true });
    setModalOpen(true);
  };

  const openEdit = (auth: WechatDlAuth) => {
    setEditing(auth);
    form.setFieldsValue({
      authorize_owner: auth.owner || '',
      authorize_type: auth.type || 'channel_auth',
      authorize_scope: auth.scope || '',
      authorize_note: auth.note || '',
      is_active: auth.is_active,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    try {
      if (editing) {
        await wechatDlApi.updateAuth(editing.id, values);
        message.success('授权材料已更新');
      } else {
        await wechatDlApi.createAuth(values);
        message.success('授权材料已登记');
      }
      setModalOpen(false);
      load();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await wechatDlApi.deleteAuth(id);
      message.success('已删除');
      load();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleToggle = async (auth: WechatDlAuth) => {
    try {
      await wechatDlApi.toggleAuth(auth.id);
      message.success(auth.is_active ? '已停用（关联链接将拦截）' : '已启用');
      load();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '切换失败');
    }
  };

  const columns = [
    { title: '授权主体', dataIndex: 'owner', key: 'owner', width: 160, render: (v: string | null) => v || '-' },
    {
      title: '类型', dataIndex: 'type', key: 'type', width: 120,
      render: (v: string | null) => <Tag>{v || 'other'}</Tag>,
    },
    { title: '授权备注', dataIndex: 'note', key: 'note', ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '授权范围', dataIndex: 'scope', key: 'scope', width: 180, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 90,
      render: (v: boolean) => (v ? <Tag color="success">有效</Tag> : <Tag color="default">失效</Tag>),
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (d: string | null) => formatDateTime(d),
    },
    {
      title: '操作', key: 'op', width: 200,
      render: (_: unknown, r: WechatDlAuth) => (
        <Space>
          <Switch size="small" checked={r.is_active} onChange={() => handleToggle(r)} checkedChildren="开" unCheckedChildren="关" />
          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="确认删除该授权材料？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title="授权材料管理"
      extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreate}>登记授权</Button>}
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="授权文件通道暂未启用（P1 后续版本），当前仅支持文字备注通道。失效的授权材料将导致关联链接导入被拦截。"
      />
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={auths}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1000 }}
      />

      <Modal
        title={editing ? '编辑授权材料' : '登记授权材料'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText={editing ? '保存' : '登记'}
      >
        <Form form={form} layout="vertical" initialValues={{ authorize_type: 'channel_auth', is_active: true }}>
          <Form.Item
            name="authorize_owner"
            label="授权主体"
            rules={[{ required: true, message: '请输入授权主体' }]}
          >
            <Input placeholder="如：XX 版权方 / XX 授权账号" />
          </Form.Item>
          <Form.Item name="authorize_type" label="授权类型">
            <Select
              options={[
                { value: 'copyright', label: '版权授权' },
                { value: 'channel_auth', label: '账号授权' },
                { value: 'other', label: '其他' },
              ]}
            />
          </Form.Item>
          <Form.Item name="authorize_note" label="授权备注" rules={[{ required: true, message: '请输入授权材料备注' }]}>
            <TextArea rows={2} placeholder="授权材料内容/说明，如：已获授权书 2026-08" />
          </Form.Item>
          <Form.Item name="authorize_scope" label="授权范围">
            <Input placeholder="可选的授权范围描述" />
          </Form.Item>
          <Form.Item name="is_active" label="是否有效" valuePropName="checked">
            <Switch checkedChildren="有效" unCheckedChildren="失效" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
};

// ========== 主页面 ==========
const ResourceDownload: React.FC = () => {
  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>资源下载</Title>
      <Tabs
        defaultActiveKey="import"
        items={[
          {
            key: 'import',
            label: <span><ImportOutlined /> 链接导入</span>,
            children: <ImportPanel />,
          },
          {
            key: 'tasks',
            label: <span><DownloadOutlined /> 下载任务</span>,
            children: <TaskListPanel />,
          },
          {
            key: 'auths',
            label: <span><SafetyCertificateOutlined /> 授权管理</span>,
            children: <AuthPanel />,
          },
        ]}
      />
    </div>
  );
};

export default ResourceDownload;
