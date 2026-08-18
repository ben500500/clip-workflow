# frontend/src/components/ResizableTable.tsx · [[frontend-reusable-ui-components]]

- ResizableHeaderCell · function · L11-L93 — function ResizableHeaderCell(props: Record<string, unknown>)
- handleMouseDown · function · L29-L37 — handleMouseDown = (e: React.MouseEvent<HTMLDivElement>)
- handleMove · function · L41-L46 — handleMove = (ev: MouseEvent)
- handleUp · function · L47-L51 — handleUp = ()
- ResizableTableProps · interface · L95-L100 — interface ResizableTableProps<RecordType> extends Omit<TableProps<RecordType>, 'columns' | 'components'>
- ResizableTable · function · L108-L155 — function ResizableTable<RecordType extends object = any>({ columns, resizableColumns = true, components, ...rest }: ResizableTableProps<RecordType>)
