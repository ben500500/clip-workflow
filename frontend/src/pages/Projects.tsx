import React, { useEffect, useState } from 'react';
import {
  Table,
  Button,
  Card,
  Input,
  Space,
  Tag,
  Modal,
  Form,
  Select,
  message,
  Popconfirm,
  Typography,
  Row,
  Col,
  Empty,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  SearchOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import type { Project, ProjectFormValues } from '../types';
import {
  formatDateTime,
  getStatusColor,
  getStatusLabel,
} from '../utils/format';

const { Title, Text } = Typography;

const Projects: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<ProjectFormValues>();

  useEffect(() => {
    fetchProjects();
  }, [page, pageSize]);

  const fetchProjects = async () => {
    setLoading(true);
    try {
      const res = await projectApi.getList({ page, page_size: pageSize, search });
      setProjects(res.data.items);
      setTotal(res.data.total);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取项目列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => {
    setPage(1);
    fetchProjects();
  };

  const handleCreate = () => {
    setEditingProject(null);
    form.resetFields();
    form.setFieldsValue({ platform: 'bilibili' });
    setModalOpen(true);
  };

  const handleEdit = (project: Project) => {
    setEditingProject(project);
    form.setFieldsValue({
      name: project.name,
      description: project.description,
      platform: project.platform,
      platform_profile_id: project.platform_profile_id,
    });
    setModalOpen(true);
  };

  const handleDelete = async (id: number) => {
    try {
      await projectApi.delete(id);
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
      if (editingProject) {
        await projectApi.update(editingProject.id, values);
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
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
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
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 100,
      render: (platform: string) => <Tag>{platform}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '剧集数',
      dataIndex: 'total_episodes',
      key: 'total_episodes',
      width: 80,
      render: (val: number, record: Project) => (
        <span>
          {record.processed_episodes}/{val}
        </span>
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
      width: 180,
      render: (_: unknown, record: Project) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => navigate(`/projects/${record.id}`)}
            >
              详情
            </Button>
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            >
              编辑
            </Button>
          </Tooltip>
          <Popconfirm
            title="确定删除该项目？"
            description="删除后相关数据将无法恢复"
            onConfirm={() => handleDelete(record.id)}
          >
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            项目管理
          </Title>
        </Col>
        <Col>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            新建项目
          </Button>
        </Col>
      </Row>

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
            <Button type="primary" onClick={handleSearch}>
              搜索
            </Button>
          </Col>
        </Row>
      </Card>

      <Card size="small">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={projects}
          loading={loading}
          size="middle"
          locale={{ emptyText: <Empty description="暂无项目，点击右上角新建" /> }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 个项目`,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
          scroll={{ x: 900 }}
        />
      </Card>

      <Modal
        title={editingProject ? '编辑项目' : '新建项目'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        width={600}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="请输入项目名称" />
          </Form.Item>
          <Form.Item
            name="platform"
            label="目标平台"
            rules={[{ required: true, message: '请选择目标平台' }]}
          >
            <Select
              placeholder="请选择平台"
              options={[
                { label: 'Bilibili', value: 'bilibili' },
                { label: '抖音', value: 'douyin' },
                { label: '快手', value: 'kuaishou' },
                { label: 'YouTube', value: 'youtube' },
                { label: '微信视频号', value: 'wechat' },
              ]}
            />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea rows={3} placeholder="请输入项目描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Projects;