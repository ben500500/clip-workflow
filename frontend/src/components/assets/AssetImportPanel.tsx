import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Button, Card, Col, Input, Row, Select, Space, Statistic, Table, Tag, Tooltip, Typography, Upload, message,
} from 'antd';
import { CloudUploadOutlined, InboxOutlined, LinkOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { DEFAULT_TIER, DURATION_TIERS, assetApi } from '../../api/assets';
import type { AssetBatch, AssetImportBatchResponse, AssetImportDuplicate, AssetUploadResponse } from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { MonoText, yuan } from './AssetBits';

const { Text } = Typography;
const { TextArea } = Input;

interface Props {
  canProduce: boolean;
  /** 点了批次行就把素材列表按这个批次筛 */
  onSelectBatch?: (batchId: string) => void;
}

/**
 * 导入面板：链接批量导入 / 视频文件批量上传 / 批次台账。
 *
 * 三个必须在前端讲清楚的口径：
 *  - 导入本身**不扣费**：链接形态只是把地址登记进库，真正花钱的是下一步反推。
 *    所以这里的 budget 是「这批若全按 tier 档反推要多少钱」的预警，不是账单。
 *  - 跨批次重复**默认不入库**，只回「几月几日 谁 导入（AS-XXXX）」；
 *    放行有整批（force_duplicates）和逐条（force_urls）两种粒度，默认用逐条。
 *  - 超单批上限由服务端**自动拆批**（批次名带「第 i/k 批」），不是打回让人自己数。
 */
const AssetImportPanel: React.FC<Props> = ({ canProduce, onSelectBatch }) => {
  const [tab, setTab] = useState<'link' | 'file'>('link');

  // ── 链接导入 ──
  const [links, setLinks] = useState('');
  const [batchName, setBatchName] = useState('');
  const [tier, setTier] = useState<number>(DEFAULT_TIER);
  const [importing, setImporting] = useState(false);
  const [lastImport, setLastImport] = useState<AssetImportBatchResponse | null>(null);

  // ── 文件上传 ──
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const rawFiles = useRef<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [lastUpload, setLastUpload] = useState<AssetUploadResponse | null>(null);

  // ── 批次台账 ──
  const [batches, setBatches] = useState<AssetBatch[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);

  const fetchBatches = useCallback(async () => {
    setBatchLoading(true);
    try {
      const data = await assetApi.listBatches({ limit: 100 });
      setBatches(data.items || []);
    } catch (e) {
      message.error((e as Error).message || '加载批次列表失败');
    } finally {
      setBatchLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  const parsedLinks = links
    .split(/[\r\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const submitLinks = async (forceUrls?: string[]) => {
    if (!parsedLinks.length) {
      message.warning('粘贴至少一条分享链接');
      return;
    }
    setImporting(true);
    try {
      const res = await assetApi.importBatch({
        links: parsedLinks,
        name: batchName || undefined,
        prompt_max_duration: tier,
        force_urls: forceUrls,
      });
      setLastImport(res);
      message.success(res.message);
      fetchBatches();
      if (!res.duplicates?.length && !forceUrls) setLinks('');
    } catch (e) {
      message.error((e as Error).message || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  /** 逐条放行：只放行点名的这几条，别拿整批 force_duplicates 陪跑 */
  const forceOne = (dup: AssetImportDuplicate) => {
    const carried = (lastImport?.duplicates || [])
      .filter((d) => d.source_url !== dup.source_url)
      .map((d) => d.source_url);
    submitLinks([dup.source_url, ...carried]);
  };

  const submitFiles = async () => {
    if (!rawFiles.current.length) {
      message.warning('选择要上传的视频文件');
      return;
    }
    setUploading(true);
    setProgress(0);
    try {
      const res = await assetApi.uploadBatch(
        {
          files: rawFiles.current,
          name: batchName || undefined,
          max_duration: tier,
        },
        setProgress,
      );
      setLastUpload(res);
      message.success(res.message);
      fetchBatches();
      if (!res.failed?.length) {
        setFileList([]);
        rawFiles.current = [];
      }
    } catch (e) {
      message.error((e as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  /** 补投只投失败的那几个，且落回**同一批次**（不新建批次行，对账才认得出） */
  const retryFailed = async () => {
    const names = lastUpload?.failed_files || [];
    if (!lastUpload?.batch_id || !names.length) return;
    const again = rawFiles.current.filter((f) => names.includes(f.name));
    if (!again.length) {
      message.warning('失败的文件已不在本次选择里，请重新选中这几个原文件再补投');
      return;
    }
    setUploading(true);
    try {
      const res = await assetApi.retryUpload({ batch_id: lastUpload.batch_id, files: again });
      setLastUpload(res);
      message.success(res.message);
      fetchBatches();
    } catch (e) {
      message.error((e as Error).message || '补投失败');
    } finally {
      setUploading(false);
    }
  };

  const batchCols: ColumnsType<AssetBatch> = [
    {
      title: '批次',
      dataIndex: 'code',
      width: 130,
      render: (v: string, row) => (
        <a onClick={() => onSelectBatch?.(row.id)}>
          <MonoText>{v}</MonoText>
        </a>
      ),
    },
    { title: '名称', dataIndex: 'name', ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '来路',
      dataIndex: 'source_kind',
      width: 70,
      render: (v: string) => <Tag>{v === 'link' ? '链接' : '文件'}</Tag>,
    },
    { title: '条数', dataIndex: 'item_count', width: 66 },
    {
      title: '档位',
      dataIndex: 'prompt_max_duration',
      width: 70,
      render: (v: number | null) => (v ? `${v}s` : '未定'),
    },
    {
      title: '预估',
      dataIndex: 'cost_estimate',
      width: 90,
      render: (v: number | null) => yuan(v),
    },
    {
      title: '实扣',
      dataIndex: 'cost_actual',
      width: 90,
      render: (v: number | null, row) => (
        <Tooltip title="实扣是 Σ(反推 + 回源解析) 重算，不是逐条累加；反推落库的是按档位推算的额度，对账用，别当精确值">
          <span>{yuan(v)}</span>
          {row.cost_actual != null && row.cost_estimate != null && row.cost_actual > row.cost_estimate && (
            <Tag color="warning" style={{ marginLeft: 4 }}>
              超预估
            </Tag>
          )}
        </Tooltip>
      ),
    },
    {
      title: '预算闸门',
      dataIndex: 'budget_gate',
      width: 110,
      render: (v: string | null, row) => {
        if (!v) return '-';
        const color = v === 'blocked' ? 'red' : v === 'need_approval' ? 'orange' : 'green';
        return (
          <Tooltip title={row.budget_note || undefined}>
            <Tag color={color}>{v}</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '创建',
      dataIndex: 'created_at',
      width: 120,
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {parseServerTime(v)?.format('MM-DD HH:mm') || '-'}
        </Text>
      ),
    },
  ];

  if (!canProduce) {
    return (
      <Card size="small">
        <Alert
          type="info"
          showIcon
          message="当前角色不能导入"
          description="导入/上传属于生产动作，只有素材专员（material）、运营（operator）与管理员可以做；读口不受影响，素材列表照常可看。"
        />
        <Table<AssetBatch>
          rowKey="id"
          size="small"
          style={{ marginTop: 16 }}
          loading={batchLoading}
          columns={batchCols}
          dataSource={batches}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 批` }}
        />
      </Card>
    );
  }

  return (
    <Row gutter={12}>
      <Col span={14}>
        <Card
          size="small"
          title={
            <Space>
              <Button type={tab === 'link' ? 'primary' : 'default'} size="small" icon={<LinkOutlined />} onClick={() => setTab('link')}>
                链接导入
              </Button>
              <Button type={tab === 'file' ? 'primary' : 'default'} size="small" icon={<CloudUploadOutlined />} onClick={() => setTab('file')}>
                文件上传
              </Button>
            </Space>
          }
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space.Compact style={{ width: '100%' }}>
              <Text style={{ lineHeight: '32px', marginRight: 8 }}>批次名</Text>
              <Input
                placeholder={`默认「链接导入 ${tier}s」；超上限拆批会自动加「第 i/k 批」`}
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
              />
              <Select
                style={{ width: 150 }}
                value={tier}
                onChange={setTier}
                options={DURATION_TIERS.map((t) => ({ value: t, label: `${t}s${t === DEFAULT_TIER ? '（默认）' : ''}` }))}
              />
            </Space.Compact>

            {tab === 'link' ? (
              <>
                <TextArea
                  rows={10}
                  value={links}
                  onChange={(e) => setLinks(e.target.value)}
                  placeholder={'一行一条分享链接（可以整段粘含中文的分享文案，后端自己提 http token）\n例如：https://v.douyin.com/xxxx/ 这剧太上头了'}
                />
                <Space>
                  <Button type="primary" loading={importing} onClick={() => submitLinks()}>
                    导入 {parsedLinks.length} 条链接
                  </Button>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    导入不扣费：这一步只是登记地址，档位与成本在「反推」那一步才生效
                  </Text>
                </Space>
              </>
            ) : (
              <>
                <Upload.Dragger
                  multiple
                  accept="video/*"
                  fileList={fileList}
                  beforeUpload={(file) => {
                    rawFiles.current = [...rawFiles.current, file as unknown as File];
                    // status 'done' 只表示「已在待传列表里」：这里没真上传（beforeUpload 返回 false，
                    // 字节要在点「上传」时由 uploadBatch 一次性带走）
                    setFileList((prev) => [
                      ...prev,
                      { uid: `${prev.length}-${file.name}`, name: file.name, size: file.size, status: 'done' },
                    ]);
                    return false;
                  }}
                  onRemove={(file) => {
                    rawFiles.current = rawFiles.current.filter((f) => f.name !== file.name);
                    setFileList((prev) => prev.filter((p) => p.uid !== file.uid));
                  }}
                >
                  <p className="ant-upload-drag-icon">
                    <InboxOutlined />
                  </p>
                  <p className="ant-upload-text">拖入或选择视频文件（可多个）</p>
                  <p className="ant-upload-hint" style={{ fontSize: 12 }}>
                    落自有 MinIO 桶（raw-footage/asset/），不借智令 temp 桶（那个 6 小时自删）。
                    逐文件 fail-soft：单个失败不影响整批，失败的一键补投回同一批次。
                  </p>
                </Upload.Dragger>
                <Space>
                  <Button type="primary" loading={uploading} onClick={submitFiles}>
                    上传 {rawFiles.current.length} 个文件
                  </Button>
                  {uploading && <Progressish percent={progress} />}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    反推时文件还要经 doc/125 中转上传一次，所以文件批次的预估里含 0.001 元/次的上传费
                  </Text>
                </Space>
              </>
            )}

            {lastImport && (
              <Alert
                type={lastImport.duplicates?.length ? 'warning' : 'success'}
                showIcon
                message={lastImport.message}
                description={
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {lastImport.split_into && (
                      <Text style={{ fontSize: 12 }}>{lastImport.split_into.note}</Text>
                    )}
                    {!!lastImport.skipped?.length && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        清洗提示：{lastImport.skipped.slice(0, 6).join('；')}
                      </Text>
                    )}
                    {lastImport.budget?.gate !== 'ok' && (
                      <Text type="warning" style={{ fontSize: 12 }}>
                        {lastImport.budget.note || `这批全按 ${lastImport.budget.tier}s 档反推预估 ${yuan(lastImport.budget.cost_estimate)}，超单批上限 ${yuan(lastImport.budget.cap)}`}
                      </Text>
                    )}
                  </Space>
                }
              />
            )}

            {!!lastImport?.duplicates?.length && (
              <Card size="small" title={`跨批次重复 ${lastImport.duplicates.length} 条（默认没入库）`} style={{ background: '#fffbe6' }}>
                <Table<AssetImportDuplicate>
                  rowKey={(r) => r.source_url}
                  size="small"
                  pagination={false}
                  dataSource={lastImport.duplicates}
                  columns={[
                    {
                      title: '你提交的链接',
                      dataIndex: 'source_url',
                      ellipsis: true,
                      render: (v: string) => <MonoText>{v}</MonoText>,
                    },
                    {
                      title: '已存在的素材',
                      key: 'existing',
                      width: 260,
                      render: (_, r) => (
                        <Space direction="vertical" size={0}>
                          <MonoText>{r.existing.code}</MonoText>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {r.hint || r.existing.hint}
                          </Text>
                        </Space>
                      ),
                    },
                    {
                      title: '',
                      key: 'op',
                      width: 100,
                      render: (_, r) => (
                        <Button size="small" onClick={() => forceOne(r)}>
                          仍要入库
                        </Button>
                      ),
                    },
                  ]}
                />
              </Card>
            )}

            {lastUpload && (
              <Alert
                type={lastUpload.failed?.length ? 'warning' : 'success'}
                showIcon
                message={lastUpload.message}
                description={
                  !!lastUpload.failed?.length && (
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      {lastUpload.failed.slice(0, 8).map((f) => (
                        <Text key={f.file_name} style={{ fontSize: 12 }}>
                          {f.file_name}：{f.error}
                        </Text>
                      ))}
                      <Button size="small" icon={<ReloadOutlined />} onClick={retryFailed} loading={uploading}>
                        一键补投这 {lastUpload.failed_files.length} 个（落回同一批次）
                      </Button>
                    </Space>
                  )
                }
              />
            )}
          </Space>
        </Card>
      </Col>

      <Col span={10}>
        <Card
          size="small"
          title="批次台账（成本对账用）"
          extra={
            <Button size="small" icon={<ReloadOutlined />} onClick={fetchBatches}>
              刷新
            </Button>
          }
        >
          <Row gutter={8} style={{ marginBottom: 12 }}>
            <Col span={8}>
              <Statistic title="批次数" value={batches.length} />
            </Col>
            <Col span={8}>
              <Statistic title="素材条数" value={batches.reduce((a, b) => a + (b.item_count || 0), 0)} />
            </Col>
            <Col span={8}>
              <Statistic
                title="实扣合计"
                value={batches.reduce((a, b) => a + (b.cost_actual || 0), 0)}
                precision={2}
                suffix="元"
              />
            </Col>
          </Row>
          <Table<AssetBatch>
            rowKey="id"
            size="small"
            loading={batchLoading}
            columns={batchCols}
            dataSource={batches}
            scroll={{ x: 760 }}
            pagination={{ pageSize: 12, showTotal: (t) => `共 ${t} 批` }}
          />
        </Card>
      </Col>
    </Row>
  );
};

/** 上传进度条：antd 的 Progress 在这里只是显示，不参与逻辑 */
const Progressish: React.FC<{ percent: number }> = ({ percent }) => (
  <Tag color={percent >= 100 ? 'green' : 'blue'}>上传 {percent}%</Tag>
);

export default AssetImportPanel;
