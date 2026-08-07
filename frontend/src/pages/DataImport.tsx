import React, { useState } from 'react';
import {
  Card, Upload, Button, Typography, message, Space, Row, Col, Alert, Input, Tabs, Table, Tag, Modal, Select,
} from 'antd';
import { InboxOutlined, DownloadOutlined, ThunderboltOutlined, ToolOutlined, FileTextOutlined, HistoryOutlined } from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';
import type { PlatformDetectResult, ImportHistoryRecord } from '../types';
import { formatDate } from '../utils/format';

const { Title, Text } = Typography;
const { Dragger } = Upload;

// ========== 智能导入面板 ==========

const SmartImportPanel: React.FC = () => {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PlatformDetectResult | null>(null);
  const [fileBytes, setFileBytes] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [targetTable, setTargetTable] = useState<string>('video_metrics');

  const handleUpload = async (file: File) => {
    setBusy(true);
    setFileBytes(file);
    try {
      const res = await dashboardApi.smartImportUpload(file);
      setResult(res);
      if (res.detected) {
        setMapping(res.suggested_mapping as Record<string, string>);
        setTargetTable(res.target_table || 'video_metrics');
        message.success(`检测到平台: ${res.platform?.name}`);
      } else {
        setMapping({});
        message.info('未识别到已知平台格式，请手动映射');
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '上传失败');
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async () => {
    if (!fileBytes) return;
    setBusy(true);
    try {
      const res = await dashboardApi.importConfirm(fileBytes, mapping, targetTable);
      if (res.success) {
        message.success(`导入成功，共 ${res.imported_count} 条`);
        setResult(null);
        setFileBytes(null);
      } else {
        message.error(`导入失败：${res.errors.join('; ')}`);
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '导入失败');
    } finally {
      setBusy(false);
    }
  };

  const systemFields = [
    { value: '', label: '（不导入）' },
    { value: 'play_count', label: '播放量' },
    { value: 'finish_rate', label: '完播率' },
    { value: 'like_count', label: '点赞' },
    { value: 'comment_count', label: '评论' },
    { value: 'share_count', label: '转发' },
    { value: 'favorite_count', label: '收藏' },
    { value: 'jump_click_count', label: '跳转点击' },
    { value: 'attributed_uv', label: '归因UV' },
    { value: 'attributed_revenue', label: '归因收益' },
    { value: 'uv', label: 'UV' },
    { value: 'impression_count', label: '曝光量' },
    { value: 'click_count', label: '点击量' },
    { value: 'ctr', label: '点击率' },
    { value: 'ecpm', label: 'eCPM' },
    { value: 'revenue', label: '收益' },
    { value: 'date', label: '日期' },
    { value: 'title', label: '标题' },
    { value: 'video_id', label: '视频ID' },
  ];

  return (
    <div>
      <Dragger
        showUploadList={false}
        accept=".xlsx,.xls,.csv"
        disabled={busy}
        beforeUpload={(file) => {
          handleUpload(file as File);
          return false;
        }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件到此处</p>
        <p className="ant-upload-hint">支持 .xlsx / .csv，自动识别视频号/抖音/快手/广告平台格式</p>
      </Dragger>

      {result && (
        <div style={{ marginTop: 16 }}>
          {result.detected ? (
            <Alert
              type="success"
              message={`检测到平台: ${result.platform?.name}`}
              description="已自动匹配字段映射，请确认后导入"
              showIcon
              style={{ marginBottom: 12 }}
            />
          ) : (
            <Alert
              type="warning"
              message="未识别到已知平台格式"
              description="请手动选择字段映射关系"
              showIcon
              style={{ marginBottom: 12 }}
            />
          )}

          <Text strong style={{ display: 'block', marginBottom: 8 }}>文件表头: {result.headers.join('、')}</Text>

          {/* Preview rows */}
          {result.preview.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>预览（前 {result.preview.length} 行）:</Text>
              <Table
                size="small"
                pagination={false}
                dataSource={result.preview.map((r, i) => ({ _key: i, ...r }))}
                rowKey="_key"
                columns={result.headers.map((h) => ({
                  title: h, dataIndex: h, key: h, ellipsis: true, width: 120,
                  render: (v: unknown) => String(v ?? ''),
                }))}
                scroll={{ x: 'max-content' }}
              />
            </div>
          )}

          {/* Manual mapping */}
          <Text strong style={{ display: 'block', marginBottom: 8 }}>字段映射：</Text>
          <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
            {result.headers.map((h) => (
              <Col key={h} span={12}>
                <Space>
                  <Text>{h} →</Text>
                  <Select
                    style={{ width: 160 }}
                    value={Object.entries(mapping).find(([, v]) => v === h)?.[0] || ''}
                    onChange={(val) => {
                      const newMapping = { ...mapping };
                      // Remove old mapping for this value
                      Object.keys(newMapping).forEach((k) => {
                        if (newMapping[k] === h) delete newMapping[k];
                      });
                      if (val) newMapping[val] = h;
                      setMapping(newMapping);
                    }}
                    options={systemFields}
                  />
                </Space>
              </Col>
            ))}
          </Row>

          <Space>
            <Button type="primary" onClick={handleConfirm} loading={busy} icon={<ThunderboltOutlined />}>确认导入</Button>
            <Button onClick={() => { setResult(null); setFileBytes(null); }}>取消</Button>
          </Space>
        </div>
      )}
    </div>
  );
};

// ========== 标准模板导入面板 ==========

interface ImportPanelProps {
  title: string;
  description: string;
  templateType: string;
  onImport: (file: File) => Promise<{ success: boolean; imported_count: number; errors: string[] }>;
}

const ImportPanel: React.FC<ImportPanelProps> = ({ title, description, templateType, onImport }) => {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ success: boolean; imported_count: number; errors: string[] } | null>(null);

  return (
    <Card size="small" title={title}>
      <Text type="secondary">{description}</Text>
      <div style={{ margin: '12px 0' }}>
        <Dragger
          showUploadList={false}
          accept=".xlsx,.xls,.csv"
          disabled={busy}
          beforeUpload={(file) => {
            setBusy(true);
            onImport(file as File)
              .then((r) => {
                setResult(r);
                if (r.success) {
                  message.success(`导入成功，共 ${r.imported_count} 条`);
                } else {
                  message.error(`导入失败：${r.errors.join('; ')}`);
                }
              })
              .catch((err: unknown) => {
                message.error(err instanceof Error ? err.message : '导入失败');
              })
              .finally(() => setBusy(false));
            return false;
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 Excel 文件到此处</p>
          <p className="ant-upload-hint">支持 .xlsx / .csv</p>
        </Dragger>
      </div>
      <Space>
        <Button size="small" icon={<DownloadOutlined />} onClick={async () => {
          try {
            const blob = await dashboardApi.downloadTemplate(templateType);
            const url = URL.createObjectURL(blob as Blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${templateType}_metrics_template.xlsx`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
            }, 1000);
          } catch (err: unknown) {
            message.error(err instanceof Error ? err.message : '下载失败');
          }
        }}>下载模板</Button>
      </Space>
      {result && (
        <Alert
          style={{ marginTop: 12 }}
          type={result.success ? 'success' : 'warning'}
          message={result.success ? `已导入 ${result.imported_count} 条` : '存在错误'}
          description={result.errors.slice(0, 5).join('；') || undefined}
        />
      )}
    </Card>
  );
};

// ========== 导入历史 ==========

const ImportHistoryPanel: React.FC = () => {
  const [data, setData] = useState<ImportHistoryRecord[]>([]);
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    setLoading(true);
    dashboardApi.getImportHistory()
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const columns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true, width: 200 },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 120, render: (v: string) => v || '-' },
    { title: '导入模式', dataIndex: 'import_mode', key: 'import_mode', width: 100, render: (v: string) => <Tag>{v || '-'}</Tag> },
    { title: '目标表', dataIndex: 'target_table', key: 'target_table', width: 130 },
    { title: '导入数', dataIndex: 'imported_count', key: 'imported_count', width: 80 },
    { title: '错误数', dataIndex: 'error_count', key: 'error_count', width: 80, render: (v: number) => v > 0 ? <Tag color="red">{v}</Tag> : v },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDate(d) },
  ];

  return (
    <Table rowKey="id" size="small" columns={columns} dataSource={data} loading={loading} pagination={{ pageSize: 10 }} scroll={{ x: 880 }} />
  );
};

// ========== 主组件 ==========

const DataImport: React.FC = () => {
  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>数据录入</Title>

      <Tabs
        defaultActiveKey="smart"
        items={[
          {
            key: 'smart',
            label: <span><ThunderboltOutlined /> 智能导入</span>,
            children: (
              <Card size="small" title="智能导入（自动识别平台格式）">
                <SmartImportPanel />
              </Card>
            ),
          },
          {
            key: 'template',
            label: <span><FileTextOutlined /> 标准模板导入</span>,
            children: (
              <div>
                <Row gutter={[16, 16]}>
                  <Col xs={24} md={8}>
                    <ImportPanel
                      title="视频数据"
                      description="导入播放、互动、跳转与归因数据"
                      templateType="video"
                      onImport={(f) => dashboardApi.importVideoMetrics(f)}
                    />
                  </Col>
                  <Col xs={24} md={8}>
                    <ImportPanel
                      title="小程序数据"
                      description="导入小程序 UV、播放、完播率"
                      templateType="mini_program"
                      onImport={(f) => dashboardApi.importMiniProgramMetrics(f)}
                    />
                  </Col>
                  <Col xs={24} md={8}>
                    <ImportPanel
                      title="广告数据"
                      description="导入广告曝光、点击、eCPM 与收益"
                      templateType="ad"
                      onImport={(f) => dashboardApi.importAdMetrics(f)}
                    />
                  </Col>
                </Row>
              </div>
            ),
          },
          {
            key: 'history',
            label: <span><HistoryOutlined /> 导入历史</span>,
            children: <ImportHistoryPanel />,
          },
        ]}
      />
    </div>
  );
};

export default DataImport;