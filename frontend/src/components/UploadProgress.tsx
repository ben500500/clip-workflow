import React from 'react';
import { Modal, Progress, Typography, Space, Button, Upload } from 'antd';
import { InboxOutlined, CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons';
import { formatFileSize } from '../utils/format';
import type { UploadFile } from 'antd';

const { Text, Title } = Typography;

interface UploadProgressProps {
  visible: boolean;
  uploading: boolean;
  uploadProgress: number;
  currentFile: File | null;
  uploadStatus: 'idle' | 'uploading' | 'success' | 'error';
  errorMessage?: string;
  uploadedFiles: UploadFile[];
  onCancel: () => void;
  onClose: () => void;
}

const UploadProgress: React.FC<UploadProgressProps> = ({
  visible,
  uploading,
  uploadProgress,
  currentFile,
  uploadStatus,
  errorMessage,
  uploadedFiles,
  onCancel,
  onClose,
}) => {
  const renderContent = () => {
    if (uploadStatus === 'idle') {
      return (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <InboxOutlined style={{ fontSize: 48, color: '#1677ff' }} />
          <Title level={5} style={{ marginTop: 16 }}>
            准备上传
          </Title>
          <Text type="secondary">
            {currentFile?.name} ({formatFileSize(currentFile?.size || 0)})
          </Text>
        </div>
      );
    }

    if (uploadStatus === 'uploading') {
      return (
        <div style={{ padding: '20px 0' }}>
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <div>
              <Text strong>{currentFile?.name}</Text>
              <br />
              <Text type="secondary">
                {formatFileSize(currentFile?.size || 0)}
              </Text>
            </div>
            <Progress
              percent={uploadProgress}
              status="active"
              strokeColor="#1677ff"
              format={(p) => `${p}%`}
            />
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">正在上传，请勿关闭页面...</Text>
            </div>
          </Space>
        </div>
      );
    }

    if (uploadStatus === 'success') {
      return (
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <CheckCircleFilled style={{ fontSize: 48, color: '#52c41a' }} />
          <Title level={5} style={{ marginTop: 16, color: '#52c41a' }}>
            上传成功
          </Title>
          <Text type="secondary">
            {currentFile?.name} 已成功上传
          </Text>
          {uploadedFiles.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">
                已上传 {uploadedFiles.length} 个文件
              </Text>
            </div>
          )}
        </div>
      );
    }

    if (uploadStatus === 'error') {
      return (
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <CloseCircleFilled style={{ fontSize: 48, color: '#ff4d4f' }} />
          <Title level={5} style={{ marginTop: 16, color: '#ff4d4f' }}>
            上传失败
          </Title>
          <Text type="danger">{errorMessage || '上传过程中发生错误，请重试'}</Text>
        </div>
      );
    }

    return null;
  };

  return (
    <Modal
      title="文件上传"
      open={visible}
      footer={
        uploadStatus === 'success' || uploadStatus === 'error'
          ? [
              <Button key="close" type="primary" onClick={onClose}>
                {uploadStatus === 'success' ? '完成' : '关闭'}
              </Button>,
            ]
          : uploading
            ? [
                <Button key="cancel" danger onClick={onCancel}>
                  取消上传
                </Button>,
              ]
            : undefined
      }
      onCancel={uploading ? undefined : onClose}
      closable={!uploading}
      maskClosable={!uploading}
      width={480}
      destroyOnClose
    >
      {renderContent()}
    </Modal>
  );
};

export default UploadProgress;