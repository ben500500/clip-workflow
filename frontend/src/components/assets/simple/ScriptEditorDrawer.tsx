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
 */
const ScriptEditorDrawer: React.FC<Props> = ({
  open, script, activeCategories, defaultCategoryId, canFinalize, onSaved, onClose,
}) => {
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  const [categoryId, setCategoryId] = useState<string | undefined>();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<'save' | 'finalize' | ''>('');

  const isReady = script?.state === 'ready';
  const base = useMemo(() => blank(script, defaultCategoryId), [script, defaultCategoryId]);
  useEffect(() => {
    if (!open) return;
    setName(base.name);
    setBody(base.body);
    setCategoryId(base.categoryId);
    setNote(base.note);
    // 只在「打开 / 换了一条」时重置表单；defaultCategoryId 变化不该冲掉正在敲的字
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, script?.id]);

  const dirty =
    name !== base.name || body !== base.body || (categoryId ?? null) !== (base.categoryId ?? null)
    || note !== base.note;
  const over = body.length > SCRIPT_BODY_MAX;

  /** 把表单落库（新建 or 改/派生），返回落库后的那一行；失败回 null */
  const persist = async (): Promise<AssetScript | null> => {
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
      return await assetApi.updateScript(script.id, {
        name: name.trim() !== script.name ? name.trim().slice(0, NAME_MAX) : undefined,
        body: body !== (script.body ?? '') ? body : undefined,
        category_id: categoryId !== (script.category_id ?? undefined) ? categoryId ?? null : undefined,
        clear_category: !categoryId && !!script.category_id,
        note: note !== (script.note ?? '') ? note : undefined,
      });
    } catch (e) {
      message.error((e as Error).message || '脚本没存上', 8);
      return null;
    } finally {
      setBusy('');
    }
  };

  const saveDraft = async () => {
    const row = await persist();
    if (!row) return;
    if (row.forked) message.success('已另存为新草稿（原定稿没动）', 5);
    else if (row.reused) message.info('库里已有一条内容相同的脚本，打开的是那一行', 6);
    else message.success('已保存', 4);
    onSaved(row, row.forked ? 'fork' : script ? 'update' : 'create', true);
  };

  const saveAndFinalize = async () => {
    // 已定稿且没改：没什么可做的
    if (script && isReady && !dirty) {
      message.info('这条已经定稿了');
      onSaved(script, 'finalize', true);
      return;
    }
    const row = script && !dirty ? script : await persist();
    if (!row) return;
    if (row.state === 'ready') {
      // 派生/新建时后端发现内容与已有定稿相同，直接回了那条定稿
      message.success('内容已有一条定稿，直接用那一行', 5);
      onSaved(row, 'finalize', true);
      return;
    }
    setBusy('finalize');
    try {
      const done = await assetApi.finalizeScript(row.id, {});
      message.success('已定稿，可以投豆包了', 5);
      onSaved(done, 'finalize', true);
    } catch (e) {
      // 定稿被拦（多半是风险词）：稿子已经存下了，留着抽屉让人改——切到刚存的那条
      message.error((e as Error).message || '定稿没成', 8);
      onSaved(row, 'update', false);
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
            {body.length} / {SCRIPT_BODY_MAX} 字
          </Text>
          <span style={{ flex: 1 }} />
          <Button onClick={onClose}>关闭</Button>
          <Button loading={busy === 'save'} disabled={busy === 'finalize'} onClick={() => void saveDraft()}>
            {script && isReady ? '另存为新草稿' : '保存草稿'}
          </Button>
          {canFinalize && !(script && isReady && !dirty) && (
            <Tooltip title="定稿后正文冻结、可以直接投豆包；要改会另存为新草稿">
              <Button
                type="primary"
                loading={busy === 'finalize'}
                disabled={busy === 'save'}
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
          placeholder="投给豆包的成品提示词——直接写或粘贴，改到满意再定稿"
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
