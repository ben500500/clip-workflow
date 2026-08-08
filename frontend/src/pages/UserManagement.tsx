import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Form, Input, Select, Popconfirm, Tooltip,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined, SafetyOutlined } from '@ant-design/icons';
import { authApi } from '../api/auth';
import { ROLE_OPTIONS, DATA_SCOPE_OPTIONS } from '../types';
import type { User, Role } from '../types';
import { formatDateTime } from '../utils/format';

const { Title } = Typography;

const UserManagement: React.FC = () => {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [scopeModalOpen, setScopeModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form] = Form.useForm();
  const [scopeForm] = Form.useForm();

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const list = await authApi.getUsers();
      setUsers(list);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleAdd = () => {
    setEditingUser(null);
    form.resetFields();
    form.setFieldsValue({ role: 'operator' });
    setModalOpen(true);
  };

  const handleEdit = (user: User) => {
    setEditingUser(user);
    form.setFieldsValue({ role: user.role });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingUser) {
        // 更新角色
        await authApi.updateUserRole(editingUser.id, values.role as Role);
        message.success('角色已更新');
      } else {
        // 创建用户
        await authApi.register({
          username: values.username,
          password: values.password,
          display_name: values.display_name,
          role: values.role as Role,
        });
        message.success('用户已创建');
      }
      setModalOpen(false);
      fetchUsers();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '操作失败');
    }
  };

  const handleScopeEdit = (user: User) => {
    setEditingUser(user);
    scopeForm.setFieldsValue({ data_scope: user.data_scope || 'own' });
    setScopeModalOpen(true);
  };

  const handleScopeSubmit = async () => {
    try {
      const values = await scopeForm.validateFields();
      if (!editingUser) return;
      await authApi.updateUserDataScope(editingUser.id, values.data_scope as string);
      message.success('数据范围已更新');
      setScopeModalOpen(false);
      fetchUsers();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '操作失败');
    }
  };

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username', width: 150 },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name', width: 120, render: (v: string | null) => v || '-' },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 120,
      render: (role: string) => {
        const opt = ROLE_OPTIONS.find((r) => r.value === role);
        const color = role === 'admin' ? 'red' : role === 'operator' ? 'blue' : role === 'publisher' ? 'green' : 'orange';
        return <Tag color={color}>{opt?.label || role}</Tag>;
      },
    },
    {
      title: '数据范围',
      dataIndex: 'data_scope',
      key: 'data_scope',
      width: 130,
      render: (scope: string, record: User) => {
        const effective = scope || (record.role === 'operator' ? 'own' : 'all');
        return effective === 'all'
          ? <Tag color="geekblue">全部素材</Tag>
          : <Tag>仅自己创建</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      render: (active: boolean) => active ? <Tag color="green">启用</Tag> : <Tag color="red">禁用</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: User) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>修改角色</Button>
          <Tooltip title="授予/收回该用户查看全部素材的权限">
            <Button size="small" icon={<SafetyOutlined />} onClick={() => handleScopeEdit(record)}>权限编辑</Button>
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1000 }}>
      <Space style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>用户管理</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchUsers}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新增用户</Button>
      </Space>
      <Card size="small">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={users}
          loading={loading}
          pagination={false}
          size="small"
          scroll={{ x: 900 }}
        />
      </Card>
      <Modal
        title={editingUser ? '权限编辑：数据可见范围' : '权限编辑'}
        open={scopeModalOpen}
        onOk={handleScopeSubmit}
        onCancel={() => setScopeModalOpen(false)}
        destroyOnClose
        width={460}
      >
        <Form form={scopeForm} layout="vertical">
          <Form.Item label="用户">
            <Input value={editingUser?.username} disabled />
          </Form.Item>
          <Form.Item name="data_scope" label="数据可见范围" rules={[{ required: true, message: '请选择数据范围' }]}>
            <Select options={DATA_SCOPE_OPTIONS.map((r) => ({ value: r.value, label: r.label }))} />
          </Form.Item>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            说明：管理员、素材专员、发布专员默认可见全部素材；运营专员默认仅可见自己创建的素材，
            可通过此处授予「全部素材」权限。
          </Typography.Text>
        </Form>
      </Modal>

      <Modal
        title={editingUser ? '修改用户角色' : '新增用户'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
        width={480}
      >
        <Form form={form} layout="vertical">
          {!editingUser && (
            <>
              <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }, { min: 2, message: '用户名至少2个字符' }]}>
                <Input placeholder="请输入用户名" />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '密码至少6个字符' }]}>
                <Input.Password placeholder="请输入密码" />
              </Form.Item>
              <Form.Item name="display_name" label="显示名称">
                <Input placeholder="可选，留空则默认使用用户名" />
              </Form.Item>
            </>
          )}
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={ROLE_OPTIONS.map((r) => ({ value: r.value, label: r.label }))} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default UserManagement;