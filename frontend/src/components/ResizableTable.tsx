import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Table } from 'antd';
import type { TableProps, ColumnsType, ColumnType } from 'antd/es/table';

// 列宽拖动调整上下文：子表头单元通过它回调更新列宽
const ResizeContext = React.createContext<(key: string, width: number) => void>(() => {});

// 可拖拽表头单元：在单元格右侧渲染 6px 拖拽手柄
function ResizableHeaderCell(props: Record<string, unknown>) {
  const { children, column, ...rest } = props as {
    children: React.ReactNode;
    column?: { key?: React.Key; dataIndex?: React.Key; width?: number | string };
    [k: string]: unknown;
  };
  const onResize = useContext(ResizeContext);
  const key = column?.key ?? column?.dataIndex;
  const [dragging, setDragging] = useState(false);
  const startX = useRef(0);
  const startWidth = useRef(0);
  const currentWidth = useRef<number>(typeof column?.width === 'number' ? column.width : 100);

  // 外部列宽（如默认宽度）变化时同步本地 ref
  useEffect(() => {
    if (typeof column?.width === 'number') currentWidth.current = column.width;
  }, [column?.width]);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    startX.current = e.clientX;
    startWidth.current = currentWidth.current;
    setDragging(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  useEffect(() => {
    if (!dragging) return;
    const handleMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX.current;
      const w = Math.max(48, startWidth.current + delta);
      currentWidth.current = w;
      if (key != null) onResize(String(key), w);
    };
    const handleUp = () => {
      setDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    return () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
  }, [dragging, key, onResize]);

  return (
    <div
      {...rest}
      style={{ position: 'relative', display: 'flex', alignItems: 'center', width: '100%' }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
      <div
        onMouseDown={handleMouseDown}
        style={{
          position: 'absolute',
          right: -1,
          top: 0,
          bottom: 0,
          width: 8,
          cursor: 'col-resize',
          zIndex: 10,
          background: dragging ? 'rgba(24, 144, 255, 0.25)' : 'transparent',
        }}
        title="拖动调整列宽"
      />
    </div>
  );
}

export interface ResizableTableProps<RecordType>
  extends Omit<TableProps<RecordType>, 'columns' | 'components'> {
  columns?: ColumnsType<RecordType>;
  components?: TableProps<RecordType>['components'];
  resizableColumns?: boolean;
}

/**
 * 支持列宽拖动调整的 Table 封装。
 * - 所有配置了 key/dataIndex 的列，其表头右侧会出现拖拽手柄，可拖动调整列宽（最小 48px）。
 * - 默认开启（resizableColumns=true），可通过 resizableColumns={false} 关闭。
 * - 用法与 antd Table 完全一致。
 */
function ResizableTable<RecordType extends object = any>({
  columns,
  resizableColumns = true,
  components,
  ...rest
}: ResizableTableProps<RecordType>) {
  const [widths, setWidths] = useState<Record<string, number>>({});

  const onResize = useCallback((key: string, width: number) => {
    setWidths((prev) => ({ ...prev, [key]: width }));
  }, []);

  const finalColumns = useMemo(() => {
    if (!resizableColumns || !columns) return columns;
    return columns.map((col) => {
      const raw = (col as ColumnType<RecordType> & {
        key?: React.Key;
        dataIndex?: React.Key;
      });
      const key = raw.key ?? raw.dataIndex;
      if (key == null) return col;
      const override = widths[String(key)];
      if (override == null) return col;
      return { ...col, width: override };
    });
  }, [columns, widths, resizableColumns]);

  const finalComponents = useMemo(
    () => ({
      ...(components as object | undefined),
      header: {
        ...((components as { header?: object } | undefined)?.header as object | undefined),
        cell: ResizableHeaderCell,
      },
    }),
    [components]
  );

  return (
    <ResizeContext.Provider value={onResize}>
      <Table
        columns={finalColumns}
        components={finalComponents}
        {...(rest as TableProps<RecordType>)}
      />
    </ResizeContext.Provider>
  );
}

export default ResizableTable;
