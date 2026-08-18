# frontend/src/pages/PublishMaterialTab.tsx · [[publishing-material-generation]]

- PublishMaterialTab · function · L59-L736 — PublishMaterialTab: React.FC<{ promptRecords?: ShortdramaPromptRecord[]; onLoadPromptRecords?: () => void; initialPromptRecordId?: string | null; onPromptIdConsumed?: () => void; }> = ({ promptRecords = [], onLoadPromptRecords, initialPromptRecordId, onPromptIdConsumed })
- importPromptRecord · function · L148-L159 — importPromptRecord = (recordId?: string)
- handleGenerate · function · L162-L190 — handleGenerate = async ()
- handleCopy · function · L192-L222 — handleCopy = async (key: string, textToCopy: string)
- clearForm · function · L224-L234 — clearForm = ()
- deleteRecord · function · L236-L244 — deleteRecord = async (recordId: string)
- buildFullCopy · function · L247-L264 — buildFullCopy = (m: PublishMaterialType, version?: keyof PublishMaterialType['captions'])
- versionLabel · function · L266-L273 — versionLabel = (v: string)
- renderMaterialContent · function · L276-L443 — renderMaterialContent = (m: PublishMaterialType, showCopy = true)
