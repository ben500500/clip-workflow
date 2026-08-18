# frontend/src/pages/ClipReview.tsx · [[clip-workflow-pages]]

- VideoPreview · function · L20-L144 — VideoPreview: React.FC<{ videoUrl: string; clip: ClipCandidate; onRangeChange?: (start: number, end: number) => void; }> = ({ videoUrl, clip, onRangeChange })
- ClipReview · function · L147-L553 — ClipReview: React.FC = ()
- fetchClips · function · L158-L169 — fetchClips = async ()
- fetchVideoUrl · function · L171-L178 — fetchVideoUrl = async ()
- updateStatus · function · L186-L194 — updateStatus = async (clip: ClipCandidate, status: string)
- batchUpdate · function · L197-L216 — batchUpdate = async (status: string)
- batchAllUpdate · function · L219-L234 — batchAllUpdate = async (status: string)
- adjust · function · L237-L245 — adjust = async (clip: ClipCandidate, field: 'adjusted_start' | 'adjusted_end', value: number | null)
- adjustDebounced · function · L248-L257 — adjustDebounced = (clip: ClipCandidate, field: 'adjusted_start' | 'adjusted_end', value: number | null)
- onTitleClick · function · L289-L296 — onTitleClick = (clipId: string)
