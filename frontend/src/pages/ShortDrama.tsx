import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Card, Typography, Space, Button, Input, Radio, Tag, Table, Modal,
  Popconfirm, message, Steps, Alert, Empty, Tabs, Select, InputNumber,
  AutoComplete, Upload, Tooltip,
} from 'antd';
import {
  ThunderboltOutlined, CopyOutlined, DeleteOutlined, ReloadOutlined,
  ClearOutlined, VideoCameraOutlined, FileTextOutlined, CheckOutlined,
  UploadOutlined, PlayCircleOutlined, ImportOutlined, InboxOutlined,
  SendOutlined, EditOutlined, SaveOutlined, UndoOutlined,
  RobotOutlined, QrcodeOutlined, StopOutlined, SyncOutlined,
  CloseCircleOutlined, CheckCircleOutlined, ClockCircleOutlined,
} from '@ant-design/icons';
import { shortdramaApi, type ShortdramaPromptRecord, type PromptTemplates, type DoubaoRewriteItem } from '../api/shortdrama';
import Watermark, { type ImportedVideo } from './Watermark';
import PublishMaterialTab from './PublishMaterialTab';
import { formatFileSize } from '../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { Dragger } = Upload;

// 示例文案（可一键填充，便于快速体验）
const EXAMPLE_SCRIPTS: Record<string, string> = {
  被开除当天中十个亿:
    `【第1集】
（画外音旁白）我叫林晚，在盛世集团勤勤恳恳干了八年，却因为不肯替总监背锅，被当场开除。
（对白）总监：林晚，这锅你不背也得背，不然明天别来了！
（对白）林晚：我不背，事实就是你把项目做砸了。
（对白）总监：你被解雇了！保安，送她出去！
（画外音旁白）就在我被赶出公司大门的瞬间，手机突然收到一条银行短信——
（对白）林晚：个、十、百、千、万……十个亿？！这怎么可能！
（画外音旁白）而当年那个把我赶出公司的总监，此刻正站在我面前，脸上写满了错愕。`,
};

// ── 短剧市场调研：题材 / 基调 / 角色 预设备选（均可自由输入） ──
// 参考当前短剧投放市场的热门分类：都市逆袭、战神赘婿、豪门霸总、甜宠、
// 重生复仇、穿越古装、萌宝团宠、悬疑反转、家庭伦理、轻喜搞笑等。
const THEME_OPTIONS = [
  { value: '都市逆袭爽文' },
  { value: '职场逆袭' },
  { value: '战神归来' },
  { value: '赘婿逆袭' },
  { value: '豪门霸总' },
  { value: '重生复仇' },
  { value: '穿越古装' },
  { value: '玄幻修仙' },
  { value: '甜宠' },
  { value: '萌宝团宠' },
  { value: '悬疑反转' },
  { value: '家庭伦理' },
  { value: '轻喜搞笑' },
  { value: '神医圣手' },
  { value: '民国风云' },
];

const TONE_OPTIONS = [
  { value: '先压抑后爽快' },
  { value: '轻松幽默' },
  { value: '紧张悬疑' },
  { value: '甜宠温馨' },
  { value: '热血燃爆' },
  { value: '催泪虐心' },
  { value: '反转不断' },
  { value: '冷峻暗黑' },
  { value: '明快治愈' },
];

// 角色预设：按短剧常见人设组合，供快速挑选后自行补充描述
const CHARACTER_OPTIONS = [
  { value: '女主：女，25岁，职业装，干练倔强；男主：男，28岁，西装，高冷腹黑；反派：女，27岁，时尚套装，心机深沉' },
  { value: '男主：男，30岁，西装，霸道总裁；女主：女，24岁，休闲装，甜美纯真；萌宝：男，5岁，童装，古灵精怪' },
  { value: '男主：男，35岁，军装/便装，沉稳战神；女主：女，26岁，简约着装，温婉坚韧；反派：男，40岁，名牌西装，阴险嚣张' },
  { value: '男主：男，28岁，朴素工装，隐忍逆袭；女主：女，25岁，都市穿搭，知性温柔；岳父：男，55岁，中山装，势利刻薄' },
  { value: '女主：女，22岁，古装，机灵聪慧；男主：男，27岁，古装，冷面深情；反派：女，25岁，华服，嫉妒狠辣' },
];

// 豆包任务状态展示映射
const DOUBAO_STATUS_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  none: { label: '未生成', color: 'default', icon: <RobotOutlined /> },
  pending: { label: '排队中', color: 'blue', icon: <ClockCircleOutlined /> },
  need_login: { label: '等待扫码', color: 'gold', icon: <QrcodeOutlined /> },
  running: { label: '生成中', color: 'processing', icon: <SyncOutlined spin /> },
  awaiting_rewrite: { label: '待确认改写', color: 'volcano', icon: <ClockCircleOutlined /> },
  completed: { label: '已完成', color: 'green', icon: <CheckCircleOutlined /> },
  failed: { label: '失败', color: 'red', icon: <CloseCircleOutlined /> },
  cancelled: { label: '已取消', color: 'default', icon: <StopOutlined /> },
};

const ShortDrama: React.FC = () => {
  // ── 提示词生成表单 ──
  const [text, setText] = useState('');
  const [duration, setDuration] = useState<number>(15);
  const [durationCustom, setDurationCustom] = useState(false);
  const [theme, setTheme] = useState('');
  const [tone, setTone] = useState('');
  const [characters, setCharacters] = useState('');
  const [extra, setExtra] = useState('');
  const [generating, setGenerating] = useState(false);

  // 生成结果（三版本：长提示词 / 短提示词 / AI提示词）
  const [resultPrompt, setResultPrompt] = useState('');       // AI 提示词（Seedance 七段）
  const [resultLong, setResultLong] = useState('');          // 长提示词（固定模板）
  const [resultShort, setResultShort] = useState('');        // 短提示词（固定模板）
  const [resultModel, setResultModel] = useState<string | null>(null);
  const [resultRecordId, setResultRecordId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [activePromptTab, setActivePromptTab] = useState('long');

  // 长 / 短提示词模板（可编辑并持久化）
  const [templates, setTemplates] = useState<PromptTemplates | null>(null);
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [templateDraft, setTemplateDraft] = useState<{ long: string; short: string }>({ long: '', short: '' });
  const [templateSaving, setTemplateSaving] = useState(false);

  // 历史
  const [records, setRecords] = useState<ShortdramaPromptRecord[]>([]);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [previewRecord, setPreviewRecord] = useState<ShortdramaPromptRecord | null>(null);

  // 成片视频快速预览弹窗（历史表格内直接播放）
  const [previewVideo, setPreviewVideo] = useState<{ url: string; title: string } | null>(null);

  // 去水印页签：一键导入的成片视频
  const [activeTab, setActiveTab] = useState('prompt');
  const [watermarkImports, setWatermarkImports] = useState<ImportedVideo[]>([]);
  // 去水印完成 → 发布：待代入的提示词记录 id（任务关联）
  const [pendingPublishPromptId, setPendingPublishPromptId] = useState<string | null>(null);

  // ── 一键豆包生成 ──
  // 当前登录用户默认豆包账户类型（选择后即作为默认值）
  const [doubaoAccountType, setDoubaoAccountType] = useState<'free' | 'pro'>('free');
  const [doubaoLimits, setDoubaoLimits] = useState<{ free_max_seconds: number; pro_max_seconds: number }>({
    free_max_seconds: 10,
    pro_max_seconds: 30,
  });
  // 正在进行豆包生成任务 / 需要轮询状态的记录 id 集合
  const [doubaoActiveIds, setDoubaoActiveIds] = useState<Set<string>>(new Set());
  // 二维码弹窗：等待扫码的记录
  const [qrRecord, setQrRecord] = useState<ShortdramaPromptRecord | null>(null);
  // 改写确认弹窗
  const [rewriteRecord, setRewriteRecord] = useState<ShortdramaPromptRecord | null>(null);
  const [rewriteBusy, setRewriteBusy] = useState(false);
  // 已确认/已忽略的改写稿标识（round-attempt-created_at），避免点「再让豆包改写」后立刻重新弹窗
  const acknowledgedRewriteRef = useRef<string>('');
  // 发起豆包生成中（按钮 loading）
  const [doubaoGeneratingId, setDoubaoGeneratingId] = useState<string | null>(null);

  // ── 加载历史 ──
  const fetchRecords = useCallback(async (silent = false) => {
    if (!silent) setLoadingRecords(true);
    try {
      const list = await shortdramaApi.listPrompts(50);
      setRecords(list);
    } catch (err: unknown) {
      if (!silent) message.error(err instanceof Error ? err.message : '获取生成历史失败');
    } finally {
      if (!silent) setLoadingRecords(false);
    }
  }, []);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  // ── 加载长 / 短提示词模板 ──
  useEffect(() => {
    shortdramaApi
      .getTemplates()
      .then((tpl) => {
        setTemplates(tpl);
      })
      .catch(() => {
        // 模板加载失败不阻断页面（生成时后端会兜底用内置默认模板）
      });
  }, []);

  // ── 加载当前用户默认豆包账户类型 ──
  useEffect(() => {
    shortdramaApi
      .getDoubaoAccountType()
      .then((data) => {
        setDoubaoAccountType(data.account_type);
        setDoubaoLimits(data.limits || { free_max_seconds: 10, pro_max_seconds: 30 });
      })
      .catch(() => {
        // 读取失败不阻断，使用默认 free
      });
  }, []);

  // ── 豆包进行中任务轮询（5s）：更新状态 / 二维码 / 改写确认弹窗 ──
  useEffect(() => {
    if (doubaoActiveIds.size === 0) return;
    const timer = window.setInterval(async () => {
      const ids = Array.from(doubaoActiveIds);
      for (const rid of ids) {
        try {
          const cur = await shortdramaApi.doubaoStatus(rid);
          // 更新历史列表中的记录
          setRecords((prev) => prev.map((r) => (r.id === rid ? { ...r, ...cur } : r)));
          const status = cur.doubao_status || 'none';
          if (status === 'need_login' && cur.doubao_qrcode) {
            setQrRecord((prev) => (prev?.id === rid ? prev : cur));
          } else if (qrRecord?.id === rid && status !== 'need_login') {
            setQrRecord(null);
          }
          if (status === 'awaiting_rewrite') {
            // 仅当出现新的改写稿（与已确认标识不同）时才弹出确认框
            const last = cur.doubao_rewrite_history?.[cur.doubao_rewrite_history.length - 1];
            const mark = last ? `${last.round}-${last.attempt ?? 1}-${last.created_at ?? ''}` : rid;
            if (mark !== acknowledgedRewriteRef.current) {
              setRewriteRecord((prev) => (prev?.id === rid ? prev : cur));
            }
          } else if (rewriteRecord?.id === rid && status !== 'awaiting_rewrite') {
            setRewriteRecord(null);
          }
          if (['completed', 'failed', 'cancelled'].includes(status)) {
            setDoubaoActiveIds((prev) => {
              const next = new Set(prev);
              next.delete(rid);
              return next;
            });
          }
        } catch {
          // 单条轮询失败忽略，下轮重试
        }
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [doubaoActiveIds, qrRecord, rewriteRecord]);

  // ── 生成提示词 ──
  const handleGenerate = async () => {
    if (!text.trim()) {
      message.warning('请先输入短剧文案');
      return;
    }
    setGenerating(true);
    setCopied(false);
    try {
      const res = await shortdramaApi.generate({
        text: text.trim(),
        duration,
        theme: theme.trim() || undefined,
        tone: tone.trim() || undefined,
        characters: characters.trim() || undefined,
        extra_requirements: extra.trim() || undefined,
        save: true,
      });
      setResultPrompt(res.prompt);
      setResultLong(res.versions?.long || '');
      setResultShort(res.versions?.short || '');
      setResultModel(res.model || null);
      setResultRecordId(res.record_id || null);
      setActivePromptTab('long');
      message.success(res.message || '提示词生成成功');
      fetchRecords(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async (textToCopy: string) => {
    // 非 HTTPS 环境（http://IP 访问）navigator.clipboard 不可用，需降级方案
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(textToCopy);
        message.success('已复制到剪贴板');
        return;
      }
      // 降级：textarea + execCommand('copy')，兼容 http://IP 部署环境
      const textarea = document.createElement('textarea');
      textarea.value = textToCopy;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (ok) {
        message.success('已复制到剪贴板');
      } else {
        message.error('复制失败，请手动选择复制');
      }
    } catch {
      message.error('复制失败，请手动选择复制');
    }
  };

  const clearForm = () => {
    setText('');
    setTheme('');
    setTone('');
    setCharacters('');
    setExtra('');
    setResultPrompt('');
    setResultLong('');
    setResultShort('');
    setResultModel(null);
    setResultRecordId(null);
  };

  // ── 长 / 短提示词模板编辑 ──
  const openTemplateEditor = () => {
    setTemplateDraft({
      long: templates?.long || '',
      short: templates?.short || '',
    });
    setTemplateModalOpen(true);
  };

  const handleSaveTemplates = async () => {
    if (!templateDraft.long.trim() && !templateDraft.short.trim()) {
      message.warning('请至少填写一个模板');
      return;
    }
    setTemplateSaving(true);
    try {
      const saved = await shortdramaApi.saveTemplates({
        long: templateDraft.long,
        short: templateDraft.short,
      });
      setTemplates(saved);
      setTemplateModalOpen(false);
      message.success('模板已保存，下次生成将使用新模板');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存模板失败');
    } finally {
      setTemplateSaving(false);
    }
  };

  const resetTemplates = async () => {
    try {
      const saved = await shortdramaApi.saveTemplates({
        long: '',
        short: '',
      });
      setTemplates(saved);
      message.success('已恢复默认模板');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '恢复默认模板失败');
    }
  };

  const deleteRecord = async (recordId: string) => {
    try {
      const res = await shortdramaApi.deletePrompt(recordId);
      message.success(res.message);
      fetchRecords();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // ── 成片视频：上传 / 删除 / 一键导入去水印 ──
  const handleUploadVideo = async (record: ShortdramaPromptRecord, file: File) => {
    try {
      const updated = await shortdramaApi.uploadVideo(record.id, file);
      message.success('视频上传成功，可一键导入去水印');
      // 更新当前行数据
      setRecords((prev) => prev.map((r) => (r.id === record.id ? { ...r, ...updated } : r)));
      if (previewRecord && previewRecord.id === record.id) {
        setPreviewRecord({ ...previewRecord, ...updated });
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '视频上传失败');
    }
  };

  const handleDeleteVideo = async (record: ShortdramaPromptRecord) => {
    try {
      const res = await shortdramaApi.deleteVideo(record.id);
      message.success(res.message);
      const updated = { ...record, video_file_name: null, video_file_key: null, video_bucket: null, video_file_size: null, video_status: null, video_url: null, video_uploaded_at: null };
      setRecords((prev) => prev.map((r) => (r.id === record.id ? updated : r)));
      if (previewRecord && previewRecord.id === record.id) {
        setPreviewRecord(updated);
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '视频删除失败');
    }
  };

  const handleImportToWatermark = async (record: ShortdramaPromptRecord) => {
    try {
      const res = await shortdramaApi.importToWatermark(record.id);
      setWatermarkImports([
        {
          sourceFileKey: res.source_file_key,
          fileName: res.file_name,
          fileSize: res.file_size,
          promptRecordId: record.id,
        },
      ]);
      setActiveTab('watermark');
      message.success(res.message || '已导入去水印流程');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '导入去水印失败');
    }
  };

  // ── 一键豆包生成相关操作 ──

  // 切换豆包账户类型（保存为当前用户默认值）
  const handleDoubaoAccountTypeChange = async (type: 'free' | 'pro') => {
    setDoubaoAccountType(type);
    try {
      await shortdramaApi.setDoubaoAccountType(type);
      message.success(type === 'free' ? '已切换为免费账户（10s 上限）' : '已切换为包月会员（30s 上限）');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存账户类型失败');
    }
  };

  // 发起一键豆包生成
  const handleDoubaoGenerate = async (record: ShortdramaPromptRecord) => {
    const limit = doubaoAccountType === 'pro' ? doubaoLimits.pro_max_seconds : doubaoLimits.free_max_seconds;
    // 提示词时长超过当前账户上限时，提示并按上限生成
    if (record.duration > limit) {
      message.warning(`当前账户（${doubaoAccountType === 'pro' ? '包月会员' : '免费'}）仅支持生成 ${limit}s，将按 ${limit}s 生成`);
    }
    setDoubaoGeneratingId(record.id);
    try {
      const res = await shortdramaApi.doubaoGenerate(record.id, {
        account_type: doubaoAccountType,
        duration: Math.min(record.duration || limit, limit),
      });
      message.success(res.message || '豆包生成任务已启动');
      // 加入轮询
      setDoubaoActiveIds((prev) => {
        const next = new Set(prev);
        next.add(record.id);
        return next;
      });
      setRecords((prev) => prev.map((r) => (r.id === record.id ? { ...r, doubao_status: 'pending' } : r)));
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '豆包生成启动失败');
    } finally {
      setDoubaoGeneratingId(null);
    }
  };

  // 取消豆包生成任务
  const handleDoubaoCancel = async (record: ShortdramaPromptRecord) => {
    try {
      const res = await shortdramaApi.doubaoCancel(record.id);
      message.success(res.message);
      setRecords((prev) => prev.map((r) => (r.id === record.id ? { ...r, doubao_status: 'cancelled', doubao_message: '任务已取消' } : r)));
      setDoubaoActiveIds((prev) => {
        const next = new Set(prev);
        next.delete(record.id);
        return next;
      });
      setQrRecord(null);
      setRewriteRecord(null);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '取消失败');
    }
  };

  // 改写确认：approved / rejected / cancelled
  const handleRewriteDecision = async (decision: 'approved' | 'rejected' | 'cancelled') => {
    if (!rewriteRecord) return;
    setRewriteBusy(true);
    // 记录当前改写稿标识，避免轮询立即重新弹出
    const last = rewriteRecord.doubao_rewrite_history?.[rewriteRecord.doubao_rewrite_history.length - 1];
    if (last) {
      acknowledgedRewriteRef.current = `${last.round}-${last.attempt ?? 1}-${last.created_at ?? ''}`;
    }
    try {
      const res = await shortdramaApi.doubaoConfirmRewrite(rewriteRecord.id, decision);
      if (decision === 'cancelled') {
        message.info('已放弃本次豆包生成');
        setDoubaoActiveIds((prev) => {
          const next = new Set(prev);
          next.delete(rewriteRecord.id);
          return next;
        });
        setRewriteRecord(null);
      } else {
        message.success(decision === 'approved' ? '已确认改写稿，继续生成视频' : '已让豆包继续改写');
        setRewriteRecord(null);
        // 继续轮询直到完成
        setDoubaoActiveIds((prev) => {
          const next = new Set(prev);
          next.add(rewriteRecord.id);
          return next;
        });
      }
      fetchRecords(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setRewriteBusy(false);
    }
  };

  // 判断记录是否有进行中的豆包任务
  const isDoubaoActive = (record: ShortdramaPromptRecord): boolean => {
    const s = record.doubao_status || 'none';
    return ['pending', 'running', 'need_login', 'awaiting_rewrite'].includes(s);
  };

  // ── 时长切换 ──
  const switchDurationMode = (custom: boolean) => {
    setDurationCustom(custom);
    if (custom) {
      // 切到自定义时给一个默认值
      setDuration((prev) => (prev === 10 || prev === 15 ? 20 : prev));
    }
  };

  // ── 历史表格列 ──
  const recordColumns = [
    {
      title: '时长',
      dataIndex: 'duration',
      key: 'duration',
      width: 80,
      render: (d: number) => <Tag color={d === 10 ? 'blue' : d === 15 ? 'purple' : 'orange'}>{d}s</Tag>,
    },
    {
      title: '文案（摘要）',
      dataIndex: 'source_text',
      key: 'source_text',
      ellipsis: true,
      render: (s: string) => (
        <Text style={{ fontSize: 13 }}>{s.length > 80 ? `${s.slice(0, 80)}…` : s}</Text>
      ),
    },
    {
      title: '题材 / 基调',
      key: 'theme_tone',
      width: 150,
      render: (_: unknown, r: ShortdramaPromptRecord) => (
        <Space size={4} wrap>
          {r.theme ? <Tag>{r.theme}</Tag> : null}
          {r.tone ? <Tag color="orange">{r.tone}</Tag> : null}
          {!r.theme && !r.tone ? <Text type="secondary" style={{ fontSize: 12 }}>-</Text> : null}
        </Space>
      ),
    },
    {
      title: '成片视频',
      key: 'video',
      width: 220,
      render: (_: unknown, r: ShortdramaPromptRecord) => {
        if (r.video_status && r.video_file_name) {
          return (
            <Space size={4} wrap>
              <Tag color="green" icon={<VideoCameraOutlined />}>
                {r.video_file_name.length > 16 ? `${r.video_file_name.slice(0, 16)}…` : r.video_file_name}
              </Tag>
              {r.video_file_size ? (
                <Text type="secondary" style={{ fontSize: 12 }}>{formatFileSize(r.video_file_size)}</Text>
              ) : null}
              {r.video_url && (
                <Button
                  size="small"
                  type="link"
                  icon={<PlayCircleOutlined />}
                  style={{ padding: 0, height: 'auto' }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setPreviewVideo({ url: r.video_url!, title: r.video_file_name! });
                  }}
                >
                  预览
                </Button>
              )}
            </Space>
          );
        }
        return <Text type="secondary" style={{ fontSize: 12 }}>未上传</Text>;
      },
    },
    {
      title: '豆包任务',
      key: 'doubao',
      width: 170,
      render: (_: unknown, r: ShortdramaPromptRecord) => {
        const s = r.doubao_status || 'none';
        const meta = DOUBAO_STATUS_META[s] || DOUBAO_STATUS_META.none;
        const active = isDoubaoActive(r);
        return (
          <Space size={4} wrap>
            <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
            {r.doubao_account_type ? (
              <Tag color={r.doubao_account_type === 'pro' ? 'purple' : 'default'} style={{ fontSize: 11 }}>
                {r.doubao_account_type === 'pro' ? '包月' : '免费'}
              </Tag>
            ) : null}
            {r.doubao_message && active ? (
              <Text type="secondary" style={{ fontSize: 11 }} ellipsis={{ tooltip: r.doubao_message }}>
                {r.doubao_message}
              </Text>
            ) : null}
            {r.doubao_rewrite_count ? (
              <Tag color="volcano" style={{ fontSize: 11 }}>改写{r.doubao_rewrite_count}次</Tag>
            ) : null}
            {r.doubao_status === 'completed' ? (
              <Button
                size="small"
                type="link"
                style={{ padding: 0, height: 'auto' }}
                onClick={() => setPreviewRecord(r)}
              >
                查看成片
              </Button>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      render: (_: unknown, r: ShortdramaPromptRecord) => {
        const active = isDoubaoActive(r);
        return (
        <Space size="small" wrap>
          <Button size="small" onClick={() => setPreviewRecord(r)}>
            查看
          </Button>
          <Tooltip title="自动打开豆包网页端生成视频，成片自动回填到历史">
            <Button
              size="small"
              type="primary"
              ghost
              icon={<RobotOutlined />}
              loading={doubaoGeneratingId === r.id}
              disabled={active || !!doubaoGeneratingId}
              onClick={() => handleDoubaoGenerate(r)}
            >
              一键豆包生成
            </Button>
          </Tooltip>
          {active && (
            <Popconfirm
              title="取消该豆包生成任务？"
              okText="取消任务"
              okButtonProps={{ danger: true }}
              cancelText="返回"
              onConfirm={() => handleDoubaoCancel(r)}
            >
              <Button size="small" danger icon={<StopOutlined />}>取消</Button>
            </Popconfirm>
          )}
          <Upload
            accept=".mp4,.avi,.mov,.mkv,.webm,video/*"
            showUploadList={false}
            customRequest={({ file }) => {
              handleUploadVideo(r, file as File);
            }}
          >
            <Button size="small" icon={<UploadOutlined />}>
              {r.video_status ? '更换' : '上传视频'}
            </Button>
          </Upload>
          {r.video_status && r.video_file_key && (
            <Tooltip title="把该成片视频导入到去水印流程处理">
              <Button
                size="small"
                type="primary"
                ghost
                icon={<ImportOutlined />}
                onClick={() => handleImportToWatermark(r)}
              >
                导入去水印
              </Button>
            </Tooltip>
          )}
          <Popconfirm
            title="删除该条生成记录？"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => deleteRecord(r.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
        );
      },
    },
  ];

  const promptTabContent = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* ── 1. 提示词生成 ── */}
      <Card
        size="small"
        title="① 生成 Seedance 提示词"
        extra={
          <Space>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={openTemplateEditor}
            >
              编辑长/短提示词模板
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="根据《Seedance短剧视频生成提示词模板》七段结构生成：题材基调 / 故事 / 场景人物 / 镜头执行 / 音频 / 画面风格 / 性别声明。模型借用 AutoClip 中配置的大模型。提示词中的人名、地名等一律使用代称，结尾自动附上侵权/违规改写确认句。"
          />

          {/* 时长：预设 + 自定义 */}
          <Space wrap>
            <Text strong>视频时长：</Text>
            <Radio.Group
              value={durationCustom ? 'custom' : 'preset'}
              onChange={(e) => switchDurationMode(e.target.value === 'custom')}
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'preset', label: '预设时长' },
                { value: 'custom', label: '自定义' },
              ]}
            />
            {durationCustom ? (
              <Space>
                <InputNumber
                  min={3}
                  max={300}
                  value={duration}
                  onChange={(v) => setDuration(Number(v) || 15)}
                  addonAfter="秒"
                  style={{ width: 130 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>支持 3~300 秒自定义</Text>
              </Space>
            ) : (
              <Radio.Group
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                optionType="button"
                buttonStyle="solid"
                options={[
                  { value: 10, label: '10 秒' },
                  { value: 15, label: '15 秒' },
                ]}
              />
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              10s：3s 钩子 / 4s 铺垫 / 3s 反转；15s：3s 钩子 / 6s 铺垫 / 6s 反转；自定义按比例分配三镜头
            </Text>
          </Space>

          {/* 文案输入 */}
          <div>
            <Space style={{ marginBottom: 6 }}>
              <Text strong>短剧文案：</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                对白 / 旁白原文，生成时将逐字锁定、禁止模型扩写；人名/地名将自动替换为代称
              </Text>
            </Space>
            <TextArea
              rows={8}
              placeholder="在此输入短剧文案（对白用【角色】标注、旁白标注（画外音旁白）），支持 10s / 15s / 自定义时长剧情…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <Space wrap style={{ marginTop: 6 }}>
              {Object.entries(EXAMPLE_SCRIPTS).map(([name, script]) => (
                <Button
                  key={name}
                  size="small"
                  icon={<FileTextOutlined />}
                  onClick={() => setText(script)}
                >
                  填充示例：{name}
                </Button>
              ))}
            </Space>
          </div>

          {/* 可选参数：题材 / 基调 / 角色（下拉预设 + 可自定义输入） */}
          <Space wrap align="start">
            <Space>
              <Text>题材：</Text>
              <AutoComplete
                style={{ width: 180 }}
                value={theme}
                onChange={setTheme}
                options={THEME_OPTIONS}
                placeholder="选择或输入题材"
                allowClear
              />
            </Space>
            <Space>
              <Text>基调：</Text>
              <AutoComplete
                style={{ width: 160 }}
                value={tone}
                onChange={setTone}
                options={TONE_OPTIONS}
                placeholder="选择或输入基调"
                allowClear
              />
            </Space>
            <Space>
              <Text>角色：</Text>
              <AutoComplete
                style={{ width: 360 }}
                value={characters}
                onChange={setCharacters}
                options={CHARACTER_OPTIONS}
                placeholder="选择预设人设或自定义，如：女主，女，25岁，职业装…"
                allowClear
              />
            </Space>
          </Space>
          <div>
            <Text>补充要求：</Text>
            <Input
              placeholder="可选，如：结尾反转要夸张、全程不要镜头晃动"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              style={{ width: 460 }}
            />
          </div>

          {/* 操作 */}
          <Space wrap>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={generating}
              onClick={handleGenerate}
            >
              生成提示词
            </Button>
            <Button icon={<ClearOutlined />} onClick={clearForm}>
              清空
            </Button>
          </Space>

          {/* 生成结果（三版本：长提示词 / 短提示词 / AI提示词） */}
          {(resultLong || resultShort || resultPrompt) && (
            <Card size="small" type="inner" title="生成结果">
              <Space style={{ marginBottom: 8 }} wrap>
                <Tag color={duration === 10 ? 'blue' : duration === 15 ? 'purple' : 'orange'}>{duration}s 模板</Tag>
                {resultModel && <Tag color="cyan">模型：{resultModel}</Tag>}
                {resultRecordId && <Tag color="green">已保存到历史</Tag>}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  长 / 短提示词为固定模板（仅替换文案），AI 提示词为模型生成
                </Text>
              </Space>
              <Tabs
                activeKey={activePromptTab}
                onChange={setActivePromptTab}
                items={[
                  {
                    key: 'long',
                    label: (
                      <span>
                        <FileTextOutlined /> 长提示词
                        {resultLong ? <Tag style={{ marginLeft: 6 }} color="blue">模板</Tag> : null}
                      </span>
                    ),
                    children: (
                      <PromptResultBlock
                        text={resultLong}
                        onCopy={async () => {
                          await handleCopy(resultLong);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        }}
                        copied={copied}
                      />
                    ),
                  },
                  {
                    key: 'short',
                    label: (
                      <span>
                        <FileTextOutlined /> 短提示词
                        {resultShort ? <Tag style={{ marginLeft: 6 }} color="geekblue">模板</Tag> : null}
                      </span>
                    ),
                    children: (
                      <PromptResultBlock
                        text={resultShort}
                        onCopy={async () => {
                          await handleCopy(resultShort);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        }}
                        copied={copied}
                      />
                    ),
                  },
                  {
                    key: 'ai',
                    label: (
                      <span>
                        <ThunderboltOutlined /> AI提示词
                        {resultPrompt ? <Tag style={{ marginLeft: 6 }} color="purple">Seedance 七段</Tag> : null}
                      </span>
                    ),
                    children: (
                      <PromptResultBlock
                        text={resultPrompt}
                        onCopy={async () => {
                          await handleCopy(resultPrompt);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        }}
                        copied={copied}
                      />
                    ),
                  },
                ]}
              />
            </Card>
          )}
        </Space>
      </Card>

      {/* ── 生成历史 ── */}
      <Card
        size="small"
        title="提示词生成历史"
        extra={
          <Space wrap>
            <Space size={4}>
              <Text strong style={{ fontSize: 12 }}>豆包账户：</Text>
              <Radio.Group
                size="small"
                value={doubaoAccountType}
                onChange={(e) => handleDoubaoAccountTypeChange(e.target.value as 'free' | 'pro')}
                optionType="button"
                buttonStyle="solid"
                options={[
                  { value: 'free', label: '免费（≤10s）' },
                  { value: 'pro', label: '包月会员（≤30s）' },
                ]}
              />
              <Tooltip title="账户类型选择后即作为当前登录用户的默认值；豆包单次生成时长受账户限制，超出自动按上限生成">
                <Text type="secondary" style={{ fontSize: 11 }}>
                  <QrcodeOutlined /> 上限：免费 {doubaoLimits.free_max_seconds}s / 包月 {doubaoLimits.pro_max_seconds}s
                </Text>
              </Tooltip>
            </Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => fetchRecords()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          loading={loadingRecords}
          dataSource={records}
          columns={recordColumns}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 1500 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无生成记录，先在上方生成一条吧"
              />
            ),
          }}
        />
      </Card>
    </Space>
  );

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Title level={4} style={{ margin: 0 }}>
          <VideoCameraOutlined /> 短片制作
        </Title>
        <Tag color="green">v7 新增</Tag>
      </Space>

      {/* ── 工作流 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          size="small"
          current={-1}
          items={[
            { title: '输入文案', description: '对白/旁白原文' },
            { title: '生成提示词', description: '复用 AutoClip 模型' },
            { title: 'Seedance 生成', description: '10s / 15s / 自定义竖屏' },
            { title: '去水印出片', description: '历史一键导入「去水印」页签' },
            { title: '发布素材', description: '短标题/配文/标签/神评' },
          ]}
        />
      </Card>

      <Tabs
        activeKey={activeTab}
        destroyOnHidden
        onChange={(key) => {
          // 切换页签时重置页面状态：不保留上次生成后展开/已选的状态
          setActiveTab(key);
          if (key !== 'prompt') {
            setResultPrompt('');
            setResultLong('');
            setResultShort('');
            setResultModel(null);
            setResultRecordId(null);
            setActivePromptTab('long');
          }
        }}
        items={[
          {
            key: 'prompt',
            label: (
              <span style={{ fontSize: 18, fontWeight: 600 }}>
                <ThunderboltOutlined /> ① 提示词生成
              </span>
            ),
            children: promptTabContent,
          },
          {
            key: 'watermark',
            label: (
              <span style={{ fontSize: 18, fontWeight: 600 }}>
                <ClearOutlined /> ② 去水印
              </span>
            ),
            children: (
              <Watermark
                imports={watermarkImports}
                onImportsConsumed={() => setWatermarkImports([])}
                onGoToPublish={(promptRecordId) => {
                  setPendingPublishPromptId(promptRecordId || null);
                  setActiveTab('publish');
                }}
              />
            ),
          },
          {
            key: 'publish',
            label: (
              <span style={{ fontSize: 18, fontWeight: 600 }}>
                <SendOutlined /> ③ 发布素材
              </span>
            ),
            children: (
              <PublishMaterialTab
                promptRecords={records}
                onLoadPromptRecords={() => fetchRecords(true)}
                initialPromptRecordId={pendingPublishPromptId}
                onPromptIdConsumed={() => setPendingPublishPromptId(null)}
              />
            ),
          },
        ]}
      />

      {/* ── 成片视频快速播放弹窗 ── */}
      <Modal
        title={previewVideo?.title || '视频预览'}
        open={!!previewVideo}
        footer={null}
        width={900}
        onCancel={() => setPreviewVideo(null)}
        destroyOnClose
      >
        {previewVideo && (
          <video
            src={previewVideo.url}
            controls
            autoPlay
            style={{ width: '100%', maxHeight: 560, background: '#000' }}
          />
        )}
      </Modal>

      {/* ── 提示词详情弹窗（含成片视频上传 / 预览 / 导入去水印） ── */}
      <Modal
        title="提示词详情"
        open={!!previewRecord}
        footer={null}
        width={860}
        onCancel={() => setPreviewRecord(null)}
        destroyOnClose
      >
        {previewRecord && (
          <div>
            <Space style={{ marginBottom: 8 }} wrap>
              <Tag color={previewRecord.duration === 10 ? 'blue' : previewRecord.duration === 15 ? 'purple' : 'orange'}>
                {previewRecord.duration}s
              </Tag>
              {previewRecord.theme && <Tag>{previewRecord.theme}</Tag>}
              {previewRecord.tone && <Tag color="orange">{previewRecord.tone}</Tag>}
            </Space>

            {/* 成片视频区 */}
            <Card
              size="small"
              title="成片视频（Seedance 生成结果）"
              style={{ marginBottom: 12 }}
            >
              {previewRecord.video_status && previewRecord.video_file_name ? (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Dragger
                    accept=".mp4,.avi,.mov,.mkv,.webm,video/*"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      handleUploadVideo(previewRecord!, file as File);
                      return false;
                    }}
                  >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p className="ant-upload-text">点击或拖拽视频到此处更换</p>
                    <p className="ant-upload-hint">支持 .mp4 / .avi / .mov / .mkv / .webm，替换当前成片视频</p>
                  </Dragger>
                  <Space wrap>
                    <Tag color="green" icon={<VideoCameraOutlined />}>{previewRecord.video_file_name}</Tag>
                    {previewRecord.video_file_size ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {formatFileSize(previewRecord.video_file_size)}
                      </Text>
                    ) : null}
                  </Space>
                  {previewRecord.video_url && (
                    <video
                      src={previewRecord.video_url}
                      controls
                      style={{ width: '100%', maxHeight: 320, background: '#000', borderRadius: 8 }}
                    />
                  )}
                  <Space wrap>
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<ImportOutlined />}
                      onClick={() => handleImportToWatermark(previewRecord!)}
                    >
                      一键导入去水印
                    </Button>
                    <Popconfirm
                      title="删除该成片视频？"
                      description="仅删除视频，保留提示词记录"
                      okText="删除"
                      okButtonProps={{ danger: true }}
                      cancelText="取消"
                      onConfirm={() => handleDeleteVideo(previewRecord!)}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />}>删除视频</Button>
                    </Popconfirm>
                  </Space>
                </Space>
              ) : (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Dragger
                    accept=".mp4,.avi,.mov,.mkv,.webm,video/*"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      handleUploadVideo(previewRecord!, file as File);
                      return false;
                    }}
                  >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p className="ant-upload-text">点击或拖拽视频到此处上传</p>
                    <p className="ant-upload-hint">上传 Seedance 生成的成片视频，可一键导入去水印流程</p>
                  </Dragger>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    <InboxOutlined /> 尚未上传成片视频，可拖拽 / 点击上传 Seedance 生成的视频后一键导入去水印流程。
                  </Text>
                </Space>
              )}
            </Card>

            <Text strong>原始文案：</Text>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                background: '#fafafa',
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                padding: 10,
                fontSize: 12,
                maxHeight: 160,
                overflow: 'auto',
              }}
            >
              {previewRecord.source_text}
            </pre>
            <Text strong>生成的提示词（三版本）：</Text>
            <Tabs
              defaultActiveKey="long"
              items={[
                {
                  key: 'long',
                  label: <span><FileTextOutlined /> 长提示词</span>,
                  children: (
                    <PromptResultBlock
                      text={previewRecord.prompt_long || ''}
                      onCopy={() => handleCopy(previewRecord!.prompt_long || '')}
                      copied={false}
                    />
                  ),
                },
                {
                  key: 'short',
                  label: <span><FileTextOutlined /> 短提示词</span>,
                  children: (
                    <PromptResultBlock
                      text={previewRecord.prompt_short || ''}
                      onCopy={() => handleCopy(previewRecord!.prompt_short || '')}
                      copied={false}
                    />
                  ),
                },
                {
                  key: 'ai',
                  label: (
                    <span>
                      <ThunderboltOutlined /> AI提示词
                      {previewRecord.model ? <span style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>（{previewRecord.model}）</span> : null}
                    </span>
                  ),
                  children: (
                    <PromptResultBlock
                      text={previewRecord.prompt_text}
                      onCopy={() => handleCopy(previewRecord!.prompt_text)}
                      copied={false}
                    />
                  ),
                },
              ]}
            />
            <Space style={{ marginTop: 8 }}>
              <Button
                icon={<PlayCircleOutlined />}
                onClick={() => {
                  if (previewRecord!.video_url) window.open(previewRecord!.video_url, '_blank');
                }}
                disabled={!previewRecord!.video_url}
              >
                新窗口播放视频
              </Button>
            </Space>
          </div>
        )}
      </Modal>

      {/* ── 长 / 短提示词模板编辑弹窗 ── */}
      <Modal
        title="编辑长/短提示词模板"
        open={templateModalOpen}
        onCancel={() => setTemplateModalOpen(false)}
        footer={
          <Space>
            <Button
              icon={<UndoOutlined />}
              onClick={resetTemplates}
              disabled={templateSaving}
            >
              恢复默认
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={templateSaving}
              onClick={handleSaveTemplates}
            >
              保存模板
            </Button>
          </Space>
        }
        width={900}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="模板内需保留 [视频文案] 占位符，生成时会替换为用户输入的文案；留空则恢复内置默认模板。"
        />
        <Text strong>长提示词模板：</Text>
        <TextArea
          rows={9}
          style={{ marginTop: 6, marginBottom: 16, fontFamily: 'monospace', fontSize: 13 }}
          value={templateDraft.long}
          onChange={(e) => setTemplateDraft((d) => ({ ...d, long: e.target.value }))}
          placeholder="输入长提示词模板…"
        />
        <Text strong>短提示词模板：</Text>
        <TextArea
          rows={9}
          style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 13 }}
          value={templateDraft.short}
          onChange={(e) => setTemplateDraft((d) => ({ ...d, short: e.target.value }))}
          placeholder="输入短提示词模板…"
        />
      </Modal>

      {/* ── 豆包登录二维码弹窗 ── */}
      <Modal
        title={
          <Space>
            <QrcodeOutlined /> 豆包扫码登录
          </Space>
        }
        open={!!qrRecord && !!qrRecord.doubao_qrcode}
        footer={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              登录后 Cookie 将持久化，下次免扫码
            </Text>
            <Button
              size="small"
              danger
              icon={<StopOutlined />}
              onClick={() => qrRecord && handleDoubaoCancel(qrRecord)}
            >
              取消任务
            </Button>
          </Space>
        }
        width={420}
        onCancel={() => setQrRecord(null)}
        destroyOnClose
      >
        {qrRecord?.doubao_qrcode && (
          <Space direction="vertical" style={{ width: '100%', alignItems: 'center' }} size={12}>
            <Alert
              type="info"
              showIcon
              message="请使用豆包 App「扫一扫」登录，登录后自动继续生成视频"
            />
            <img
              src={qrRecord.doubao_qrcode}
              alt="豆包登录二维码"
              style={{ width: 280, height: 280, objectFit: 'contain', border: '1px solid #f0f0f0', borderRadius: 8 }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              二维码实时刷新，请尽快扫码；登录成功后将自动继续
            </Text>
          </Space>
        )}
      </Modal>

      {/* ── 豆包改写确认弹窗 ── */}
      <Modal
        title={
          <Space>
            <RobotOutlined /> 豆包提示词改写确认
          </Space>
        }
        open={!!rewriteRecord}
        footer={
          <Space wrap>
            <Button
              icon={<SyncOutlined />}
              loading={rewriteBusy}
              onClick={() => handleRewriteDecision('rejected')}
            >
              再让豆包改写
            </Button>
            <Button
              danger
              icon={<StopOutlined />}
              loading={rewriteBusy}
              onClick={() => handleRewriteDecision('cancelled')}
            >
              放弃生成
            </Button>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={rewriteBusy}
              onClick={() => handleRewriteDecision('approved')}
            >
              确认使用并继续生成
            </Button>
          </Space>
        }
        width={860}
        onCancel={() => setRewriteRecord(null)}
        destroyOnClose
      >
        {rewriteRecord && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type="warning"
              showIcon
              message="豆包拒绝了原提示词，已让豆包改写。请确认改写稿是否符合预期，确认后将用改写稿重新生成视频；最终通过的提示词会自动保存到历史。"
            />
            {rewriteRecord.doubao_error_message && !rewriteRecord.doubao_rewrite_count ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                拒绝原因：{rewriteRecord.doubao_error_message}
              </Text>
            ) : null}
            {rewriteRecord.doubao_rewrite_history && rewriteRecord.doubao_rewrite_history.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <Text strong style={{ fontSize: 13 }}>原提示词（被拒）</Text>
                  <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#fff1f0', border: '1px solid #ffccc7', borderRadius: 8, padding: 10, fontSize: 12, maxHeight: 260, overflow: 'auto' }}>
                    {rewriteRecord.doubao_rewrite_history[rewriteRecord.doubao_rewrite_history.length - 1].original}
                  </pre>
                </div>
                <div>
                  <Text strong style={{ fontSize: 13 }}>豆包改写稿</Text>
                  <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 8, padding: 10, fontSize: 12, maxHeight: 260, overflow: 'auto' }}>
                    {rewriteRecord.doubao_rewrite_history[rewriteRecord.doubao_rewrite_history.length - 1].rewritten}
                  </pre>
                </div>
              </div>
            )}
            {rewriteRecord.doubao_rewrite_history && rewriteRecord.doubao_rewrite_history.length > 0 && (
              <div>
                <Text strong style={{ fontSize: 13 }}>改写轮次</Text>
                <div style={{ marginTop: 4 }}>
                  {rewriteRecord.doubao_rewrite_history.map((item: DoubaoRewriteItem, idx: number) => (
                    <Tag key={idx} color="volcano">
                      第{item.round ?? idx + 1}轮{item.attempt ? `-${item.attempt}` : ''}
                      {item.reason ? `（${item.reason.slice(0, 24)}${item.reason.length > 24 ? '…' : ''}）` : ''}
                    </Tag>
                  ))}
                </div>
              </div>
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
};

// ── 提示词单版本展示块（带复制按钮） ──
const PromptResultBlock: React.FC<{
  text: string;
  onCopy: () => void;
  copied: boolean;
}> = ({ text, onCopy, copied }) => (
  <div>
    <Space style={{ marginBottom: 8 }} wrap>
      <Button
        size="small"
        type="primary"
        icon={copied ? <CheckOutlined /> : <CopyOutlined />}
        onClick={onCopy}
      >
        {copied ? '已复制' : '复制提示词'}
      </Button>
    </Space>
    <pre
      style={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        padding: 12,
        fontSize: 13,
        maxHeight: 420,
        overflow: 'auto',
      }}
    >
      {text || '（该版本暂未生成）'}
    </pre>
  </div>
);

export default ShortDrama;
