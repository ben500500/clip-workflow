import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Form, Input, Button, Select, Table, Tag, Modal, message, Space, Typography,
  Popconfirm, Drawer, Descriptions, Upload, Image as AntImage, Empty, Tooltip, Spin,
  Radio, Checkbox, Divider, Alert, Steps,
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, ImportOutlined,
  UploadOutlined, LinkOutlined, FileImageOutlined, ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import dayjs from 'dayjs';
import {
  Drama, DramaDetail, DramaCreateParams, DramaUpdateParams, DramaImportRow,
  listDramas, getDrama, createDrama, updateDrama, deleteDrama,
  uploadDramaImage, addDramaStill, deleteDramaStill, linkDramaAccounts,
  dramaImportParse, dramaImportPreview, dramaImportConfirm,
} from '../api/dramas';
import { publishApi } from '../api/publish';
import type { VideoAccount } from '../types';

const { Text } = Typography;

// 受控枚举
const FREQUENCIES = ['男频', '女频'];
const DRAMA_TYPES = ['AI真人剧', '真人剧', '动漫', '微短剧'];
const LISTING_STATUSES = ['草稿', '待上架', '已上架', '已下架', '归档'];
const RATINGS = ['SS+', '新剧S+', '新剧A+', '新剧B+'];
const STATUS_COLORS: Record<string, string> = {
  已上架: 'green',
  待上架: 'orange',
  草稿: 'default',
  已下架: 'red',
  归档: 'default',
};

const DraggableUpload: React.FC<{
  text: string;
  onFile: (key: string, name: string) => void;
}> = ({ text, onFile }) => {
  const [uploading, setUploading] = useState(false);
  const handle = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadDramaImage(file);
      onFile(res.file_key, res.file_name);
      message.success('图片上传成功');
    } catch (e) {
      message.error((e as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
    return false;
  };
  return (
    <Upload.Dragger
      beforeUpload={handle}
      showUploadList={false}
      accept=".png,.jpg,.jpeg,.webp,.gif,.bmp"
      disabled={uploading}
    >
      <p className="ant-upload-drag-icon"><FileImageOutlined /></p>
      <p className="ant-upload-text">{uploading ? '上传中…' : text}</p>
    </Upload.Dragger>
  );
};

const DramaLibrary: React.FC = () => {
  const [data, setData] = useState<Drama[]>([]);
  const [loading, setLoading] = useState(false);
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);

  // 筛选
  const [keyword, setKeyword] = useState('');
  const [freq, setFreq] = useState<string | undefined>();
  const [rating, setRating] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();

  // 新增/编辑弹窗
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Drama | null>(null);
  const [form] = Form.useForm();

  // 详情抽屉
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DramaDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 导入弹窗
  const [importOpen, setImportOpen] = useState(false);
  const [importStep, setImportStep] = useState(0);
  const [parsedRows, setParsedRows] = useState<DramaImportRow[]>([]);
  const [fileName, setFileName] = useState('');
  const [preview, setPreview] = useState<{
    new: Array<{ name: string; fields: Record<string, unknown> }>;
    update: Array<{ id: string; code: string; name: string; diff: Record<string, { old: unknown; new: unknown }> }>;
    unchanged: Array<{ id: string; code: string; name: string }>;
    summary: { new_count: number; update_count: number; unchanged_count: number };
  } | null>(null);
  const [checkNew, setCheckNew] = useState<Set<number>>(new Set());
  const [checkUpdate, setCheckUpdate] = useState<Set<number>>(new Set());
  const [importing, setImporting] = useState(false);

  const fetchList = useCallback(async (kw?: string, f?: string, r?: string, s?: string) => {
    setLoading(true);
    try {
      const list = await listDramas({ q: kw, frequency: f, rating: r, listing_status: s });
      setData(list);
    } catch (e) {
      message.error((e as Error).message || '加载剧目库失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // 加载视频号账号库（用于关联）
  useEffect(() => {
    publishApi.getVideoAccounts().then(setVideoAccounts).catch(() => setVideoAccounts([]));
  }, []);

  const doSearch = () => fetchList(keyword, freq, rating, status);

  // ── 新增/编辑 ──
  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ listing_status: '已上架' });
    setModalOpen(true);
  };

  const openEdit = (d: Drama) => {
    setEditing(d);
    form.setFieldsValue({
      name: d.name,
      frequency: d.frequency || undefined,
      type: d.type || undefined,
      tags: d.tags || [],
      rating: d.rating || undefined,
      synopsis: d.synopsis || undefined,
      listing_status: d.listing_status,
      material_link: d.material_link || undefined,
      updated_date: d.updated_date ? dayjs(d.updated_date) : undefined,
    });
    setModalOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload: DramaCreateParams = {
      name: values.name as string,
      frequency: values.frequency || null,
      type: values.type || null,
      tags: values.tags || null,
      rating: values.rating || null,
      synopsis: values.synopsis || null,
      listing_status: values.listing_status,
      material_link: values.material_link || null,
      updated_date: values.updated_date ? values.updated_date.format('YYYY-MM-DD') : null,
    };
    try {
      if (editing) {
        await updateDrama(editing.id, payload);
        message.success('剧目已更新');
      } else {
        await createDrama(payload);
        message.success('剧目已创建');
      }
      setModalOpen(false);
      fetchList(keyword, freq, rating, status);
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    }
  };

  const remove = async (id: string, name: string) => {
    try {
      await deleteDrama(id);
      message.success(`已删除 ${name}`);
      fetchList(keyword, freq, rating, status);
    } catch (e) {
      message.error((e as Error).message || '删除失败');
    }
  };

  // ── 详情 ──
  const openDetail = async (d: Drama) => {
    setDetailId(d.id);
    setDetailOpen(true);
    setDetailLoading(true);
    try {
      const res = await getDrama(d.id);
      setDetail(res);
    } catch (e) {
      message.error((e as Error).message || '加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const setCover = async (fileKey: string) => {
    if (!detailId) return;
    try {
      await updateDrama(detailId, { cover_file_key: fileKey });
      message.success('封面已更新');
      const res = await getDrama(detailId);
      setDetail(res);
      fetchList(keyword, freq, rating, status);
    } catch (e) {
      message.error((e as Error).message || '更新封面失败');
    }
  };

  const addStill = async (fileKey: string) => {
    if (!detailId) return;
    try {
      await addDramaStill(detailId, fileKey, (detail?.stills.length || 0));
      message.success('剧照已添加');
      const res = await getDrama(detailId);
      setDetail(res);
    } catch (e) {
      message.error((e as Error).message || '添加剧照失败');
    }
  };

  const removeStill = async (stillId: string) => {
    try {
      await deleteDramaStill(stillId);
      message.success('剧照已删除');
      if (detailId) {
        const res = await getDrama(detailId);
        setDetail(res);
      }
    } catch (e) {
      message.error((e as Error).message || '删除剧照失败');
    }
  };

  const linkAccounts = async (accountIds: string[]) => {
    if (!detailId) return;
    try {
      await linkDramaAccounts(detailId, accountIds);
      message.success('账号关联已更新');
      const res = await getDrama(detailId);
      setDetail(res);
    } catch (e) {
      message.error((e as Error).message || '关联失败');
    }
  };

  // ── 导入 ──
  const resetImport = () => {
    setImportStep(0);
    setParsedRows([]);
    setFileName('');
    setPreview(null);
    setCheckNew(new Set());
    setCheckUpdate(new Set());
  };

  const onImportFile = async (file: File) => {
    try {
      const res = await dramaImportParse(file);
      setParsedRows(res.rows);
      setFileName(res.file_name);
      message.success(res.message);
      setImportStep(1);
      // 自动预览
      const pv = await dramaImportPreview(res.rows, res.file_name);
      setPreview(pv);
      setCheckNew(new Set(pv.new.map((_, i) => i)));
      setCheckUpdate(new Set(pv.update.map((_, i) => i)));
      setImportStep(2);
    } catch (e) {
      message.error((e as Error).message || '解析失败');
    }
    return false;
  };

  const toggleNew = (i: number) => {
    const s = new Set(checkNew);
    if (s.has(i)) s.delete(i); else s.add(i);
    setCheckNew(s);
  };
  const toggleUpdate = (i: number) => {
    const s = new Set(checkUpdate);
    if (s.has(i)) s.delete(i); else s.add(i);
    setCheckUpdate(s);
  };

  const doImport = async () => {
    setImporting(true);
    try {
      const acceptNew = [...checkNew].sort((a, b) => a - b)
        .filter((i) => Boolean(preview?.new[i]))
        .map((i) => ({
          name: (preview!.new[i] as { name: string }).name,
          frequency: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.frequency as string) || null,
          type: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.type as string) || null,
          tags: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.tags as string[]) || null,
          rating: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.rating as string) || null,
          listing_status: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.listing_status as string) || '已上架',
          updated_date: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.updated_date as string) || null,
          listed_at: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.listed_at as string) || null,
          material_link: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.material_link as string) || null,
          account_name: ((preview!.new[i] as { fields: Record<string, unknown> }).fields.account_name as string) || null,
        }));
      const acceptUpdate = [...checkUpdate].sort((a, b) => a - b).map((i) => {
        const u = preview!.update[i] as { id: string; code: string; name: string; diff: Record<string, { old: unknown; new: unknown }> };
        return {
          id: u.id,
          name: u.name,
          frequency: (u.diff.frequency?.new as string) || null,
          type: (u.diff.type?.new as string) || null,
          tags: (u.diff.tags?.new as string[]) || null,
          rating: (u.diff.rating?.new as string) || null,
          listing_status: (u.diff.listing_status?.new as string) || '已上架',
          updated_date: (u.diff.updated_date?.new as string) || null,
          listed_at: (u.diff.listed_at?.new as string) || null,
          material_link: (u.diff.material_link?.new as string) || null,
        };
      });
      const res = await dramaImportConfirm(acceptNew, acceptUpdate, fileName);
      message.success(`导入完成：新增 ${res.imported}，更新 ${res.updated}，跳过 ${res.skipped}`);
      setImportOpen(false);
      resetImport();
      fetchList(keyword, freq, rating, status);
    } catch (e) {
      message.error((e as Error).message || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  // ── 表格列 ──
  const columns: ColumnsType<Drama> = [
    {
      title: '封面',
      dataIndex: 'cover_file_key',
      width: 70,
      render: (_, r) =>
        r.cover_url ? (
          <AntImage src={r.cover_url} width={44} height={44} style={{ objectFit: 'cover', borderRadius: 4 }} />
        ) : (
          <div style={{ width: 44, height: 44, borderRadius: 4, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FileImageOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />
          </div>
        ),
    },
    {
      title: '剧目ID',
      dataIndex: 'code',
      width: 120,
      render: (v) => <Text code>{v}</Text>,
    },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '频', dataIndex: 'frequency', width: 70, render: (v) => v || '-' },
    {
      title: '题材',
      dataIndex: 'tags',
      width: 200,
      render: (v: string[] | null) =>
        v && v.length ? v.slice(0, 4).map((t) => <Tag key={t} color="blue">{t}</Tag>) : '-',
    },
    { title: '评级', dataIndex: 'rating', width: 90, render: (v) => (v ? <Tag color="gold">{v}</Tag> : '-') },
    {
      title: '状态',
      dataIndex: 'listing_status',
      width: 90,
      render: (v) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '操作',
      width: 180,
      render: (_, r) => (
        <Space>
          <Button size="small" type="link" onClick={() => openDetail(r)}>详情</Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title={`删除「${r.name}」？`} onConfirm={() => remove(r.id, r.name)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const accountNameById = (id: string) => videoAccounts.find((a) => a.id === id)?.account_name || id;

  return (
    <div>
      <Card
        title="剧目库"
        extra={
          <Space>
            <Input
              placeholder="搜索名称/ID"
              prefix={<SearchOutlined />}
              style={{ width: 200 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={doSearch}
            />
            <Select
              placeholder="男/女频"
              allowClear
              style={{ width: 110 }}
              value={freq}
              onChange={(v) => { setFreq(v); fetchList(keyword, v, rating, status); }}
              options={FREQUENCIES.map((f) => ({ value: f, label: f }))}
            />
            <Select
              placeholder="评级"
              allowClear
              style={{ width: 120 }}
              value={rating}
              onChange={(v) => { setRating(v); fetchList(keyword, freq, v, status); }}
              options={RATINGS.map((f) => ({ value: f, label: f }))}
            />
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 110 }}
              value={status}
              onChange={(v) => { setStatus(v); fetchList(keyword, freq, rating, v); }}
              options={LISTING_STATUSES.map((f) => ({ value: f, label: f }))}
            />
            <Button icon={<SearchOutlined />} onClick={doSearch}>查询</Button>
            <Button icon={<ImportOutlined />} onClick={() => { resetImport(); setImportOpen(true); }}>导入剧目</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增剧目</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>

      {/* 新增/编辑弹窗 */}
      <Modal
        title={editing ? `编辑剧目：${editing.name}` : '新增剧目'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        width={640}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="漫剧名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="剧目名称（去重键）" />
          </Form.Item>
          <Space size="large" style={{ display: 'flex' }}>
            <Form.Item name="frequency" label="男/女频">
              <Select allowClear placeholder="男频/女频" style={{ width: 140 }} options={FREQUENCIES.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item name="type" label="漫剧类型">
              <Select allowClear placeholder="AI真人剧等" style={{ width: 160 }} options={DRAMA_TYPES.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item name="rating" label="评级">
              <Select allowClear placeholder="评级" style={{ width: 120 }} options={RATINGS.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
          </Space>
          <Form.Item name="tags" label="题材标签">
            <Select mode="tags" placeholder="输入题材，回车添加" tokenSeparators={[',', '/']} />
          </Form.Item>
          <Form.Item name="synopsis" label="剧情简介">
            <Input.TextArea rows={3} placeholder="用于发布时生成短标题/配文/话题" />
          </Form.Item>
          <Space size="large" style={{ display: 'flex' }}>
            <Form.Item name="listing_status" label="上架状态" initialValue="已上架">
              <Select style={{ width: 130 }} options={LISTING_STATUSES.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item name="updated_date" label="更新日期">
              <Input type="date" style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name="material_link" label="素材链接">
            <Input placeholder="百度网盘等素材链接（提取码请勿填入）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情抽屉 */}
      <Drawer
        title={detail ? `${detail.name}（${detail.code}）` : '剧目详情'}
        width={620}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      >
        {detailLoading || !detail ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
              <Descriptions.Item label="剧目ID"><Text code>{detail.code}</Text></Descriptions.Item>
              <Descriptions.Item label="男/女频">{detail.frequency || '-'}</Descriptions.Item>
              <Descriptions.Item label="类型">{detail.type || '-'}</Descriptions.Item>
              <Descriptions.Item label="评级">{detail.rating || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">{detail.listing_status}</Descriptions.Item>
            </Descriptions>
            {detail.synopsis && (
              <Alert type="info" showIcon message="剧情简介" description={detail.synopsis} />
            )}

            <Divider orientation="left">封面</Divider>
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              {detail.cover_url ? (
                <AntImage src={detail.cover_url} width={120} height={160} style={{ objectFit: 'cover', borderRadius: 6 }} />
              ) : (
                <div style={{ width: 120, height: 160, borderRadius: 6, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FileImageOutlined style={{ color: '#bfbfbf', fontSize: 28 }} />
                </div>
              )}
              <div style={{ flex: 1 }}>
                <DraggableUpload text="上传/更换封面" onFile={(key) => setCover(key)} />
              </div>
            </div>

            <Divider orientation="left">剧照</Divider>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
              {detail.stills.map((s) => (
                <div key={s.id} style={{ position: 'relative' }}>
                  {s.presigned_url ? (
                    <AntImage src={s.presigned_url} width={96} height={96} style={{ objectFit: 'cover', borderRadius: 6 }} />
                  ) : (
                    <div style={{ width: 96, height: 96, borderRadius: 6, background: '#f5f5f5' }} />
                  )}
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    style={{ position: 'absolute', top: -8, right: -8 }}
                    onClick={() => removeStill(s.id)}
                  />
                </div>
              ))}
            </div>
            <DraggableUpload text="添加剧照（可多张）" onFile={(key) => addStill(key)} />

            <Divider orientation="left">关联视频号</Divider>
            <Select
              mode="multiple"
              style={{ width: '100%' }}
              placeholder="选择该剧目在哪些视频号上架"
              value={detail.account_ids || []}
              onChange={linkAccounts}
              optionFilterProp="label"
              options={videoAccounts.map((a) => ({ value: a.id, label: a.account_name }))}
            />
            {detail.material_link && (
              <Alert type="info" showIcon message="素材链接" description={detail.material_link} />
            )}
          </Space>
        )}
      </Drawer>

      {/* 导入弹窗 */}
      <Modal
        title="导入剧目"
        open={importOpen}
        onCancel={() => { setImportOpen(false); resetImport(); }}
        footer={null}
        width={860}
      >
        <Steps
          current={importStep}
          items={[{ title: '上传' }, { title: '解析' }, { title: '确认' }]}
          style={{ marginBottom: 20 }}
        />
        {importStep === 0 && (
          <Upload.Dragger
            beforeUpload={onImportFile}
            showUploadList={false}
            accept=".xlsx,.xls,.csv"
          >
            <p className="ant-upload-drag-icon"><ImportOutlined /></p>
            <p className="ant-upload-text">点击或拖拽剧目 Excel 文件到此处</p>
            <p className="ant-upload-hint">列名对齐：漫剧名称 / 更新日期 / 男/女频 / 题材 / 漫剧类型 / 上架状态 / 上架日期 / 评级 / 素材链接 / 上架账号</p>
          </Upload.Dragger>
        )}
        {importStep === 1 && (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin tip="解析中…" /></div>
        )}
        {importStep === 2 && preview && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Alert
              type="info"
              showIcon
              message={`文件「${fileName}」解析到 ${preview.summary.new_count + preview.summary.update_count + preview.summary.unchanged_count} 条，同名称剧目会自动 diff 并询问`}
            />
            {preview.new.length > 0 && (
              <div>
                <Divider orientation="left">
                  <Space>
                    <Checkbox
                      checked={checkNew.size === preview.new.length}
                      onChange={(e) => setCheckNew(e.target.checked ? new Set(preview.new.map((_, i) => i)) : new Set())}
                    />
                    <Text strong>新增（{preview.new.length} 条）</Text>
                  </Space>
                </Divider>
                <Table
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  dataSource={preview.new.map((n, i) => ({ ...n, __i: i }))}
                  columns={[
                    {
                      title: '', width: 40,
                      render: (_, row) => (
                        <Checkbox checked={checkNew.has(row.__i)} onChange={() => toggleNew(row.__i)} />
                      ),
                    },
                    { title: '名称', dataIndex: 'name' },
                    { title: '频', dataIndex: ['fields', 'frequency'], render: (v) => v || '-' },
                    { title: '题材', dataIndex: ['fields', 'tags'], render: (v: string[]) => (v && v.length ? v.join(' / ') : '-') },
                    { title: '评级', dataIndex: ['fields', 'rating'], render: (v) => v || '-' },
                    { title: '状态', dataIndex: ['fields', 'listing_status'], render: (v) => v || '已上架' },
                  ]}
                />
              </div>
            )}
            {preview.update.length > 0 && (
              <div>
                <Divider orientation="left">
                  <Space>
                    <Checkbox
                      checked={checkUpdate.size === preview.update.length}
                      onChange={(e) => setCheckUpdate(e.target.checked ? new Set(preview.update.map((_, i) => i)) : new Set())}
                    />
                    <Text strong>更新（{preview.update.length} 条）</Text>
                  </Space>
                </Divider>
                {preview.update.map((u, i) => (
                  <Card key={u.id} size="small" style={{ marginBottom: 8 }}>
                    <Space align="start" style={{ width: '100%' }}>
                      <Checkbox checked={checkUpdate.has(i)} onChange={() => toggleUpdate(i)} />
                      <div style={{ flex: 1 }}>
                        <Text strong>{u.name}</Text> <Text code>{u.code}</Text>
                        {Object.entries(u.diff).map(([field, d]) => (
                          <div key={field} style={{ marginTop: 4 }}>
                            <Text type="secondary">{field}: </Text>
                            <Text delete>{String(d.old ?? '-')}</Text>
                            <Text type="warning"> → </Text>
                            <Text>{String(d.new ?? '-')}</Text>
                          </div>
                        ))}
                      </div>
                    </Space>
                  </Card>
                ))}
              </div>
            )}
            {preview.unchanged.length > 0 && (
              <Alert type="success" showIcon message={`${preview.unchanged.length} 条无变化，默认跳过`} />
            )}
            <Divider />
            <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button onClick={() => { setImportStep(0); setParsedRows([]); setPreview(null); }}>重新选择</Button>
              <Button type="primary" loading={importing} onClick={doImport}>
                确认导入（新增 {checkNew.size} / 更新 {checkUpdate.size}）
              </Button>
            </Space>
          </Space>
        )}
      </Modal>
    </div>
  );
};

export default DramaLibrary;
