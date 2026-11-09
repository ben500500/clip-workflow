import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Button, Card, Collapse, Col, Input, Row, Select, Space, Table, Tag, Tooltip, Typography, Upload, message,
} from 'antd';
import { CloudUploadOutlined, InboxOutlined, LinkOutlined, QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { DEFAULT_TIER, DURATION_TIERS, assetApi } from '../../api/assets';
import type { AssetBatch, AssetImportBatchResponse, AssetImportDuplicate, AssetUploadResponse } from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { MonoText, yuan } from './AssetBits';
import { CategorySelect, useAssetCategories } from './AssetCategoryBits';
import { nudgeAssetJobBanner } from './AssetJobBanner';

const { Text } = Typography;
const { TextArea } = Input;

interface Props {
  canProduce: boolean;
  /** 点了批次行就把素材列表按这个批次筛 */
  onSelectBatch?: (batchId: string) => void;
  /** A′ UX：页签切回来自动刷新 */
  active?: boolean;
}

/**
 * 导入面板：链接批量导入 / 视频与图片文件批量上传 / 批次台账。
 *
 * 三个必须在前端讲清楚的口径：
 *  - 导入本身**不扣费**：链接形态只是把地址登记进库，真正花钱的是下一步反推。
 *    所以这里的 budget 是「这批若全按 tier 档反推要多少钱」的预警，不是账单。
 *  - 跨批次重复**默认不入库**，只回「几月几日 谁 导入（AS-XXXX）」；
 *    放行有整批（force_duplicates）和逐条（force_urls）两种粒度，默认用逐条。
 *  - 超单批上限由服务端**自动拆批**（批次名带「第 i/k 批」），不是打回让人自己数。
 *  - 「整批默认原型」（11-04 拍板①）只是给这一批每条素材起个结构层标记，
 *    可不选、不拦任何后续动作；建好之后逐条改在素材列表那一列上点。
 *  - 批 G：文件口同时收图片。图片进来是 `media_kind=image` 的**角色卡**，
 *    四环（反推文案/出文案/投产/拼接）对它都不成立，也不计费——所以它的「下一步」
 *    不是在本面板提交，而是到投产弹窗里被挑走。
 */
const AssetImportPanel: React.FC<Props> = ({ canProduce, onSelectBatch, active = true }) => {
  const [tab, setTab] = useState<'link' | 'file'>('link');

  // ── 链接导入 ──
  const [links, setLinks] = useState('');
  // 直接贴文案导入
  const [copyText, setCopyText] = useState('');
  const [copyBatchName, setCopyBatchName] = useState('');
  const [copyBusy, setCopyBusy] = useState(false);
  // P1（评审定稿⑪）：导入前重复预检（0 元、不建行）——粘贴完就地知道哪些已入库
  const [duplicates, setDuplicates] = useState<Map<string, { code?: string; imported_at?: string | null }>>(new Map());
  useEffect(() => {
    const urls = links.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
    if (!urls.length) {
      setDuplicates(new Map());
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await assetApi.importPreflight(urls);
        const map = new Map<string, { code?: string; imported_at?: string | null }>();
        (res.items || []).forEach((d) => d.source_url_norm && map.set(d.source_url_norm, d));
        setDuplicates(map);
      } catch {
        /* 预检失败静默（提交时后端硬拦还在） */
      }
    }, 600);
    return () => clearTimeout(t);
  }, [links]);
  const [batchName, setBatchName] = useState('');
  const [tier, setTier] = useState<number>(DEFAULT_TIER);
  /** 整批默认钩子原型：链接导入和文件上传共用这一个选择（不选＝整批未分类） */
  const [category, setCategory] = useState<string | undefined>();
  const cats = useAssetCategories();
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

  // 直接贴文案提交：按空行分段，一段=一条候选
  const submitCopyImport = async () => {
    const texts = copyText
      .split(/\n{2,}/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!texts.length) {
      message.warning('没有可导入的文案（按空行分隔，一条一段）');
      return;
    }
    setCopyBusy(true);
    try {
      const res = await assetApi.importCopySummaries(copyBatchName, texts);
      message.success(res.message, 6);
      if (res.skipped.length) {
        message.warning(`${res.skipped.length} 条形态不合格被跳过（超字数等），明细看控制台`, 8);
        console.warn('贴文案导入被跳过的条目', res.skipped);
      }
      setCopyText('');
      setCopyBatchName('');
      fetchBatches();
      onSelectBatch?.(res.batch_id);
    } catch (e) {
      message.error((e as Error).message || '贴文案导入失败');
    } finally {
      setCopyBusy(false);
    }
  };

  // 上传文件即导入：txt/csv 读文本 → 按空行分段（无空行则按行分段）→ 直接调导入接口
  const importCopyFromFile = async (file: File) => {
    try {
      const text = await file.text();
      // 优先空行分段（多段式）；整段没有空行时退化为按行分段（一列一条）
      let segs = text.split(/\n{2,}/).map((s) => s.trim()).filter(Boolean);
      if (segs.length <= 1) {
        segs = text.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
      }
      if (!segs.length) {
        message.warning(`文件 ${file.name} 里没有可导入的文案`);
        return false;
      }
      setCopyBusy(true);
      const res = await assetApi.importCopySummaries(
        copyBatchName || `文件导入-${file.name}`,
        segs,
      );
      message.success(res.message, 6);
      if (res.skipped.length) {
        message.warning(`${res.skipped.length} 条形态不合格被跳过（超字数等）`, 8);
        console.warn('文件导入被跳过的条目', res.skipped);
      }
      setCopyText('');
      setCopyBatchName('');
      fetchBatches();
      onSelectBatch?.(res.batch_id);
    } catch (e) {
      message.error((e as Error).message || `文件 ${file.name} 导入失败`);
    } finally {
      setCopyBusy(false);
    }
    return false; // 阻止 antd 默认上传
  };

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

  // A′ UX：切走再切回页签时自动刷新批次台账
  const wasActive = React.useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) fetchBatches();
    wasActive.current = active;
  }, [active, fetchBatches]);

  const parsedLinks = links
    .split(/[\r\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const submitLinks = async (forceUrls?: string[]) => {
    if (!parsedLinks.length) {
      message.warning('粘贴至少一条分享链接');
      return;
    }
    // R-2（11-04 第二轮审核）：连点两次＝同一批链接发两个请求，库里没有唯一约束，
    // 于是同一条视频建出两行素材、反推**按行计费＝同一部片子付两遍钱**（实测 0.0972 元/条）。
    // 上一份请求没回来之前不再接受第二次提交。
    if (importing) return;
    setImporting(true);
    try {
      const res = await assetApi.importBatch({
        links: parsedLinks,
        name: batchName || undefined,
        prompt_max_duration: tier,
        force_urls: forceUrls,
        category_id: category || null,
      });
      setLastImport(res);
      message.success(res.message);
      fetchBatches();
      // 11-06 用户拍板：导入即自动下载原片——下载是后台任务，nudge 让任务条立刻亮出来
      if ((res.items || []).length) nudgeAssetJobBanner();
      // 原来只在「没有重复且不是放行请求」时清空输入框，于是**这一次真建出来的那几条还留在框里**：
      // 下次再点（或点某条的放行）它们就全被判成跨批次重复，一线看到的是"怎么全是重复"。
      // 改成按返回的 items 精确摘掉已入库的那几行，只留下这次没建成的（重复/被跳过）继续在框里等处理。
      const done = new Set((res.items || []).map((it) => (it.source_url || '').trim()));
      if (done.size) {
        const rest = parsedLinks.filter((u) => !done.has(u));
        setLinks(rest.join('\n'));
      } else if (!res.duplicates?.length && !forceUrls) {
        setLinks('');
      }
    } catch (e) {
      message.error((e as Error).message || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  /**
   * 逐条放行：**只**放行点名的这一条。
   *
   * R-2（11-04 第二轮审核）原来这里把「点名的这条 + 上一次回显里其余全部重复」一起塞进
   * `force_urls`，注释还写着「别拿整批陪跑」——实现正好相反，等于**整批放行**：
   * 一线只想放一条，结果另外几条重复素材一起入库、反推按行扣钱。
   * 放行成功后这条会从重复清单里消失（新响应的 duplicates 不再含它），
   * 所以不存在"再点一次把同一部片子二次入库"的路径。
   */
  const forceOne = (dup: AssetImportDuplicate) => submitLinks([dup.source_url]);

  const submitFiles = async () => {
    if (!rawFiles.current.length) {
      message.warning('选择要上传的视频或图片文件');
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
          category_id: category,
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
      message.warning('失败的文件已不在本次选择里，请重新选中这几个原文件再补传');
      return;
    }
    setUploading(true);
    try {
      const res = await assetApi.retryUpload({ batch_id: lastUpload.batch_id, files: again });
      setLastUpload(res);
      message.success(res.message);
      fetchBatches();
    } catch (e) {
      message.error((e as Error).message || '补传失败');
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
    // 批 N（评审二·P2）：给名称定宽＋ellipsis——原来不定宽，被其它列挤压后整列只剩两三个字
    { title: '名称', dataIndex: 'name', width: 150, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '来路',
      dataIndex: 'source_kind',
      width: 70,
      render: (v: string) => <Tag>{v === 'link' ? '链接' : '文件'}</Tag>,
    },
    { title: '条数', dataIndex: 'item_count', width: 66 },
    {
      // 批 N（评审二·P2）：width 70 装不下四个字的表头（折行成两行）
      title: '时长上限',
      dataIndex: 'prompt_max_duration',
      width: 88,
      render: (v: number | null) => (v ? `${v}s` : '未定'),
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

  // 用户口径 2026-09：批次账目不再占大块空间——钱的明细收进行展开，看哪行点哪行
  const batchExpand = (row: AssetBatch) => (
    <div style={{ padding: '4px 12px', fontSize: 12 }}>
      <Space size={16} wrap>
        <span>
          预估 <b>{yuan(row.cost_estimate)}</b>
        </span>
        <span>
          实扣 <b>{yuan(row.cost_actual)}</b>
          {row.cost_actual != null && row.cost_estimate != null && row.cost_actual > row.cost_estimate && (
            <Tag color="warning" style={{ marginLeft: 4 }}>
              超预估
            </Tag>
          )}
          <Tooltip title="实扣是按（反推文案 + 查时长）重新汇总的，不是逐条累加；反推文案记的是按时长上限推算的额度，对账用，别当精确值">
            <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
          </Tooltip>
        </span>
        <span>预算上限 {row.budget_cap != null ? yuan(row.budget_cap) : '全局默认'}</span>
        <span>
          预算检查{' '}
          {row.budget_gate ? (
            <Tag color={row.budget_gate === 'blocked' ? 'red' : row.budget_gate === 'need_approval' ? 'orange' : 'green'}>
              {row.budget_gate === 'blocked' ? '已拦下' : row.budget_gate === 'need_approval' ? '要审批' : '正常'}
            </Tag>
          ) : (
            '-'
          )}
        </span>
        <span>档位 {row.prompt_max_duration ? `${row.prompt_max_duration}s` : '未定'}</span>
      </Space>
      {row.budget_note && (
        <div style={{ color: '#888', marginTop: 4 }}>预算说明：{row.budget_note}</div>
      )}
    </div>
  );

  if (!canProduce) {
    return (
      <Card size="small">
        <Alert
          type="info"
          showIcon
          message="当前角色不能导入"
          description="导入/上传是生产动作，只有素材专员、运营与管理员可以做；浏览不受影响，素材列表照常可看。"
        />
        <Table<AssetBatch>
          rowKey="id"
          size="small"
          style={{ marginTop: 16 }}
          loading={batchLoading}
          columns={batchCols}
          dataSource={batches}
          expandable={{ expandedRowRender: batchExpand, rowExpandable: () => true }}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 批` }}
        />
      </Card>
    );
  }

  return (
    <>
    <Row gutter={12}>
      {/* P1 新增：直接贴文案——跳过链接/反推，直挂候选进审核队列 */}
      <Col span={24} style={{ marginBottom: 12 }}>
        <Collapse
          size="small"
          items={[{
            key: 'paste-copy',
            label: <Text strong style={{ fontSize: 12 }}>直接贴文案（跳过链接/反推，直进审核队列）</Text>,
            children: (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已有外部生成好的钩子文案？按空行分段粘贴（一段=一条候选），提交后直进审核队列——后面质检、投产、投板照走。
                </Text>
                <Input
                  placeholder="批次名（可选，留空自动命名）"
                  value={copyBatchName}
                  onChange={(e) => setCopyBatchName(e.target.value)}
                  style={{ width: 260 }}
                  size="small"
                />
                <Input.TextArea
                  rows={6}
                  placeholder={'一条文案一段（空行分隔），例：\n\n她替姐姐嫁的第二天，新郎出现在她姐的婚礼上\n\n总裁摘下手表坐在塑料凳上吃泡面，秘书问他为什么'}
                  value={copyText}
                  onChange={(e) => setCopyText(e.target.value)}
                />
                <Space size={8} wrap>
                  <Button
                    type="primary"
                    size="small"
                    loading={copyBusy}
                    disabled={!copyText.trim()}
                    onClick={submitCopyImport}
                  >
                    导入进审核队列
                  </Button>
                  <Upload
                    accept=".txt,.csv,.text"
                    showUploadList={false}
                    beforeUpload={importCopyFromFile}
                    disabled={copyBusy}
                  >
                    <Button size="small" icon={<InboxOutlined />} loading={copyBusy} disabled={copyBusy}>
                      上传文件导入（.txt/.csv，空行或换行分条）
                    </Button>
                  </Upload>
                </Space>
              </Space>
            ),
          }]}
        />
      </Col>
      <Col span={24}>
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

            <Space wrap align="center">
              <Text>整批默认原型</Text>
              <Tooltip title="给这一批每条素材起个开头套路的标记（A–G，照《钩子模版换皮参数设定.docx》）；不选照样导入和反推，之后在素材列表「原型」那列逐条改">
                <Text type="secondary" style={{ fontSize: 12 }}>可不选，鼠标放这看说明</Text>
              </Tooltip>
              <CategorySelect
                items={cats.activeItems}
                value={category}
                onChange={setCategory}
                width={250}
                loading={cats.loading}
                placeholder="可不选（这批全标未分类）"
              />
            </Space>

            {tab === 'link' ? (
              <>
                <TextArea
                  rows={10}
                  value={links}
                  onChange={(e) => setLinks(e.target.value)}
                  placeholder={'一行一条分享链接（可以整段粘含中文的分享文案，后端自己提 http token）\n例如：https://v.douyin.com/xxxx/ 这剧太上头了'}
                />
            {duplicates.size > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 6 }}
                message={`${duplicates.size} 条已导入过（提交会被拦，逐条放行或删除）——${[...duplicates.values()].slice(0, 3).map((d) => d.code).join('、')}${duplicates.size > 3 ? '…' : ''}`}
              />
            )}
                <Space>
                  <Button type="primary" loading={importing} onClick={() => submitLinks()}>
                    导入 {parsedLinks.length} 条链接
                  </Button>
                  <Tooltip title="导入后系统自动下载原片（解析 0.01 元/条照记账，进批次成本）；不想要这批的片就别导入。进度看页面顶上的任务条">
                    <Text type="secondary" style={{ fontSize: 12 }}>导入后自动下载原片</Text>
                  </Tooltip>
                </Space>
              </>
            ) : (
              <>
                <Upload.Dragger
                  multiple
                  /**
                   * 批 G：这里同时收视频和图片。图片（jpg/jpeg/png/webp）落库后
                   * `media_kind=image`，**只作投产的角色卡**——不反推、不出文案、不拼接、不抽帧、不计费。
                   * ⚠️ 只改这一个 accept，不改采集侧那两个全局视频白名单
                   * （`prompt_service.UPLOAD_ALLOWED_EXTS` / `settings.ALLOWED_VIDEO_EXTENSIONS`）：
                   * 那两处一放图片，就能把 jpg 喂进 doc/120 视频反推，白扣一次钱。
                   */
                  accept="video/*,.jpg,.jpeg,.png,.webp"
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
                  <p className="ant-upload-text">拖入或选择视频／图片文件（可多个）</p>
                  <p className="ant-upload-hint" style={{ fontSize: 12 }}>
                    视频直接落到我们自己的存储；单文件失败不影响整批，可一键补传。
                    图片是<b>投产用的角色卡</b>（不反推、不计费），长边超了只提醒不拦。
                  </p>
                </Upload.Dragger>
                <Space>
                  <Button type="primary" loading={uploading} onClick={submitFiles}>
                    上传 {rawFiles.current.length} 个文件
                  </Button>
                  {uploading && <Progressish percent={progress} />}
                  <Tooltip title="反推文案时文件还要经中转再上传一次，所以文件批次的预估里含每次 0.001 元的上传费（图片不进反推，不收这笔）">
                    <Text type="secondary" style={{ fontSize: 12 }}>文件批次预估含 0.001 元/条中转上传费</Text>
                  </Tooltip>
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
                        {lastImport.budget.note || `这批全按 ${lastImport.budget.tier}s 上限反推文案预估要 ${yuan(lastImport.budget.cost_estimate)}，超了单批上限 ${yuan(lastImport.budget.cap)}`}
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
                        // 上一份放行请求没回来前掐住按钮：连点两次＝同一部片子建两行素材（R-2）
                        <Button size="small" loading={importing} disabled={importing} onClick={() => forceOne(r)}>
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
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {!!lastUpload.failed?.length && (
                      <>
                        {lastUpload.failed.slice(0, 8).map((f) => (
                          <Text key={f.file_name} style={{ fontSize: 12 }}>
                            {f.file_name}：{f.error}
                          </Text>
                        ))}
                        <Button size="small" icon={<ReloadOutlined />} onClick={retryFailed} loading={uploading}>
                          一键补传这 {lastUpload.failed_files.length} 个（放回同一批次）
                        </Button>
                      </>
                    )}
                    {/* 批 G：图片尺寸/画幅超限**不拒收**，但必须逐张看见——
                        角色卡的宽高比决定成片是竖屏还是横屏，看不见这条就会投出一批横屏片 */}
                    {!!lastUpload.image_notes?.length && (
                      <div>
                        <Text type="warning" style={{ fontSize: 12 }}>
                          {lastUpload.image_notes.length} 张图入库时量出要留意的尺寸/画幅：
                        </Text>
                        {lastUpload.image_notes.slice(0, 8).map((note, i) => (
                          <div key={`${note.file_name}-${i}`} style={{ fontSize: 12, color: '#8c8c8c' }}>
                            {note.file_name || '未命名'}
                            {note.resolution ? `（${note.resolution}${note.ratio ? ` · ${note.ratio}` : ''}）` : ''}
                            ：{note.notes.join('；')}
                          </div>
                        ))}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          照样收下了，不改也能用；想竖屏就换竖版卡重传一张。
                        </Text>
                      </div>
                    )}
                  </Space>
                }
              />
            )}
          </Space>
        </Card>
      </Col>

    </Row>
    {/* 用户口径 2026-11-09：整个批次台账不占主区——收进下方折叠块（默认收起），
        标题带上概览数字（批次数/素材/实扣合计），要用再点开；行可展开看单批账目 */}
    <Collapse
      size="small"
      style={{ marginTop: 12 }}
      items={[{
        key: 'batch-ledger',
        label: (
          <Space size={8} wrap>
            <Text strong style={{ fontSize: 12 }}>批次台账</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {batches.length} 批 · 素材 {batches.reduce((a, b) => a + (b.item_count || 0), 0)} 条 · 实扣合计{' '}
              {yuan(batches.reduce((a, b) => a + (b.cost_actual || 0), 0))}（点开看每批，行内可展开账目）
            </Text>
          </Space>
        ),
        extra: (
          <Button size="small" icon={<ReloadOutlined />} onClick={(e) => { e.stopPropagation(); fetchBatches(); }}>
            刷新
          </Button>
        ),
        children: (
          <Table<AssetBatch>
            rowKey="id"
            size="small"
            loading={batchLoading}
            columns={batchCols}
            dataSource={batches}
            expandable={{ expandedRowRender: batchExpand, rowExpandable: () => true }}
            pagination={{
              pageSize: 12,
              showTotal: (t) =>
                `共 ${t} 批 · 素材 ${batches.reduce((a, b) => a + (b.item_count || 0), 0)} 条 · 实扣合计 ${yuan(batches.reduce((a, b) => a + (b.cost_actual || 0), 0))}`,
            }}
          />
        ),
      }]}
    />
    </>
  );
};

/** 上传进度条：antd 的 Progress 在这里只是显示，不参与逻辑 */
const Progressish: React.FC<{ percent: number }> = ({ percent }) => (
  <Tag color={percent >= 100 ? 'green' : 'blue'}>上传 {percent}%</Tag>
);

export default AssetImportPanel;
