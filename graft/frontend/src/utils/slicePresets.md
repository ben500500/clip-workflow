# frontend/src/utils/slicePresets.ts

- SlicePreset · interface · L16-L92 — interface SlicePreset
- BatchSliceExtras · interface · L155-L159 — interface BatchSliceExtras
- buildBatchSlicePayload · function · L171-L211 — function buildBatchSlicePayload( preset: Omit<SlicePreset, 'id' | 'name'>, extras: BatchSliceExtras = {}, ): Record<string, unknown>
- loadCustomPresets · function · L217-L228 — function loadCustomPresets(): SlicePreset[]
- loadPresetList · function · L237-L250 — function loadPresetList(): { presets: SlicePreset[]; activeId: string }
- persistPresets · function · L255-L263 — function persistPresets(list: SlicePreset[], activeId: string): void
