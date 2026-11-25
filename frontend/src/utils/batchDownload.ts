// 批量直链下载（fetch+blob 受控单飞）。
//
// 背景（2026-11-24 用户反馈）：旧实现用 <a>.click() 连发（固定间隔），浏览器
// 下载管理器对并发下载有硬限制——直链速度慢时，后面的点击会被排队上限吞掉，
// 根本进不了下载列表。fetch 单飞不受该限制：一次拉一个（带进度+重试），落
// blob 后再触发保存，全部完成才结束。
// presigned 直链指向 MinIO 外部 endpoint（与前端跨域），MinIO 默认回显
// Access-Control-Allow-Origin，fetch 可直拉（163 实测确认）。

export interface BatchDownloadFile {
  url: string;
  file_name: string;
}

export interface BatchDownloadProgress {
  done: number;
  total: number;
  name: string;
  pct: number; // 当前文件 0-100（无 content-length 时恒 0，完成时 100）
}

export interface BatchDownloadResult {
  ok: string[];
  failed: { name: string; reason: string }[];
}

function saveBlob(blob: Blob, name: string) {
  const a = document.createElement('a');
  const objUrl = URL.createObjectURL(blob);
  a.href = objUrl;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 30s 后释放，留足浏览器接管下载的时间
  setTimeout(() => URL.revokeObjectURL(objUrl), 30_000);
}

export async function downloadFilesSequentially(
  files: BatchDownloadFile[],
  opts?: { onProgress?: (p: BatchDownloadProgress) => void; retries?: number },
): Promise<BatchDownloadResult> {
  const retries = opts?.retries ?? 2; // 失败重试次数（不含首试）
  const ok: string[] = [];
  const failed: { name: string; reason: string }[] = [];
  // 大批量（GB 级总传输）下偶发 TCP 中断不可避免：整批跑完后对失败项自动
  // 再补一轮完整重试，把瞬时失败捞回来（2026-11-25 实测：100 条 8.5GB 批量
  // 下载中 2 条失败，均为传输中断而非文件问题）
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const name = f.file_name || `file_${i + 1}.mp4`;
    let lastReason = '';
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const resp = await fetch(f.url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const total = Number(resp.headers.get('content-length') || 0);
        const reader = resp.body?.getReader();
        let blob: Blob;
        if (reader) {
          const chunks: BlobPart[] = [];
          let received = 0;
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            if (value) {
              chunks.push(value as unknown as BlobPart);
              received += value.length;
              const pct = total ? Math.min(99, Math.round((received / total) * 100)) : 0;
              opts?.onProgress?.({ done: i, total: files.length, name, pct });
            }
          }
          blob = new Blob(chunks);
        } else {
          blob = await resp.blob();
        }
        saveBlob(blob, name);
        ok.push(name);
        opts?.onProgress?.({ done: i + 1, total: files.length, name, pct: 100 });
        lastReason = '';
        break;
      } catch (e) {
        lastReason = e instanceof Error ? e.message : String(e);
        if (attempt < retries) await new Promise((r) => setTimeout(r, 1500));
      }
    }
    if (lastReason) failed.push({ name, reason: lastReason });
  }
  return { ok, failed };
}
