import { Modal } from 'antd';

/**
 * 11-06 拍板②「确认＋标注都要」的前端半边。
 *
 * 后端口径：跨人批次（素材导入人 ≠ 操作者）的**扣费动作**（反推/出文案/下载/查时长/投板）
 * 不带 `cross_person_confirm=true` 会 400，白话里点名批次号与导入人。内容可见性不受影响
 * （11-03 拍板），这里只管"花钱前点一下头"。
 */

/** 后端 400 白话里固定的点名短语，前端靠它识别"这是要确认跨人"，不要改后端这句话 */
export const CROSS_PERSON_MARKER = '替他人批次花钱';

export const isCrossPersonAsk = (e: unknown): boolean =>
  e instanceof Error && e.message.includes(CROSS_PERSON_MARKER);

/**
 * 跨人批次扣费动作的统一壳：先照常发一次；后端回 400 白话就弹确认窗，
 * 用户点「确认替他人批次操作」后带 `cross_person_confirm=true` 重发，
 * 点取消就什么都不做（那次 400 本来就没动账，返回 undefined）。
 * 其余错误原样抛回，仍由调用方自己的 catch 处理。
 */
export async function withCrossPersonConfirm<T>(
  run: (confirmed: boolean) => Promise<T>,
): Promise<T | undefined> {
  try {
    return await run(false);
  } catch (e) {
    if (!isCrossPersonAsk(e)) throw e;
    return new Promise<T | undefined>((resolve, reject) => {
      Modal.confirm({
        title: '这是别人导入的批次，费用会记到那批的成本上',
        width: 560,
        content: (e as Error).message,
        okText: '确认替他人批次操作',
        cancelText: '取消',
        onOk: async () => {
          try {
            resolve(await run(true));
          } catch (err) {
            reject(err);
          }
        },
        onCancel: () => resolve(undefined),
      });
    });
  }
}


/**
 * A′ 按运营隔离（2026-11-07）：归属跨人确认的前端半边。
 *
 * 后端口径：投**别人过审**的候选（reviewed_by≠操作者）不带 `cross_person_confirm=true`
 * 会 400，白话点名候选与过审人。谁投账算谁（生产单记实际投产人、候选过审人进审计）——
 * 这里只管"投产前点一下头"，与花钱口径的 withCrossPersonConfirm（替他人批次）并存。
 */

export const CROSS_OWNER_MARKER = '替他人过审候选投产';

export const isCrossOwnerAsk = (e: unknown): boolean =>
  e instanceof Error && e.message.includes(CROSS_OWNER_MARKER);

export async function withCrossOwnerConfirm<T>(
  run: (confirmed: boolean) => Promise<T>,
): Promise<T | undefined> {
  try {
    return await run(false);
  } catch (e) {
    if (!isCrossOwnerAsk(e)) throw e;
    return new Promise<T | undefined>((resolve, reject) => {
      Modal.confirm({
        title: '这是别人过审的文案，生产单会记在你名下',
        width: 560,
        content: (e as Error).message,
        okText: '确认替他人投产',
        cancelText: '取消',
        onOk: async () => {
          try {
            resolve(await run(true));
          } catch (err) {
            reject(err);
          }
        },
        onCancel: () => resolve(undefined),
      });
    });
  }
}
