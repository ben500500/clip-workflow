import { Modal, Typography, message } from 'antd';
/** 逐条结果的最小形状：送审/过审/投产三个口的 results 都满足（投产口的 error 是 string|null） */
export interface VerdictRow {
  script_id: string;
  ok: boolean;
  code?: string;
  error?: string | null;
}


const { Text } = Typography;

/**
 * 把「逐条结果」念出来（极简模式 S2，2026-11-23）。
 *
 * 为什么必须有这个：送审／过审／投产口都是 **HTTP 200 ＋ 逐条 ok**——没过审的、含风险词的、
 * 没定稿的，接口不会整批报错，只在 `results[].ok:false` 里说。界面不念这一句，
 * 人就会以为「整批都过了」，回头找不到单还以为系统吞了（§9.5c 那条半拉子自审闸的
 * 现场就是这个形态）。
 *
 * 全过 → 一句成功；有没过的 → 弹窗逐条点名（最多列 12 条），**成功的那些照常生效**，
 * 所以标题要把「成了几条」也说清，别让人以为全部失败去重点一遍。
 * 返回没成的条数。
 */
export const reportVerdict = (
  results: VerdictRow[],
  okText: string,
  failNoun: string,
): number => {
  const failed = results.filter((r) => !r.ok);
  if (!failed.length) {
    message.success(okText, 5);
    return 0;
  }
  const okCount = results.length - failed.length;
  Modal.warning({
    title: `${failed.length} ${failNoun}没成${okCount ? `（其余 ${okCount} 条已成功）` : ''}`,
    width: 640,
    content: (
      <div>
        {failed.slice(0, 12).map((f, i) => (
          <div key={f.script_id || i} style={{ marginBottom: 6 }}>
            <Text strong style={{ fontSize: 12 }}>
              {f.code || f.script_id.slice(0, 8)}
            </Text>
            <Text type="danger" style={{ fontSize: 12, marginLeft: 8 }}>
              {f.error || '原因没带回来'}
            </Text>
          </div>
        ))}
        {failed.length > 12 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            另有 {failed.length - 12} 条没列出
          </Text>
        )}
      </div>
    ),
  });
  return failed.length;
};
