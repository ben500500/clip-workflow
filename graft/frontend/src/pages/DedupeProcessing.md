# frontend/src/pages/DedupeProcessing.tsx

- DedupeProcessing · function · L30-L378 — DedupeProcessing: React.FC = ()
- buildDedupeConfig · function · L81-L110 — buildDedupeConfig = (preset: string, manual: DedupeManualConfigValue)
- handleGenerateSelected · function · L113-L133 — handleGenerateSelected = async ()
- handleUpload · function · L136-L151 — handleUpload = async (file: File)
- removeUploaded · function · L153-L155 — removeUploaded = (uid: string)
- handleRunBatch · function · L158-L188 — handleRunBatch = async ()
- GroupRow · type · L191-L198 — type GroupRow = { key: string; type: 'project' | 'episode' | 'output'; title: string; meta?: string; item?: SliceOutputListItem; children?: GroupRow[]; };
- buildTreeData · function · L199-L216 — buildTreeData = (): GroupRow[]
- formatSize · function · L381-L387 — formatSize = (n: number): string
