import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Descriptions, Empty, Input, Modal, Radio, Space, Spin, Table, Tabs, Tag, Typography, Upload, message,
} from 'antd';
import { InboxOutlined, LinkOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { assetApi } from '../../api/assets';
import type { AssetConcatOrder, AssetConcatResult, AssetItem } from '../../api/assets';
import { variantsApi } from '../../api/variants';
import type { SliceOutputListItem } from '../../api/variants';
import { AssetStatusTag, MonoText, durationText } from './AssetBits';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  /** A 段：产物挂在这条素材名下（后端固定用它落 stage_compose） */
  asset: AssetItem | null;
  onClose: () => void;
  /** 拼成功后通知列表/抽屉重取（status 会从 composing 收敛到 ready） */
  onDone?: () => void;
}

/**
 * 简单拼接弹窗（11-04 用户改定口径）。
 *
 * 用户原话：「只需要一个简单的拼贴……可以选择顺序，比如说拼在前或者拼在后之类的」。
 * 所以这里**没有**选点、剪切、智能裁剪、多段混排——只有「第二段拿哪条」+「谁在前」。
 *
 * 三个必须显示在界面上的事实（都是后端实测出来的行为，藏起来一线会当成 bug 报）：
 * 1. **排在最前那段决定输出画幅**（宽高/帧率取自它，后一段 scale+pad 进去）。
 *    所以「把横屏那条放前面」＝出横屏，这不是 bug 是设计——竖屏加黑边比裁头尾好。
 * 2. **本地文件不是临时文件**：后端不留未入库的中间产物（留了没人对账），
 *    所以选本地文件会先建一个批次把文件收进素材库，再拿它的 id 当第二段。
 * 3. **拼接 0 元**：不调智令、不调模型，纯 ffmpeg，所以没有成本确认单、不过预算闸门。
 */
const AssetComposeModal: React.FC<Props> = ({ open, asset, onClose, onDone }) => {
  /** 只取 id 作依赖：抽屉里刷新详情会让 `asset` 换个对象身份，整个弹窗不该因此被重置 */
  const excludeId = asset?.id || null;
  const [sourceTab, setSourceTab] = useState<'asset' | 'slice' | 'local'>('asset');

  // 素材库候选
  const [assetKeyword, setAssetKeyword] = useState('');
  const [assetRows, setAssetRows] = useState<AssetItem[]>([]);
  const [assetLoading, setAssetLoading] = useState(false);
  const [pickedAssetId, setPickedAssetId] = useState<string | null>(null);

  // 切片产物候选
  const [sliceKeyword, setSliceKeyword] = useState('');
  const [sliceRows, setSliceRows] = useState<SliceOutputListItem[]>([]);
  const [sliceLoading, setSliceLoading] = useState(false);
  const [pickedSliceId, setPickedSliceId] = useState<string | null>(null);

  // 本地文件
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  // 真正的 File 对象单独存一份：beforeUpload 返回 false 时 antd 给的 UploadFile 上
  // 并没有 originFileObj（那是 rc-upload 走完上传流程才回填的字段），只把列表项留着
  // 等于留了个名字——点「上传并用作第二段」会以为没选文件（11-04 CDP 验收抓到过）。
  const [localFile, setLocalFile] = useState<File | null>(null);
  const [localUploading, setLocalUploading] = useState(false);
  const [localAsset, setLocalAsset] = useState<AssetItem | null>(null);

  const [order, setOrder] = useState<AssetConcatOrder>('asset_first');
  const [title, setTitle] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssetConcatResult | null>(null);

  const fetchAssets = useCallback(
    async (kw: string) => {
      setAssetLoading(true);
      try {
        const data = await assetApi.listAssets({
          keyword: kw || undefined,
          // 没文件的（链接素材还没回源）拼不了，但别把它藏起来——一线要先知道是这条、要去解析
          page_size: 50,
        });
        setAssetRows((data.items || []).filter((i) => i.id !== excludeId));
      } catch (e) {
        message.error((e as Error).message || '加载素材列表失败');
      } finally {
        setAssetLoading(false);
      }
    },
    [excludeId],
  );

  const fetchSlices = useCallback(async (kw: string) => {
    setSliceLoading(true);
    try {
      const data = await variantsApi.listSliceOutputs({ keyword: kw || undefined, page_size: 100 });
      const flat = (data.groups || [])
        .flatMap((g) => g.episodes || [])
        .flatMap((ep) => ep.outputs || [])
        .filter((o) => !!o.file_key);
      setSliceRows(flat);
    } catch (e) {
      message.error((e as Error).message || '加载切片产物失败');
    } finally {
      setSliceLoading(false);
    }
  }, []);

  // 每次打开重排队列：清掉上一次的选择与结果，防止「显示 A 拼的是 B」
  useEffect(() => {
    if (!open) return;
    setPickedAssetId(null);
    setPickedSliceId(null);
    setLocalFile(null);
    setFileList([]);
    setLocalAsset(null);
    setOrder('asset_first');
    setTitle('');
    setResult(null);
    fetchAssets('');
    fetchSlices('');
  }, [open, asset?.id, fetchAssets, fetchSlices]);

  const second: { id: string; label: string; ready: boolean; hint?: string } = useMemo(() => {
    if (sourceTab === 'asset') {
      const row = assetRows.find((a) => a.id === pickedAssetId) || null;
      const ok = !!row && !!row.file_key;
      return {
        id: row?.id || '',
        label: row ? `${row.code}·${row.title || row.file_name || '未命名'}` : '未选',
        ready: ok,
        hint: row && !row.file_key ? '这条是链接素材，库里没有原片文件（先「查视频时长」把文件取回来，或改用文件素材）' : undefined,
      };
    }
    if (sourceTab === 'slice') {
      const row = sliceRows.find((s) => s.id === pickedSliceId) || null;
      return { id: row?.id || '', label: row?.file_name || '未选', ready: !!row };
    }
    return {
      id: localAsset?.id || '',
      label: localAsset ? `${localAsset.code}·${localAsset.file_name || '本地文件'}` : '未上传',
      ready: !!localAsset && !!localAsset.file_key,
      hint: localAsset ? undefined : '先上传本地文件（会作为一条新素材入库）',
    };
  }, [sourceTab, assetRows, pickedAssetId, sliceRows, pickedSliceId, localAsset]);

  const uploadLocal = async () => {
    if (!localFile) {
      message.warning('先选择本地视频文件');
      return;
    }
    setLocalUploading(true);
    try {
      const res = await assetApi.uploadBatch({ files: [localFile], name: '拼接补段' }, (p) =>
        setFileList((prev) => prev.map((f) => ({ ...f, percent: p, status: 'uploading' as const }))),
      );
      const item = res.items?.[0];
      if (!item) {
        const why = res.failed?.[0]?.error || res.message;
        message.error(`上传失败：${why}`);
        setFileList((prev) => prev.map((f) => ({ ...f, status: 'error' as const })));
        return;
      }
      setLocalAsset(item);
      setFileList((prev) => prev.map((f) => ({ ...f, status: 'done' as const, percent: 100 })));
      message.success(`已入库为 ${item.code}，可直接用作第二段`);
    } catch (e) {
      message.error((e as Error).message || '上传失败');
    } finally {
      setLocalUploading(false);
    }
  };

  const submit = async () => {
    if (!asset) return;
    if (!second.ready) {
      message.warning(second.hint || '先选好第二段');
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const res = await assetApi.concat({
        asset_id: asset.id,
        second_source: sourceTab === 'slice' ? 'slice' : 'asset',
        second_id: second.id,
        order,
        title: title.trim() || undefined,
      });
      setResult(res);
      message.success(`拼好了（${res.resolution || '-'}，${durationText(res.duration)}，${res.elapsed_seconds}s）`);
      onDone?.();
    } catch (e) {
      message.error((e as Error).message || '拼接失败');
    } finally {
      setBusy(false);
    }
  };

  const assetColumns: ColumnsType<AssetItem> = [
    { title: '编号', dataIndex: 'code', width: 110, render: (v: string) => <MonoText>{v}</MonoText> },
    {
      title: '标题/文件',
      dataIndex: 'title',
      ellipsis: true,
      render: (_, row) => (
        <Space size={4}>
          <span>{row.title || row.file_name || '-'}</span>
          {!row.file_key && <Tag color="warning">无原片</Tag>}
        </Space>
      ),
    },
    { title: '时长', dataIndex: 'duration', width: 72, render: (v: number | null) => durationText(v) },
    { title: '画幅', dataIndex: 'resolution', width: 92, render: (v: string | null) => v || '-' },
    { title: '状态', dataIndex: 'status', width: 96, render: (v: any) => <AssetStatusTag status={v} /> },
  ];

  const sliceColumns: ColumnsType<SliceOutputListItem> = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (v: string | null) => v || <Text type="secondary">（无名）</Text>,
    },
    { title: '时长', dataIndex: 'duration', width: 72, render: (v: number | null) => durationText(v) },
    { title: '画幅', dataIndex: 'resolution', width: 92, render: (v: string | null) => v || '-' },
    {
      title: '大小',
      dataIndex: 'file_size',
      width: 90,
      render: (v: number | null) => (v ? `${(v / 1024 / 1024).toFixed(1)} MB` : '-'),
    },
  ];

  return (
    <Modal
      open={open}
      width={880}
      title={asset ? `拼接成片：${asset.code}` : '拼接成片'}
      onCancel={onClose}
      okText={busy ? '正在拼接，请等它跑完' : '开始拼接'}
      okButtonProps={{ loading: busy, disabled: !second.ready }}
      onOk={submit}
      destroyOnClose
    >
      {!asset ? (
        <Empty description="没有选中素材" />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="两段直拼：不选点、不剪切，只决定「第二段拿哪条」和「谁在前」"
            description={
              <span style={{ fontSize: 12 }}>
                排在<b>最前</b>那一段决定输出的画幅和帧率（后一段等比缩放后补边进去，不裁头尾）；
                某一段没有音轨会自动补静音轨，不会整条失败。拼接不调模型、不调智令，<b>0 元</b>，
                也不做预算检查。每拼一次新增一条产物、不覆盖旧的，可以拼几个顺序挑一条用。
              </span>
            }
          />

          <Descriptions size="small" column={2} bordered title="第一段（本条）">
            <Descriptions.Item label="编号">
              <MonoText>{asset.code}</MonoText>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <AssetStatusTag status={asset.status} />
            </Descriptions.Item>
            <Descriptions.Item label="标题" span={2}>
              {asset.title || asset.file_name || <Text type="secondary">（未命名）</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="时长">{durationText(asset.duration)}</Descriptions.Item>
            <Descriptions.Item label="画幅">{asset.resolution || '未知'}</Descriptions.Item>
          </Descriptions>
          {!asset.file_key && (
            <Alert
              type="warning"
              showIcon
              message="这条是链接素材、桶里没有原片文件"
              description={<span style={{ fontSize: 12 }}>先在详情抽屉里「查视频时长」并确认文件已存进我们自己的存储，否则后端会拒。</span>}
            />
          )}

          <div>
            <Text strong>第二段</Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
              当前：{second.label}
              {second.hint && <span style={{ color: '#fa8c16', marginLeft: 8 }}>{second.hint}</span>}
            </Text>
            <Tabs
              size="small"
              activeKey={sourceTab}
              onChange={(k) => setSourceTab(k as typeof sourceTab)}
              items={[
                {
                  key: 'asset',
                  label: '素材库里再选一条',
                  children: (
                    <>
                      <Input
                        allowClear
                        size="small"
                        prefix={<SearchOutlined />}
                        placeholder="搜编号/标题/链接"
                        style={{ width: 220, marginBottom: 8 }}
                        value={assetKeyword}
                        onChange={(e) => setAssetKeyword(e.target.value)}
                        onPressEnter={() => fetchAssets(assetKeyword)}
                      />
                      <Button size="small" style={{ marginLeft: 8 }} onClick={() => fetchAssets(assetKeyword)}>
                        搜索
                      </Button>
                      <Spin spinning={assetLoading}>
                        <Table
                          rowKey="id"
                          size="small"
                          dataSource={assetRows}
                          columns={assetColumns}
                          scroll={{ y: 220, x: 620 }}
                          pagination={false}
                          rowSelection={{
                            type: 'radio',
                            selectedRowKeys: pickedAssetId ? [pickedAssetId] : [],
                            onChange: (keys) => setPickedAssetId((keys[0] as string) || null),
                            getCheckboxProps: (row) => ({ disabled: !row.file_key }),
                          }}
                        />
                      </Spin>
                    </>
                  ),
                },
                {
                  key: 'slice',
                  label: '现网已有的切片产物',
                  children: (
                    <>
                      <Input
                        allowClear
                        size="small"
                        prefix={<SearchOutlined />}
                        placeholder="搜文件名"
                        style={{ width: 220, marginBottom: 8 }}
                        value={sliceKeyword}
                        onChange={(e) => setSliceKeyword(e.target.value)}
                        onPressEnter={() => fetchSlices(sliceKeyword)}
                      />
                      <Button size="small" style={{ marginLeft: 8 }} onClick={() => fetchSlices(sliceKeyword)}>
                        搜索
                      </Button>
                      <Spin spinning={sliceLoading}>
                        <Table
                          rowKey="id"
                          size="small"
                          dataSource={sliceRows}
                          columns={sliceColumns}
                          scroll={{ y: 220, x: 560 }}
                          pagination={false}
                          locale={{ emptyText: '没有切片产物（去重工作台切过的才会出现在这里）' }}
                          rowSelection={{
                            type: 'radio',
                            selectedRowKeys: pickedSliceId ? [pickedSliceId] : [],
                            onChange: (keys) => setPickedSliceId((keys[0] as string) || null),
                          }}
                        />
                      </Spin>
                    </>
                  ),
                },
                {
                  key: 'local',
                  label: '本地文件现场上传',
                  children: (
                    <>
                      <Upload.Dragger
                        maxCount={1}
                        fileList={fileList}
                        accept="video/*"
                        beforeUpload={(file) => {
                          // 返回 false：只进待传列表，真上传由下面按钮触发（与导入面板同一写法）。
                          // status 留空＝「选好了但还没传」，别显示成 done（11-03 验收就栽在把
                          // 「已在列表里」当成「已就绪」）。
                          setLocalFile(file);
                          setFileList([{ uid: file.uid, name: file.name, size: file.size } as UploadFile]);
                          setLocalAsset(null);
                          return false;
                        }}
                        onRemove={() => {
                          setLocalFile(null);
                          setFileList([]);
                          setLocalAsset(null);
                        }}
                      >
                        <p className="ant-upload-drag-icon">
                          <InboxOutlined />
                        </p>
                        <p className="ant-upload-text">把视频拖进来，或点击选择文件</p>
                        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
                          服务端不留「没入库的临时文件」（留了没人对账），所以这里会先把它收进素材库、
                          建一个「拼接补段」批次，再拿这条当第二段。单请求整包上限 2GB（撞线会回 nginx 的 413，界面只说「上传失败」）。
                        </p>
                      </Upload.Dragger>
                      <Space style={{ marginTop: 8 }}>
                        <Button
                          size="small"
                          icon={<LinkOutlined />}
                          loading={localUploading}
                          disabled={!localFile || localUploading}
                          onClick={uploadLocal}
                        >
                          上传并用作第二段
                        </Button>
                        {localAsset && (
                          <Text type="success" style={{ fontSize: 12 }}>
                            已入库：{localAsset.code}（{durationText(localAsset.duration)}）
                          </Text>
                        )}
                      </Space>
                    </>
                  ),
                },
              ]}
            />
          </div>

          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Space wrap>
              <Text strong>顺序</Text>
              <Radio.Group value={order} onChange={(e) => setOrder(e.target.value as AssetConcatOrder)}>
                <Radio value="asset_first">本条在前 · 另一段在后</Radio>
                <Radio value="second_first">另一段在前 · 本条在后</Radio>
              </Radio.Group>
            </Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              换顺序同时换画幅：{order === 'asset_first' ? '按本条' : '按第二段'}的宽高出片
              （本条 {asset.resolution || '未知'}）。
            </Text>
            <Space wrap>
              <Text>产物名前缀</Text>
              <Input
                size="small"
                style={{ width: 260 }}
                maxLength={80}
                placeholder={`默认 ${asset.code}`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </Space>
          </Space>

          {result && (
            <Alert
              type="success"
              showIcon
              message={`产物：${result.file_name || result.file_key || '-'}`}
              description={
                <Space direction="vertical" size={2} style={{ fontSize: 12 }}>
                  <Text>
                    画幅 {result.resolution || '-'}｜时长 {durationText(result.duration)}｜
                    耗时 {result.elapsed_seconds}s｜素材状态 {result.asset_status}
                  </Text>
                  <Text type="secondary">{(result.segments || []).join('  +  ')}</Text>
                  <Paragraph style={{ marginBottom: 0, fontSize: 12 }}>
                    <MonoText>{result.file_key}</MonoText>
                  </Paragraph>
                  <Text type="secondary">在详情抽屉的「拼接产物」页签里可下载；再拼一次会新增一条、不覆盖。</Text>
                </Space>
              }
            />
          )}
        </Space>
      )}
    </Modal>
  );
};

export default AssetComposeModal;
