# frontend/src/pages/ProjectDetail.tsx · [[project-episode-management]] [[slice-configuration-presets]]

- BatchSliceConfig · interface · L21-L35 — interface BatchSliceConfig
- loadSavedBatchConfig · function · L56-L67 — function loadSavedBatchConfig(projectId: string): BatchSliceConfig | null
- saveBatchConfig · function · L69-L75 — function saveBatchConfig(projectId: string, cfg: BatchSliceConfig): void
- ProjectDetail · function · L79-L1044 — ProjectDetail: React.FC = ()
- applyBatchPreset · function · L126-L137 — applyBatchPreset = (id: string)
- fetchData · function · L164-L179 — fetchData = async (silent = false)
- handleUpload · function · L188-L217 — handleUpload = async (file: File)
- submitMultiUpload · function · L220-L251 — submitMultiUpload = async ()
- handleMultiFileUpload · function · L254-L291 — handleMultiFileUpload = async (files: File[])
- handleTabChange · function · L312-L317 — handleTabChange = (key: string)
- togglePreview · function · L320-L360 — togglePreview = async (record: Episode, expanded?: boolean)
- refreshPreview · function · L362-L387 — refreshPreview = (id: string)
- renderSourcePreview · function · L389-L441 — renderSourcePreview = (record: Episode)
- handleCoverUpload · function · L444-L464 — handleCoverUpload = async (file: File)
- runOneClickSlice · function · L467-L487 — runOneClickSlice = async (episode: Episode)
- runBatchSlice · function · L490-L515 — runBatchSlice = async ()
