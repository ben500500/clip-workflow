import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Drawer, Input, Space, Tooltip, Typography, message } from 'antd';
import { assetApi, type AssetCategory, type AssetScript } from '../../../api/assets';
import { CategorySelect } from '../AssetCategoryBits';

const { Text } = Typography;

export const SCRIPT_BODY_MAX = 20000;
const NAME_MAX = 60;

export type SaveKind = 'create' | 'update' | 'fork' | 'finalize';

interface Props {
  open: boolean;
  /** 编辑哪条；null＝新建 */
  script: AssetScript | null;
  activeCategories: AssetCategory[];
  /** 新建时的默认原型（页面顶部那个选择器，可改） */
  defaultCategoryId?: string | null;
  /**
   * 「保存并定稿」给不给。定稿只是「我用这一版」（仅本人可做），与审核职能无关，
   * 所以有建稿权限的人都有；留这个开关是为了以后要收紧时不用改结构。
   */
  canFinalize: boolean;
  /** 保存成功：父层重拉列表；`close`＝能不能直接关抽屉（定稿被拦时要留着让人改） */
  onSaved: (row: AssetScript, kind: SaveKind, close: boolean) => void;
  onClose: () => void;
}

const blank = (script: AssetScript | null, defaultCategoryId?: string | null) => ({
  name: script?.name ?? '',
  body: script?.body ?? '',
  categoryId: script ? script.category_id ?? undefined : defaultCategoryId ?? undefined,
  note: script?.note ?? '',
});

/**
 * 脚本编辑抽屉（极简模式屏 1，2026-11-23）。用户原话：「手动修改脚本→保存脚本」
 * 「并可打开脚本修改」。
 *
 * 三种落点，一颗抽屉走完：
 * - 保存草稿：新建＝建一条库稿；改草稿＝原地改；
 * - **改已定稿的脚本＝另存为新草稿**（后端 PUT 对 ready 行自动派生），原稿一字不动——
 *   投出去的永远是过审的那一版，所以定稿不能被悄悄改写；
 * - 保存并定稿：先落稿再定稿；定稿被拦（风险词 block）时**稿子已经存下了**，
 *   抽屉不关、切到刚存的那条，改掉再点一次，不用重敲一遍。
 *
 * 正文是**打开时按 id 取回来的**（11-24 用户：「列表中有详细的内容，但是打开后却没有」）：
 * 列表口为了不把几十条全文一起拖过来，只回 `preview`（前 100 字）＋`body_chars`，
 * 全文只在详情口 `GET /assets/scripts/{id}` 里给。所以抽屉进来先转一下取全文，
 * 取到之前表单禁用（避免"正文是空的"被当成用户写空的），取不到就明确报错并且
 * **不让保存**——否则容易把正文当成空串往回写。
 */
const ScriptEditorDrawer: React.FC<Props> = ({
  open, script, activeCategories, defaultCategoryId, canFinalize, onSaved, onClose,
}) => {
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  const [categoryId, setCategoryId] = useState<string | undefined>();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<'save' | 'finalize' | ''>('');
  /** 详情口取回的那一行（带正文）；列表行没有正文，取到之前一律以它为空 */
  const [full, setFull] = useState<AssetScript | null>(null);
  const [loadingBody, setLoadingBody] = useState(false);
  const [bodyError, setBodyError] = useState('');

  // 一律以"详情到手后的那一行"为准：状态、正文、原型都从它读
  const row = full ?? script;
  const isReady = row?.state === 'ready';
  const base = useMemo(() => blank(row, defaultCategoryId), [row, defaultCategoryId]);
  useEffect(() => {
    if (!open) return;
    setName(base.name);
    setBody(base.body);
    setCategoryId(base.categoryId);
    setNote(base.note);
    // 只在「打开 / 换了一条 / 全文取回来了」时重置表单；defaultCategoryId 变化不该冲掉正在敲的字
    // （全文到达前表单是禁用的，所以这一步不会盖掉用户已经敲的内容）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, script?.id, base]);

  const needBody = open && !!script && script.body === undefined;
  useEffect(() => {
    if (!open || !script) {
      setFull(null);
      setBodyError('');
      return;
    }
    if (script.body !== undefined) {
      // 调用方把全文带进来了（例如刚从「保存」回的那一行），不用再取
      setFull(null);
      setBodyError('');
      return;
    }
    let alive = true;
    setFull(null);
    setBodyError('');
    setLoadingBody(true);
    void (async () => {
      try {
        const detail = await assetApi.getScript(script.id);
        if (alive) setFull(detail);
      } catch (e) {
        if (alive) setBodyError((e as Error).message || '正文没读到');
      } finally {
        if (alive) setLoadingBody(false);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, script?.id]);

  const dirty =
    name !== base.name || body !== base.body || (categoryId ?? null) !== (base.categoryId ?? null)
    || note !== base.note;
  const over = body.length > SCRIPT_BODY_MAX;

  /** 把表单落库（新建 or 改/派生），返回落库后的那一行；失败回 null */
  const persist = async (): Promise<AssetScript | null> => {
    if (loadingBody) {
      message.info('正文还在读取，稍等一下再存');
      return null;
    }
    if (bodyError) {
      message.error('正文没读到，这条先别存（关掉重开一次通常就好）', 8);
      return null;
    }
    if (!name.trim()) {
      message.warning('给脚本起个名字');
      return null;
    }
    if (!body.trim()) {
      message.warning('脚本正文不能为空');
      return null;
    }
    if (over) {
      message.warning(`脚本正文超长（上限 ${SCRIPT_BODY_MAX} 字）`);
      return null;
    }
    setBusy('save');
    try {
      if (!script) {
        return await assetApi.createScript({
          name: name.trim().slice(0, NAME_MAX), body, category_id: categoryId ?? null,
          source_kind: 'manual', note: note.trim() || null,
        });
      }
      // 比对基准＝取回来的那一行（row），不是列表行：列表行没有正文，
      // 拿它当基准会把"没改"误判成"被清空"。
      return await assetApi.updateScript(script.id, {
        name: name.trim() !== row!.name ? name.trim().slice(0, NAME_MAX) : undefined,
        body: body !== (row!.body ?? '') ? body : undefined,
        category_id: categoryId !== (row!.category_id ?? undefined) ? categoryId ?? null : undefined,
        clear_category: !categoryId && !!row!.category_id,
        note: note !== (row!.note ?? '') ? note : undefined,
      });
    } catch (e) {
      message.error((e as Error).message || '脚本没存上', 8);
      return null;
    } finally {
      setBusy('');
    }
  };

  const saveDraft = async () => {
    const saved = await persist();
    if (!saved) return;
    if (saved.forked) message.success('已另存为新草稿（原定稿没动）', 5);
    else if (saved.reused) message.info('库里已有一条内容相同的脚本，打开的是那一行', 6);
    else message.success('已保存', 4);
    onSaved(saved, saved.forked ? 'fork' : script ? 'update' : 'create', true);
  };

  const saveAndFinalize = async () => {
    // 已定稿且没改：没什么可做的
    if (script && isReady && !dirty) {
      message.info('这条已经定稿了');
      onSaved(row!, 'finalize', true);
      return;
    }
    const saved = script && !dirty ? row! : await persist();
    if (!saved) return;
    if (saved.state === 'ready') {
      // 派生/新建时后端发现内容与已有定稿相同，直接回了那条定稿
      message.success('内容已有一条定稿，直接用那一行', 5);
      onSaved(saved, 'finalize', true);
      return;
    }
    setBusy('finalize');
    try {
      const done = await assetApi.finalizeScript(saved.id, {});
      message.success('已定稿，可以投豆包了', 5);
      onSaved(done, 'finalize', true);
    } catch (e) {
      // 定稿被拦（多半是风险词）：稿子已经存下了，留着抽屉让人改——切到刚存的那条
      message.error((e as Error).message || '定稿没成', 8);
      onSaved(saved, 'update', false);
    } finally {
      setBusy('');
    }
  };

  return (
    <Drawer
      title={script ? `脚本：${script.name}` : '新建脚本'}
      width={760}
      open={open}
      onClose={onClose}
      maskClosable={false}
      destroyOnClose
      footer={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text type={over ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
            {loadingBody ? '正文读取中…' : `${body.length} / ${SCRIPT_BODY_MAX} 字`}
          </Text>
          <span style={{ flex: 1 }} />
          <Button onClick={onClose}>关闭</Button>
          <Button
            loading={busy === 'save'}
            disabled={busy === 'finalize' || loadingBody || !!bodyError}
            onClick={() => void saveDraft()}
          >
            {script && isReady ? '另存为新草稿' : '保存草稿'}
          </Button>
          {canFinalize && !(script && isReady && !dirty) && (
            <Tooltip title="定稿后正文冻结、可以直接投豆包；要改会另存为新草稿">
              <Button
                type="primary"
                loading={busy === 'finalize'}
                disabled={busy === 'save' || loadingBody || !!bodyError}
                onClick={() => void saveAndFinalize()}
              >
                保存并定稿
              </Button>
            </Tooltip>
          )}
        </div>
      }
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {needBody && !bodyError && (
          <Alert type="info" showIcon message="正文读取中，取回来之前先别保存（免得把没看到的正文当成空的）" />
        )}
        {!!bodyError && (
          <Alert type="warning" showIcon message={`正文没读到：${bodyError}`} description="关掉重开一次通常就好。这条先别保存。" />
        )}
        {script && isReady && dirty && (
          <Alert
            type="info"
            showIcon
            message="这条已定稿。保存会另存为一条新草稿，原稿不变（投出去的永远是过审的那一版）"
          />
        )}
        <Space wrap size={8}>
          <Input
            placeholder="脚本名（必填，60 字内）"
            value={name}
            maxLength={NAME_MAX}
            style={{ width: 260 }}
            onChange={(e) => setName(e.target.value)}
          />
          <CategorySelect
            value={categoryId}
            onChange={(v) => setCategoryId(v)}
            items={activeCategories}
            placeholder="原型（可不选）"
            width={240}
          />
        </Space>
        <Input.TextArea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={loadingBody
            ? '正文读取中…'
            : '投给豆包的成品提示词——直接写或粘贴，改到满意再定稿'}
          disabled={loadingBody}
          autoSize={{ minRows: 16, maxRows: 26 }}
          style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 12, lineHeight: 1.7 }}
        />
        <Input
          placeholder="备注（可不填，只有自己看）"
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
        />
      </Space>
    </Drawer>
  );
};

export default ScriptEditorDrawer;
