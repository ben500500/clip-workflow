import React, { useEffect, useState } from 'react';
import {
  Table, Button, Card, Input, Space, Tag, Modal, Form, Select, message, Popconfirm,
  Typography, Row, Col, Tooltip,
} from 'antd';
import { PlusOutlined, SearchOutlined, DeleteOutlined, EditOutlined, EyeOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import type { Project, ProjectFormValues } from '../types';
import { formatDateTime, getStatusColor, getStatusLabel } from '../utils/format';
import { BizGuideEntry, SliceFlowGuide } from '../components/assets/BizGuides';

const { Title } = Typography;

const Projects: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // 「短剧切片怎么用」内嵌动画（11-15 业务区推进①，话术逐字耦合本页与 ProjectDetail/EpisodeDetail/ClipReview）
  const [sliceGuideOpen, setSliceGuideOpen] = useState(false);
  const [form] = Form.useForm<ProjectFormValues>();

  const fetchProjects = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await projectApi.getList({ page, page_size: pageSize, search: search || undefined });
      setProjects(res.items);
      setTotal(res.total);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取项目列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // 实时运行状态（2026-11-25 用户需求）：每 10s 静默刷新列表，让「运行中 ×N」
  // 徽标随任务起停实时变化；静默=不置 loading、不弹错误，避免打断用户操作
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const res = await projectApi.getList({ page, page_size: pageSize, search: search || undefined });
        if (!stopped) {
          setProjects(res.items);
          setTotal(res.total);
        }
      } catch {
        /* 轮询失败静默，保留现有列表 */
      }
      if (!stopped) timer = window.setTimeout(tick, 10000);
    };
    timer = window.setTimeout(tick, 10000);
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [page, pageSize, search]);

  const handleSearch = () => {
    setPage(1);
    // 若已在第 1 页，手动触发一次刷新
    if (page === 1) fetchProjects();
  };

  const handleCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleEdit = (project: Project) => {
    setEditing(project);
    form.setFieldsValue({
      name: project.name,
      description: project.description || undefined,
      status: project.status,
    });
    setModalOpen(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await projectApi.remove(id);
      message.success('项目已删除');
      fetchProjects();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      if (editing) {
        await projectApi.update(editing.id, values);
        message.success('项目已更新');
      } else {
        await projectApi.create(values);
        message.success('项目已创建');
      }
      setModalOpen(false);
      fetchProjects();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: Project) => (
        <a onClick={() => navigate(`/projects/${record.id}`)}>
          <FolderOpenOutlined style={{ marginRight: 6 }} />
          {name}
        </a>
      ),
    },
    {
      title: '剧集数',
      dataIndex: 'episode_count',
      key: 'episode_count',
      width: 100,
    },
    {
      title: '存储空间',
      key: 'storage',
      width: 110,
      render: (_: unknown, r: Project) => {
        const b = r.storage_bytes || 0;
        const fmt = (n: number) => (n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} GB` : n >= 1024 ** 2 ? `${(n / 1024 ** 2).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`);
        return <span style={{ fontSize: 13 }}>{b > 0 ? fmt(b) : '-'}</span>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (status: string, record: Project) =>
        (record.slice_running ?? 0) > 0 ? (
          <Tag color="processing" style={{ marginInlineEnd: 0 }}>
            ● 运行中 ×{record.slice_running}
          </Tag>
        ) : (
          <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
        ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => text || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (date: string) => formatDateTime(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: Project) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/projects/${record.id}`)}>详情</Button>
          </Tooltip>
          <Tooltip title="编辑">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          </Tooltip>
          <Popconfirm title="确定删除该项目？" description="删除后相关数据将无法恢复" onConfirm={() => handleDelete(record.id)}>
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col><Title level={4} style={{ margin: 0 }}>短剧切片</Title><BizGuideEntry label="短剧切片怎么用" onOpen={() => setSliceGuideOpen(true)} /></Col>
        <Col><Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建项目</Button></Col>
      </Row>
      <SliceFlowGuide open={sliceGuideOpen} onClose={() => setSliceGuideOpen(false)} />
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Input
              placeholder="搜索项目名称..."
              prefix={<SearchOutlined />}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onPressEnter={handleSearch}
              allowClear
            />
          </Col>
          <Col>
            <Button type="primary" onClick={handleSearch}>搜索</Button>
          </Col>
        </Row>
      </Card>
      <Card size="small">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={projects}
          loading={loading}
          scroll={{ x: 1000 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
        />
      </Card>
      <Modal
        title={editing ? '编辑项目' : '新建项目'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="例如：甜宠短剧 A 组" />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="draft">
            <Select
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'processing', label: '处理中' },
                { value: 'completed', label: '已完成' },
                { value: 'archived', label: '已归档' },
              ]}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="项目说明" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Projects;
