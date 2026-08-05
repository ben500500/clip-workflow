import React, { useState } from 'react';
import {
  Card, Upload, Button, Typography, message, Space, Row, Col, Alert, Input,
} from 'antd';
import { InboxOutlined, DownloadOutlined } from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';

const { Title, Text } = Typography;
const { Dragger } = Upload;

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
            // 延迟释放 URL，避免部分浏览器下载未开始即被撤销
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

const DataImport: React.FC = () => {
  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>数据录入</Title>
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
  );
};

export default DataImport;
