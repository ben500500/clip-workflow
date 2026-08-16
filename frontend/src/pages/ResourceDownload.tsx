import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Tabs, Form, Input, Select, Button, Table, Tag, message, Space,
  Typography, Progress, Modal, Alert,
} from 'antd';
import {
  ImportOutlined, DownloadOutlined,
  LinkOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { wechatDlApi, WechatDlTask } from '../api/wechatDl';
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

// ========== 链接导入 Tab ==========
const ImportPanel: React.FC = () => {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<'single' | 'batch'>('single');

  const handleImport = async () => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      if (mode === 'single') {
        const res = await wechatDlApi.import({
          source_url: values.source_url.trim(),
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
        message="直接导入"
        description="粘贴视频号分享链接即可创建下载任务，无需绑定授权材料（授权校验已移除）。"
      />
      <Space style={{ marginBottom: 16 }}>
        <Button
          type={mode === 'single' ? 'primary' : 'default'}
          icon={<LinkOutlined />}
          onClick={() => { setMode('single'); form.resetFields(); }}
        >
          单链接导入
        </Button>
        <Button
          type={mode === 'batch' ? 'primary' : 'default'}
          icon={<ImportOutlined />}
          onClick={() => { setMode('batch'); form.resetFields(); }}
        >
          批量导入
        </Button>
      </Space>

      <Form
        form={form}
        layout="vertical"
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

  // WebSocket 实时进度（页面订阅刷新）
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
        ]}
      />
    </div>
  );
};

export default ResourceDownload;
