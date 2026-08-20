# frontend/src/components/DedupeManualConfig.tsx · [[dedupe-config-contract]] [[frontend-reusable-ui-components]]

- DedupeManualConfigValue · interface · L12-L51 — interface DedupeManualConfigValue
- Props · interface · L53-L58 — interface Props
- DedupeManualConfig · function · L66-L218 — DedupeManualConfig: React.FC<Props> = ({ value, onChange, preset })
- set · function · L70-L72 — set = (key: string, val: unknown)
- setDict · function · L73-L77 — setDict = (key: string, fieldKey: string, val: unknown)
- row · function · L79-L87 — row = (label: string, tip: string | undefined, control: React.ReactNode)
- renderControl · function · L90-L138 — renderControl = ( def: DedupeFieldDef, currentVal: unknown, onChangeVal: (v: unknown) => void, )
- num · function · L95-L95 — num = (v?: unknown): number
- renderDictGroup · function · L141-L179 — renderDictGroup = (def: DedupeFieldDef)
