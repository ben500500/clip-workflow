# frontend/src/utils/slicePresets.ts

- SlicePreset · interface · L16-L90 — interface SlicePreset
- BatchSliceExtras · interface · L151-L155 — interface BatchSliceExtras
- buildBatchSlicePayload · function · L167-L207 — function buildBatchSlicePayload( preset: Omit<SlicePreset, 'id' | 'name'>, extras: BatchSliceExtras = {}, ): Record<string, unknown>
- loadCustomPresets · function · L213-L224 — function loadCustomPresets(): SlicePreset[]
- loadPresetList · function · L233-L246 — function loadPresetList(): { presets: SlicePreset[]; activeId: string }
- persistPresets · function · L251-L259 — function persistPresets(list: SlicePreset[], activeId: string): void
