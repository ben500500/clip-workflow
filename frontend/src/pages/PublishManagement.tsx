import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Form, Input, Select, InputNumber, Alert, Tabs, Tooltip, Switch,
} from 'antd';
import { ReloadOutlined, PlusOutlined, CheckCircleOutlined, DeleteOutlined, EyeOutlined, EditOutlined, QrcodeOutlined, HeartOutlined } from '@ant-design/icons';
import { publishApi, type VideoAccountInput, type MiniProgramInput } from '../api/publish';
import type { PublishProfile, PublishTask, VideoAccount, MiniProgram, OperatorRouteRow, OperatorStat, PublishAuditItem, LoginAuditItem, RiskEventItem, AuditResult } from '../types';
import { formatDateTime, getStatusColor, getStatusLabel } from '../utils/format';

const { Title } = Typography;

const PLATFORM_LABELS: Record<string, string> = {
  wechat_channel: '视频号',
  douyin: '抖音',
  kuaishou: '快手',
};

const PublishManagement: React.FC = () => {
  const [tasks, setTasks] = useState<PublishTask[]>([]);
  const [profiles, setProfiles] = useState<PublishProfile[]>([]);
  const [accounts, setAccounts] = useState<VideoAccount[]>([]);
  const [miniPrograms, setMiniPrograms] = useState<MiniProgram[]>([]);
  const [taskModal, setTaskModal] = useState(false);
  const [profileModal, setProfileModal] = useState(false);
  const [accountModal, setAccountModal] = useState(false);
  const [miniProgramModal, setMiniProgramModal] = useState(false);
  const [editingProfile, setEditingProfile] = useState<PublishProfile | null>(null);
  const [editingAccount, setEditingAccount] = useState<VideoAccount | null>(null);
  const [editingMiniProgram, setEditingMiniProgram] = useState<MiniProgram | null>(null);
  const [taskLoading, setTaskLoading] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [miniProgramLoading, setMiniProgramLoading] = useState(false);
  const [taskForm] = Form.useForm();
  const [profileForm] = Form.useForm();
  const [accountForm] = Form.useForm();
  const [miniProgramForm] = Form.useForm();
  const [screenshotModal, setScreenshotModal] = useState(false);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);
  const [screenshotLoading, setScreenshotLoading] = useState(false);
  // ── 多运营者：端口矩阵 + 审计（P1 问题10） ──
  const [operatorMatrix, setOperatorMatrix] = useState<OperatorRouteRow[]>([]);
  const [operatorStats, setOperatorStats] = useState<OperatorStat[]>([]);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [auditKind, setAuditKind] = useState('publish');
  const [auditLogs, setAuditLogs] = useState<AuditResult>({ kind: 'publish', items: [] });
  const [auditLoading, setAuditLoading] = useState(false);
  const [traceModalOpen, setTraceModalOpen] = useState(false);
  const [traceData, setTraceData] = useState<{
    request_id: string;
    publish: PublishAuditItem[];
    login: LoginAuditItem[];
    cookie: Array<{ id: string; profile_id: string | null; account_id: string | null; actor_id: string | null; operator_id: string | null; purpose: string | null; ip_address: string | null; request_id: string | null; created_at: string | null }>;
    risk: RiskEventItem[];
  } | null>(null);

  // ── 登录态自服务扫码（P0 主题1 / 4.1） ──
  const [qrAccountId, setQrAccountId] = useState('');
  const [qrClaiming, setQrClaiming] = useState(false);
  const [qrClaimToken, setQrClaimToken] = useState('');
  const [qrModalOpen, setQrModalOpen] = useState(false);
  const [qrUrl, setQrUrl] = useState('');
  const [qrHeartbeatStatus, setQrHeartbeatStatus] = useState<string | null>(null);
  const [qrHeartbeating, setQrHeartbeating] = useState(false);

  const fetchTasks = () => {
    setTaskLoading(true);
    publishApi.getTasks().then(setTasks).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败')).finally(() => setTaskLoading(false));
  };

  const fetchProfiles = () => {
    setProfileLoading(true);
    publishApi.getProfiles().then(setProfiles).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败')).finally(() => setProfileLoading(false));
  };

  const fetchAccounts = () => {
    setAccountLoading(true);
    publishApi.getVideoAccounts().then(setAccounts).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败')).finally(() => setAccountLoading(false));
  };

  const fetchMiniPrograms = () => {
    setMiniProgramLoading(true);
    publishApi.getMiniPrograms({ enabled_only: false }).then(setMiniPrograms).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败')).finally(() => setMiniProgramLoading(false));
  };

  const fetchMatrix = () => {
    setMatrixLoading(true);
    publishApi.getOperatorMatrix()
      .then((rows) => { setOperatorMatrix(rows); return publishApi.getOperatorStats(); })
      .then(setOperatorStats)
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setMatrixLoading(false));
  };

  // 登录态自服务扫码：申请 → 领取二维码 → 展示扫码
  const applyQr = () => {
    if (!qrAccountId) { message.warning('请先选择账号'); return; }
    setQrClaiming(true);
    publishApi.applyLoginQr(qrAccountId)
      .then(async (res) => {
        setQrClaimToken(res.claim_token);
        // 领取二维码链接
        const claim = await publishApi.claimLoginQr(res.claim_token);
        setQrUrl(claim.qr_url);
        setQrModalOpen(true);
        message.success('已生成登录二维码，请在 90s 内微信扫码');
      })
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '申请扫码失败'))
      .finally(() => setQrClaiming(false));
  };

  const runHeartbeat = () => {
    if (!qrAccountId) { message.warning('请先选择账号'); return; }
    setQrHeartbeating(true);
    publishApi.loginHeartbeat(qrAccountId)
      .then((res) => { setQrHeartbeatStatus(res.status); message.info(`登录态心跳: ${res.status}`); })
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '心跳检查失败'))
      .finally(() => setQrHeartbeating(false));
  };

  const fetchAudit = () => {
    setAuditLoading(true);
    publishApi.getAuditLogs({ kind: auditKind, limit: 100 })
      .then((res) => { setAuditLogs({ kind: res.kind, items: res.items }); })
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setAuditLoading(false));
  };

  const fetchAll = () => {
    fetchTasks();
    fetchProfiles();
    fetchAccounts();
    fetchMiniPrograms();
    fetchMatrix();
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const confirmTask = async (id: string) => {
    try {
      await publishApi.confirmTask(id);
      message.success('已确认，正在发布');
      setTimeout(fetchTasks, 3000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '确认失败');
    }
  };

  const viewScreenshot = async (id: string) => {
    setScreenshotModal(true);
    setScreenshotLoading(true);
    setScreenshotUrl(null);
    try {
      const res = await publishApi.getTaskScreenshot(id);
      setScreenshotUrl(res.screenshot_url);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载截图失败');
      setScreenshotModal(false);
    } finally {
      setScreenshotLoading(false);
    }
  };

  const createTask = async () => {
    try {
      const values = await taskForm.validateFields();
      // 账号库/小程序库选择后自动代入名称与链接
      const selectedAccount = accounts.find((a) => a.id === values.video_account_id);
      const selectedMiniProgram = miniPrograms.find((m) => m.id === values.mini_program_id);
      const payload = {
        output_id: values.output_id,
        platform: values.platform,
        account_name: selectedAccount ? selectedAccount.account_name : (values.account_name || undefined),
        video_account_id: values.video_account_id || undefined,
        mini_program_id: selectedMiniProgram ? selectedMiniProgram.id : undefined,
        title: values.title,
        description: values.description,
        tags: values.tags,
        mini_program_link: selectedMiniProgram ? selectedMiniProgram.full_link : (values.mini_program_link || undefined),
        require_manual_confirm: true,
      };
      await publishApi.createTask(payload);
      message.success('发布任务已创建');
      setTaskModal(false);
      fetchTasks();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '创建失败');
    }
  };

  const saveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      if (editingProfile) {
        await publishApi.updateProfile(editingProfile.id, values);
        message.success('配置已更新');
      } else {
        await publishApi.createProfile(values);
        message.success('配置已创建');
      }
      setProfileModal(false);
      fetchProfiles();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const saveAccount = async () => {
    try {
      const values = await accountForm.validateFields();
      const payload: VideoAccountInput = {
        account_name: values.account_name,
        platform: values.platform,
        group_name: values.group_name,
        wxid: values.wxid,
        account_uid: values.account_uid,
        profile_id: values.profile_id || undefined,
        mini_program_enabled: values.mini_program_enabled || false,
        remark: values.remark,
        enabled: values.enabled !== false,
      };
      if (editingAccount) {
        await publishApi.updateVideoAccount(editingAccount.id, payload);
        message.success('账号已更新');
      } else {
        await publishApi.createVideoAccount(payload);
        message.success('账号已创建');
      }
      setAccountModal(false);
      fetchAccounts();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const saveMiniProgram = async () => {
    try {
      const values = await miniProgramForm.validateFields();
      const payload: MiniProgramInput = {
        name: values.name,
        appid: values.appid,
        path: values.path,
        full_link: values.full_link,
        remark: values.remark,
        enabled: values.enabled !== false,
      };
      if (editingMiniProgram) {
        await publishApi.updateMiniProgram(editingMiniProgram.id, payload);
        message.success('小程序链接已更新');
      } else {
        await publishApi.createMiniProgram(payload);
        message.success('小程序链接已创建');
      }
      setMiniProgramModal(false);
      fetchMiniPrograms();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const taskColumns = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => t || '-' },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 100, render: (p: string) => p ? <Tag color={p === 'wechat_channel' ? 'green' : p === 'douyin' ? 'geekblue' : 'purple'}>{PLATFORM_LABELS[p] || p}</Tag> : '-' },
    { title: '账号', dataIndex: 'account_name', key: 'account_name', width: 120, ellipsis: true, render: (a: string) => a || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
    },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true, render: (e: string) => e || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作',
      key: 'action',
      width: 210,
      render: (_: unknown, t: PublishTask) =>
        t.status === 'pending_confirm' ? (
          <Space size="small" wrap>
            <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => confirmTask(t.id)}>确认发布</Button>
            {t.screenshot_key && (
              <Button size="small" icon={<EyeOutlined />} onClick={() => viewScreenshot(t.id)}>查看截图</Button>
            )}
          </Space>
        ) : (
          <span>{t.published_url ? <a href={t.published_url} target="_blank" rel="noreferrer">已发布</a> : '-'}</span>
        ),
    },
  ];

  const profileColumns = [
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 100, render: (p: string) => <Tag>{PLATFORM_LABELS[p] || p}</Tag> },
    { title: '账号', dataIndex: 'account_name', key: 'account_name', ellipsis: true },
    { title: 'Chrome 端口', dataIndex: 'chrome_debug_port', key: 'chrome_debug_port', width: 110 },
    { title: '每日上限', dataIndex: 'max_daily_publish', key: 'max_daily_publish', width: 100 },
    { title: '发布间隔(秒)', dataIndex: 'min_interval_seconds', key: 'min_interval_seconds', width: 120 },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, p: PublishProfile) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditingProfile(p);
            profileForm.setFieldsValue({
              platform: p.platform,
              account_name: p.account_name,
              chrome_debug_port: p.chrome_debug_port,
              max_daily_publish: p.max_daily_publish,
              min_interval_seconds: p.min_interval_seconds,
              require_manual_confirm: p.require_manual_confirm,
            });
            setProfileModal(true);
          }}>编辑</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={async () => {
            try {
              await publishApi.deleteProfile(p.id);
              message.success('已删除');
              fetchProfiles();
            } catch (err: unknown) {
              message.error(err instanceof Error ? err.message : '删除失败');
            }
          }}>删除</Button>
        </Space>
      ),
    },
  ];

  const accountColumns = [
    { title: '账号名称', dataIndex: 'account_name', key: 'account_name', width: 150, ellipsis: true },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 90, render: (p: string) => <Tag color={p === 'wechat_channel' ? 'green' : p === 'douyin' ? 'geekblue' : 'purple'}>{PLATFORM_LABELS[p] || p}</Tag> },
    { title: '分组', dataIndex: 'group_name', key: 'group_name', width: 110, ellipsis: true, render: (g: string) => g ? <Tag>{g}</Tag> : '-' },
    { title: '视频号ID', dataIndex: 'wxid', key: 'wxid', width: 130, ellipsis: true, render: (w: string) => w || '-' },
    { title: '小程序挂载', dataIndex: 'mini_program_enabled', key: 'mini_program_enabled', width: 110, render: (v: boolean) => v ? <Tag color="green">支持</Tag> : <Tag>不支持</Tag> },
    { title: '备注', dataIndex: 'remark', key: 'remark', width: 160, ellipsis: true, render: (r: string) => r || '-' },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (v: boolean, a: VideoAccount) => (
        <Switch
          size="small"
          checked={v !== false}
          onChange={async (checked) => {
            try {
              await publishApi.updateVideoAccount(a.id, { enabled: checked });
              message.success(checked ? '已启用' : '已停用');
              fetchAccounts();
            } catch (err: unknown) {
              message.error(err instanceof Error ? err.message : '操作失败');
            }
          }}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, a: VideoAccount) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditingAccount(a);
            accountForm.setFieldsValue({
              account_name: a.account_name,
              platform: a.platform,
              group_name: a.group_name,
              wxid: a.wxid,
              account_uid: a.account_uid,
              profile_id: a.profile_id || undefined,
              mini_program_enabled: a.mini_program_enabled,
              remark: a.remark,
              enabled: a.enabled,
            });
            setAccountModal(true);
          }}>编辑</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={async () => {
            try {
              await publishApi.deleteVideoAccount(a.id);
              message.success('已删除');
              fetchAccounts();
            } catch (err: unknown) {
              message.error(err instanceof Error ? err.message : '删除失败');
            }
          }}>删除</Button>
        </Space>
      ),
    },
  ];

  const miniProgramColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
    { title: 'AppID', dataIndex: 'appid', key: 'appid', width: 150, ellipsis: true, render: (v: string) => v || '-' },
    { title: 'Path', dataIndex: 'path', key: 'path', width: 140, ellipsis: true, render: (v: string) => v || '-' },
    { title: '完整链接', dataIndex: 'full_link', key: 'full_link', ellipsis: true, render: (v: string) => v ? <Tooltip title={v}><a href={v} target="_blank" rel="noreferrer">{v}</a></Tooltip> : '-' },
    { title: '备注', dataIndex: 'remark', key: 'remark', width: 140, ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, m: MiniProgram) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditingMiniProgram(m);
            miniProgramForm.setFieldsValue({
              name: m.name,
              appid: m.appid,
              path: m.path,
              full_link: m.full_link,
              remark: m.remark,
              enabled: m.enabled,
            });
            setMiniProgramModal(true);
          }}>编辑</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={async () => {
            try {
              await publishApi.deleteMiniProgram(m.id);
              message.success('已删除');
              fetchMiniPrograms();
            } catch (err: unknown) {
              message.error(err instanceof Error ? err.message : '删除失败');
            }
          }}>删除</Button>
        </Space>
      ),
    },
  ];

  // ── 多运营者：运营者端口矩阵 + 审计 列定义 ──
  const matrixColumns = [
    { title: '端口', dataIndex: 'port', key: 'port', width: 80, render: (p: number) => p ? `:${p}` : '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (s: string) => {
        const map: Record<string, { c: string; l: string }> = {
          ready: { c: 'green', l: '就绪' },
          logging: { c: 'orange', l: '登录中' },
          expired: { c: 'red', l: '失效' },
          disabled: { c: 'default', l: '停用' },
          graduating: { c: 'blue', l: '毕业中' },
        };
        const m = map[s] || { c: 'default', l: s || '-' };
        return <Tag color={m.c}>{m.l}</Tag>;
      },
    },
    { title: '账号 ID', dataIndex: 'account_id', key: 'account_id', ellipsis: true, render: (a: string) => a ? a.slice(0, 8) : '-' },
    { title: '运营者 ID', dataIndex: 'operator_id', key: 'operator_id', ellipsis: true, render: (o: string) => o ? o.slice(0, 8) : '-' },
    { title: '当日发布', dataIndex: 'daily_used', key: 'daily_used', width: 90 },
    { title: '运营者当日累计', dataIndex: 'op_daily_used', key: 'op_daily_used', width: 110 },
    { title: '最后发布', dataIndex: 'last_post_at', key: 'last_post_at', width: 150, render: (t: string) => t || '-' },
    { title: '最后心跳', dataIndex: 'last_heartbeat', key: 'last_heartbeat', width: 150, render: (t: string) => t || '-' },
    { title: '出口 IP', dataIndex: 'egress_ip', key: 'egress_ip', width: 120, render: (v: string) => v || '-' },
  ];

  const operatorStatColumns = [
    { title: '运营者 ID', dataIndex: 'operator_id', key: 'operator_id', ellipsis: true, render: (o: string) => o ? o.slice(0, 8) : '-' },
    { title: '当日发布数', dataIndex: 'daily_used', key: 'daily_used', width: 120 },
    { title: '进行中 (inflight)', dataIndex: 'inflight', key: 'inflight', width: 130 },
  ];

  const traceAction = (requestId: string | null) => {
    if (!requestId) return;
    publishApi.traceAudit(requestId).then(setTraceData).then(() => setTraceModalOpen(true))
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
  };

  const auditColumns = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 150, render: (t: string | null) => t || '-' },
    { title: '动作', dataIndex: 'action', key: 'action', width: 90, render: (a: string) => {
      const map: Record<string, { c: string; l: string }> = {
        publish: { c: 'blue', l: '发布' },
        confirm: { c: 'green', l: '确认' },
        fail: { c: 'red', l: '失败' },
        reauth: { c: 'orange', l: '重新登录' },
      };
      const m = map[a] || { c: 'default', l: a || '-' };
      return <Tag color={m.c}>{m.l}</Tag>;
    } },
    { title: '结果', dataIndex: 'result', key: 'result', width: 90, render: (r: string | null) => r || '-' },
    { title: '运营者', dataIndex: 'operator_id', key: 'operator_id', ellipsis: true, render: (o: string | null) => o ? o.slice(0, 8) : '-' },
    { title: '操作人', dataIndex: 'actor_id', key: 'actor_id', ellipsis: true, render: (o: string | null) => o ? o.slice(0, 8) : '-' },
    { title: '端口', dataIndex: 'port', key: 'port', width: 60, render: (p: number | null) => p ? `:${p}` : '-' },
    { title: '风控', dataIndex: 'risk_flag', key: 'risk_flag', width: 70, render: (r: boolean) => r ? <Tag color="red">风控</Tag> : '-' },
    { title: 'trace_id', dataIndex: 'request_id', key: 'request_id', ellipsis: true, render: (rid: string | null) => rid ? <a onClick={() => traceAction(rid)}>{rid.slice(0, 16)}</a> : '-' },
    { title: '备注', dataIndex: 'risk_note', key: 'risk_note', ellipsis: true, render: (n: string | null) => n || '-' },
  ];

  const riskColumns = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 150, render: (t: string | null) => t || '-' },
    { title: '风控类型', dataIndex: 'risk_type', key: 'risk_type', width: 130, render: (t: string) => <Tag color="red">{t}</Tag> },
    { title: '级别', dataIndex: 'level', key: 'level', width: 80 },
    { title: '运营者', dataIndex: 'operator_id', key: 'operator_id', ellipsis: true, render: (o: string | null) => o ? o.slice(0, 8) : '-' },
    { title: '处置', dataIndex: 'disposition', key: 'disposition', width: 110, render: (d: string | null) => d || '-' },
    { title: '信息', dataIndex: 'message', key: 'message', ellipsis: true },
  ];

  const loginColumns = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 150, render: (t: string | null) => t || '-' },
    { title: '动作', dataIndex: 'action', key: 'action', width: 90, render: (a: string) => {
      const map: Record<string, string> = { claim: '领取', scanned: '扫码', expired: '过期', refreshed: '刷新' };
      return map[a] || a || '-';
    } },
    { title: '运营者', dataIndex: 'operator_id', key: 'operator_id', ellipsis: true, render: (o: string | null) => o ? o.slice(0, 8) : '-' },
    { title: '扫码人', dataIndex: 'scanner_name', key: 'scanner_name', width: 110, render: (s: string | null) => s || '-' },
    { title: '结果', dataIndex: 'result', key: 'result', width: 90, render: (r: string | null) => r || '-' },
    { title: 'TTL', dataIndex: 'ttl_seconds', key: 'ttl_seconds', width: 60, render: (t: number | null) => t ?? '-' },
  ];

  const tabItems = [
    {
      key: 'tasks',
      label: `发布任务 (${tasks.length})`,
      children: (
        <Card size="small" title="发布任务">
          <Table rowKey="id" columns={taskColumns} dataSource={tasks} loading={taskLoading} pagination={false} size="small" scroll={{ x: 1050 }} />
        </Card>
      ),
    },
    {
      key: 'profiles',
      label: '发布配置',
      children: (
        <Card size="small" title="发布配置" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => { setEditingProfile(null); profileForm.resetFields(); setProfileModal(true); }}>新增配置</Button>}>
          <Table rowKey="id" columns={profileColumns} dataSource={profiles} loading={profileLoading} pagination={false} size="small" scroll={{ x: 900 }} />
        </Card>
      ),
    },
    {
      key: 'accounts',
      label: `视频号账号 (${accounts.length})`,
      children: (
        <Card size="small" title="视频号/抖音账号库（矩阵管理）" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => { setEditingAccount(null); accountForm.resetFields(); setAccountModal(true); }}>新增账号</Button>}>
          <Alert type="info" showIcon style={{ marginBottom: 12 }} message="账号库用于「一键发布」时下拉选择账号（自动绑定发布配置的 Chrome 端口与 Cookie 登录态），支持分组（如剧集A/B、情感）与小程序挂载资质标记。可在「发布配置」中先建好配置，再把账号与其关联。" />
          <Table rowKey="id" columns={accountColumns} dataSource={accounts} loading={accountLoading} pagination={false} size="small" scroll={{ x: 1100 }} />
        </Card>
      ),
    },
    {
      key: 'mini_programs',
      label: `小程序链接 (${miniPrograms.length})`,
      children: (
        <Card size="small" title="小程序链接库" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => { setEditingMiniProgram(null); miniProgramForm.resetFields(); setMiniProgramModal(true); }}>新增链接</Button>}>
          <Alert type="info" showIcon style={{ marginBottom: 12 }} message="视频号发布时可挂载的小程序链接（带渠道归因参数）。「一键发布」时从小程序库下拉选择，自动代入完整链接。" />
          <Table rowKey="id" columns={miniProgramColumns} dataSource={miniPrograms} loading={miniProgramLoading} pagination={false} size="small" scroll={{ x: 900 }} />
        </Card>
      ),
    },
    {
      key: 'matrix',
      label: '运营者端口矩阵',
      children: (
        <Card size="small" title="运营者端口矩阵（多运营者看板）" extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchMatrix}>刷新</Button>}>
          <Alert type="info" showIcon style={{ marginBottom: 12 }} message="读取 Redis 路由表实时渲染各运营者 Chrome 端口/登录态/限额消耗。启用 MULTI_OPERATOR_ENABLED 后生效；未启用时列表为空。" />
          <Space style={{ marginBottom: 12 }} wrap>
            <Select
              placeholder="选择账号发起扫码/心跳"
              style={{ width: 240 }}
              value={qrAccountId || undefined}
              onChange={(v) => setQrAccountId(v)}
              options={operatorMatrix.map((r) => ({ value: r.account_id, label: `${r.account_id?.slice(0, 8)} (${r.status})` }))}
              allowClear
            />
            <Button type="primary" icon={<QrcodeOutlined />} loading={qrClaiming} onClick={applyQr}>登录态扫码</Button>
            <Button icon={<HeartOutlined />} loading={qrHeartbeating} onClick={runHeartbeat}>心跳检查</Button>
            {qrHeartbeatStatus && <Tag color={qrHeartbeatStatus === 'valid' ? 'green' : qrHeartbeatStatus === 'need_login' ? 'orange' : 'red'}>心跳: {qrHeartbeatStatus}</Tag>}
          </Space>
          <Table rowKey="account_id" columns={matrixColumns} dataSource={operatorMatrix} loading={matrixLoading} pagination={false} size="small" scroll={{ x: 1150 }} />
          <Typography.Text strong style={{ display: 'block', margin: '16px 0 8px' }}>运营者当日配额消耗</Typography.Text>
          <Table rowKey="operator_id" columns={operatorStatColumns} dataSource={operatorStats} loading={matrixLoading} pagination={false} size="small" scroll={{ x: 500 }} />
        </Card>
      ),
    },
    {
      key: 'audit',
      label: '审计日志',
      children: (
        <Card size="small" title="发布审计与可观测（仅管理员）" extra={
          <Space>
            <Select
              value={auditKind}
              style={{ width: 120 }}
              onChange={(v: string) => { setAuditKind(v); }}
              options={[
                { value: 'publish', label: '发布' },
                { value: 'login', label: '登录态' },
                { value: 'risk', label: '风控' },
              ]}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={fetchAudit}>查询</Button>
          </Space>
        }>
          <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="审计日志含完整发布上下文（操作人/号主/IP/内容哈希/trace_id），仅 superadmin/admin 可查。点击 trace_id 可溯源全链路（审核→确认→发布→风控）。" />
          {auditKind === 'publish' && (
            <Table rowKey="id" columns={auditColumns} dataSource={auditLogs.items as PublishAuditItem[]} loading={auditLoading} pagination={false} size="small" scroll={{ x: 1300 }} />
          )}
          {auditKind === 'risk' && (
            <Table rowKey="id" columns={riskColumns} dataSource={auditLogs.items as RiskEventItem[]} loading={auditLoading} pagination={false} size="small" scroll={{ x: 1100 }} />
          )}
          {auditKind === 'login' && (
            <Table rowKey="id" columns={loginColumns} dataSource={auditLogs.items as LoginAuditItem[]} loading={auditLoading} pagination={false} size="small" scroll={{ x: 900 }} />
          )}
        </Card>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>发布管理</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchAll}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { taskForm.resetFields(); setTaskModal(true); }}>新建发布任务</Button>
      </Space>

      <Tabs items={tabItems} />

      {/* 登录态扫码二维码弹窗（P0 主题1） */}
      <Modal title="登录态扫码" open={qrModalOpen} footer={null} onCancel={() => setQrModalOpen(false)}>
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="请用对应运营者微信扫码确认登录。二维码链接 TTL 90s 单次有效，过期需重新申请。" />
        {qrUrl && (
          <div style={{ textAlign: 'center' }}>
            <img src={qrUrl} alt="登录二维码" style={{ width: 260, height: 260, border: '1px solid #f0f0f0', borderRadius: 8 }} />
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              微信扫码确认后，登录态将置为就绪
            </Typography.Paragraph>
          </div>
        )}
      </Modal>

      <Modal title="新建发布任务" open={taskModal} onOk={createTask} onCancel={() => setTaskModal(false)} destroyOnClose>
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="创建后立即触发 RPA 自动发布；若开启了截图确认，需在任务列表「确认发布」。多平台批量发布请到成品预览点「一键发布」。账号与小程序链接可在下方「视频号账号 / 小程序链接」Tab 中维护。" />
        <Form form={taskForm} layout="vertical">
          <Form.Item name="output_id" label="切片输出 ID" rules={[{ required: true, message: '请输入切片输出 ID' }]}>
            <Input placeholder="在成品预览页复制输出 ID" />
          </Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="video_account_id" label="发布账号（从账号库选择）">
            <Select
              allowClear
              showSearch
              placeholder="选择账号库账号"
              optionFilterProp="label"
              options={accounts.map((a) => ({
                value: a.id,
                label: `${a.account_name}${a.group_name ? `（${a.group_name}）` : ''} - ${PLATFORM_LABELS[a.platform] || a.platform}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="account_name" label="账号（选填）"><Input placeholder="如：主号 / 副号" /></Form.Item>
          <Form.Item name="title" label="标题"><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="tags" label="标签"><Select mode="tags" placeholder="回车添加标签" /></Form.Item>
          <Form.Item name="mini_program_id" label="小程序链接（从链接库选择）">
            <Select
              allowClear
              showSearch
              placeholder="选择小程序链接"
              optionFilterProp="label"
              options={miniPrograms.map((m) => ({
                value: m.id,
                label: `${m.name}（${m.full_link.slice(0, 40)}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="mini_program_link" label="小程序链接（选填）"><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal title={editingProfile ? '编辑发布配置' : '新增发布配置'} open={profileModal} onOk={saveProfile} onCancel={() => setProfileModal(false)} destroyOnClose>
        <Form form={profileForm} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="account_name" label="账号" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="chrome_debug_port" label="Chrome 调试端口" initialValue={9222}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="max_daily_publish" label="每日最大发布数" initialValue={20}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="min_interval_seconds" label="最小发布间隔（秒）" initialValue={300}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="require_manual_confirm" label="需要人工确认" initialValue={true}>
            <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={editingAccount ? '编辑账号' : '新增账号'} open={accountModal} onOk={saveAccount} onCancel={() => setAccountModal(false)} destroyOnClose width={640}>
        <Form form={accountForm} layout="vertical">
          <Form.Item name="account_name" label="账号名称" rules={[{ required: true, message: '请输入账号名称' }]}>
            <Input placeholder="如：主号-剧集A" />
          </Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true, message: '请选择平台' }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="group_name" label="分组">
            <Input placeholder="如：剧集A / 情感 / 爽文" />
          </Form.Item>
          <Form.Item name="wxid" label="视频号 ID / 平台号">
            <Input placeholder="平台侧账号唯一标识" />
          </Form.Item>
          <Form.Item name="profile_id" label="关联发布配置（选填）">
            <Select
              allowClear
              showSearch
              placeholder="选择绑定的发布配置（决定 Chrome 端口与 Cookie 登录态）"
              optionFilterProp="label"
              options={profiles.map((p) => ({
                value: p.id,
                label: `${PLATFORM_LABELS[p.platform || ''] || p.platform} - ${p.account_name}（端口 ${p.chrome_debug_port}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="mini_program_enabled" label="视频号小程序挂载资质" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={editingMiniProgram ? '编辑小程序链接' : '新增小程序链接'} open={miniProgramModal} onOk={saveMiniProgram} onCancel={() => setMiniProgramModal(false)} destroyOnClose>
        <Form form={miniProgramForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：XX短剧-小程序" />
          </Form.Item>
          <Form.Item name="appid" label="AppID"><Input /></Form.Item>
          <Form.Item name="path" label="Path"><Input /></Form.Item>
          <Form.Item name="full_link" label="完整链接（含渠道归因参数）" rules={[{ required: true, message: '请输入完整链接' }]}>
            <Input placeholder="https://…" />
          </Form.Item>
          <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={traceData ? `trace 溯源：${traceData.request_id.slice(0, 20)}` : 'trace 溯源'}
        open={traceModalOpen}
        footer={null}
        width={900}
        onCancel={() => setTraceModalOpen(false)}
        destroyOnClose
      >
        {traceData && (
          <div>
            <Typography.Paragraph type="secondary">全链路（审核→确认→发布→风控）审计，可溯源 operator/actor/IP/hash。</Typography.Paragraph>
            <Typography.Text strong>发布/确认</Typography.Text>
            <Table size="small" rowKey="id" columns={auditColumns} dataSource={traceData.publish} pagination={false} scroll={{ x: 1000 }} />
            {traceData.cookie.length > 0 && (
              <>
                <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>Cookie 访问</Typography.Text>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={false}
                  scroll={{ x: 700 }}
                  dataSource={traceData.cookie}
                  columns={[
                    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 150, render: (t: string | null) => t || '-' },
                    { title: '用途', dataIndex: 'purpose', key: 'purpose', width: 110 },
                    { title: 'IP', dataIndex: 'ip_address', key: 'ip_address', width: 130, render: (v: string | null) => v || '-' },
                    { title: '操作人', dataIndex: 'actor_id', key: 'actor_id', ellipsis: true, render: (o: string | null) => o ? o.slice(0, 8) : '-' },
                  ]}
                />
              </>
            )}
            {traceData.login.length > 0 && (
              <>
                <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>登录态</Typography.Text>
                <Table size="small" rowKey="id" columns={loginColumns} dataSource={traceData.login} pagination={false} scroll={{ x: 800 }} />
              </>
            )}
            {traceData.risk.length > 0 && (
              <>
                <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>风控事件</Typography.Text>
                <Table size="small" rowKey="id" columns={riskColumns} dataSource={traceData.risk} pagination={false} scroll={{ x: 800 }} />
              </>
            )}
          </div>
        )}
      </Modal>

      <Modal
        title="发布确认截图"
        open={screenshotModal}
        footer={null}
        width={720}
        onCancel={() => setScreenshotModal(false)}
        destroyOnClose
      >
        {screenshotLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>加载中…</div>
        ) : screenshotUrl ? (
          <img src={screenshotUrl} alt="发布确认截图" style={{ width: '100%', borderRadius: 6 }} />
        ) : (
          <Typography.Text type="secondary">暂无截图</Typography.Text>
        )}
      </Modal>
    </div>
  );
};

export default PublishManagement;
