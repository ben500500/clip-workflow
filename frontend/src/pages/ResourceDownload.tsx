import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Tabs, Form, Input, Select, Button, Table, Tag, message, Space,
  Typography, Progress, Modal, Alert, Radio,
} from 'antd';
import {
  ImportOutlined, DownloadOutlined,
  LinkOutlined, ReloadOutlined,
  EyeOutlined, ExportOutlined, PlusOutlined, FolderOpenOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { wechatDlApi, WechatDlTask } from '../api/wechatDl';
import { projectApi } from '../api/projects';
import { configApi } from '../api/config';
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
  // 默认下载分辨率（720p/1080p，默认 720p）：入库前统一缩放
  const [dlResolution, setDlResolution] = useState<string>('720p');
  const [dlResolutionSaving, setDlResolutionSaving] = useState(false);

  // 加载全局默认下载分辨率配置
  useEffect(() => {
    configApi.getAll().then((cfgs) => {
      const cfg = cfgs.find((c) => c.key === 'default_download_resolution');
      if (cfg && (cfg.value === '720p' || cfg.value === '1080p')) {
        setDlResolution(String(cfg.value));
      }
    }).catch(() => undefined);
  }, []);

  const handleResolutionChange = (v: string) => {
    setDlResolution(v);
    setDlResolutionSaving(true);
    configApi.update('default_download_resolution', v)
      .then(() => message.success(`默认分辨率已设为 ${v}`))
      .catch(() => { setDlResolution('720p'); message.error('保存默认分辨率失败'); })
      .finally(() => setDlResolutionSaving(false));
  };

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

      <Space align="center" size={8} style={{ marginBottom: 16 }}>
        <Text strong style={{ fontSize: 13 }}>默认分辨率</Text>
        <Select
          value={dlResolution}
          onChange={handleResolutionChange}
          loading={dlResolutionSaving}
          style={{ width: 120 }}
          options={[
            { value: '720p', label: '720p' },
            { value: '1080p', label: '1080p' },
          ]}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          下载入库时按所选分辨率统一缩放（默认 720p），更省存储且适配主流清晰度
        </Text>
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
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<WechatDlTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  // 查看/下载结果 modal
  const [previewTask, setPreviewTask] = useState<WechatDlTask | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // 一键导入切片 modal
  const [importTask, setImportTask] = useState<WechatDlTask | null>(null);
  const [importTarget, setImportTarget] = useState<'new' | 'existing'>('new');
  const [importName, setImportName] = useState('');
  const [importProjectId, setImportProjectId] = useState<string | undefined>();
  const [projectOptions, setProjectOptions] = useState<{ value: string; label: string }[]>([]);
  const [importBusy, setImportBusy] = useState(false);

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

  const canImport = (t: WechatDlTask) => t.status === 'completed' && !!t.episode_id;

  const openPreview = async (t: WechatDlTask) => {
    setPreviewTask(t);
    setPreviewUrl(null);
    setPreviewLoading(true);
    try {
      const res = await projectApi.getVideoUrl(t.episode_id as string);
      setPreviewUrl(res.url);
    } catch {
      message.error('获取预览地址失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const openImport = async (t: WechatDlTask) => {
    setImportTask(t);
    setImportTarget('new');
    const meta = (t.video_meta || {}) as Record<string, unknown>;
    setImportName(typeof meta.title === 'string' && meta.title ? meta.title : '');
    setImportProjectId(undefined);
    setImportBusy(false);
    try {
      const res = await projectApi.getList({ page_size: 200 });
      setProjectOptions((res.items || []).map((p) => ({ value: p.id, label: p.name })));
    } catch {
      setProjectOptions([]);
    }
  };

  const handleImportConfirm = async () => {
    if (!importTask) return;
    if (importTarget === 'new' && !importName.trim()) {
      message.warning('请输入切片项目名称');
      return;
    }
    if (importTarget === 'existing' && !importProjectId) {
      message.warning('请选择目标切片项目');
      return;
    }
    setImportBusy(true);
    try {
      const res = await wechatDlApi.importToProject(importTask.id, {
        target: importTarget,
        project_name: importTarget === 'new' ? importName.trim() : undefined,
        project_id: importTarget === 'existing' ? importProjectId : undefined,
      });
      message.success('已导入切片项目，正在跳转…');
      setImportTask(null);
      navigate(`/projects/${res.project_id}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '导入失败');
    } finally {
      setImportBusy(false);
    }
  };

  const metaDuration = (t: WechatDlTask): string => {
    const meta = (t.video_meta || {}) as Record<string, unknown>;
    const d = typeof meta.duration === 'number' ? meta.duration : null;
    if (d == null || !isFinite(d)) return '-';
    const m = Math.floor(d / 60);
    const s = Math.floor(d % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  };

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
      title: '结果', dataIndex: 'video_meta', key: 'result', width: 200, ellipsis: true,
      render: (_: unknown, r: WechatDlTask) => {
        if (!canImport(r)) return <Text type="secondary" style={{ fontSize: 12 }}>-</Text>;
        const meta = (r.video_meta || {}) as Record<string, unknown>;
        const title = typeof meta.title === 'string' && meta.title ? meta.title : '已下载素材';
        return (
          <Space size={4}>
            <VideoCameraOutlined style={{ color: '#7b6ed4' }} />
            <span style={{ fontSize: 12 }}>{title}</span>
            <Text type="secondary" style={{ fontSize: 12 }}>{metaDuration(r)}</Text>
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
      title: '操作', dataIndex: 'action', key: 'action', width: 190, fixed: 'right' as const,
      render: (_: unknown, r: WechatDlTask) => {
        if (!canImport(r)) return <Text type="secondary" style={{ fontSize: 12 }}>-</Text>;
        return (
          <Space size={4}>
            <Button size="small" icon={<EyeOutlined />} onClick={() => openPreview(r)}>查看</Button>
            <Button size="small" type="primary" icon={<ExportOutlined />} onClick={() => openImport(r)}>导入切片</Button>
          </Space>
        );
      },
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
        scroll={{ x: 1200 }}
      />

      {/* 查看 / 下载结果 */}
      <Modal
        open={!!previewTask}
        title="查看下载结果"
        footer={null}
        onCancel={() => setPreviewTask(null)}
        width={720}
        destroyOnClose
      >
        {previewTask && (
          <div>
            <p style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{previewTask.source_url}</Text>
            </p>
            {previewLoading && <Progress percent={30} status="active" />}
            {!previewLoading && previewUrl && (
              <video controls src={previewUrl} style={{ width: '100%', borderRadius: 8, background: '#000' }} />
            )}
            {!previewLoading && !previewUrl && <Text type="danger">无法获取视频地址</Text>}
            {previewUrl && (
              <div style={{ marginTop: 12 }}>
                <Button icon={<DownloadOutlined />} href={previewUrl} target="_blank" rel="noreferrer">
                  下载视频（新标签页中保存）
                </Button>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* 一键导入切片 */}
      <Modal
        open={!!importTask}
        title="一键导入切片"
        okText="确认导入"
        cancelText="取消"
        confirmLoading={importBusy}
        onOk={handleImportConfirm}
        onCancel={() => setImportTask(null)}
        destroyOnClose
      >
        {importTask && (
          <div>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="将把该下载任务的素材归入切片项目"
              description={`来源：${(importTask.video_meta as Record<string, unknown>)?.title || importTask.source_url}`}
            />
            <Radio.Group
              value={importTarget}
              onChange={(e) => setImportTarget(e.target.value)}
              style={{ marginBottom: 16 }}
            >
              <Radio.Button value="new"><PlusOutlined /> 新建切片项目</Radio.Button>
              <Radio.Button value="existing"><FolderOpenOutlined /> 加入已有切片项目</Radio.Button>
            </Radio.Group>

            {importTarget === 'new' ? (
              <Form layout="vertical">
                <Form.Item label="切片项目名称" required>
                  <Input
                    placeholder="请输入切片项目名称"
                    value={importName}
                    onChange={(e) => setImportName(e.target.value)}
                    maxLength={255}
                  />
                </Form.Item>
              </Form>
            ) : (
              <Form layout="vertical">
                <Form.Item label="选择切片项目" required>
                  <Select
                    showSearch
                    placeholder="搜索并选择已有切片项目"
                    value={importProjectId}
                    onChange={setImportProjectId}
                    options={projectOptions}
                    filterOption={(input, option) =>
                      (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                    }
                  />
                </Form.Item>
              </Form>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              导入后页面将自动跳转到对应的切片项目。
            </Text>
          </div>
        )}
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
        ]}
      />
    </div>
  );
};

export default ResourceDownload;
