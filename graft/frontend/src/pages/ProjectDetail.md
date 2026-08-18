# frontend/src/pages/ProjectDetail.tsx · [[project-episode-management]] [[slice-configuration-presets]]

- BatchSliceConfig · interface · L19-L33 — interface BatchSliceConfig
- BatchPresetOption · interface · L60-L67 — interface BatchPresetOption
- ProjectDetail · function · L70-L1035 — ProjectDetail: React.FC = ()
- applyBatchPreset · function · L109-L120 — applyBatchPreset = (id: string)
- fetchData · function · L155-L170 — fetchData = async (silent = false)
- handleUpload · function · L179-L208 — handleUpload = async (file: File)
- submitMultiUpload · function · L211-L242 — submitMultiUpload = async ()
- handleMultiFileUpload · function · L245-L282 — handleMultiFileUpload = async (files: File[])
- handleTabChange · function · L303-L308 — handleTabChange = (key: string)
- togglePreview · function · L311-L351 — togglePreview = async (record: Episode, expanded?: boolean)
- refreshPreview · function · L353-L378 — refreshPreview = (id: string)
- renderSourcePreview · function · L380-L432 — renderSourcePreview = (record: Episode)
- handleCoverUpload · function · L435-L455 — handleCoverUpload = async (file: File)
- runOneClickSlice · function · L458-L478 — runOneClickSlice = async (episode: Episode)
- runBatchSlice · function · L481-L506 — runBatchSlice = async ()
