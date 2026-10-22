import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Tabs, Form, Input, Select, Button, Table, Tag, message, Space,
  Typography, Progress, Modal, Alert, Radio, Tooltip, Upload, Segmented, Switch,
} from 'antd';
import {
  ImportOutlined, DownloadOutlined,
  LinkOutlined, ReloadOutlined, ScissorOutlined,
  EyeOutlined, ExportOutlined, PlusOutlined, FolderOpenOutlined,
  VideoCameraOutlined, ApiOutlined, GlobalOutlined, SafetyCertificateOutlined,
  FileTextOutlined, CopyOutlined, ThunderboltOutlined, RobotOutlined,
  InboxOutlined, CloudUploadOutlined, RedoOutlined,
  AudioOutlined, ScissorOutlined as EraserIcon, PictureOutlined, SoundOutlined,
  ExperimentOutlined, DownloadOutlined as DownloadFileIcon, PlayCircleOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  wechatDlApi, WechatDlTask, WechatDlProviderInfo, WechatDlPromptTask,
  ZhilingServiceTask, ZhilingServiceTaskType, ZhilingServiceOptions,
} from '../api/wechatDl';
import { projectApi } from '../api/projects';
import { configApi } from '../api/config';
import { formatDateTime, parseServerTime } from '../utils/format';

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

// 反推提示词任务状态（与后端 wechat_download.models.PT_* 对齐）
const PROMPT_STATUS_META: Record<string, { color: string; label: string }> = {
  processing: { color: 'processing', label: '生成中' },
  success: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

// 反推任务轮询间隔（官方建议 3~5s 查一次；本系统查自建接口，顺带触发一次上游查询）
const PROMPT_POLL_INTERVAL_MS = 4000;

// 本地视频上传反推（ISSUE #363）：与后端 wechat_download.prompt_service.UPLOAD_ALLOWED_EXTS
// 及 settings.WECHAT_DL_PROMPT_UPLOAD_MAX_MB 对齐；前端只做预校验省一次白跑的网络请求。
export const PROMPT_UPLOAD_ACCEPT = '.mp4,.mov,.webm,.avi,.mkv,.m4v';
export const PROMPT_UPLOAD_MAX_MB = 500;

/** 上传前本地预校验：返回错误文案，通过返回 null。 */
export const validatePromptUploadFile = (file: File): string | null => {
  const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`;
  const allow = PROMPT_UPLOAD_ACCEPT.split(',');
  if (!allow.includes(ext)) {
    return `不支持的文件类型 ${ext === '.' ? '(无扩展名)' : ext}，仅支持 ${allow.join(' ')}`;
  }
  if (file.size <= 0) return '文件为空，请重新选择';
  if (file.size > PROMPT_UPLOAD_MAX_MB * 1024 * 1024) {
    return `文件过大（${(file.size / 1024 / 1024).toFixed(1)}MB），上限 ${PROMPT_UPLOAD_MAX_MB}MB`;
  }
  return null;
};

// 与后端 WECHAT_DL_STALE_TIMEOUT_SECONDS 对齐（默认 3600s）：
// 超过该时长未更新仍非终态 = worker 崩溃/节点重启遗留的孤儿任务
const STALE_TIMEOUT_MS = 60 * 60 * 1000;

/** 判断任务是否「超时卡死」（非终态且长期无更新），用于放行重试入口。 */
export const isStaleTask = (t: WechatDlTask): boolean => {
  if (['completed', 'failed'].includes(t.status)) return false;
  const ref = parseServerTime(t.updated_at || t.created_at);
  if (!ref) return false;
  return Date.now() - ref.valueOf() > STALE_TIMEOUT_MS;
};

/**
 * 复制文本到剪贴板。
 * Clipboard API 仅在安全上下文（HTTPS / localhost）可用；本系统经
 * http://192.168.1.163 局域网 IP 访问时 navigator.clipboard 为 undefined，
 * 必须回退到隐藏 textarea + document.execCommand('copy')。
 */
export const copyTextToClipboard = async (text: string): Promise<boolean> => {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch { /* 安全上下文下也可能被权限拒绝，继续走回退 */ }
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
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
          message.warning('请至少填写一个视频分享链接');
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
    <Card size="small" title="导入视频素材（URL 直链）">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="直接导入"
        description="粘贴视频分享链接即可创建下载任务，无需绑定授权材料（授权校验已移除）。支持微信视频号、抖音、快手、小红书等 30+ 平台链接（含视频直链，直链请确保已 URL 编码）。"
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
            label="视频分享链接"
            rules={[{ required: true, message: '请输入视频分享链接' }]}
          >
            <Input placeholder="粘贴视频分享链接（视频号 / 抖音 / 快手 / 小红书等 30+ 平台，或视频直链），如 https://channels.weixin.qq.com/..." />
          </Form.Item>
        ) : (
          <Form.Item
            name="source_urls"
            label="视频分享链接（每行一条）"
            rules={[{ required: true, message: '请输入至少一个链接' }]}
          >
            <TextArea
              rows={5}
              placeholder={'每行粘贴一个视频分享链接（视频号 / 抖音 / 快手 / 小红书等 30+ 平台）\n支持一次批量导入最多 100 条'}
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
const TaskListPanel: React.FC<{ onReversePrompt?: (sourceUrl: string) => void }> = ({ onReversePrompt }) => {
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

  // 方向① 闭环：下载完成 → 一键入切片
  const [slicingId, setSlicingId] = useState<string | null>(null);
  const handleToSlice = async (task: WechatDlTask) => {
    setSlicingId(task.id);
    try {
      const res = await wechatDlApi.toSlice(task.id, { mode: 'fast' });
      message.success('已投入切片队列：' + res.message);
      await loadTasks();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '入切片失败');
    } finally {
      setSlicingId(null);
    }
  };

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
  // 失败任务，或「超时卡死」的非终态任务（worker 崩溃遗留的 pending/中间态，
  // 与后端 retry_task 的放宽判定保持一致；beat 守护亦会把它们回写 failed）。
  const canRetry = (t: WechatDlTask) =>
    t.status === 'failed' || isStaleTask(t);

  // 重试失败/超时任务
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const handleRetry = async (task: WechatDlTask) => {
    setRetryingId(task.id);
    try {
      await wechatDlApi.retry(task.id);
      message.success('任务已重新投递到下载队列');
      await loadTasks();
    } catch (e: unknown) {
      // axios 拦截器已把后端 detail 归一为 Error.message
      message.error(e instanceof Error ? e.message : '重试失败');
    } finally {
      setRetryingId(null);
    }
  };

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
    {
      title: '操作', key: 'action', width: 160, fixed: 'right' as const,
      render: (_: unknown, r: WechatDlTask) => {
        const buttons = [];
        if (r.status === 'completed' && r.episode_id) {
          buttons.push(
            <Button
              key="slice"
              size="small"
              type="link"
              icon={<ScissorOutlined />}
              loading={slicingId === r.id}
              onClick={() => handleToSlice(r)}
            >
              入切片
            </Button>,
          );
        }
        // 已完成的任务：用其来源链接一键反推提示词（ISSUE #361 任务 A）
        if (r.status === 'completed' && onReversePrompt) {
          buttons.push(
            <Tooltip key="reverse" title="用该视频反推 AI 提示词">
              <Button
                size="small"
                type="link"
                icon={<RobotOutlined />}
                onClick={() => onReversePrompt(r.source_url)}
              >
                反推提示词
              </Button>
            </Tooltip>,
          );
        }
        // 失败任务，或超时卡死的孤儿任务：beat 守护回写 failed 之前的人工即时补救入口
        if (canRetry(r)) {
          buttons.push(
            <Tooltip
              key="retry"
              title={r.status === 'failed' ? '重新投递到下载队列' : '任务可能已卡死（超 1 小时无更新），点击重新投递'}
            >
              <Button
                size="small"
                type="link"
                danger={r.status !== 'failed'}
                icon={<ReloadOutlined />}
                loading={retryingId === r.id}
                onClick={() => handleRetry(r)}
              >
                重试
              </Button>
            </Tooltip>,
          );
        }
        return buttons.length ? <Space size={0}>{buttons}</Space> : <Text type="secondary" style={{ fontSize: 12 }}>-</Text>;
      },
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

// ========== 反推提示词 Tab（智令 doc/120 提交 + doc/119 轮询）==========
const ReversePromptPanel: React.FC<{ presetUrl?: string }> = ({ presetUrl }) => {
  const [form] = Form.useForm();
  const [tasks, setTasks] = useState<WechatDlPromptTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [detail, setDetail] = useState<WechatDlPromptTask | null>(null);
  // 本地视频上传（ISSUE #363）：上传进度 + 当前文件名
  const [uploading, setUploading] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [uploadName, setUploadName] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    wechatDlApi.listReversePrompts({ limit: 50 })
      .then((res) => setTasks(res.items || []))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  // 选中某个任务时拉一次最新状态（同时触发后端向上游查询一次）
  const refreshOne = useCallback(async (id: string) => {
    try {
      const t = await wechatDlApi.getReversePrompt(id);
      setTasks((prev) => prev.map((p) => (p.id === t.id ? t : p)));
      setDetail((d) => (d && d.id === t.id ? t : d));
      return t;
    } catch {
      return null;
    }
  }, []);

  // processing 的任务每 4s 轮询一次自建接口，直至终态
  const processingIds = tasks.filter((t) => t.status === 'processing').map((t) => t.id).join(',');
  useEffect(() => {
    if (!processingIds) return undefined;
    const ids = processingIds.split(',');
    const timer = setInterval(() => { ids.forEach((id) => { void refreshOne(id); }); }, PROMPT_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processingIds, refreshOne]);

  // 失败任务一键重试（智令偶发空返回等瞬时故障，重试通常可恢复）
  const [retryingPromptId, setRetryPromptId] = useState<string | null>(null);
  const handlePromptRetry = async (t: WechatDlPromptTask) => {
    setRetryPromptId(t.id);
    try {
      const nt = await wechatDlApi.retryReversePrompt(t.id);
      message.success('已用原参数重新提交');
      setTasks((prev) => [nt, ...prev]);
      setDetail(nt);
      void refreshOne(nt.id);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '重试失败');
    } finally {
      setRetryPromptId(null);
    }
  };

  // 外部入口（下载任务行「反推提示词」）预填链接
  useEffect(() => {
    if (presetUrl) form.setFieldsValue({ source_url: presetUrl });
  }, [presetUrl, form]);

  const handleSubmit = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const t = await wechatDlApi.submitReversePrompt({
        source_url: values.source_url.trim(),
        max_duration: values.max_duration,
      });
      setTasks((prev) => [t, ...prev]);
      setDetail(t);
      if (t.status === 'failed') {
        message.error(`反推任务创建失败：${t.error || '未知原因'}`);
      } else {
        message.success('已提交反推任务，正在生成提示词…');
      }
      form.resetFields();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  // 本地视频上传 → 反推（doc/125 签名直传 → doc/120）；beforeUpload 返回 false 走自定义上传
  const handleUpload = async (file: File): Promise<boolean> => {
    const localErr = validatePromptUploadFile(file);
    if (localErr) {
      message.error(localErr);
      return false;
    }
    const values = form.getFieldsValue();
    setUploading(true);
    setUploadPercent(0);
    setUploadName(file.name);
    try {
      const t = await wechatDlApi.uploadReversePrompt(
        { file, max_duration: values.max_duration },
        (percent) => setUploadPercent(percent),
      );
      setTasks((prev) => [t, ...prev.filter((p) => p.id !== t.id)]);
      setDetail(t);
      if (t.status === 'failed') {
        message.error(`上传后提交反推失败：${t.error || '未知原因'}`);
      } else {
        message.success('视频已上传，正在生成提示词…');
      }
    } catch (err: unknown) {
      const detailMsg = (err as { message?: string })?.message;
      message.error(detailMsg || '上传失败');
    } finally {
      setUploading(false);
      setUploadPercent(0);
      setUploadName(null);
    }
    // 返回 false：阻止 antd 自己发起上传（我们自己走 axios 以便拿进度与凭据）
    return false;
  };

  const handleCopy = async (text: string) => {
    const ok = await copyTextToClipboard(text);
    if (ok) message.success('提示词已复制到剪贴板');
    else message.warning('复制失败，请手动选中复制');
  };

  const columns = [
    {
      title: '来源', dataIndex: 'source_type', key: 'source_type', width: 190, ellipsis: true,
      render: (v: string | null, r: WechatDlPromptTask) => (
        v === 'upload' ? (
          <Tooltip title={r.file_name || ''}>
            <Tag color="blue" icon={<CloudUploadOutlined />} style={{ maxWidth: 170 }}>
              <span style={{ display: 'inline-block', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', verticalAlign: 'bottom' }}>
                {r.file_name || '本地视频'}
              </span>
            </Tag>
          </Tooltip>
        ) : (
          <Tag color="default" icon={<LinkOutlined />}>链接</Tag>
        )
      ),
    },
    {
      title: '视频地址', dataIndex: 'source_url', key: 'source_url', ellipsis: true,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string, r: WechatDlPromptTask) => {
        const meta = PROMPT_STATUS_META[v] || { color: 'default', label: v };
        return (
          <Tooltip title={r.status === 'failed' ? r.error || '' : ''}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '计时上限', dataIndex: 'max_duration', key: 'max_duration', width: 100,
      render: (v: number | null) => (
        <Text type="secondary" style={{ fontSize: 12 }}>{v ? `${v}s` : '-'}</Text>
      ),
    },
    {
      title: '结果预览', dataIndex: 'content', key: 'content', ellipsis: true,
      render: (v: string | null, r: WechatDlPromptTask) =>
        r.status === 'failed' ? (
          <Text type="danger" style={{ fontSize: 12 }}>{r.error || '生成失败'}</Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>{v ? v.slice(0, 60) : '生成中…'}</Text>
        ),
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (d: string) => formatDateTime(d),
    },
    {
      title: '操作', key: 'action', width: 220, fixed: 'right' as const,
      render: (_: unknown, r: WechatDlPromptTask) => (
        <Space size={4}>
          <Button
            size="small"
            type="link"
            icon={<FileTextOutlined />}
            onClick={() => { setDetail(r); void refreshOne(r.id); }}
          >
            查看
          </Button>
          {r.content && (
            <Button size="small" type="link" icon={<CopyOutlined />} onClick={() => handleCopy(r.content as string)}>
              复制
            </Button>
          )}
          {r.status === 'failed' && r.source_type !== 'upload' && (
            <Button
              size="small"
              type="link"
              danger
              icon={<RedoOutlined />}
              loading={retryingPromptId === r.id}
              onClick={() => void handlePromptRetry(r)}
              title="智令偶发空返回等瞬时故障，用原参数重新提交"
            >
              重试
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title="视频反推提示词（AI 提示词提取）"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        icon={<RobotOutlined />}
        message="粘贴任意视频链接或上传本地视频，自动反推生成结构化提示词"
        description="基于智令 doc/120《视频反推提示词（计时）》：支持 30+ 平台分享链接与视频直链，按计时上限计费（0.00054 元/秒，注册赠 30 次）。本地视频经 doc/125 签名直传智令临时桶后走同一反推链路（上传计费 0.001 元/次，文件 6 小时自动删除）。生成中约需数十秒，页面每 4s 自动刷新；完成后可一键复制 markdown 提示词。"
      />

      <Form form={form} layout="inline" style={{ marginBottom: 16, rowGap: 8 }}>
        <Form.Item
          name="source_url"
          label="视频链接"
          style={{ flex: 1, minWidth: 320, marginBottom: 8 }}
          rules={[{ required: true, message: '请输入视频链接' }]}
        >
          <Input placeholder="粘贴视频链接（视频号 / 抖音 / 快手 / 小红书等 30+ 平台，或视频直链）" />
        </Form.Item>
        <Form.Item name="max_duration" label="计时上限" style={{ marginBottom: 8 }}>
          <Select
            style={{ width: 130 }}
            placeholder="默认 600s"
            allowClear
            options={[
              { value: 60, label: '60 秒' },
              { value: 180, label: '180 秒' },
              { value: 300, label: '300 秒' },
              { value: 600, label: '600 秒（最大）' },
            ]}
          />
        </Form.Item>
        <Form.Item style={{ marginBottom: 8 }}>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={submitting} onClick={handleSubmit}>
            开始反推
          </Button>
        </Form.Item>
      </Form>

      {/* 本地视频上传（ISSUE #363）：没有可分享链接的视频，直接传文件反推 */}
      <div style={{ marginBottom: 16 }}>
        <Upload.Dragger
          accept={PROMPT_UPLOAD_ACCEPT}
          multiple={false}
          maxCount={1}
          showUploadList={false}
          disabled={uploading}
          beforeUpload={(file) => { void handleUpload(file as File); return false; }}
          style={{ background: '#fafafa' }}
        >
          <p style={{ margin: 0 }}>
            <InboxOutlined style={{ fontSize: 28, color: '#1677ff' }} />
          </p>
          <p style={{ margin: '6px 0 2px', fontSize: 13 }}>
            没有链接？点此或拖拽本地视频到这里上传后反推
          </p>
          <p style={{ margin: 0 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              支持 {PROMPT_UPLOAD_ACCEPT.replace(/\./g, '').replace(/,/g, ' / ')}，单个文件 ≤ {PROMPT_UPLOAD_MAX_MB}MB；
              文件仅中转至智令临时桶，6 小时后自动删除
            </Text>
          </p>
        </Upload.Dragger>
        {uploading && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              <CloudUploadOutlined /> 正在上传 {uploadName}…
            </Text>
            <Progress percent={uploadPercent} size="small" status="active" />
          </div>
        )}
      </div>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={tasks}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1000 }}
        locale={{ emptyText: '暂无反推任务，粘贴视频链接或上传本地视频开始生成' }}
      />

      <Modal
        open={!!detail}
        title="反推提示词结果"
        footer={null}
        onCancel={() => setDetail(null)}
        width={760}
        destroyOnClose
      >
        {detail && (
          <div>
            <p style={{ marginBottom: 8 }}>
              <Space size={6} wrap>
                {detail.source_type === 'upload' ? (
                  <Tag color="blue" icon={<CloudUploadOutlined />}>{detail.file_name || '本地视频'}</Tag>
                ) : (
                  <Tag color="default" icon={<LinkOutlined />}>链接</Tag>
                )}
                <Text type="secondary" style={{ fontSize: 12 }}>{detail.source_url || '-'}</Text>
              </Space>
            </p>
            <Space style={{ marginBottom: 12 }}>
              {(() => {
                const meta = PROMPT_STATUS_META[detail.status] || { color: 'default', label: detail.status };
                return <Tag color={meta.color}>{meta.label}</Tag>;
              })()}
              {detail.status === 'processing' && (
                <Text type="secondary" style={{ fontSize: 12 }}>生成中，页面每 4s 自动刷新…</Text>
              )}
              {detail.content && (
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => handleCopy(detail.content as string)}
                >
                  一键复制
                </Button>
              )}
            </Space>
            {detail.status === 'failed' && (
              <Alert type="error" showIcon message="生成失败" description={detail.error || '未知原因'} />
            )}
            {detail.content && (
              <pre
                style={{
                  maxHeight: 420, overflow: 'auto', background: '#fafafa',
                  border: '1px solid #f0f0f0', borderRadius: 8, padding: 12,
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 13,
                }}
              >
                {detail.content}
              </pre>
            )}
          </div>
        )}
      </Modal>
    </Card>
  );
};

// ========== 解析服务商 Tab（API 名称 / 官网 / 余量）==========
const ProvidersPanel: React.FC = () => {
  const [providers, setProviders] = useState<WechatDlProviderInfo[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    wechatDlApi.getProviders()
      .then((res) => setProviders(res.items || []))
      .catch(() => { message.error('获取解析服务信息失败'); setProviders([]); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const renderBalance = (p: WechatDlProviderInfo) => {
    if (p.balance != null) {
      return (
        <Space>
          <Tag color="green" style={{ fontSize: 13 }}>
            {p.balance.toLocaleString()} {p.balance_unit}
          </Tag>
          {p.balance_error && (
            <Tooltip title={p.balance_error}>
              <Text type="secondary" style={{ fontSize: 11 }}>查询有波动</Text>
            </Tooltip>
          )}
        </Space>
      );
    }
    if (p.balance_error) {
      return <Tag color="red" style={{ fontSize: 12 }}>余量查询失败：{p.balance_error}</Tag>;
    }
    if (p.rechargeable) {
      return <Text type="secondary" style={{ fontSize: 12 }}>未配置余量接口（未知）</Text>;
    }
    return <Text type="secondary" style={{ fontSize: 12 }}>免费 / 无需充值</Text>;
  };

  const columns = [
    {
      title: 'API 名称', dataIndex: 'display_name', key: 'display_name', width: 150,
      render: (_: unknown, r: WechatDlProviderInfo) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ fontSize: 13 }}>{r.display_name}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>channel: {r.channel}</Text>
        </Space>
      ),
    },
    {
      title: '充值 / 是否计费', dataIndex: 'rechargeable', key: 'rechargeable', width: 120,
      render: (v: boolean) =>
        v
          ? <Tag color="gold">需充值计费</Tag>
          : <Tag color="default">免费 / 官方链路</Tag>,
    },
    {
      title: '官网（充值入口）', dataIndex: 'home', key: 'home', width: 190,
      render: (v: string | null, r: WechatDlProviderInfo) =>
        v ? (
          <a href={v} target="_blank" rel="noreferrer">
            <GlobalOutlined /> {r.rechargeable ? '前往充值 / 开通' : '官方网站'}
          </a>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>-</Text>
        ),
    },
    {
      title: '接口文档', dataIndex: 'doc', key: 'doc', width: 140,
      render: (v: string | null) =>
        v ? (
          <a href={v} target="_blank" rel="noreferrer">
            <FileTextOutlined /> 查看文档
          </a>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>-</Text>
        ),
    },
    {
      title: '当前余量', dataIndex: 'balance', key: 'balance', width: 200,
      render: (_: unknown, r: WechatDlProviderInfo) => renderBalance(r),
    },
    {
      title: '说明', dataIndex: 'desc', key: 'desc', ellipsis: true,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
  ];

  return (
    <Card
      size="small"
      title="当前使用的解析 API 服务"
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        icon={<ApiOutlined />}
        message="资源下载通过下方解析服务获取真实视频播放地址（支持 30+ 平台）"
        description="标为「需充值计费」的服务为第三方 API，按次数计费，请在对应官网充值续费；「免费 / 官方链路」为微信/腾讯官方能力，无需充值。余量来自服务商接口，若未配置则显示未知。默认主力为智令 doc/107《视频去水印下载》，支持微信视频号、抖音、快手、小红书等 30+ 平台链接解析（约 0.01 元/次，注册赠 30 次）。"
      />
      <Table
        rowKey="channel"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={providers}
        pagination={false}
        locale={{ emptyText: '未配置解析服务（WECHAT_DL_PROVIDERS 为空）' }}
      />
      <div style={{ marginTop: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          <SafetyCertificateOutlined /> 提示：请妥善保管各服务的 Key/Token，勿泄露；余量为实时查询结果，仅供参考，以服务商后台为准。
        </Text>
      </div>
    </Card>
  );
};


// ========== 其他服务 Tab（文案提取 / AI消除 / 画质修复 / TTS / 音色训练）==========
// 后端：wechat_download/services_service.py + /api/wechat-dl/zhiling-services*
// 智令文档：doc/102 文案提取、doc/114 AI消除、doc/123 画质修复、doc/108 TTS、doc/128 音色训练

const ZS_STATUS_META: Record<string, { color: string; label: string }> = {
  processing: { color: 'processing', label: '处理中' },
  success: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

// 与后端 models.ZS_DIRECT_URL_TYPES 对齐
const ZS_DIRECT_URL_TYPES: string[] = ['ai_eraser', 'hd_restore'];

/** 结果预览：文案取正文，其余取结果地址 */
const zsPreview = (t: ZhilingServiceTask): string => {
  if (t.status === 'failed') return t.error || '处理失败';
  if (t.task_type === 'copy_extract') return t.result_text ? t.result_text.slice(0, 60) : '提取中…';
  if (t.task_type === 'voice_clone') return t.voice_model_id ? `modelId: ${t.voice_model_id}` : '训练中…';
  return t.result_url ? t.result_url : '处理中…';
};

const zsStatusTag = (t: ZhilingServiceTask) => {
  const meta = ZS_STATUS_META[t.status] || { color: 'default', label: t.status };
  return (
    <Tooltip title={t.status === 'failed' ? t.error || '' : ''}>
      <Tag color={meta.color}>{meta.label}</Tag>
    </Tooltip>
  );
};

/** 公共列表行为：拉取 / 4s 轮询 processing / 失败重试。各面板只负责表单与详情。 */
const useZhilingServiceList = (taskType: ZhilingServiceTaskType) => {
  const [tasks, setTasks] = useState<ZhilingServiceTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<ZhilingServiceTask | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    wechatDlApi.listZhilingServices({ limit: 50 })
      .then((res) => setTasks((res.items || []).filter((t) => t.task_type === taskType)))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [taskType]);

  useEffect(() => { load(); }, [load]);

  const refreshOne = useCallback(async (id: string) => {
    try {
      const t = await wechatDlApi.getZhilingService(id);
      setTasks((prev) => prev.map((p) => (p.id === t.id ? t : p)));
      setDetail((d) => (d && d.id === t.id ? t : d));
      return t;
    } catch {
      return null;
    }
  }, []);

  // processing 的任务每 4s 轮询一次自建接口（同时触发后端向上游查一次）
  const processingIds = tasks.filter((t) => t.status === 'processing').map((t) => t.id).join(',');
  useEffect(() => {
    if (!processingIds) return undefined;
    const ids = processingIds.split(',');
    const timer = setInterval(() => { ids.forEach((id) => { void refreshOne(id); }); }, PROMPT_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processingIds, refreshOne]);

  const retry = async (t: ZhilingServiceTask) => {
    setRetryingId(t.id);
    try {
      const nt = await wechatDlApi.retryZhilingService(t.id);
      message.success('已用原参数重新提交');
      setTasks((prev) => [nt, ...prev]);
      setDetail(nt);
      void refreshOne(nt.id);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '重试失败');
    } finally {
      setRetryingId(null);
    }
  };

  const prepend = useCallback((t: ZhilingServiceTask) => {
    setTasks((prev) => [t, ...prev.filter((p) => p.id !== t.id)]);
    setDetail(t);
  }, []);

  return { tasks, loading, detail, setDetail, refreshOne, retry, retryingId, prepend, load };
};

/** 明细 Modal 骨架：头部标签 + 状态 + 正文内容由各面板 provide。 */
const ZsDetailModal: React.FC<{
  detail: ZhilingServiceTask | null;
  onClose: () => void;
  onRetry: (t: ZhilingServiceTask) => void;
  retrying: boolean;
  title: string;
  children: (t: ZhilingServiceTask) => React.ReactNode;
}> = ({ detail, onClose, onRetry, retrying, title, children }) => (
  <Modal
    open={!!detail}
    title={title}
    footer={null}
    onCancel={onClose}
    width={760}
    destroyOnClose
  >
    {detail && (
      <div>
        <p style={{ marginBottom: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {detail.input_url || (detail.input_text ? `文本 ${detail.input_text.length} 字` : '-')}
          </Text>
        </p>
        <Space style={{ marginBottom: 12 }} wrap>
          {zsStatusTag(detail)}
          {detail.status === 'processing' && (
            <Text type="secondary" style={{ fontSize: 12 }}>处理中，页面每 4s 自动刷新…</Text>
          )}
          {detail.status === 'failed' && (
            <Button
              size="small"
              danger
              icon={<RedoOutlined />}
              loading={retrying}
              onClick={() => onRetry(detail)}
            >
              重试
            </Button>
          )}
        </Space>
        {detail.status === 'failed' && (
          <Alert type="error" showIcon message="处理失败" description={detail.error || '未知原因'} style={{ marginBottom: 12 }} />
        )}
        {children(detail)}
      </div>
    )}
  </Modal>
);

/** 公共操作列：查看 / 失败重试 */
const zsActions = (
  t: ZhilingServiceTask,
  ctx: { onView: (t: ZhilingServiceTask) => void; onRetry: (t: ZhilingServiceTask) => void; retryingId: string | null },
) => (
  <Space size={4}>
    <Button size="small" type="link" icon={<FileTextOutlined />} onClick={() => ctx.onView(t)}>
      查看
    </Button>
    {t.status === 'failed' && (
      <Button
        size="small"
        type="link"
        danger
        icon={<RedoOutlined />}
        loading={ctx.retryingId === t.id}
        onClick={() => ctx.onRetry(t)}
      >
        重试
      </Button>
    )}
  </Space>
);

const copyWithToast = async (text: string, okMsg: string) => {
  const ok = await copyTextToClipboard(text);
  if (ok) message.success(okMsg);
  else message.warning('复制失败，请手动选中复制');
};

/** 文案提取（doc/102，0.1 元/次） */
const CopyExtractPanel: React.FC<{ presetUrl?: string }> = ({ presetUrl }) => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const list = useZhilingServiceList('copy_extract');

  useEffect(() => {
    if (presetUrl) form.setFieldsValue({ source_url: presetUrl });
  }, [presetUrl, form]);

  const submit = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    try {
      const t = await wechatDlApi.submitZhilingService({
        task_type: 'copy_extract',
        source_url: v.source_url.trim(),
        options: { need_srt: v.need_srt !== false } as ZhilingServiceOptions,
      });
      list.prepend(t);
      if (t.status === 'failed') message.error(`提交失败：${t.error || '未知原因'}`);
      else message.success('已提交，正在提取文案…');
      form.resetFields(['source_url']);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: '来源', dataIndex: 'input_url', key: 'input_url', ellipsis: true,
      render: (v: string | null) => <Text style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (_: unknown, r: ZhilingServiceTask) => zsStatusTag(r) },
    {
      title: '结果预览', dataIndex: 'result_text', key: 'result_text', ellipsis: true,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Text type={r.status === 'failed' ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
          {zsPreview(r)}
        </Text>
      ),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作', key: 'action', width: 170, fixed: 'right' as const,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Space size={4}>
          {zsActions(r, { onView: (t) => { list.setDetail(t); void list.refreshOne(t.id); }, onRetry: (t) => void list.retry(t), retryingId: list.retryingId })}
          {r.result_text && (
            <Button size="small" type="link" icon={<CopyOutlined />} onClick={() => void copyWithToast(r.result_text as string, '文案已复制')}>
              复制
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title="文案提取（视频 → 文案 / 字幕）"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={list.load} loading={list.loading}>刷新</Button>}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        icon={<FileTextOutlined />}
        message="粘贴 30+ 平台视频链接，自动提取口播文案与 SRT 字幕（0.1 元/次）"
        description="基于智令 doc/102：支持微信视频号、抖音、快手、小红书等分享链接。勾选「同时生成 SRT」可一并产出字幕文件；处理中页面每 4s 自动刷新，完成后可一键复制文案或字幕。"
      />
      <Form form={form} layout="inline" style={{ marginBottom: 16, rowGap: 8 }}>
        <Form.Item
          name="source_url"
          label="视频链接"
          style={{ flex: 1, minWidth: 320, marginBottom: 8 }}
          rules={[{ required: true, message: '请输入视频链接' }]}
        >
          <Input placeholder="粘贴视频分享链接（视频号 / 抖音 / 快手 / 小红书等）" />
        </Form.Item>
        <Form.Item name="need_srt" label="同时生成 SRT" valuePropName="checked" initialValue style={{ marginBottom: 8 }}>
          <Switch size="small" />
        </Form.Item>
        <Form.Item style={{ marginBottom: 8 }}>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={submitting} onClick={submit}>
            提取文案
          </Button>
        </Form.Item>
      </Form>
      <Table
        rowKey="id" size="small" loading={list.loading} columns={columns}
        dataSource={list.tasks} pagination={{ pageSize: 10 }} scroll={{ x: 900 }}
        locale={{ emptyText: '暂无文案提取任务' }}
      />
      <ZsDetailModal
        detail={list.detail}
        onClose={() => list.setDetail(null)}
        onRetry={(t) => void list.retry(t)}
        retrying={list.retryingId === list.detail?.id}
        title="文案提取结果"
      >
        {(t) => (
          <div>
            <Space style={{ marginBottom: 12 }} wrap>
              {t.result_text && (
                <Button size="small" icon={<CopyOutlined />} onClick={() => void copyWithToast(t.result_text as string, '文案已复制')}>
                  复制文案
                </Button>
              )}
              {t.srt_text && (
                <Button size="small" icon={<CopyOutlined />} onClick={() => void copyWithToast(t.srt_text as string, 'SRT 字幕已复制')}>
                  复制 SRT
                </Button>
              )}
            </Space>
            <pre
              style={{
                maxHeight: 420, overflow: 'auto', background: '#fafafa',
                border: '1px solid #f0f0f0', borderRadius: 8, padding: 12,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 13,
              }}
            >
              {t.result_text || (t.status === 'processing' ? '提取中，请稍候…' : '暂无文案')}
            </pre>
          </div>
        )}
      </ZsDetailModal>
    </Card>
  );
};

/** AI消除（doc/114，0.005 元/秒）+ 画质修复（doc/123，0.3 元/分钟）：同一套 UI，只换文案。 */
const EraserPanel: React.FC<{
  taskType: 'ai_eraser' | 'hd_restore';
  presetUrl?: string;
}> = ({ taskType, presetUrl }) => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const list = useZhilingServiceList(taskType);
  const isHd = taskType === 'hd_restore';

  useEffect(() => {
    if (presetUrl) form.setFieldsValue({ source_url: presetUrl });
  }, [presetUrl, form]);

  const submit = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    try {
      const t = await wechatDlApi.submitZhilingService({
        task_type: taskType,
        source_url: v.source_url.trim(),
      });
      list.prepend(t);
      if (t.status === 'failed') message.error(`提交失败：${t.error || '未知原因'}`);
      else message.success(isHd ? '已提交画质修复…' : '已提交 AI 消除…');
      form.resetFields(['source_url']);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: '视频地址', dataIndex: 'input_url', key: 'input_url', ellipsis: true,
      render: (v: string | null, r: ZhilingServiceTask) => (
        <Tooltip title={r.params?.direct_url || v || ''}>
          <Text style={{ fontSize: 12 }}>{v || '-'}</Text>
        </Tooltip>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 160,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Space size={4}>
          {zsStatusTag(r)}
          {r.status === 'processing' && r.progress != null && (
            <Progress percent={Math.round((r.progress || 0) * 100)} size="small" style={{ width: 70 }} />
          )}
        </Space>
      ),
    },
    {
      title: '结果预览', dataIndex: 'result_url', key: 'result_url', ellipsis: true,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Text type={r.status === 'failed' ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>{zsPreview(r)}</Text>
      ),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作', key: 'action', width: 240, fixed: 'right' as const,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Space size={4}>
          {zsActions(r, { onView: (t) => { list.setDetail(t); void list.refreshOne(t.id); }, onRetry: (t) => void list.retry(t), retryingId: list.retryingId })}
          {r.result_url && (
            <>
              <Button
                size="small" type="link" icon={<CopyOutlined />}
                onClick={() => void copyWithToast(r.result_url as string, '结果地址已复制')}
              >
                复制
              </Button>
              <Button size="small" type="link" icon={<DownloadFileIcon />} href={r.result_url} target="_blank" rel="noreferrer">
                下载
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title={isHd ? '画质修复（视频高清化）' : 'AI 消除（去水印 / 去杂物）'}
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={list.load} loading={list.loading}>刷新</Button>}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        icon={isHd ? <PictureOutlined /> : <EraserIcon />}
        message={isHd ? '视频画质修复至高清（0.3 元/分钟）' : '框选区域去水印 / 去杂物（0.005 元/秒）'}
        description={
          isHd
            ? '基于智令 doc/123：接口只接受视频直链。若粘贴的是分享链接，系统会先走 doc/107 解析直链（额外 0.01 元/次）；解析失败会直接置为失败并给出原因。处理耗时较长，页面每 4s 自动刷新进度。'
            : '基于智令 doc/114：接口只接受视频直链。若粘贴的是分享链接，系统会先走 doc/107 解析直链（额外 0.01 元/次）；解析失败会直接置为失败并给出原因。处理耗时按视频时长计，页面每 4s 自动刷新进度。'
        }
      />
      <Form form={form} layout="inline" style={{ marginBottom: 16, rowGap: 8 }}>
        <Form.Item
          name="source_url"
          label="视频链接"
          style={{ flex: 1, minWidth: 320, marginBottom: 8 }}
          rules={[{ required: true, message: '请输入视频链接或直链' }]}
        >
          <Input placeholder="视频直链（.mp4/.mov…）或任意平台分享链接（会自动解析直链）" />
        </Form.Item>
        <Form.Item style={{ marginBottom: 8 }}>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={submitting} onClick={submit}>
            {isHd ? '开始修复' : '开始消除'}
          </Button>
        </Form.Item>
      </Form>
      <Table
        rowKey="id" size="small" loading={list.loading} columns={columns}
        dataSource={list.tasks} pagination={{ pageSize: 10 }} scroll={{ x: 960 }}
        locale={{ emptyText: isHd ? '暂无画质修复任务' : '暂无 AI 消除任务' }}
      />
      <ZsDetailModal
        detail={list.detail}
        onClose={() => list.setDetail(null)}
        onRetry={(t) => void list.retry(t)}
        retrying={list.retryingId === list.detail?.id}
        title={isHd ? '画质修复结果' : 'AI 消除结果'}
      >
        {(t) => (
          <div>
            {t.status === 'processing' && (
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  处理进度 {Math.round((t.progress || 0) * 100)}%
                </Text>
                <Progress percent={Math.round((t.progress || 0) * 100)} size="small" status="active" />
              </div>
            )}
            {t.result_url ? (
              <>
                <video controls src={t.result_url} style={{ width: '100%', maxHeight: 420, background: '#000', borderRadius: 8 }} />
                <Space style={{ marginTop: 12 }}>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => void copyWithToast(t.result_url as string, '结果地址已复制')}>
                    复制地址
                  </Button>
                  <Button size="small" type="primary" icon={<DownloadFileIcon />} href={t.result_url} target="_blank" rel="noreferrer">
                    下载视频
                  </Button>
                </Space>
              </>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t.status === 'processing' ? '处理中，完成后可在此预览与下载…' : '暂无结果'}
              </Text>
            )}
          </div>
        )}
      </ZsDetailModal>
    </Card>
  );
};

/** 文字转语音（doc/108，1 元/万字） */
const TTS_BUILTIN_VOICES = [
  { value: '306', label: '306 晓妍 - 自然流畅' },
  { value: '307', label: '307 晓辰 - 知性女声' },
  { value: '309', label: '309 晓颜 - 青年女声' },
  { value: '464', label: '464 解说小美' },
];
const TTS_MAX_TEXT = 5000;

const TtsPanel: React.FC = () => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const list = useZhilingServiceList('tts');
  const voiceType = (Form.useWatch('voice_type', form) as string) || 'builtin';
  const textValue = (Form.useWatch('text', form) as string) || '';

  const submit = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    try {
      const t = await wechatDlApi.submitZhilingService({
        task_type: 'tts',
        text: v.text,
        options: {
          voice_type: v.voice_type || 'builtin',
          voice_id: v.voice_id,
          model_id: v.model_id,
          format: v.format || 'mp3',
        } as ZhilingServiceOptions,
      });
      list.prepend(t);
      if (t.status === 'failed') message.error(`提交失败：${t.error || '未知原因'}`);
      else message.success('已提交合成任务，处理中…');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: '文本', dataIndex: 'input_text', key: 'input_text', ellipsis: true,
      render: (v: string | null) => <Text style={{ fontSize: 12 }}>{v ? v.slice(0, 40) : '-'}</Text>,
    },
    {
      title: '音色', key: 'voice', width: 130,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Text style={{ fontSize: 12 }}>
          {r.params?.voice_type === 'cloned' ? `自定义 ${r.params?.model_id || ''}` : `内置 ${r.params?.voice_id || ''}`}
        </Text>
      ),
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (_: unknown, r: ZhilingServiceTask) => zsStatusTag(r) },
    {
      title: '格式', key: 'format', width: 70,
      render: (_: unknown, r: ZhilingServiceTask) => <Text style={{ fontSize: 12 }}>{r.params?.format || 'mp3'}</Text>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作', key: 'action', width: 240, fixed: 'right' as const,
      render: (_: unknown, r: ZhilingServiceTask) => (
        <Space size={4}>
          {zsActions(r, { onView: (t) => { list.setDetail(t); void list.refreshOne(t.id); }, onRetry: (t) => void list.retry(t), retryingId: list.retryingId })}
          {r.result_url && (
            <Button size="small" type="link" icon={<DownloadFileIcon />} href={r.result_url} target="_blank" rel="noreferrer">
              下载
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title="文字转语音（TTS）"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={list.load} loading={list.loading}>刷新</Button>}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        icon={<SoundOutlined />}
        message="输入文本 → 合成语音（1 元/万字，音频 24 小时有效）"
        description="基于智令 doc/108：单次文本 ≤5000 字。内置音色可直接选；自定义音色需先在「音色训练」训练出 modelId 后粘贴使用。合成完成后请及时下载，音频链接仅 24 小时有效。"
      />
      <Form form={form} layout="vertical" initialValues={{ voice_type: 'builtin', format: 'mp3', voice_id: '306' }} style={{ marginBottom: 16 }}>
        <Form.Item
          name="text"
          label={`合成文本（${textValue.length}/${TTS_MAX_TEXT}）`}
          rules={[
            { required: true, message: '请输入要合成的文本' },
            { max: TTS_MAX_TEXT, message: `单次上限 ${TTS_MAX_TEXT} 字` },
          ]}
        >
          <TextArea rows={4} placeholder="粘贴或输入要合成的文本，单次最多 5000 字" showCount maxLength={TTS_MAX_TEXT} />
        </Form.Item>
        <Space wrap style={{ marginBottom: 8 }}>
          <Form.Item name="voice_type" label="音色类型" style={{ marginBottom: 8 }}>
            <Segmented
              options={[
                { label: '内置音色', value: 'builtin' },
                { label: '自定义音色', value: 'cloned' },
              ]}
            />
          </Form.Item>
          {voiceType === 'builtin' ? (
            <Form.Item
              name="voice_id"
              label="内置音色"
              style={{ minWidth: 260, marginBottom: 8 }}
              rules={[{ required: true, message: '请选择内置音色' }]}
              extra={<Text type="secondary" style={{ fontSize: 11 }}>可搜索或直接输入音色 id（完整列表见智令音色文档）</Text>}
            >
              <Select
                showSearch
                options={TTS_BUILTIN_VOICES}
                placeholder="搜索或输入音色 id"
                // 允许自定义输入：官方音色列表远多于预置的 4 个
                mode={undefined}
                filterOption={(input, option) => String(option?.label || '').includes(input) || String(option?.value || '').includes(input)}
                onSearch={(v) => { if (v) form.setFieldsValue({ voice_id: v }); }}
              />
            </Form.Item>
          ) : (
            <Form.Item
              name="model_id"
              label="自定义 modelId"
              style={{ minWidth: 260, marginBottom: 8 }}
              rules={[{ required: true, message: '请填写音色训练得到的 modelId' }]}
              extra={<Text type="secondary" style={{ fontSize: 11 }}>到「音色训练」面板训练后复制 modelId 粘贴到这里</Text>}
            >
              <Input placeholder="音色训练产出的 modelId" />
            </Form.Item>
          )}
          <Form.Item name="format" label="音频格式" style={{ marginBottom: 8 }}>
            <Select
              style={{ width: 110 }}
              options={[
                { value: 'mp3', label: 'mp3' },
                { value: 'wav', label: 'wav' },
                { value: 'pcm', label: 'pcm' },
              ]}
            />
          </Form.Item>
          <Form.Item label=" " style={{ marginBottom: 8 }}>
            <Button type="primary" icon={<AudioOutlined />} loading={submitting} onClick={submit}>
              合成语音
            </Button>
          </Form.Item>
        </Space>
      </Form>
      <Table
        rowKey="id" size="small" loading={list.loading} columns={columns}
        dataSource={list.tasks} pagination={{ pageSize: 10 }} scroll={{ x: 900 }}
        locale={{ emptyText: '暂无语音合成任务' }}
      />
      <ZsDetailModal
        detail={list.detail}
        onClose={() => list.setDetail(null)}
        onRetry={(t) => void list.retry(t)}
        retrying={list.retryingId === list.detail?.id}
        title="语音合成结果"
      >
        {(t) => (
          <div>
            {t.result_url ? (
              <div style={{ marginBottom: 12 }}>
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`⚠️ 音频 ${24} 小时有效，请及时下载`}
                  description="智令侧音频产物 24 小时后失效，需要长期保存请立即下载到本地。"
                />
                <audio controls src={t.result_url} style={{ width: '100%' }} />
                <Space style={{ marginTop: 12 }}>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => void copyWithToast(t.result_url as string, '音频地址已复制')}>
                    复制地址
                  </Button>
                  <Button size="small" type="primary" icon={<DownloadFileIcon />} href={t.result_url} target="_blank" rel="noreferrer">
                    下载音频
                  </Button>
                </Space>
              </div>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t.status === 'processing' ? '合成中，完成后可在此试听与下载…' : '暂无音频'}
              </Text>
            )}
          </div>
        )}
      </ZsDetailModal>
    </Card>
  );
};

/** 音色训练（doc/128，1 元/次，同步返回） */
const VoiceClonePanel: React.FC = () => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const list = useZhilingServiceList('voice_clone');

  const submit = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    try {
      const t = await wechatDlApi.submitZhilingService({
        task_type: 'voice_clone',
        source_url: v.audio_url.trim(),
        options: {
          model_name: v.model_name.trim(),
          description: v.description?.trim() || undefined,
        } as ZhilingServiceOptions,
      });
      list.prepend(t);
      if (t.status === 'failed') message.error(`训练失败：${t.error || '未知原因'}`);
      else message.success('音色训练完成，可复制 modelId 到「文字转语音」使用');
      form.resetFields();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: '模型名称', key: 'model_name', width: 180, ellipsis: true,
      render: (_: unknown, r: ZhilingServiceTask) => <Text style={{ fontSize: 12 }}>{r.params?.model_name || '-'}</Text>,
    },
    {
      title: '音频 URL', dataIndex: 'input_url', key: 'input_url', ellipsis: true,
      render: (v: string | null) => <Text style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (_: unknown, r: ZhilingServiceTask) => zsStatusTag(r) },
    {
      title: 'modelId', dataIndex: 'voice_model_id', key: 'voice_model_id', width: 200,
      render: (v: string | null, r: ZhilingServiceTask) => (v ? (
        <Space size={4}>
          <Text code style={{ fontSize: 12 }}>{v}</Text>
          <Button size="small" type="link" icon={<CopyOutlined />} onClick={() => void copyWithToast(v, 'modelId 已复制，到「文字转语音」选自定义音色粘贴使用')}>
            复制
          </Button>
        </Space>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>{r.status === 'failed' ? '失败' : '-'}</Text>
      )),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作', key: 'action', width: 120, fixed: 'right' as const,
      render: (_: unknown, r: ZhilingServiceTask) => zsActions(r, {
        onView: (t) => { list.setDetail(t); void list.refreshOne(t.id); },
        onRetry: (t) => void list.retry(t),
        retryingId: list.retryingId,
      }),
    },
  ];

  return (
    <Card
      size="small"
      title="音色训练（克隆音色）"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={list.load} loading={list.loading}>刷新</Button>}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        icon={<ExperimentOutlined />}
        message="上传一段干净人声（mp3/wav），训练专属音色（1 元/次）"
        description="基于智令 doc/128：音频 ≤5 分钟，30 秒左右效果最佳；训练为同步接口，提交后立即返回 modelId。拿到 modelId 后到「文字转语音」选『自定义音色』粘贴即可使用。"
      />
      <Form form={form} layout="inline" style={{ marginBottom: 16, rowGap: 8 }}>
        <Form.Item
          name="model_name"
          label="模型名称"
          style={{ minWidth: 200, marginBottom: 8 }}
          rules={[{ required: true, message: '请填写音色模型名称' }]}
        >
          <Input placeholder="如：解说小哥" />
        </Form.Item>
        <Form.Item
          name="audio_url"
          label="音频 URL"
          style={{ flex: 1, minWidth: 300, marginBottom: 8 }}
          rules={[{ required: true, message: '请填写音频 URL（mp3/wav）' }]}
        >
          <Input placeholder="https://…/voice.mp3（mp3/wav，≤5 分钟）" />
        </Form.Item>
        <Form.Item name="description" label="参考文本" style={{ minWidth: 200, marginBottom: 8 }}>
          <Input placeholder="选填，音频对应的文本" />
        </Form.Item>
        <Form.Item style={{ marginBottom: 8 }}>
          <Button type="primary" icon={<ExperimentOutlined />} loading={submitting} onClick={submit}>
            训练音色（1 元/次）
          </Button>
        </Form.Item>
      </Form>
      <Table
        rowKey="id" size="small" loading={list.loading} columns={columns}
        dataSource={list.tasks} pagination={{ pageSize: 10 }} scroll={{ x: 980 }}
        locale={{ emptyText: '暂无音色模型' }}
      />
      <div style={{ marginTop: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          提示：modelId 是「文字转语音」选『自定义音色』时的必填项；同一音色可反复用于不同文本合成。
        </Text>
      </div>
      <ZsDetailModal
        detail={list.detail}
        onClose={() => list.setDetail(null)}
        onRetry={(t) => void list.retry(t)}
        retrying={list.retryingId === list.detail?.id}
        title="音色训练详情"
      >
        {(t) => (
          <div>
            <p style={{ fontSize: 13 }}>
              <Text strong>模型名称：</Text>{t.params?.model_name || '-'}
            </p>
            {t.voice_model_id ? (
              <Space style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>modelId：</Text>
                <Text code>{t.voice_model_id}</Text>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => void copyWithToast(t.voice_model_id as string, 'modelId 已复制')}
                >
                  复制 modelId
                </Button>
              </Space>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>暂无 modelId</Text>
            )}
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message="到「文字转语音」面板选『自定义音色』，粘贴此 modelId 即可使用"
            />
          </div>
        )}
      </ZsDetailModal>
    </Card>
  );
};

/** 其他服务容器：Segmented 切换 5 个面板，共用外部预填链接 */
const OTHER_SERVICES = [
  { key: 'copy_extract', label: '文案提取' },
  { key: 'ai_eraser', label: 'AI 消除' },
  { key: 'hd_restore', label: '画质修复' },
  { key: 'tts', label: '文字转语音' },
  { key: 'voice_clone', label: '音色训练' },
] as const;

type OtherServiceKey = (typeof OTHER_SERVICES)[number]['key'];

const ZhilingServicesPanel: React.FC<{ presetUrl?: string }> = ({ presetUrl }) => {
  const [sub, setSub] = useState<OtherServiceKey>('copy_extract');
  return (
    <div>
      <Segmented
        value={sub}
        onChange={(v) => setSub(v as OtherServiceKey)}
        options={OTHER_SERVICES.map((s) => ({ label: s.label, value: s.key }))}
        style={{ marginBottom: 16 }}
      />
      {sub === 'copy_extract' && <CopyExtractPanel presetUrl={presetUrl} />}
      {sub === 'ai_eraser' && <EraserPanel taskType="ai_eraser" presetUrl={presetUrl} />}
      {sub === 'hd_restore' && <EraserPanel taskType="hd_restore" presetUrl={presetUrl} />}
      {sub === 'tts' && <TtsPanel />}
      {sub === 'voice_clone' && <VoiceClonePanel />}
    </div>
  );
};

// ========== 主页面 ==========
const ResourceDownload: React.FC = () => {
  const [activeTab, setActiveTab] = useState('import');
  // 下载任务行「反推提示词」→ 带链接跳到反推页签
  const [presetUrl, setPresetUrl] = useState<string | undefined>();

  const gotoReversePrompt = (url: string) => {
    setPresetUrl(url);
    setActiveTab('reverse-prompt');
  };

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>资源下载</Title>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'import',
            label: <span><ImportOutlined /> 链接导入</span>,
            children: <ImportPanel />,
          },
          {
            key: 'providers',
            label: <span><ApiOutlined /> 解析服务</span>,
            children: <ProvidersPanel />,
          },
          {
            key: 'reverse-prompt',
            label: <span><RobotOutlined /> 反推提示词</span>,
            children: <ReversePromptPanel presetUrl={presetUrl} />,
          },
          {
            key: 'services',
            label: <span><ThunderboltOutlined /> 其他服务</span>,
            children: <ZhilingServicesPanel presetUrl={presetUrl} />,
          },
          {
            key: 'tasks',
            label: <span><DownloadOutlined /> 下载任务</span>,
            children: <TaskListPanel onReversePrompt={gotoReversePrompt} />,
          },
        ]}
      />
    </div>
  );
};

export default ResourceDownload;
