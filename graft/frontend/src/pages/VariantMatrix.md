# frontend/src/pages/VariantMatrix.tsx · [[variant-matrix-dedup-dashboard]]

- FilterKey · type · L37-L37 — type FilterKey = 'all' | 'collision' | 'unbound';
- VariantMatrix · function · L45-L494 — VariantMatrix: React.FC = ()
- handleVerify · function · L136-L147 — handleVerify = async (v: VariantMatrixItem)
- openBind · function · L149-L152 — openBind = (v: VariantMatrixItem)
- handleBind · function · L154-L167 — handleBind = async ()
- openThreshold · function · L169-L172 — openThreshold = ()
- handleSaveThreshold · function · L174-L186 — handleSaveThreshold = async ()
- handleDownload · function · L189-L200 — handleDownload = async (v: VariantMatrixItem)
- handleDeleteVariant · function · L203-L211 — handleDeleteVariant = async (v: VariantMatrixItem)
- handleDeleteGroup · function · L214-L222 — handleDeleteGroup = async (g: VariantGroup)
- handleCleanupStuck · function · L225-L240 — handleCleanupStuck = async ()
- DistanceCell · function · L496-L508 — DistanceCell: React.FC<{ v: number | null; threshold?: number; label: string }> = ({ v, threshold, label })
