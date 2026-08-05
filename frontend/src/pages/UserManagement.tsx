import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Form, Input, Select, Popconfirm,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { authApi } from '../api/auth';
import { ROLE_OPTIONS } from '../types';
import type { User, Role } from '../types';
import { formatDateTime } from '../utils/format';

const { Title } = Typography;

const UserManagement: React.FC = () => {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form] = Form.useForm();

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
      width: 120,
      render: (_: unknown, record: User) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>修改角色</Button>
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
        />
      </Card>
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