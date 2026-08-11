import React, { useEffect, useState, useRef, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Select, Modal, Form, Input, DatePicker, Popconfirm, Alert, Spin, InputNumber,
} from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined, DownloadOutlined, LinkOutlined, CloudDownloadOutlined, EditOutlined, SendOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { sliceApi } from '../api/slice';
import { previewApi } from '../api/preview';
import { publishApi } from '../api/publish';
import { publishMaterialApi, type PublishMaterialRecord } from '../api/publishMaterial';
import type { Publication, SliceOutput, SliceTask, VideoAccount, MiniProgram } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

// 平台中文名（账号库下拉展示）
const PLATFORM_LABELS: Record<string, string> = {
  wechat_channel: '视频号',
  douyin: '抖音',
  kuaishou: '快手',
};

// 切片模式中文展示
const SLICE_MODE_LABELS: Record<string, string> = {
  fast: '快速模式',
  dedupe: '去重模式',
  scrub: '挖洞模式',
};

// 成品预览只展示真实切片任务，过滤掉区间检测复用的 detect_* 内部进度记录
const isRealSliceTask = (t: SliceTask) => !(t.mode && t.mode.startsWith('detect_'));

const OutputPreview: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<SliceTask[]>([]);
  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [pubModal, setPubModal] = useState(false);
  const [pubForm] = Form.useForm();
  const [currentOutput, setCurrentOutput] = useState<string | null>(null);

  // ── 一键发布（对标「一键豆包生成」体验） ──
  const [publishModal, setPublishModal] = useState(false);
  const [publishForm] = Form.useForm();
  const [publishTarget, setPublishTarget] = useState<SliceOutput | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [materialRecords, setMaterialRecords] = useState<PublishMaterialRecord[]>([]);
  // 账号矩阵 / 小程序库（一期）
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);
  const [miniPrograms, setMiniPrograms] = useState<MiniProgram[]>([]);

  // ── 成品重新剪辑 ──
  const [recutModal, setRecutModal] = useState(false);
  const [recutForm] = Form.useForm();
  const [recutTarget, setRecutTarget] = useState<SliceOutput | null>(null);
  const [recutting, setRecutting] = useState(false);

  // 多选批量下载
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchDownloading, setBatchDownloading] = useState(false);

  // 任务/输出加载竞态防护：重复进入页面或快速切换任务时，
  // 以最后一次请求为准，避免旧响应把列表重复/覆盖回去
  const taskLoadSeqRef = useRef(0);
  const outputLoadSeqRef = useRef(0);
  const mountedRef = useRef(true);

  // 点击行区域展开预览：展开后自动加载该输出的视频预览
  const [expandedRowKeys, setExpandedRowKeys] = useState<React.Key[]>([]);
  const [expandedVideoUrls, setExpandedVideoUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const seq = ++taskLoadSeqRef.current;
    sliceApi
      .listTasks(episodeId || '')
      .then((list) => {
        if (mountedRef.current && seq === taskLoadSeqRef.current) {
          // 完全替换而非追加，确保重复进入页面不会让任务列表重复
          setTasks(list);
        }
      })
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
  }, [episodeId]);

  const loadTask = async (taskId: string) => {
    const seq = ++outputLoadSeqRef.current;
    setSelectedTask(taskId);
    setOutputs([]);
    setVideoUrl(null);
    setPublications([]);
    setSelectedRowKeys([]);
    setExpandedRowKeys([]);
    setExpandedVideoUrls({});
    try {
      const list = await sliceApi.getOutputs(taskId);
      if (mountedRef.current && seq === outputLoadSeqRef.current) {
        // 完全替换，避免重复加载时列表叠加
        setOutputs(list);
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取输出失败');
    }
  };

  // ─── 点击行区域展开预览 ─────────────────────────────
  // 点击行的任意位置都展开/收起该行的视频预览，无需点击"预览"按钮
  const toggleRowExpand = useCallback(async (output: SliceOutput) => {
    const isExpanded = expandedRowKeys.includes(output.id);
    if (isExpanded) {
      setExpandedRowKeys(expandedRowKeys.filter((k) => k !== output.id));
      return;
    }
    // 展开并自动加载视频预览地址
    setExpandedRowKeys([...expandedRowKeys, output.id]);
    // 当前输出也同步到预览/发布记录区
    setCurrentOutput(output.id);
    try {
      const video = await previewApi.getVideoUrl(output.id);
      if (mountedRef.current) {
        setExpandedVideoUrls((prev) => ({ ...prev, [output.id]: video.url }));
        setVideoUrl(video.url);
      }
      const pubs = await previewApi.getPublications(output.id);
      if (mountedRef.current) setPublications(pubs);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载预览失败');
    }
  }, [expandedRowKeys]);

  // ─── 多选批量下载（顺序逐个下载，不打 ZIP） ─────────────
  const downloadSelected = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先勾选要下载的切片');
      return;
    }
    setBatchDownloading(true);
    try {
      const res = await previewApi.batchDownload(selectedRowKeys as string[]);
      const files = res.files ?? [];
      if (files.length === 0) {
        message.warning('没有可下载的文件');
        return;
      }
      // 顺序逐个触发下载，间隔触发避免浏览器拦截多个自动下载
      let done = 0;
      for (const f of files) {
        const a = document.createElement('a');
        a.href = f.url;
        a.download = f.file_name || `output_${f.output_id}.mp4`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        done += 1;
        // 最后一个不用等，其余间隔 800ms 依次触发
        if (done < files.length) {
          await new Promise((r) => setTimeout(r, 800));
        }
      }
      message.success(`已开始按顺序下载 ${files.length} 个切片`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量下载失败');
    } finally {
      setBatchDownloading(false);
    }
  };

  // ─── 单个下载：直接触发浏览器下载，不跳转到播放/下载界面 ───────────
  const downloadOne = (o: SliceOutput) => {
    if (!o.id) {
      message.warning('暂无下载地址');
      return;
    }
    // 使用隐藏 a 标签 + download 属性，跟随后端 302 到 presigned URL 并直接下载，
    // 避免 window.open 跳转到新标签页播放视频导致后续下载被浏览器拦截/中断。
    const a = document.createElement('a');
    a.href = `/api/outputs/${o.id}/download`;
    a.download = o.file_name || `output_${o.id}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // ─── 一键发布：选平台 + 选发布素材（自动代入标题/描述/标签） ─────
  const openPublishModal = async (o: SliceOutput) => {
    setPublishTarget(o);
    publishForm.resetFields();
    publishForm.setFieldsValue({
      platforms: ['wechat_channel', 'douyin'],
      require_manual_confirm: true,
    });
    setPublishModal(true);
    // 加载发布素材历史供选取
    try {
      const records = await publishMaterialApi.listMaterials(30);
      setMaterialRecords(records);
    } catch {
      setMaterialRecords([]);
    }
    // 加载账号矩阵 + 小程序链接库（发布弹窗下拉）
    try {
      const accounts = await publishApi.getVideoAccounts();
      setVideoAccounts(accounts);
    } catch {
      setVideoAccounts([]);
    }
    try {
      const programs = await publishApi.getMiniPrograms({ enabled_only: true });
      setMiniPrograms(programs);
    } catch {
      setMiniPrograms([]);
    }
  };

  const submitPublish = async () => {
    if (!publishTarget) return;
    try {
      const values = await publishForm.validateFields();
      const platforms: string[] = values.platforms || [];
      if (platforms.length === 0) {
        message.warning('请至少选择一个发布平台');
        return;
      }
      // 若选取了发布素材记录，自动代入短标题/配文/标签
      let title = values.title || '';
      let description = values.description || '';
      let tags: string[] = values.tags || [];
      if (values.material_id) {
        const rec = materialRecords.find((r) => r.id === values.material_id);
        if (rec?.material) {
          const m = rec.material;
          title = title || m.short_title || '';
          const caption = m.captions?.suspense_hook || '';
          description = description || caption;
          const allTags = Object.values(m.tags || {}).flat();
          tags = tags.length > 0 ? tags : allTags;
        }
      }
      // 若选取了账号库账号，自动代入账号名称
      const selectedAccount = videoAccounts.find((a) => a.id === values.video_account_id);
      const accountName = selectedAccount ? selectedAccount.account_name : (values.account_name || undefined);
      // 若选取了小程序库链接，自动代入完整链接
      const selectedMiniProgram = miniPrograms.find((m) => m.id === values.mini_program_id);
      const miniProgramLink = selectedMiniProgram ? selectedMiniProgram.full_link : (values.mini_program_link || undefined);
      setPublishing(true);
      // 发布任务关联：material 记录可带出素材的 prompt_record_id
      const selectedMaterial = materialRecords.find((r) => r.id === values.material_id);
      const promptRecordId = selectedMaterial?.prompt_record_id || publishTarget.prompt_record_id || undefined;
      const tasks = platforms.map((platform: string) => ({
        output_id: publishTarget.id,
        platform,
        account_name: accountName,
        video_account_id: values.video_account_id || undefined,
        mini_program_id: selectedMiniProgram ? selectedMiniProgram.id : undefined,
        title: title || undefined,
        description: description || undefined,
        tags: tags.length > 0 ? tags : undefined,
        mini_program_link: miniProgramLink,
        require_manual_confirm: values.require_manual_confirm !== false,
        prompt_record_id: promptRecordId,
        material_id: values.material_id || undefined,
      }));
      const created = await publishApi.createTasks(tasks);
      message.success(`已创建 ${created.length} 个发布任务，正在发布`);
      setPublishModal(false);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '发布任务创建失败');
    } finally {
      setPublishing(false);
    }
  };

  // 选择发布素材后自动填入标题/描述/标签
  const onMaterialChange = (materialId: string | undefined) => {
    const rec = materialRecords.find((r) => r.id === materialId);
    if (!rec?.material) return;
    const m = rec.material;
    publishForm.setFieldsValue({
      title: m.short_title || '',
      description: m.captions?.suspense_hook || '',
      tags: Object.values(m.tags || {}).flat(),
    });
  };

  const openRecutModal = (o: SliceOutput) => {
    setRecutTarget(o);
    recutForm.resetFields();
    // 默认整段保留（0 ~ 成品时长），便于用户只填需要裁剪的头尾
    recutForm.setFieldsValue({
      cut_start: 0,
      cut_end: o.duration ?? 0,
    });
    setRecutModal(true);
  };

  const submitRecut = async () => {
    if (!recutTarget) return;
    try {
      const values = await recutForm.validateFields();
      const start = Number(values.cut_start ?? 0);
      const end = Number(values.cut_end ?? recutTarget.duration ?? 0);
      if (!(start >= 0) || !(end > start)) {
        message.warning('剪辑区间不合法：需要 0 <= 开始时间 < 结束时间');
        return;
      }
      setRecutting(true);
      const res = await sliceApi.run(episodeId || '', 'fast', {
        output_id: recutTarget.id,
        cut_start: start,
        cut_end: end,
        engine: 'worker',
      });
      message.success('重新剪辑任务已启动，完成后会在下方任务列表中生成新成品');
      setRecutModal(false);
      // 刷新任务列表，让新任务出现在顶部，可直接进入查看进度
      const list = await sliceApi.listTasks(episodeId || '');
      setTasks(list);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动重新剪辑失败');
    } finally {
      setRecutting(false);
    }
  };

  const outputColumns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    { title: '大小', dataIndex: 'file_size', key: 'file_size', width: 110, render: (s: number) => formatFileSize(s) },
    { title: '时长', dataIndex: 'duration', key: 'duration', width: 100, render: (d: number) => formatDuration(d) },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作',
      key: 'action',
      width: 330,
      fixed: 'right' as const,
      render: (_: unknown, o: SliceOutput) => (
        <Space size="small" wrap>
          <Button size="small" icon={<PlayCircleOutlined />} onClick={(e) => { e.stopPropagation(); toggleRowExpand(o); }}>预览</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={(e) => { e.stopPropagation(); downloadOne(o); }}>下载</Button>
          <Button size="small" type="primary" icon={<SendOutlined />} onClick={(e) => { e.stopPropagation(); openPublishModal(o); }}>一键发布</Button>
          <Button size="small" icon={<LinkOutlined />} onClick={(e) => { e.stopPropagation(); setCurrentOutput(o.id); pubForm.resetFields(); setPubModal(true); }}>登记发布</Button>
          <Button size="small" type="primary" ghost icon={<EditOutlined />} onClick={(e) => { e.stopPropagation(); openRecutModal(o); }}>编辑</Button>
        </Space>
      ),
    },
  ];

  const pubColumns = [
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 120 },
    { title: '链接', dataIndex: 'publish_url', key: 'publish_url', ellipsis: true, render: (u: string) => u ? <a href={u} target="_blank" rel="noreferrer">{u}</a> : '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag> },
    { title: '发布时间', dataIndex: 'publish_time', key: 'publish_time', width: 170, render: (d: string) => formatDateTime(d) },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${episodeId}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>成品预览</Title>
      </Space>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <span>选择切片任务：</span>
          <Select
            style={{ width: 320 }}
            placeholder="选择任务查看输出"
            value={selectedTask ?? undefined}
            onChange={loadTask}
            options={tasks
              .filter(isRealSliceTask)
              .map((t) => ({
                value: t.id,
                label: `${SLICE_MODE_LABELS[t.mode || ''] || t.mode || '未知模式'} / ${getStatusLabel(t.status || '')} / ${formatDateTime(t.created_at)}`,
              }))}
          />
          {selectedTask && outputs.length > 0 && (
            <Popconfirm
              title={`确定下载选中的 ${selectedRowKeys.length} 个切片？`}
              description="将按顺序逐个下载，不打包"
              onConfirm={downloadSelected}
              okText="下载"
              cancelText="取消"
              disabled={selectedRowKeys.length === 0}
            >
              <Button
                type="primary"
                icon={<CloudDownloadOutlined />}
                loading={batchDownloading}
                disabled={selectedRowKeys.length === 0}
              >
                批量下载选中 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
        </Space>
      </Card>
      {selectedTask && (
        <Card size="small" title={`切片输出（共 ${outputs.length} 个）`} style={{ marginBottom: 16 }}>
          {outputs.length > 0 ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message={
                  <Text style={{ fontSize: 12 }}>
                    勾选左侧复选框可一次选择多个切片，然后点击顶部「批量下载选中」打包下载。
                  </Text>
                }
              />
              <Table
                rowKey="id"
                columns={outputColumns}
                dataSource={outputs}
                pagination={false}
                size="small"
                scroll={{ x: 900 }}
                rowSelection={{
                  selectedRowKeys,
                  onChange: (keys) => setSelectedRowKeys(keys),
                }}
                onRow={(record: SliceOutput) => ({
                  onClick: () => toggleRowExpand(record),
                  style: { cursor: 'pointer' },
                })}
                expandable={{
                  expandedRowKeys,
                  onExpandedRowsChange: (keys: readonly React.Key[]) => setExpandedRowKeys(keys as React.Key[]),
                  expandedRowRender: (record: SliceOutput) => {
                    const url = expandedVideoUrls[record.id];
                    return (
                      <div style={{ padding: '4px 0' }}>
                        {url ? (
                          <video src={url} controls autoPlay style={{ width: '100%', maxHeight: 380, background: '#000', borderRadius: 6 }} />
                        ) : (
                          <Space>
                            <Spin size="small" />
                            <Text type="secondary">正在加载预览…</Text>
                          </Space>
                        )}
                      </div>
                    );
                  },
                }}
              />
            </>
          ) : (
            <Text type="secondary">该任务暂无输出文件</Text>
          )}
        </Card>
      )}
      {videoUrl && (
        <Card size="small" title="视频预览" style={{ marginBottom: 16 }}>
          <video src={videoUrl} controls style={{ width: '100%', maxHeight: 420, background: '#000' }} />
        </Card>
      )}
      {currentOutput && (
        <Card size="small" title="发布记录">
          <Table rowKey="id" columns={pubColumns} dataSource={publications} pagination={false} size="small" scroll={{ x: 560 }} />
        </Card>
      )}
      {/* ── 成品重新剪辑弹窗 ── */}
      <Modal
        title={`重新剪辑${recutTarget ? `：${recutTarget.file_name}` : ''}`}
        open={recutModal}
        onOk={submitRecut}
        onCancel={() => setRecutModal(false)}
        okText="开始剪辑"
        cancelText="取消"
        confirmLoading={recutting}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="以当前成品视频为源，裁剪出新的时间区间，生成一个新片段（会重新编码输出）。"
        />
        <Form form={recutForm} layout="vertical">
          <Form.Item
            name="cut_start"
            label="开始时间（秒）"
            rules={[{ required: true, message: '请输入开始时间' }]}
          >
            <InputNumber min={0} precision={3} style={{ width: '100%' }} placeholder="0" />
          </Form.Item>
          <Form.Item
            name="cut_end"
            label="结束时间（秒）"
            rules={[{ required: true, message: '请输入结束时间' }]}
          >
            <InputNumber min={0} precision={3} style={{ width: '100%' }} placeholder={`${recutTarget?.duration ?? 0}`} />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            当前成品时长：{formatDuration(recutTarget?.duration ?? 0)}。区间为相对成品起点的秒数。
          </Text>
        </Form>
      </Modal>
      {/* ── 一键发布弹窗（对标「一键豆包生成」体验） ── */}
      <Modal
        title={`一键发布${publishTarget ? `：${publishTarget.file_name}` : ''}`}
        open={publishModal}
        onOk={submitPublish}
        onCancel={() => setPublishModal(false)}
        okText="创建发布任务"
        cancelText="取消"
        confirmLoading={publishing}
        width={640}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="选择发布平台（可多选批量发布），可选取已生成的发布素材自动代入标题/配文/标签，提交后自动触发 RPA 发布。"
        />
        <Form form={publishForm} layout="vertical">
          <Form.Item
            name="platforms"
            label="发布平台（可多选）"
            rules={[{ required: true, message: '请至少选择一个平台' }]}
          >
            <Select
              mode="multiple"
              placeholder="选择发布平台，可多选批量发布"
              options={[
                { value: 'wechat_channel', label: '视频号' },
                { value: 'douyin', label: '抖音' },
                { value: 'kuaishou', label: '快手' },
              ]}
            />
          </Form.Item>
          <Form.Item name="material_id" label="发布素材（选填，自动代入标题/配文/标签）">
            <Select
              allowClear
              showSearch
              placeholder="选取已生成的发布素材"
              optionFilterProp="label"
              onChange={onMaterialChange}
              options={materialRecords.map((r) => ({
                value: r.id,
                label: `${r.material?.short_title || r.story?.slice(0, 20) || r.id}（${formatDateTime(r.created_at)}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="video_account_id" label="发布账号（从账号库选择）">
            <Select
              allowClear
              showSearch
              placeholder="选择账号库账号（留空则手填或使用默认配置）"
              optionFilterProp="label"
              options={videoAccounts.map((a) => ({
                value: a.id,
                label: `${a.account_name}${a.group_name ? `（${a.group_name}）` : ''} - ${PLATFORM_LABELS[a.platform] || a.platform}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="account_name" label="或手填账号（选填）">
            <Input placeholder="如：主号 / 副号" />
          </Form.Item>
          <Form.Item name="title" label="标题">
            <Input placeholder="标题（短标题，8-18 字）" />
          </Form.Item>
          <Form.Item name="description" label="描述/配文">
            <Input.TextArea rows={3} placeholder="描述或配文，可含话题标签" />
          </Form.Item>
          <Form.Item name="tags" label="话题标签">
            <Select mode="tags" placeholder="回车添加标签" />
          </Form.Item>
          <Form.Item name="mini_program_id" label="小程序链接（从链接库选择，仅视频号）">
            <Select
              allowClear
              showSearch
              placeholder="选择小程序链接"
              optionFilterProp="label"
              options={miniPrograms.map((m) => ({
                value: m.id,
                label: `${m.name}${m.full_link ? `（${m.full_link.slice(0, 40)}）` : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="mini_program_link" label="或手填小程序链接（选填）">
            <Input placeholder="视频号可挂载小程序链接" />
          </Form.Item>
          <Form.Item name="require_manual_confirm" label="截图确认后发布" initialValue={true}>
            <Select options={[{ value: true, label: '是（推荐，RPA 填好表单后截图人工确认再发布）' }, { value: false, label: '否（直接自动发布）' }]} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="登记发布记录"
        open={pubModal}
        onOk={async () => {
          try {
            const values = await pubForm.validateFields();
            await previewApi.createPublication(currentOutput || '', {
              platform: values.platform,
              publish_url: values.publish_url,
              status: values.status || 'published',
              publish_time: values.publish_time ? values.publish_time.toISOString() : undefined,
              operator: values.operator,
            });
            message.success('已登记');
            setPubModal(false);
            if (currentOutput) {
              const pubs = await previewApi.getPublications(currentOutput);
              setPublications(pubs);
            }
          } catch (err: unknown) {
            if (err && typeof err === 'object' && 'errorFields' in err) return;
            message.error(err instanceof Error ? err.message : '登记失败');
          }
        }}
        onCancel={() => setPubModal(false)}
        destroyOnClose
      >
        <Form form={pubForm} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="publish_url" label="发布链接"><Input /></Form.Item>
          <Form.Item name="status" label="状态" initialValue="published">
            <Select options={[{ value: 'published', label: '已发布' }, { value: 'pending', label: '待发布' }, { value: 'rejected', label: '已拒绝' }]} />
          </Form.Item>
          <Form.Item name="publish_time" label="发布时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="operator" label="操作人"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default OutputPreview;
