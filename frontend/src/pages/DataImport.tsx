import React, { useState } from 'react';
import {
  Card,
  Upload,
  Button,
  Typography,
  Space,
  Table,
  Tag,
  message,
  Row,
  Col,
  Select,
  Divider,
  Alert,
  Modal,
  Steps,
  Result,
} from 'antd';
import {
  InboxOutlined,
  UploadOutlined,
  DownloadOutlined,
  FileExcelOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  VideoCameraOutlined,
  AppstoreOutlined,
  BarChartOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { dashboardApi } from '../api/dashboard';

const { Title, Text, Paragraph } = Typography;
const { Dragger } = Upload;

// ========== 类型 ==========

interface ImportRecord {
  id: string;
  type: 'video' | 'mini_program' | 'ad';
  file_name: string;
  account_id: string;
  status: 'success' | 'partial' | 'failed';
  total_rows: number;
  success_rows: number;
  failed_rows: number;
  imported_at: string;
}

// ========== Mock 数据 ==========

const mockAccounts = [
  { value: 'acc1', label: '短剧精选' },
  { value: 'acc2', label: '热播剧场' },
];

const mockImportHistory: ImportRecord[] = [
  {
    id: 'imp1',
    type: 'video',
    file_name: '视频数据_20240315.xlsx',
    account_id: 'acc1',
    status: 'success',
    total_rows: 50,
    success_rows: 50,
    failed_rows: 0,
    imported_at: '2024-03-15T14:30:00Z',
  },
  {
    id: 'imp2',
    type: 'mini_program',
    file_name: '小程序数据_20240315.xlsx',
    account_id: 'acc1',
    status: 'success',
    total_rows: 30,
    success_rows: 30,
    failed_rows: 0,
    imported_at: '2024-03-15T14:25:00Z',
  },
  {
    id: 'imp3',
    type: 'ad',
    file_name: '广告数据_20240314.xlsx',
    account_id: 'acc2',
    status: 'partial',
    total_rows: 40,
    success_rows: 36,
    failed_rows: 4,
    imported_at: '2024-03-14T16:00:00Z',
  },
  {
    id: 'imp4',
    type: 'video',
    file_name: '视频数据_20240313.xlsx',
    account_id: 'acc2',
    status: 'failed',
    total_rows: 45,
    success_rows: 0,
    failed_rows: 45,
    imported_at: '2024-03-13T10:00:00Z',
  },
];

// 预览数据 mock
const mockPreviewData = [
  { row: 1, title: '霸总逆袭 - 第一集', play_count: 258000, finish_rate: '72.0%', like_count: 12500, status: 'valid' },
  { row: 2, title: '甜蜜复仇 - 第二集', play_count: 198000, finish_rate: '68.0%', like_count: 9800, status: 'valid' },
  { row: 3, title: '都市情缘 - 第三集', play_count: 165000, finish_rate: '61.0%', like_count: 7600, status: 'valid' },
  { row: 4, title: '', play_count: null, finish_rate: null, like_count: null, status: 'invalid' },
  { row: 5, title: '豪门恩怨 - 第四集', play_count: 142000, finish_rate: '58.0%', like_count: 6200, status: 'valid' },
];

const typeLabels = { video: '视频数据', mini_program: '小程序数据', ad: '广告数据' };
const typeColors = { video: 'blue', mini_program: 'green', ad: 'orange' };
const statusLabels = { success: '成功', partial: '部分成功', failed: '失败' };
const statusColors = { success: 'green', partial: 'gold', failed: 'red' };

// ========== 组件 ==========

const DataImport: React.FC = () => {
  const [selectedAccount, setSelectedAccount] = useState<string>('acc1');
  const [importHistory] = useState<ImportRecord[]>(mockImportHistory);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [currentUploadType, setCurrentUploadType] = useState<'video' | 'mini_program' | 'ad' | null>(null);
  const [currentFile, setCurrentFile] = useState<string>('');
  const [importStep, setImportStep] = useState(0);

  // 下载模板
  const handleDownloadTemplate = async () => {
    try {
      await dashboardApi.downloadTemplate();
      message.success('模板下载成功');
    } catch {
      message.info('模板下载功能（Mock）- 将下载 Excel 模板文件');
    }
  };

  // 上传前处理
  const handleBeforeUpload = (file: File, type: 'video' | 'mini_program' | 'ad') => {
    setCurrentUploadType(type);
    setCurrentFile(file.name);
    setImportStep(0);
    setPreviewModalOpen(true);
    return false; // 阻止自动上传
  };

  // 确认导入
  const handleConfirmImport = async () => {
    setImportStep(1);
    // 模拟导入过程
    setTimeout(() => {
      setImportStep(2);
      message.success('数据导入成功');
    }, 1500);
  };

  // 导入历史表格列
  const historyColumns: ColumnsType<ImportRecord> = [
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 120,
      render: (type: keyof typeof typeLabels) => (
        <Tag color={typeColors[type]}>{typeLabels[type]}</Tag>
      ),
    },
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      width: 250,
    },
    {
      title: '账号',
      dataIndex: 'account_id',
      key: 'account_id',
      width: 120,
      render: (id: string) => mockAccounts.find((a) => a.value === id)?.label || id,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: keyof typeof statusLabels) => (
        <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
      ),
    },
    {
      title: '总行数',
      dataIndex: 'total_rows',
      key: 'total_rows',
      width: 80,
    },
    {
      title: '成功',
      dataIndex: 'success_rows',
      key: 'success_rows',
      width: 80,
      render: (val: number) => <Text type="success">{val}</Text>,
    },
    {
      title: '失败',
      dataIndex: 'failed_rows',
      key: 'failed_rows',
      width: 80,
      render: (val: number) => (val > 0 ? <Text type="danger">{val}</Text> : <Text>{val}</Text>),
    },
    {
      title: '导入时间',
      dataIndex: 'imported_at',
      key: 'imported_at',
      width: 170,
      render: (date: string) => new Date(date).toLocaleString('zh-CN'),
    },
  ];

  // 预览表格列
  const previewColumns = [
    { title: '行号', dataIndex: 'row', key: 'row', width: 60 },
    { title: '标题', dataIndex: 'title', key: 'title', width: 200, ellipsis: true },
    { title: '播放量', dataIndex: 'play_count', key: 'play_count', width: 100, render: (v: number | null) => v?.toLocaleString() || '-' },
    { title: '完播率', dataIndex: 'finish_rate', key: 'finish_rate', width: 80 },
    { title: '点赞', dataIndex: 'like_count', key: 'like_count', width: 80, render: (v: number | null) => v?.toLocaleString() || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (s: string) => s === 'valid' ? <Tag color="green">有效</Tag> : <Tag color="red">无效</Tag>,
    },
  ];

  // 上传区域配置
  const uploadSections = [
    {
      type: 'video' as const,
      title: '视频数据导入',
      description: '导入视频播放量、互动数据、跳转数据等',
      icon: <VideoCameraOutlined style={{ fontSize: 32, color: '#1677ff' }} />,
      accept: '.xlsx,.xls,.csv',
    },
    {
      type: 'mini_program' as const,
      title: '小程序数据导入',
      description: '导入小程序 UV、新增用户、播放数据等',
      icon: <AppstoreOutlined style={{ fontSize: 32, color: '#52c41a' }} />,
      accept: '.xlsx,.xls,.csv',
    },
    {
      type: 'ad' as const,
      title: '广告数据导入',
      description: '导入广告曝光、点击、eCPM、收入数据等',
      icon: <BarChartOutlined style={{ fontSize: 32, color: '#fa8c16' }} />,
      accept: '.xlsx,.xls,.csv',
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>
        <CloudUploadOutlined style={{ marginRight: 8 }} />
        数据录入
      </Title>

      {/* 账号选择 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Text>导入账号：</Text>
          <Select
            value={selectedAccount}
            onChange={setSelectedAccount}
            options={mockAccounts}
            style={{ width: 160 }}
          />
          <Divider type="vertical" />
          <Button icon={<DownloadOutlined />} onClick={handleDownloadTemplate}>
            下载导入模板
          </Button>
        </Space>
      </Card>

      {/* 三个上传区域 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {uploadSections.map((section) => (
          <Col xs={24} lg={8} key={section.type}>
            <Card>
              <div style={{ textAlign: 'center', marginBottom: 16 }}>
                {section.icon}
                <Title level={5} style={{ marginTop: 8, marginBottom: 4 }}>{section.title}</Title>
                <Text type="secondary">{section.description}</Text>
              </div>
              <Dragger
                accept={section.accept}
                showUploadList={false}
                beforeUpload={(file) => handleBeforeUpload(file, section.type)}
                maxCount={1}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">点击或拖拽文件到此区域</p>
                <p className="ant-upload-hint">支持 .xlsx, .xls, .csv 格式</p>
              </Dragger>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 导入历史 */}
      <Card title="导入历史" size="small">
        <Table
          rowKey="id"
          columns={historyColumns}
          dataSource={importHistory}
          pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 条` }}
          size="small"
        />
      </Card>

      {/* 预览确认弹窗 */}
      <Modal
        title="数据预览与确认"
        open={previewModalOpen}
        onCancel={() => { setPreviewModalOpen(false); setImportStep(0); }}
        width={800}
        footer={
          importStep < 2 ? (
            <Space>
              <Button onClick={() => { setPreviewModalOpen(false); setImportStep(0); }}>取消</Button>
              <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleConfirmImport} disabled={importStep === 1}>
                确认导入
              </Button>
            </Space>
          ) : (
            <Button type="primary" onClick={() => { setPreviewModalOpen(false); setImportStep(0); }}>
              完成
            </Button>
          )
        }
      >
        {importStep < 2 ? (
          <div>
            <Alert
              message={`即将导入: ${currentFile}`}
              description={`导入类型: ${currentUploadType ? typeLabels[currentUploadType] : ''} | 账号: ${mockAccounts.find(a => a.value === selectedAccount)?.label}`}
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            <Steps
              current={importStep}
              size="small"
              style={{ marginBottom: 16 }}
              items={[
                { title: '数据预览' },
                { title: '导入中' },
                { title: '完成' },
              ]}
            />

            <div style={{ marginBottom: 8 }}>
              <Text strong>数据预览（前5行）：</Text>
            </div>
            <Table
              rowKey="row"
              columns={previewColumns}
              dataSource={mockPreviewData}
              pagination={false}
              size="small"
              scroll={{ y: 300 }}
            />

            <div style={{ marginTop: 12 }}>
              <Text type="secondary">
                共 {mockPreviewData.length} 行数据，其中有效 {mockPreviewData.filter(d => d.status === 'valid').length} 行，
                无效 {mockPreviewData.filter(d => d.status === 'invalid').length} 行
              </Text>
            </div>
          </div>
        ) : (
          <Result
            status="success"
            title="导入成功"
            subTitle={`成功导入 ${mockPreviewData.filter(d => d.status === 'valid').length} 条数据`}
            icon={<CheckCircleOutlined />}
          />
        )}
      </Modal>
    </div>
  );
};

export default DataImport;
